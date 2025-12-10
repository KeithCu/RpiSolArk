#!/usr/bin/env python3
"""
Sol-Ark Cloud Integration Module

This module provides integration with the Sol-Ark cloud platform using Playwright
for web automation. It handles login, plant navigation, parameter reading/setting,
and data synchronization.
"""

import os
import json
import time
import logging
import threading
import queue
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from concurrent.futures import Future
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError


class SolArkCloudError(Exception):
    """Custom exception for Sol-Ark cloud operations"""
    pass


class NetworkError(SolArkCloudError):
    """Exception raised when network connectivity issues occur"""
    pass


class SolArkCloud:
    """
    Sol-Ark Cloud integration class using Playwright for web automation
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize Sol-Ark Cloud integration
        
        Args:
            config_path: Path to configuration file
        """
        self.config = self._load_config(config_path)
        try:
            self.solark_config = self.config['solark_cloud']
        except KeyError as e:
            raise KeyError(f"Missing required solark_cloud configuration key: {e}")
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Thread safety: Playwright page objects must be used from the same thread
        self._playwright_lock = threading.RLock()  # Reentrant lock for thread safety
        
        # Queue infrastructure for cross-thread Playwright operations
        self._operation_queue = queue.Queue()
        self._playwright_thread_id: Optional[int] = None  # Thread ID where Playwright was initialized
        self._playwright_worker_thread: Optional[threading.Thread] = None
        self._playwright_worker_running = False
        
        # Browser components
        self.playwright = None  # Playwright instance (must be stopped in cleanup)
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # Cache directory
        self.cache_dir = Path(self.solark_config['cache_dir'])
        self.cache_dir.mkdir(exist_ok=True)
        
        # State tracking
        self.is_logged_in = False
        self.last_sync = None
        self.current_plant_id = None  # Will be set when needed
        
        # Configuration
        self.base_url = self.solark_config['base_url']
        self.username = self.solark_config['username']
        self.password = self.solark_config['password']
        self.timeout = self.solark_config['timeout'] * 1000  # Convert to ms
        self.retry_attempts = self.solark_config['retry_attempts']
        self.headless = self.solark_config['headless']
        self.cache_pages = self.solark_config['cache_pages']
        self.cache_screenshots = self.solark_config.get('cache_screenshots')
        self.session_persistence = self.solark_config['session_persistence']
        self.session_file = self.solark_config['session_file']
        self.session_timeout = self.solark_config['session_timeout']
        
        if not self.username or not self.password:
            self.logger.warning("Sol-Ark credentials not configured in config.yaml")
    
    def _is_playwright_thread(self) -> bool:
        """
        Check if the current thread is the Playwright thread
        
        Returns:
            bool: True if current thread is the Playwright thread
        """
        if self._playwright_thread_id is None:
            return False
        return threading.current_thread().ident == self._playwright_thread_id
    
    def _queue_operation(self, operation_type: str, *args, **kwargs) -> Future:
        """
        Queue a Playwright operation to be executed on the Playwright thread
        
        Args:
            operation_type: Type of operation ('get_time_of_use_state' or 'toggle_time_of_use')
            *args: Positional arguments for the operation
            **kwargs: Keyword arguments for the operation
            
        Returns:
            Future: Future object that will contain the result
        """
        future = Future()
        self._operation_queue.put({
            'type': operation_type,
            'args': args,
            'kwargs': kwargs,
            'future': future
        })
        return future
    
    def _playwright_worker(self):
        """
        Worker thread that processes Playwright operations from the queue.
        This must run on the thread where Playwright was initialized.
        """
        self.logger.debug("Playwright worker thread started")
        while self._playwright_worker_running:
            try:
                # Get operation from queue with timeout to allow checking _playwright_worker_running
                try:
                    operation = self._operation_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                operation_type = operation['type']
                args = operation['args']
                kwargs = operation['kwargs']
                future = operation['future']
                
                try:
                    if operation_type == 'get_time_of_use_state':
                        result = self._get_time_of_use_state_impl(*args, **kwargs)
                        future.set_result(result)
                    elif operation_type == 'toggle_time_of_use':
                        result = self._toggle_time_of_use_impl(*args, **kwargs)
                        future.set_result(result)
                    else:
                        future.set_exception(ValueError(f"Unknown operation type: {operation_type}"))
                except Exception as e:
                    future.set_exception(e)
                finally:
                    self._operation_queue.task_done()
                    
            except Exception as e:
                self.logger.error(f"Error in Playwright worker thread: {e}")
        
        self.logger.debug("Playwright worker thread stopped")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise SolArkCloudError(f"Failed to load config: {e}")
    
    def initialize(self) -> bool:
        """
        Initialize browser and context
        
        Returns:
            bool: True if initialization successful
        """
        try:
            self.logger.info("Initializing Sol-Ark Cloud browser...")
            
            self.playwright = sync_playwright().start()
            
            # Force window size to match viewport - use window-size argument
            window_width = 1366
            window_height = 768
            
            launch_args = [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                f'--window-size={window_width},{window_height}',
                f'--window-position=0,0'  # Position at top-left
            ]
            
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=launch_args
            )
            
            # Use full screen viewport to ensure dropdowns are visible
            # Set viewport to None to use actual window size, or match window size
            self.context = self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': window_width, 'height': window_height},  # Match window size
                java_script_enabled=True
            )
            
            self.page = self.context.new_page()
            
            # Force viewport size to match window size
            try:
                self.page.set_viewport_size({'width': window_width, 'height': window_height})
                self.logger.info(f"Set viewport and window size to {window_width}x{window_height}")
            except Exception as e:
                self.logger.warning(f"Could not set viewport size: {e}")
            
            # In non-headless mode, try to ensure the window is actually the right size
            if not self.headless:
                try:
                    # Wait a moment for window to initialize
                    self.page.wait_for_timeout(500)
                    # Verify viewport size
                    viewport_size = self.page.viewport_size
                    if viewport_size:
                        self.logger.info(f"Actual viewport size: {viewport_size['width']}x{viewport_size['height']}")
                except Exception as e:
                    self.logger.warning(f"Could not verify viewport size: {e}")
            
            # Set default timeout
            self.page.set_default_timeout(self.timeout)
            
            # Track the thread where Playwright was initialized
            self._playwright_thread_id = threading.current_thread().ident
            self.logger.debug(f"Playwright initialized on thread {self._playwright_thread_id}")
            
            # Start the Playwright worker thread
            self._playwright_worker_running = True
            self._playwright_worker_thread = threading.Thread(
                target=self._playwright_worker,
                name="PlaywrightWorker",
                daemon=True
            )
            self._playwright_worker_thread.start()
            self.logger.debug("Playwright worker thread started")
            
            self.logger.info("Browser initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {e}")
            # Cleanup potential partial initialization
            try:
                if self.playwright:
                    self.playwright.stop()
                    self.playwright = None
            except Exception as cleanup_e:
                self.logger.error(f"Failed to cleanup after initialization error: {cleanup_e}")
            return False
    
    def cleanup(self):
        """Cleanup browser resources"""
        try:
            # Stop Playwright worker thread first
            if self._playwright_worker_running:
                self.logger.debug("Stopping Playwright worker thread...")
                self._playwright_worker_running = False
                
                # Wait for worker thread to finish processing current operation
                if self._playwright_worker_thread and self._playwright_worker_thread.is_alive():
                    # Wait a bit for the thread to finish
                    self._playwright_worker_thread.join(timeout=5.0)
                    if self._playwright_worker_thread.is_alive():
                        self.logger.warning("Playwright worker thread did not stop within timeout")
                
                # Process any remaining operations in the queue (they will fail, but we should clear them)
                remaining_ops = 0
                while not self._operation_queue.empty():
                    try:
                        operation = self._operation_queue.get_nowait()
                        if 'future' in operation:
                            operation['future'].set_exception(SolArkCloudError("Operation cancelled during cleanup"))
                        remaining_ops += 1
                    except queue.Empty:
                        break
                
                if remaining_ops > 0:
                    self.logger.warning(f"Cancelled {remaining_ops} pending Playwright operations during cleanup")
            
            # Save session before closing browser
            if self.is_logged_in and self.session_persistence:
                try:
                    self._save_session()
                except Exception as e:
                    self.logger.warning(f"Failed to save session during cleanup: {e}")
            
            if self.page:
                try:
                    self.page.close()
                except Exception as e:
                    self.logger.warning(f"Error closing page: {e}")
            if self.context:
                try:
                    self.context.close()
                except Exception as e:
                    self.logger.warning(f"Error closing context: {e}")
            if self.browser:
                try:
                    self.browser.close()
                except Exception as e:
                    self.logger.warning(f"Error closing browser: {e}")
            # Stop playwright instance to prevent resource leaks
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception as e:
                    self.logger.warning(f"Error stopping playwright: {e}")
            self.logger.info("Browser cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        finally:
            # Reset state
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
            self.is_logged_in = False
            self._playwright_thread_id = None
            self._playwright_worker_thread = None
            self._playwright_worker_running = False
    
    def login(self) -> bool:
        """
        Login to Sol-Ark cloud platform
        
        Returns:
            bool: True if login successful
            
        Raises:
            NetworkError: If network connectivity issues occur
        """
        if not self.username or not self.password:
            self.logger.error("Username or password not configured")
            return False
        
        # Initialize browser if not already done
        if not self.page:
            if not self.initialize():
                self.logger.error("Failed to initialize browser")
                return False
        
        try:
            # Try to restore existing session first
            if self.session_persistence:
                session_data = self._load_session()
                if session_data:
                    self.logger.info("Attempting to restore existing session...")
                    try:
                        if self._restore_session(session_data):
                            # Verify we're actually logged in
                            if self._is_logged_in():
                                self.is_logged_in = True
                                self.logger.info("Successfully restored session - no login needed")
                                return True
                            else:
                                self.logger.info("Session restored but not logged in - proceeding with fresh login")
                        else:
                            self.logger.info("Failed to restore session - proceeding with fresh login")
                    except NetworkError:
                        # Re-raise network errors from session restore
                        raise
            
            self.logger.info("Attempting to login to Sol-Ark Cloud...")
            
            # Navigate directly to inverter page - if not logged in, will redirect to login
            inverter_url = f"{self.base_url}/device/inverter"
            try:
                self.page.goto(inverter_url)
                self.page.wait_for_load_state('networkidle')
            except (PlaywrightTimeoutError, Exception) as e:
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'dns', 'refused', 'unreachable', 'failed to connect']):
                    self.logger.error(f"Network error during login navigation: {e}")
                    raise NetworkError(f"Network connectivity issue: {e}") from e
                raise
            
            # Check if we got redirected to login page
            current_url = self.page.url
            if 'login' not in current_url and 'signin' not in current_url:
                self.logger.info("Already logged in - no login needed")
                self.is_logged_in = True
                return True
            
            # Wait for JavaScript to load and form elements to be ready
            self.page.wait_for_selector('input[placeholder="Please input your E-mail"]', timeout=10000)
            
            # Save login page for analysis
            if self.cache_pages:
                self._save_page_to_cache("login.html")
            self._save_screenshot_to_cache("login.png")
            
            # Fill login form
            # Email field (no name attribute, just placeholder)
            self.page.fill('input[placeholder="Please input your E-mail"]', self.username)
            # Password field
            self.page.fill('input[name="txtPassword"]', self.password)
            
            # Check the terms agreement checkbox (required to enable login button)
            # Try different approaches to find and check the checkbox
            terms_checkbox = None
            
            # Try to find the checkbox by different selectors
            checkbox_selectors = [
                'input[name="type"]',
                '.el-checkbox__original',
                'input[type="checkbox"]',
                'label.el-checkbox input'
            ]
            
            for selector in checkbox_selectors:
                try:
                    terms_checkbox = self.page.query_selector(selector)
                    if terms_checkbox:
                        # Check if it's visible
                        is_visible = terms_checkbox.is_visible()
                        if is_visible:
                            break
                        else:
                            # Try to make it visible by clicking the label
                            label = self.page.query_selector('label.el-checkbox')
                            if label:
                                label.click()
                                break
                except Exception:
                    continue
            
            if terms_checkbox:
                try:
                    terms_checkbox.check()
                    self.logger.info("Terms checkbox checked")
                except Exception as e:
                    self.logger.warning(f"Could not check terms checkbox: {e}")
                    # Try clicking the label instead
                    try:
                        label = self.page.query_selector('label.el-checkbox')
                        if label:
                            label.click()
                            self.logger.info("Terms checkbox clicked via label")
                    except Exception as e2:
                        self.logger.warning(f"Could not click terms checkbox label: {e2}")
                
                # Wait a moment for the button to become enabled
                self.page.wait_for_timeout(1000)
            
            # Look for and click login button
            login_button = self.page.query_selector('button:has-text("Log In")')
            if login_button:
                # Check if button is enabled
                is_disabled = login_button.get_attribute('disabled')
                if not is_disabled:
                    login_button.click()
                else:
                    self.logger.error("Login button is disabled - terms agreement may not be checked")
                    return False
            else:
                self.logger.error("Login button not found")
                return False
            
            # Wait for navigation or success indicator
            try:
                self.page.wait_for_url(f"{self.base_url}/dashboard", timeout=10000)
                self.is_logged_in = True
                self.logger.info("Login successful")
                
                # Save session after successful login
                if self.session_persistence:
                    self._save_session()
                
                # Save dashboard page
                if self.cache_pages:
                    self._save_page_to_cache("dashboard.html")
                self._save_screenshot_to_cache("dashboard.png")
                
                return True
            except PlaywrightTimeoutError:
                # Check if we're still on login page (login failed)
                current_url = self.page.url
                if 'login' in current_url:
                    self.logger.error("Login failed - still on login page")
                    return False
                else:
                    # We might be on a different page, assume success
                    self.is_logged_in = True
                    self.logger.info("Login successful (redirected to different page)")
                    
                    # Save session after successful login
                    if self.session_persistence:
                        self._save_session()
                    
                    return True
                    
        except NetworkError:
            # Re-raise network errors so they can be handled by the integration layer
            raise
        except Exception as e:
            self.logger.error(f"Login failed: {e}")
            return False
    
    def _save_page_to_cache(self, filename: str):
        """Save current page content to cache directory"""
        try:
            content = self.page.content()
            cache_file = self.cache_dir / filename
            with open(cache_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.debug(f"Saved page to cache: {cache_file}")
        except Exception as e:
            self.logger.error(f"Failed to save page to cache: {e}")
    
    def _save_screenshot_to_cache(self, filename: str):
        """Save current page screenshot to cache directory"""
        if not self.cache_screenshots:
            return
        
        try:
            # Ensure filename has .png extension
            if not filename.endswith('.png'):
                filename = filename.replace('.html', '.png')
            
            screenshot_file = self.cache_dir / filename
            self.page.screenshot(path=str(screenshot_file))
            self.logger.debug(f"Saved screenshot to cache: {screenshot_file}")
        except Exception as e:
            self.logger.error(f"Failed to save screenshot to cache: {e}")
    
    def _save_session(self):
        """Save current session data to file"""
        if not self.session_persistence or not self.context:
            return
        
        try:
            # Get cookies from the current context
            cookies = self.context.cookies()
            
            # Also try to get cookies from the current page
            page_cookies = self.page.context.cookies()
            
            # Use page cookies if context cookies are empty
            if not cookies and page_cookies:
                cookies = page_cookies
            
            # Try to capture localStorage and sessionStorage data
            local_storage = {}
            session_storage = {}
            try:
                if self.page:
                    # Get localStorage data
                    local_storage = self.page.evaluate("() => { return {...localStorage}; }")
                    # Get sessionStorage data  
                    session_storage = self.page.evaluate("() => { return {...sessionStorage}; }")
            except Exception as e:
                self.logger.debug(f"Could not capture storage data: {e}")
            
            session_data = {
                'timestamp': datetime.now().isoformat(),
                'cookies': cookies,
                'local_storage': local_storage,
                'session_storage': session_storage,
                'base_url': self.base_url,
                'username': self.username,
                'current_url': self.page.url if self.page else None
            }
            
            with open(self.session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            self.logger.info(f"Session saved successfully with {len(cookies)} cookies, {len(local_storage)} localStorage items, {len(session_storage)} sessionStorage items")
            if cookies:
                # Log cookie names for debugging
                cookie_names = [cookie.get('name', 'unnamed') for cookie in cookies]
                self.logger.debug(f"Cookie names: {cookie_names}")
            if local_storage:
                self.logger.debug(f"localStorage keys: {list(local_storage.keys())}")
            if session_storage:
                self.logger.debug(f"sessionStorage keys: {list(session_storage.keys())}")
        except Exception as e:
            self.logger.warning(f"Failed to save session: {e}")
    
    def _load_session(self) -> Optional[Dict[str, Any]]:
        """Load session data from file"""
        if not self.session_persistence or not os.path.exists(self.session_file):
            return None
        
        try:
            with open(self.session_file, 'r') as f:
                session_data = json.load(f)
            
            # Check if session is still valid
            session_time = datetime.fromisoformat(session_data['timestamp'])
            if (datetime.now() - session_time).total_seconds() > self.session_timeout:
                self.logger.info("Session expired, will need to login again")
                return None
            
            # Check if session is for the same user and URL
            if (session_data.get('username') != self.username or 
                session_data.get('base_url') != self.base_url):
                self.logger.info("Session is for different user/URL, will need to login again")
                return None
            
            self.logger.info(f"Loaded valid session from {self.session_file}")
            return session_data
        except Exception as e:
            self.logger.warning(f"Failed to load session: {e}")
            return None
    
    def _restore_session(self, session_data: Dict[str, Any]) -> bool:
        """Restore session from saved data"""
        try:
            if not self.context:
                return False
            
            cookies = session_data.get('cookies', [])
            local_storage = session_data.get('local_storage', {})
            session_storage = session_data.get('session_storage', {})
            
            # Check if we have any session data to restore
            if not cookies and not local_storage and not session_storage:
                self.logger.warning("No session data found to restore")
                return False
            
            # Set cookies if available
            if cookies:
                self.context.add_cookies(cookies)
                self.logger.info(f"Restored {len(cookies)} cookies to browser context")
            
            # Navigate to base URL first
            try:
                self.page.goto(self.base_url)
                self.page.wait_for_load_state('networkidle')
            except (PlaywrightTimeoutError, Exception) as e:
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'dns', 'refused', 'unreachable', 'failed to connect']):
                    self.logger.error(f"Network error during session restore navigation: {e}")
                    raise NetworkError(f"Network connectivity issue: {e}") from e
                raise
            
            # Restore localStorage and sessionStorage if available
            if local_storage or session_storage:
                try:
                    # Restore localStorage (using parameter binding to prevent injection)
                    if local_storage:
                        for key, value in local_storage.items():
                            # Use a function that takes a single object argument to avoid argument count issues
                            self.page.evaluate("""([key, value]) => {
                                localStorage.setItem(key, value);
                            }""", [key, value])
                        self.logger.info(f"Restored {len(local_storage)} localStorage items")
                    
                    # Restore sessionStorage (using parameter binding to prevent injection)
                    if session_storage:
                        for key, value in session_storage.items():
                            # Use a function that takes a single object argument to avoid argument count issues
                            self.page.evaluate("""([key, value]) => {
                                sessionStorage.setItem(key, value);
                            }""", [key, value])
                        self.logger.info(f"Restored {len(session_storage)} sessionStorage items")
                    
                    # Refresh the page to apply storage changes
                    try:
                        self.page.reload()
                        self.page.wait_for_load_state('networkidle')
                    except (PlaywrightTimeoutError, Exception) as reload_e:
                        error_msg = str(reload_e).lower()
                        if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'dns', 'refused', 'unreachable', 'failed to connect']):
                            self.logger.error(f"Network error during session restore reload: {reload_e}")
                            raise NetworkError(f"Network connectivity issue: {reload_e}") from reload_e
                        raise
                    
                except NetworkError:
                    raise
                except Exception as e:
                    self.logger.warning(f"Failed to restore storage data: {e}")
            
            # Wait for the page to fully load
            self.page.wait_for_load_state('networkidle')
            
            # Check if we're still logged in by looking for login indicators
            current_url = self.page.url
            if '/login' in current_url:
                self.logger.info("Session restored but still on login page - need to login")
                return False
            
            # Additional check - try to navigate to a protected page
            try:
                try:
                    self.page.goto(f"{self.base_url}/device/inverter")
                    self.page.wait_for_load_state('networkidle')
                except (PlaywrightTimeoutError, Exception) as nav_e:
                    error_msg = str(nav_e).lower()
                    if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'dns', 'refused', 'unreachable', 'failed to connect']):
                        self.logger.error(f"Network error during session restore verification: {nav_e}")
                        raise NetworkError(f"Network connectivity issue: {nav_e}") from nav_e
                    raise
                
                # Check if we're redirected to login
                if '/login' in self.page.url:
                    self.logger.info("Session restored but redirected to login - need to login")
                    return False
                
                self.logger.info("Session restored successfully - can access protected pages")
                return True
            except Exception as e:
                self.logger.warning(f"Error testing session restoration: {e}")
                return False
            
        except Exception as e:
            self.logger.warning(f"Failed to restore session: {e}")
            return False
    
    def clear_session(self):
        """Clear saved session data"""
        try:
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
                self.logger.info("Session file cleared")
            self.is_logged_in = False
        except Exception as e:
            self.logger.warning(f"Failed to clear session: {e}")
    
    def _is_logged_in(self) -> bool:
        """Check if currently logged in by looking for login page in URL"""
        try:
            current_url = self.page.url
            return '/login' not in current_url and 'signin' not in current_url
        except Exception as e:
            self.logger.debug(f"Error checking login status: {e}")
            return False
    
    
    
    
    
    
    def _navigate_to_plant_overview(self, plant_id: str, inverter_id: str, html_prefix: str = "") -> bool:
        """
        Navigate to plant overview page
        
        Args:
            plant_id: Sol-Ark plant ID
            inverter_id: Sol-Ark inverter ID (for logging/caching)
            html_prefix: Prefix for HTML cache files (e.g., "get_state_")
            
        Returns:
            bool: True if navigation successful
        """
        plant_url = f"{self.base_url}/plants/overview/{plant_id}/2"
        
        self.logger.info(f"Navigating to plant overview page: {plant_url}")
        try:
            self.page.goto(plant_url)
            self.page.wait_for_load_state('networkidle')
        except (PlaywrightTimeoutError, Exception) as e:
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'dns', 'refused', 'unreachable', 'failed to connect']):
                self.logger.error(f"Network error during navigation: {e}")
                raise NetworkError(f"Network connectivity issue: {e}") from e
            raise
        
        # Save HTML and screenshot after navigating to plant page
        html_content = self.page.content()
        html_file = self.cache_dir / f"{html_prefix}plant_overview_{plant_id}_{inverter_id}.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        self.logger.info(f"Saved plant overview HTML to: {html_file}")
        self._save_screenshot_to_cache(f"{html_prefix}plant_overview_{plant_id}_{inverter_id}.png")
        
        # Check if we got redirected to login page
        current_url = self.page.url
        if 'login' in current_url or 'signin' in current_url:
            self.logger.info("Redirected to login page, performing login...")
            if not self.login():
                return False
            # After login, navigate back to plant page
            self.logger.info("Login successful, navigating back to plant page...")
            try:
                self.page.goto(plant_url)
                self.page.wait_for_load_state('networkidle')
            except (PlaywrightTimeoutError, Exception) as e:
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'dns', 'refused', 'unreachable', 'failed to connect']):
                    self.logger.error(f"Network error during navigation: {e}")
                    raise NetworkError(f"Network connectivity issue: {e}") from e
                raise
        
        return True
    
    def _click_equipment_tab(self, plant_id: str, inverter_id: str, html_prefix: str = "") -> bool:
        """
        Click on Equipment tab
        
        Args:
            plant_id: Sol-Ark plant ID (for logging/caching)
            inverter_id: Sol-Ark inverter ID (for logging/caching)
            html_prefix: Prefix for HTML cache files
            
        Returns:
            bool: True if successful
        """
        self.logger.info("Looking for Equipment tab...")
        try:
            # Try multiple selectors for Equipment tab (the tab, not sidebar menu)
            equipment_selectors = [
                '#tab-equipment',  # Specific tab ID
                '[id="tab-equipment"]',  # Alternative selector
                '.el-tabs__item:has-text("Equipment")',  # Tab with Equipment text
                'div[role="tab"][aria-controls="pane-equipment"]',  # Tab by aria-controls
                '.el-tabs__item[id*="equipment"]'  # Tab with equipment in ID
            ]
            
            equipment_element = None
            for selector in equipment_selectors:
                try:
                    equipment_element = self.page.query_selector(selector)
                    if equipment_element:
                        is_visible = equipment_element.is_visible()
                        self.logger.info(f"Found Equipment tab with selector: {selector}, visible: {is_visible}")
                        if is_visible:
                            break
                except Exception as e:
                    self.logger.debug(f"Error with selector {selector}: {e}")
                    continue
            
            if not equipment_element:
                self.logger.error("Could not find Equipment tab")
                # Save HTML for debugging
                html_content = self.page.content()
                html_file = self.cache_dir / f"{html_prefix}equipment_tab_not_found_{plant_id}_{inverter_id}.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                self._save_screenshot_to_cache(f"{html_prefix}equipment_tab_not_found_{plant_id}_{inverter_id}.png")
                return False
            
            # Scroll into view and click
            equipment_element.scroll_into_view_if_needed()
            self.page.wait_for_timeout(500)
            equipment_element.click()
            self.logger.info("Clicked on Equipment tab")
            self.page.wait_for_load_state('networkidle')
            self.page.wait_for_timeout(3000)  # Wait for tab content to load
            
            # Save HTML and screenshot after clicking Equipment
            html_content = self.page.content()
            html_file = self.cache_dir / f"{html_prefix}equipment_page_{plant_id}_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"Saved equipment page HTML to: {html_file}")
            self._save_screenshot_to_cache(f"{html_prefix}equipment_page_{plant_id}_{inverter_id}.png")
            
            return True
        except Exception as e:
            self.logger.error(f"Error clicking Equipment: {e}")
            return False
    
    def _find_inverter_dropdown(self, inverter_id: str, plant_id: str, html_prefix: str = "") -> Optional[Any]:
        """
        Find and click the 3-dots dropdown button for an inverter
        
        Args:
            inverter_id: Sol-Ark inverter ID
            plant_id: Sol-Ark plant ID (for logging/caching)
            html_prefix: Prefix for HTML cache files
            
        Returns:
            The dropdown button element if found and clicked, None otherwise
        """
        self.logger.info(f"Looking for inverter {inverter_id} in equipment list...")
        
        # Wait for equipment list to load
        self.page.wait_for_timeout(2000)
        
        # Save HTML before looking for inverter
        html_content = self.page.content()
        html_file = self.cache_dir / f"{html_prefix}equipment_before_inverter_search_{plant_id}_{inverter_id}.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        self.logger.info(f"Saved equipment page HTML before inverter search: {html_file}")
        self._save_screenshot_to_cache(f"{html_prefix}equipment_before_inverter_search_{plant_id}_{inverter_id}.png")
        
        # Find the inverter in the collapsible list structure
        # The structure is: collapse item with inverter ID in left panel, dropdown in right panel header
        dropdown_button = None
        try:
            # Wait for inverter ID to appear in the page
            sn_selector = f"text={inverter_id}"
            try:
                self.page.wait_for_selector(sn_selector, timeout=10000)
            except Exception as e:
                self.logger.error(f"Timeout waiting for inverter {inverter_id} to appear: {e}")
                # Save HTML for debugging
                html_content = self.page.content()
                html_file = self.cache_dir / f"{html_prefix}inverter_not_found_{plant_id}_{inverter_id}.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                self._save_screenshot_to_cache(f"{html_prefix}inverter_not_found_{plant_id}_{inverter_id}.png")
                return None
            
            # Find the right panel header that contains the inverter ID and dropdown
            # The structure is: .right-box > .right-header > (inverter ID + dropdown)
            right_headers = self.page.query_selector_all('.right-header')
            self.logger.info(f"Found {len(right_headers)} right headers")
            
            for header in right_headers:
                header_text = header.text_content()
                if inverter_id in header_text:
                    self.logger.info(f"Found right header containing inverter {inverter_id}")
                    # Find dropdown in this header
                    dropdown_selectors = [
                        '.el-dropdown-link.w24.h40.flex-align-around.el-dropdown-selfdefine',
                        '.w24.h40.flex-align-around.el-dropdown-selfdefine',
                        '.el-dropdown-link.el-dropdown-selfdefine',
                        '.el-dropdown-selfdefine',
                        '.el-dropdown-link'
                    ]
                    
                    for selector in dropdown_selectors:
                        dropdown_in_header = header.query_selector(selector)
                        if dropdown_in_header:
                            is_visible = dropdown_in_header.is_visible()
                            self.logger.info(f"Found dropdown with selector {selector}, visible: {is_visible}")
                            if is_visible:
                                dropdown_button = dropdown_in_header
                                break
                    if dropdown_button:
                        break
            
            # Alternative: find by looking for the right-box that contains the inverter ID in its header
            if not dropdown_button:
                right_boxes = self.page.query_selector_all('.right-box')
                self.logger.info(f"Found {len(right_boxes)} right boxes")
                for box in right_boxes:
                    header = box.query_selector('.right-header')
                    if header:
                        header_text = header.text_content()
                        if inverter_id in header_text:
                            self.logger.info(f"Found right box with header containing inverter {inverter_id}")
                            dropdown_button = header.query_selector('.el-dropdown-link.el-dropdown-selfdefine')
                            if dropdown_button and dropdown_button.is_visible():
                                break
            
        except Exception as e:
            self.logger.error(f"Error finding inverter dropdown: {e}")
            # Save HTML for debugging
            html_content = self.page.content()
            html_file = self.cache_dir / f"{html_prefix}dropdown_error_{plant_id}_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self._save_screenshot_to_cache(f"{html_prefix}dropdown_error_{plant_id}_{inverter_id}.png")
            return None
        
        if dropdown_button:
            # Ensure the button is in view
            dropdown_button.scroll_into_view_if_needed()
            self.page.wait_for_timeout(500)
            
            # Click the dropdown
            dropdown_button.click()
            self.logger.info("Clicked on 3 dots dropdown")
            
            # Wait for dropdown menu to appear and become visible
            # Try to find a visible menu with retries
            visible_menu = None
            for attempt in range(10):  # Try up to 10 times (5 seconds total)
                self.page.wait_for_timeout(500)  # Wait 500ms between attempts
                all_menus = self.page.query_selector_all('.el-dropdown-menu')
                self.logger.debug(f"Attempt {attempt + 1}: Found {len(all_menus)} dropdown menus")
                
                for i, menu in enumerate(all_menus):
                    try:
                        if menu.is_visible():
                            visible_menu = menu
                            self.logger.info(f"Found visible dropdown menu {i+1} after {attempt + 1} attempt(s)")
                            break
                    except Exception as e:
                        self.logger.debug(f"Error checking menu {i+1} visibility: {e}")
                        continue
                
                if visible_menu:
                    break
            
            # Save HTML and screenshot after clicking dropdown (whether menu is visible or not)
            html_content = self.page.content()
            html_file = self.cache_dir / f"{html_prefix}dropdown_opened_{plant_id}_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"Saved dropdown opened HTML: {html_file}")
            self._save_screenshot_to_cache(f"{html_prefix}dropdown_opened_{plant_id}_{inverter_id}.png")
            
            if not visible_menu:
                self.logger.warning("No visible dropdown menu found after clicking, but continuing anyway - _navigate_to_parameters_setting will retry")
            
            return dropdown_button
        else:
            self.logger.error("Could not find 3 dots dropdown button")
            # Save HTML for debugging
            html_content = self.page.content()
            html_file = self.cache_dir / f"{html_prefix}dropdown_not_found_{plant_id}_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self._save_screenshot_to_cache(f"{html_prefix}dropdown_not_found_{plant_id}_{inverter_id}.png")
            return None
    
    def _navigate_to_parameters_setting(self, plant_id: str, inverter_id: str, html_prefix: str = "") -> bool:
        """
        Navigate to Parameters Setting via dropdown menu
        
        Args:
            plant_id: Sol-Ark plant ID (for logging/caching)
            inverter_id: Sol-Ark inverter ID (for logging/caching)
            html_prefix: Prefix for HTML cache files
            
        Returns:
            bool: True if successful
        """
        self.logger.info("Navigating to inverter settings using keyboard (press down arrow twice)...")
        
        try:
            # Wait for the dropdown menu to appear and be visible
            self.logger.info("Waiting for dropdown menu to appear...")
            
            # Find visible menu with retries (menu may take time to appear after click)
            visible_menu = None
            for attempt in range(10):  # Try up to 10 times (5 seconds total)
                self.page.wait_for_timeout(500)  # Wait 500ms between attempts
                
                # Find all dropdown menus and check which one is visible
                all_menus = self.page.query_selector_all('.el-dropdown-menu')
                if attempt == 0:
                    self.logger.info(f"Found {len(all_menus)} dropdown menus on page")
                
                # Find the visible menu by checking each one
                for i, menu in enumerate(all_menus):
                    try:
                        is_visible = menu.is_visible()
                        if attempt == 0 or attempt == 9:  # Log on first and last attempt
                            self.logger.info(f"Menu {i+1} visible: {is_visible}")
                        if is_visible:
                            visible_menu = menu
                            self.logger.info(f"Found visible dropdown menu {i+1} after {attempt + 1} attempt(s)")
                            break
                    except Exception as e:
                        if attempt == 0:
                            self.logger.debug(f"Error checking menu {i+1} visibility: {e}")
                        continue
                
                if visible_menu:
                    break
            
            # If no menu is visible, try scrolling the page to bring it into view
            if not visible_menu:
                self.logger.warning("No visible menu found after retries, trying to scroll page to bring menus into view...")
                # Scroll to the dropdown button area
                dropdown_button = self.page.query_selector('.el-dropdown-link.el-dropdown-selfdefine')
                if dropdown_button:
                    dropdown_button.scroll_into_view_if_needed()
                self.page.wait_for_timeout(500)
                # Try scrolling the page down a bit
                self.page.evaluate("window.scrollBy(0, 200)")
                self.page.wait_for_timeout(500)
                # Check again
                all_menus = self.page.query_selector_all('.el-dropdown-menu')
                for i, menu in enumerate(all_menus):
                    try:
                        if menu.is_visible():
                            visible_menu = menu
                            self.logger.info(f"Found visible dropdown menu {i+1} after scrolling")
                            break
                    except:
                        continue
            
            if not visible_menu:
                self.logger.error("No visible dropdown menu found")
                return False
            
            # Scroll the dropdown menu into view to ensure it's fully visible
            self.logger.info("Scrolling dropdown menu into view...")
            try:
                visible_menu.scroll_into_view_if_needed()
                self.page.wait_for_timeout(300)  # Wait for scroll to complete
                self.logger.info("Dropdown menu scrolled into view")
            except Exception as e:
                self.logger.warning(f"Could not scroll menu into view: {e}")
            
            # Find and scroll the "Parameters Setting" menu item into view
            self.logger.info("Finding 'Parameters Setting' menu item...")
            params_item = visible_menu.query_selector('.el-dropdown-menu__item:has-text("Parameters Setting")')
            if not params_item:
                # Try alternative selectors
                all_items = visible_menu.query_selector_all('.el-dropdown-menu__item')
                self.logger.info(f"Found {len(all_items)} menu items, searching for 'Parameters Setting'...")
                for item in all_items:
                    item_text = item.text_content()
                    self.logger.info(f"Menu item text: '{item_text}'")
                    if 'Parameters Setting' in item_text or 'Parameters' in item_text:
                        params_item = item
                        self.logger.info(f"Found 'Parameters Setting' item with text: '{item_text}'")
                        break
            
            if params_item:
                self.logger.info("Scrolling 'Parameters Setting' menu item into view...")
                try:
                    params_item.scroll_into_view_if_needed()
                    self.page.wait_for_timeout(300)  # Wait for scroll to complete
                    self.logger.info("'Parameters Setting' menu item scrolled into view")
                except Exception as e:
                    self.logger.warning(f"Could not scroll 'Parameters Setting' item into view: {e}")
                
                # Click directly on the menu item instead of using keyboard navigation
                self.logger.info("Clicking directly on 'Parameters Setting' menu item...")
                try:
                    # Ensure it's visible and clickable
                    if params_item.is_visible():
                        params_item.click()
                        self.logger.info("Successfully clicked 'Parameters Setting' menu item")
                        self.page.wait_for_timeout(2000)  # Wait for page to load
                    else:
                        self.logger.warning("'Parameters Setting' item is not visible, trying keyboard navigation as fallback")
                        # Fallback to keyboard navigation
                        visible_menu.focus()
                        self.page.wait_for_timeout(500)
                        self.page.keyboard.press('ArrowDown')
                        self.page.wait_for_timeout(250)
                        self.page.keyboard.press('ArrowDown')
                        self.page.wait_for_timeout(250)
                        self.page.keyboard.press('Enter')
                        self.page.wait_for_timeout(2000)
                except Exception as e:
                    self.logger.error(f"Error clicking 'Parameters Setting' item: {e}, trying keyboard navigation as fallback")
                    # Fallback to keyboard navigation
                    try:
                        visible_menu.focus()
                        self.page.wait_for_timeout(500)
                        self.page.keyboard.press('ArrowDown')
                        self.page.wait_for_timeout(250)
                        self.page.keyboard.press('ArrowDown')
                        self.page.wait_for_timeout(250)
                        self.page.keyboard.press('Enter')
                        self.page.wait_for_timeout(2000)
                    except Exception as e2:
                        self.logger.error(f"Keyboard navigation fallback also failed: {e2}")
                        return False
            else:
                self.logger.error("Could not find 'Parameters Setting' menu item, trying keyboard navigation...")
                # Fallback to keyboard navigation if we can't find the item
                try:
                    visible_menu.focus()
                    self.page.wait_for_timeout(500)
                    self.logger.info("Pressing ↓ first time...")
                    self.page.keyboard.press('ArrowDown')
                    self.page.wait_for_timeout(250)
                    self.logger.info("Pressing ↓ second time...")
                    self.page.keyboard.press('ArrowDown')
                    self.page.wait_for_timeout(250)
                    self.logger.info("Pressing Enter...")
                    self.page.keyboard.press('Enter')
                    self.page.wait_for_timeout(2000)
                except Exception as e:
                    self.logger.error(f"Keyboard navigation failed: {e}")
                    return False
            
            self.logger.info("Successfully navigated to inverter settings!")
            
            # Wait for page to load
            self.page.wait_for_load_state('networkidle')
            self.page.wait_for_timeout(2000)
            
            # Save HTML and screenshot of inverter settings page
            html_content = self.page.content()
            html_file = self.cache_dir / f"{html_prefix}inverter_settings_{plant_id}_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"Saved inverter settings page HTML: {html_file}")
            self._save_screenshot_to_cache(f"{html_prefix}inverter_settings_{plant_id}_{inverter_id}.png")
            
            return True
        except Exception as e:
            self.logger.error(f"Error navigating to inverter settings: {e}")
            return False
    
    def _navigate_to_tou_settings(self, plant_id: str, inverter_id: str, html_prefix: str = "") -> Optional[Any]:
        """
        Navigate to TOU settings (handle iframe and System Work Mode navigation)
        
        Args:
            plant_id: Sol-Ark plant ID (for logging/caching)
            inverter_id: Sol-Ark inverter ID (for logging/caching)
            html_prefix: Prefix for HTML cache files
            
        Returns:
            The TOU element if found, None otherwise
        """
        # Wait for parameters page to load and look for iframe
        self.logger.info("Waiting for parameters page to load...")
        self.page.wait_for_load_state('networkidle')
        
        # Look for the iframe that contains the actual settings
        self.logger.info("Looking for settings iframe...")
        try:
            iframe_element = self.page.query_selector('iframe.testiframe')
            if iframe_element:
                iframe_src = iframe_element.get_attribute('src')
                self.logger.info(f"Found iframe with URL: {iframe_src}")
                
                # Navigate directly to the iframe URL
                self.logger.info("Navigating to iframe URL...")
                try:
                    self.page.goto(iframe_src)
                    self.page.wait_for_load_state('networkidle')
                    self.logger.info("Successfully navigated to iframe URL")
                except (PlaywrightTimeoutError, Exception) as e:
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'dns', 'refused', 'unreachable', 'failed to connect']):
                        self.logger.error(f"Network error during iframe navigation: {e}")
                        raise NetworkError(f"Network connectivity issue: {e}") from e
                    raise
                
                # Save HTML after navigating to iframe
                html_content = self.page.content()
                html_file = self.cache_dir / f"{html_prefix}iframe_page_{plant_id}_{inverter_id}.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                self.logger.info(f"Saved iframe page HTML: {html_file}")
                self._save_screenshot_to_cache(f"{html_prefix}iframe_page_{plant_id}_{inverter_id}.png")
                
                # First, try to find TOU switch directly on the page
                self.logger.info("Looking for TOU switch directly on page...")
                tou_switch_selectors = [
                    'label:has-text("Time Of Use")',
                    '.el-switch',
                    '.el-switch__input',
                    'input[type="checkbox"]',
                    'div:has-text("Time Of Use")',
                    '.el-form-item:has-text("Time Of Use")'
                ]
                
                tou_element = None
                tou_found_selector = None
                
                for i, selector in enumerate(tou_switch_selectors):
                    try:
                        self.logger.debug(f"Trying TOU selector {i+1}/{len(tou_switch_selectors)}: {selector}")
                        tou_element = self.page.query_selector(selector)
                        if tou_element:
                            is_visible = tou_element.is_visible()
                            if is_visible:
                                self.logger.info(f"Found TOU switch with selector: {selector}")
                                tou_found_selector = selector
                                break
                    except Exception as e:
                        self.logger.debug(f"Error with selector: {e}")
                        continue
                
                # If TOU switch not found directly, try System Work Mode
                if not tou_element:
                    self.logger.info("TOU switch not found directly, looking for System Work Mode link...")
                    
                    system_work_mode_selectors = [
                        'text=System Work Mode',
                        'span:has-text("System Work Mode")',
                        'el-link:has-text("System Work Mode")',
                        '.item-box:has-text("System Work Mode")',
                        '.item-box-rlink:has-text("System Work Mode")'
                    ]
                    
                    system_work_mode_element = None
                    system_found_selector = None
                    
                    for i, selector in enumerate(system_work_mode_selectors):
                        try:
                            self.logger.debug(f"Trying System Work Mode selector {i+1}/{len(system_work_mode_selectors)}: {selector}")
                            system_work_mode_element = self.page.query_selector(selector)
                            if system_work_mode_element:
                                is_visible = system_work_mode_element.is_visible()
                                if is_visible:
                                    self.logger.info(f"Found System Work Mode with selector: {selector}")
                                    system_found_selector = selector
                                    break
                        except Exception as e:
                            self.logger.debug(f"Error with selector: {e}")
                            continue
                    
                    if system_work_mode_element:
                        self.logger.info(f"Found System Work Mode using selector: {system_found_selector}")
                        
                        # Click the System Work Mode link
                        self.logger.info("Clicking System Work Mode link...")
                        system_work_mode_element.click()
                        self.page.wait_for_load_state('networkidle')
                        self.page.wait_for_timeout(2000)
                        self.logger.info("Successfully clicked System Work Mode link!")
                        
                        # Save HTML after clicking System Work Mode
                        html_content = self.page.content()
                        html_file = self.cache_dir / f"{html_prefix}system_work_mode_{plant_id}_{inverter_id}.html"
                        with open(html_file, 'w', encoding='utf-8') as f:
                            f.write(html_content)
                        self.logger.info(f"Saved System Work Mode HTML: {html_file}")
                        self._save_screenshot_to_cache(f"{html_prefix}system_work_mode_{plant_id}_{inverter_id}.png")
                        
                        # Now look for TOU switch on the System Work Mode page
                        self.logger.info("Looking for TOU switch element on System Work Mode page...")
                        
                        for i, selector in enumerate(tou_switch_selectors):
                            try:
                                self.logger.debug(f"Trying TOU selector {i+1}/{len(tou_switch_selectors)}: {selector}")
                                tou_element = self.page.query_selector(selector)
                                if tou_element:
                                    is_visible = tou_element.is_visible()
                                    if is_visible:
                                        self.logger.info(f"Found TOU switch with selector: {selector}")
                                        tou_found_selector = selector
                                        break
                            except Exception as e:
                                self.logger.debug(f"Error with selector: {e}")
                                continue
                    else:
                        self.logger.error("Could not find System Work Mode link and TOU switch not found directly")
                        # Save HTML for debugging
                        html_content = self.page.content()
                        html_file = self.cache_dir / f"{html_prefix}tou_not_found_{plant_id}_{inverter_id}.html"
                        with open(html_file, 'w', encoding='utf-8') as f:
                            f.write(html_content)
                        self._save_screenshot_to_cache(f"{html_prefix}tou_not_found_{plant_id}_{inverter_id}.png")
                        return None
            else:
                self.logger.error("Could not find iframe.testiframe")
                # Save HTML for debugging
                html_content = self.page.content()
                html_file = self.cache_dir / f"{html_prefix}iframe_not_found_{plant_id}_{inverter_id}.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                self._save_screenshot_to_cache(f"{html_prefix}iframe_not_found_{plant_id}_{inverter_id}.png")
                return None
            
            return tou_element
        except Exception as e:
            self.logger.error(f"Error handling iframe: {e}")
            return None
    
    def _toggle_tou_switch(self, enable: bool, plant_id: str, inverter_id: str, tou_element: Any) -> bool:
        """
        Toggle the TOU switch
        
        Args:
            enable: True to enable TOU, False to disable
            plant_id: Sol-Ark plant ID (for logging/caching)
            inverter_id: Sol-Ark inverter ID (for logging/caching)
            tou_element: The TOU element found by _navigate_to_tou_settings
            
        Returns:
            bool: True if toggle successful
        """
        self.logger.info(f"Found TOU switch")
        
        # Check current state of the TOU switch using the same approach as reading
        try:
            # Find the container with "Time Of Use" label first, then find the switch within it
            container = self.page.query_selector('.el-form-item:has-text("Time Of Use")')
            checkbox = None
            switch_element = None
            
            if container:
                self.logger.info("Found container with 'Time Of Use' label")
                # Find the switch element within the container
                switch_element = container.query_selector('.el-switch')
                if switch_element:
                    self.logger.info("Found .el-switch element within container")
                    # Find the checkbox input within the switch
                    checkbox = switch_element.query_selector('.el-switch__input')
                    if checkbox:
                        self.logger.info("Found TOU checkbox within switch element")
            
            # Fallback: try direct selector if container approach didn't work
            if not checkbox:
                self.logger.warning("Container approach failed, trying direct selector")
                checkbox = self.page.query_selector('.el-form-item:has-text("Time Of Use") .el-switch__input')
            
            if checkbox:
                is_checked = checkbox.is_checked()
                self.logger.info(f"TOU switch current state: {'ON' if is_checked else 'OFF'}")
                
                # Check if toggle is needed
                toggle_was_needed = (enable and not is_checked) or (not enable and is_checked)
                
                if not toggle_was_needed:
                    self.logger.info(f"TOU switch already in desired state ({'ON' if enable else 'OFF'}), no toggle needed - skipping save")
                    return True  # Return success immediately if no change needed
                
                # Toggle is needed - proceed with toggle and save
                # Save HTML and screenshot before TOU toggle
                html_content = self.page.content()
                html_file = self.cache_dir / f"tou_before_{plant_id}_{inverter_id}.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                self.logger.info(f"Saved TOU before HTML: {html_file}")
                self._save_screenshot_to_cache(f"tou_before_{plant_id}_{inverter_id}.png")
                
                self.logger.info(f"Toggling TOU switch from {'ON' if is_checked else 'OFF'} to {'ON' if enable else 'OFF'}...")
                
                # Try clicking the switch core first (more reliable for styled switches)
                if switch_element:
                    switch_core = switch_element.query_selector('.el-switch__core')
                    if switch_core:
                        self.logger.info("Clicking switch core...")
                        switch_core.click()
                    else:
                        self.logger.info("Switch core not found, clicking switch element...")
                        switch_element.click()
                else:
                    # Fallback: click checkbox directly
                    self.logger.info("Clicking checkbox input...")
                    checkbox.click()
                
                # Wait 1 second after toggling so user can see the change
                self.logger.info("Waiting 1 second after toggle...")
                self.page.wait_for_timeout(1000)
                
                # Check new state
                new_state = checkbox.is_checked()
                self.logger.info(f"TOU switch new state: {'ON' if new_state else 'OFF'}")
                
                # Save HTML and screenshot after TOU toggle
                html_content = self.page.content()
                html_file = self.cache_dir / f"tou_after_{plant_id}_{inverter_id}.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                self.logger.info(f"Saved TOU after HTML: {html_file}")
                self._save_screenshot_to_cache(f"tou_after_{plant_id}_{inverter_id}.png")
                
                if new_state != is_checked:
                    self.logger.info("✅ TOU switch successfully toggled!")
                    return True
                else:
                    self.logger.error("❌ TOU switch did not change state")
                    return False
            else:
                self.logger.error("Could not find checkbox input for TOU switch")
                # Try clicking the switch element directly as last resort
                self.logger.info("Trying to click TOU switch element directly...")
                tou_element.click()
                self.logger.info("Waiting 1 second after toggle...")
                self.page.wait_for_timeout(1000)
                self.logger.info("Clicked TOU switch element")
                return True
        except Exception as e:
            self.logger.error(f"Error toggling TOU switch: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    def _save_tou_changes(self, enable: bool, plant_id: str, inverter_id: str) -> bool:
        """
        Save TOU changes by clicking Save button and verifying
        
        Args:
            enable: The desired TOU state (for verification)
            plant_id: Sol-Ark plant ID (for logging/caching)
            inverter_id: Sol-Ark inverter ID (for logging/caching)
            
        Returns:
            bool: True if save successful
        """
        self.logger.info("Looking for Save button...")
        save_selectors = [
            'button:has-text("Save")',
            '.el-button--primary:has-text("Save")',
            'button.el-button--primary',
            '.save-btn',
            'button[type="button"]:has-text("Save")',
            '.el-button.el-button--primary:has-text("Save")'
        ]
        
        save_button = None
        for selector in save_selectors:
            try:
                save_button = self.page.query_selector(selector)
                if save_button:
                    is_visible = save_button.is_visible()
                    self.logger.info(f"Found save button with selector: {selector}, visible: {is_visible}")
                    if is_visible:
                        break
            except Exception as e:
                self.logger.debug(f"Error with save button selector {selector}: {e}")
                continue
        
        if save_button:
            self.logger.info("Clicking Save button to persist TOU changes...")
            
            # Ensure the button is visible and clickable
            save_button.scroll_into_view_if_needed()
            self.page.wait_for_timeout(500)
            
            # Try multiple click methods for better reliability
            save_clicked = False
            try:
                # Method 1: Regular click
                save_button.click()
                self.logger.info("✅ Save button clicked (method 1)")
                save_clicked = True
            except Exception as e1:
                self.logger.warning(f"Method 1 failed: {e1}")
                try:
                    # Method 2: Force click
                    save_button.click(force=True)
                    self.logger.info("✅ Save button clicked (method 2 - force)")
                    save_clicked = True
                except Exception as e2:
                    self.logger.warning(f"Method 2 failed: {e2}")
                    try:
                        # Method 3: JavaScript click
                        save_button.evaluate('element => element.click()')
                        self.logger.info("✅ Save button clicked (method 3 - JS)")
                        save_clicked = True
                    except Exception as e3:
                        self.logger.error(f"❌ All click methods failed: {e3}")
                        return False
            
            if not save_clicked:
                self.logger.error("❌ Failed to click Save button")
                return False
            
            # Wait for save operation to complete by looking for success indicators
            self.logger.info("Waiting for save operation to complete...")
            
            # Wait for either success indicators or timeout
            success_indicators = [
                '.el-message--success',
                '.success-message',
                '.alert-success',
                '[class*="success"]',
                'text=Success',
                'text=Saved',
                'text=保存成功'
            ]
            
            save_success = False
            try:
                # Wait for any success indicator to appear
                for indicator in success_indicators:
                    try:
                        success_element = self.page.wait_for_selector(indicator, timeout=5000)
                        if success_element and success_element.is_visible():
                            self.logger.info(f"Found success indicator: {indicator}")
                            save_success = True
                            break
                    except:
                        continue
            except:
                # If no success indicator found, assume success after reasonable wait
                self.page.wait_for_timeout(2000)
            
            if save_success:
                self.logger.info("✅ Save operation completed successfully!")
            else:
                self.logger.info("Save button clicked - no explicit success message found")
            
            # Verify the change was actually applied by checking the TOU state again
            self.logger.info("Verifying TOU setting change...")
            self.page.wait_for_timeout(1000)  # Brief wait for page to update
            
            try:
                # Check TOU state again after save
                final_checkbox = self.page.query_selector('.el-switch__input')
                if final_checkbox:
                    final_state = final_checkbox.is_checked()
                    self.logger.info(f"Final TOU switch state after save: {'ON' if final_state else 'OFF'}")
                    
                    if final_state == enable:
                        self.logger.info("✅ TOU setting change verified successfully!")
                        return True
                    else:
                        self.logger.error(f"❌ TOU setting change failed - expected {'ON' if enable else 'OFF'}, got {'ON' if final_state else 'OFF'}")
                        return False
                else:
                    self.logger.warning("Could not verify TOU state after save")
                    return True
            except Exception as e:
                self.logger.warning(f"Error verifying TOU state: {e}")
                return True
        else:
            self.logger.warning("Could not find Save button")
            return True  # Assume success if we can't find save button
    
    def _read_tou_state(self, plant_id: str, inverter_id: str, html_prefix: str = "") -> Optional[bool]:
        """
        Read current TOU state using multiple methods
        
        Args:
            plant_id: Sol-Ark plant ID (for logging/caching)
            inverter_id: Sol-Ark inverter ID (for logging/caching)
            html_prefix: Prefix for HTML cache files
            
        Returns:
            bool: True if TOU is enabled, False if disabled, None if unable to determine
        """
        # Handle iframe if present - navigate to iframe URL (like _navigate_to_tou_settings does)
        original_page = self.page
        try:
            iframe = self.page.query_selector('iframe.testiframe')
            if iframe:
                iframe_src = iframe.get_attribute('src')
                self.logger.info(f"Found iframe with URL: {iframe_src}")
                
                # Navigate directly to the iframe URL (same approach as _navigate_to_tou_settings)
                self.logger.info("Navigating to iframe URL...")
                try:
                    self.page.goto(iframe_src)
                    self.page.wait_for_load_state('networkidle')
                    self.logger.info("Successfully navigated to iframe URL")
                except (PlaywrightTimeoutError, Exception) as e:
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'dns', 'refused', 'unreachable', 'failed to connect']):
                        self.logger.error(f"Network error during iframe navigation: {e}")
                        raise NetworkError(f"Network connectivity issue: {e}") from e
                    raise
                
                # Save HTML after navigating to iframe
                html_content = self.page.content()
                html_file = self.cache_dir / f"{html_prefix}iframe_page_{plant_id}_{inverter_id}.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                self.logger.info(f"Saved iframe page HTML: {html_file}")
                self._save_screenshot_to_cache(f"{html_prefix}iframe_page_{plant_id}_{inverter_id}.png")
                
                page_to_use = self.page
            else:
                self.logger.debug("No iframe found, using main page")
                page_to_use = self.page
        except Exception as e:
            self.logger.warning(f"Error handling iframe: {e}")
            page_to_use = self.page
        
        # Find TOU switch (use page_to_use which is now the iframe page or main page)
        tou_element = None
        checkbox_element = None
        try:
            # Save HTML before looking for TOU switch
            html_content = page_to_use.content()
            html_file = self.cache_dir / f"{html_prefix}tou_before_{plant_id}_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"Saved TOU page HTML before search: {html_file}")
            self._save_screenshot_to_cache(f"{html_prefix}tou_before_{plant_id}_{inverter_id}.png")
            
            # Strategy: Find the form item with "Time Of Use" label first, then find the checkbox within it
            # This ensures we get the correct checkbox, not other switches on the page
            container_selectors = [
                '.el-form-item:has-text("Time Of Use")',
                'div:has-text("Time Of Use")',
                'label:has-text("Time Of Use")'
            ]
            
            for container_selector in container_selectors:
                try:
                    container = page_to_use.query_selector(container_selector)
                    if container:
                        self.logger.info(f"Found container with 'Time Of Use' using selector: {container_selector}")
                        # Look for the switch element first within the container
                        switch_element = container.query_selector('.el-switch')
                        if switch_element:
                            self.logger.info("Found .el-switch element within container")
                            # Then find the checkbox input within the switch
                            checkbox_element = switch_element.query_selector('.el-switch__input')
                            if checkbox_element:
                                tou_element = checkbox_element
                                self.logger.info("Found TOU checkbox within switch element")
                                break
                        # Fallback: try direct checkbox search within container
                        if not checkbox_element:
                            checkbox_element = container.query_selector('.el-switch__input')
                            if checkbox_element:
                                tou_element = checkbox_element
                                self.logger.info("Found TOU checkbox directly in container")
                                break
                except Exception as e:
                    self.logger.debug(f"Error with container selector {container_selector}: {e}")
                    continue
            
            # If container approach didn't work, try direct selectors (but these may match wrong checkbox)
            if not checkbox_element:
                self.logger.warning("Container approach failed, trying direct selectors (may match wrong checkbox)")
                tou_switch_selectors = [
                    '.el-form-item:has-text("Time Of Use") .el-switch__input',  # Most specific - checkbox in form item
                    'label:has-text("Time Of Use") input',  # Checkbox inside label
                ]
                
                for selector in tou_switch_selectors:
                    try:
                        checkbox_element = page_to_use.query_selector(selector)
                        if checkbox_element:
                            tou_element = checkbox_element
                            self.logger.info(f"Found TOU checkbox with selector: {selector}")
                            break
                    except Exception as e:
                        self.logger.debug(f"Error with selector {selector}: {e}")
                        continue
            
            # If TOU switch not found directly, try System Work Mode (like _navigate_to_tou_settings does)
            if not checkbox_element:
                self.logger.info("TOU switch not found directly, looking for System Work Mode link...")
                
                system_work_mode_selectors = [
                    'text=System Work Mode',
                    'span:has-text("System Work Mode")',
                    'el-link:has-text("System Work Mode")',
                    '.item-box:has-text("System Work Mode")',
                    '.item-box-rlink:has-text("System Work Mode")'
                ]
                
                system_work_mode_element = None
                system_found_selector = None
                
                for i, selector in enumerate(system_work_mode_selectors):
                    try:
                        self.logger.debug(f"Trying System Work Mode selector {i+1}/{len(system_work_mode_selectors)}: {selector}")
                        system_work_mode_element = page_to_use.query_selector(selector)
                        if system_work_mode_element:
                            is_visible = system_work_mode_element.is_visible()
                            if is_visible:
                                self.logger.info(f"Found System Work Mode with selector: {selector}")
                                system_found_selector = selector
                                break
                    except Exception as e:
                        self.logger.debug(f"Error with selector: {e}")
                        continue
                
                if system_work_mode_element:
                    self.logger.info(f"Found System Work Mode using selector: {system_found_selector}")
                    
                    # Click the System Work Mode link
                    self.logger.info("Clicking System Work Mode link...")
                    system_work_mode_element.click()
                    page_to_use.wait_for_load_state('networkidle')
                    page_to_use.wait_for_timeout(2000)
                    self.logger.info("Successfully clicked System Work Mode link!")
                    
                    # Save HTML after clicking System Work Mode
                    html_content = page_to_use.content()
                    html_file = self.cache_dir / f"{html_prefix}system_work_mode_{plant_id}_{inverter_id}.html"
                    with open(html_file, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    self.logger.info(f"Saved System Work Mode HTML: {html_file}")
                    self._save_screenshot_to_cache(f"{html_prefix}system_work_mode_{plant_id}_{inverter_id}.png")
                    
                    # Now look for TOU switch on the System Work Mode page
                    self.logger.info("Looking for TOU switch element on System Work Mode page...")
                    
                    # Try container selectors again
                    for container_selector in container_selectors:
                        try:
                            container = page_to_use.query_selector(container_selector)
                            if container:
                                self.logger.info(f"Found container with 'Time Of Use' using selector: {container_selector}")
                                switch_element = container.query_selector('.el-switch')
                                if switch_element:
                                    self.logger.info("Found .el-switch element within container")
                                    checkbox_element = switch_element.query_selector('.el-switch__input')
                                    if checkbox_element:
                                        tou_element = checkbox_element
                                        self.logger.info("Found TOU checkbox within switch element after System Work Mode")
                                        break
                                if not checkbox_element:
                                    checkbox_element = container.query_selector('.el-switch__input')
                                    if checkbox_element:
                                        tou_element = checkbox_element
                                        self.logger.info("Found TOU checkbox directly in container after System Work Mode")
                                        break
                        except Exception as e:
                            self.logger.debug(f"Error with container selector {container_selector}: {e}")
                            continue
                    
                    # If still not found, try direct selectors
                    if not checkbox_element:
                        for selector in tou_switch_selectors:
                            try:
                                checkbox_element = page_to_use.query_selector(selector)
                                if checkbox_element:
                                    tou_element = checkbox_element
                                    self.logger.info(f"Found TOU checkbox with selector: {selector} after System Work Mode")
                                    break
                            except Exception as e:
                                self.logger.debug(f"Error with selector {selector}: {e}")
                                continue
                else:
                    self.logger.error("Could not find System Work Mode link and TOU switch not found directly")
                    # Save HTML for debugging
                    html_content = page_to_use.content()
                    html_file = self.cache_dir / f"{html_prefix}tou_not_found_{plant_id}_{inverter_id}.html"
                    with open(html_file, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    self.logger.info(f"Saved TOU page HTML when not found: {html_file}")
                    # Restore original page reference
                    self.page = original_page
                    return None
        except Exception as e:
            self.logger.error(f"Error finding TOU switch: {e}")
            # Restore original page reference
            self.page = original_page
            return None
        
        if not checkbox_element:
            self.logger.error("Could not find TOU switch checkbox")
            # Save HTML for debugging
            html_content = page_to_use.content()
            html_file = self.cache_dir / f"{html_prefix}tou_not_found_{plant_id}_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"Saved TOU page HTML when not found: {html_file}")
            # Restore original page reference
            self.page = original_page
            return None
        
        # Read current state - try multiple methods
        try:
            is_checked = None
            
            # Method 1: Try is_checked() on the checkbox element
            try:
                is_checked = checkbox_element.is_checked()
                self.logger.info(f"Read TOU state using is_checked(): {'ON' if is_checked else 'OFF'}")
            except Exception as e:
                self.logger.warning(f"Could not use is_checked(): {e}")
            
            # Method 2: If that failed, try reading the checked attribute or parent switch
            if is_checked is None:
                try:
                    checked_attr = checkbox_element.get_attribute('checked')
                    if checked_attr is not None:
                        is_checked = True
                        self.logger.info("Read TOU state from 'checked' attribute: ON")
                    else:
                        # Try to find the parent switch element using evaluate
                        try:
                            switch_aria_checked = page_to_use.evaluate("""() => {
                                const checkbox = document.querySelector('.el-form-item:has-text("Time Of Use") .el-switch__input');
                                if (checkbox) {
                                    const switchEl = checkbox.closest('.el-switch');
                                    return switchEl ? switchEl.getAttribute('aria-checked') : null;
                                }
                                return null;
                            }""")
                            if switch_aria_checked == 'true':
                                is_checked = True
                                self.logger.info("Read TOU state from parent switch aria-checked: ON")
                            elif switch_aria_checked == 'false':
                                is_checked = False
                                self.logger.info("Read TOU state from parent switch aria-checked: OFF")
                        except Exception as e2:
                            self.logger.debug(f"Could not read parent switch: {e2}")
                except Exception as e:
                    self.logger.warning(f"Could not read checked attribute: {e}")
            
            # Method 3: Try finding the parent switch and reading its aria-checked or class
            if is_checked is None:
                try:
                    # If we have checkbox_element, try to find its parent switch
                    if checkbox_element:
                        # Use evaluate to find the closest .el-switch parent
                        switch_info = page_to_use.evaluate("""(checkbox) => {
                            const switchEl = checkbox.closest('.el-switch');
                            if (switchEl) {
                                return {
                                    ariaChecked: switchEl.getAttribute('aria-checked'),
                                    hasCheckedClass: switchEl.classList.contains('is-checked')
                                };
                            }
                            return null;
                        }""", checkbox_element)
                        if switch_info:
                            if switch_info.get('ariaChecked') == 'true' or switch_info.get('hasCheckedClass'):
                                is_checked = True
                                self.logger.info("Read TOU state from parent switch (aria-checked or class): ON")
                            elif switch_info.get('ariaChecked') == 'false':
                                is_checked = False
                                self.logger.info("Read TOU state from parent switch aria-checked: OFF")
                    
                    # Fallback: Find the switch element directly
                    if is_checked is None:
                        switch_element = page_to_use.query_selector('.el-form-item:has-text("Time Of Use") .el-switch')
                        if switch_element:
                            aria_checked = switch_element.get_attribute('aria-checked')
                            if aria_checked == 'true':
                                is_checked = True
                                self.logger.info("Read TOU state from switch aria-checked: ON")
                            elif aria_checked == 'false':
                                is_checked = False
                                self.logger.info("Read TOU state from switch aria-checked: OFF")
                            # Also check if switch has 'is-checked' class
                            if is_checked is None:
                                switch_classes = switch_element.get_attribute('class') or ''
                                if 'is-checked' in switch_classes:
                                    is_checked = True
                                    self.logger.info("Read TOU state from switch 'is-checked' class: ON")
                except Exception as e:
                    self.logger.warning(f"Could not read from switch element: {e}")
            
            if is_checked is None:
                self.logger.error("Could not determine TOU state using any method")
                # Save HTML for debugging
                html_content = page_to_use.content()
                html_file = self.cache_dir / f"{html_prefix}tou_read_error_{plant_id}_{inverter_id}.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                self.logger.info(f"Saved TOU page HTML after read error: {html_file}")
                # Restore original page reference
                self.page = original_page
                return None
            
            self.logger.info(f"TOU switch current state: {'ON' if is_checked else 'OFF'}")
            
            # Save HTML after reading state
            html_content = page_to_use.content()
            html_file = self.cache_dir / f"{html_prefix}tou_after_{plant_id}_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"Saved TOU page HTML after reading: {html_file}")
            
            # Restore original page reference
            self.page = original_page
            return is_checked
        except Exception as e:
            self.logger.error(f"Error reading TOU state: {e}")
            # Restore original page reference
            if hasattr(self, 'page'):
                self.page = original_page
            return None
    
    def _toggle_time_of_use_impl(self, enable: bool, inverter_id: str, plant_id: str = "") -> bool:
        """
        Internal implementation of toggle_time_of_use (must be called from Playwright thread)
        
        Args:
            enable: True to enable TOU, False to disable
            inverter_id: Sol-Ark inverter ID (required - should come from optocoupler config)
            plant_id: Sol-Ark plant ID (required for new navigation flow)
            
        Returns:
            bool: True if toggle successful
            
        Raises:
            NetworkError: If network connectivity issues occur
        """
        # Acquire lock to ensure thread safety for Playwright operations
        with self._playwright_lock:
            try:
                # Require inverter_id parameter - this should come from optocoupler config
                if not inverter_id:
                    self.logger.error("inverter_id parameter is required - should be provided from optocoupler configuration")
                    return False
                
                if not plant_id:
                    self.logger.error("plant_id parameter is required for navigation")
                    return False
                
                self.logger.info(f"Toggling Time of Use to {'ON' if enable else 'OFF'} "
                               f"for inverter {inverter_id} in plant {plant_id}")
                
                if not self.is_logged_in:
                    if not self.login():
                        return False
                
                # Navigate to plant overview page
                if not self._navigate_to_plant_overview(plant_id, inverter_id):
                    return False
                
                # Click on Equipment tab
                if not self._click_equipment_tab(plant_id, inverter_id):
                    return False
                
                # Find and click inverter dropdown
                dropdown_button = self._find_inverter_dropdown(inverter_id, plant_id)
                if not dropdown_button:
                    return False
                
                # Navigate to Parameters Setting
                if not self._navigate_to_parameters_setting(plant_id, inverter_id):
                    return False
                
                # Navigate to TOU settings (handle iframe and System Work Mode)
                tou_element = self._navigate_to_tou_settings(plant_id, inverter_id)
                if not tou_element:
                    self.logger.error("Could not find TOU switch - may not be on System Work Mode page")
                    return False
                
                # Toggle TOU switch
                toggle_result = self._toggle_tou_switch(enable, plant_id, inverter_id, tou_element)
                if not toggle_result:
                    return False
                
                # Save TOU changes
                return self._save_tou_changes(enable, plant_id, inverter_id)
                
            except NetworkError:
                # Re-raise network errors so they can be handled by the integration layer
                raise
            except Exception as e:
                self.logger.error(f"Failed to toggle Time of Use: {e}")
                return False



    


    def _get_time_of_use_state_impl(self, inverter_id: str, plant_id: str = "") -> Optional[bool]:
        """
        Internal implementation of get_time_of_use_state (must be called from Playwright thread)
        
        Args:
            inverter_id: Sol-Ark inverter ID
            plant_id: Sol-Ark plant ID (required for new navigation flow)
            
        Returns:
            bool: True if TOU is enabled, False if disabled, None if unable to determine
        """
        # Acquire lock to ensure thread safety for Playwright operations
        with self._playwright_lock:
            try:
                self.logger.info(f"Reading TOU state for inverter {inverter_id} in plant {plant_id}")
                
                if not plant_id:
                    self.logger.error("plant_id parameter is required for navigation")
                    return None
                
                # Check if browser/page is still valid
                try:
                    if not self.page or self.page.is_closed():
                        self.logger.warning("Page is closed, re-initializing browser...")
                        if not self.initialize() or not self.login():
                            return None
                except Exception as e:
                    self.logger.warning(f"Error checking page state: {e}, re-initializing...")
                    if not self.initialize() or not self.login():
                        return None
                
                if not self.is_logged_in:
                    if not self.login():
                        return None
                
                # Navigate to plant overview page
                if not self._navigate_to_plant_overview(plant_id, inverter_id, "get_state_"):
                    return None
                
                # Click on Equipment tab
                if not self._click_equipment_tab(plant_id, inverter_id, "get_state_"):
                    return None
                
                # Find and click inverter dropdown
                dropdown_button = self._find_inverter_dropdown(inverter_id, plant_id, "get_state_")
                if not dropdown_button:
                    return None
                
                # Navigate to Parameters Setting
                if not self._navigate_to_parameters_setting(plant_id, inverter_id, "get_state_"):
                    return None
                
                # Read TOU state
                return self._read_tou_state(plant_id, inverter_id, "get_state_")
                
            except NetworkError:
                raise
            except Exception as e:
                self.logger.error(f"Failed to read Time of Use state: {e}")
                return None
    
    def toggle_time_of_use(self, enable: bool, inverter_id: str, plant_id: str = "") -> bool:
        """
        Toggle Time of Use setting in inverter settings (thread-safe wrapper)
        
        Args:
            enable: True to enable TOU, False to disable
            inverter_id: Sol-Ark inverter ID (required - should come from optocoupler config)
            plant_id: Sol-Ark plant ID (required for new navigation flow)
            
        Returns:
            bool: True if toggle successful
            
        Raises:
            NetworkError: If network connectivity issues occur
        """
        # If called from Playwright thread, execute directly
        if self._is_playwright_thread():
            return self._toggle_time_of_use_impl(enable, inverter_id, plant_id)
        
        # Otherwise, queue the operation
        future = self._queue_operation('toggle_time_of_use', enable, inverter_id, plant_id)
        try:
            return future.result(timeout=300)  # 5 minute timeout
        except Exception as e:
            # Re-raise NetworkError if that's what happened
            if isinstance(e, NetworkError):
                raise
            # Wrap other exceptions
            raise SolArkCloudError(f"Failed to toggle Time of Use: {e}") from e
    
    def get_time_of_use_state(self, inverter_id: str, plant_id: str = "") -> Optional[bool]:
        """
        Get current Time of Use setting state for an inverter without toggling (thread-safe wrapper)
        
        Args:
            inverter_id: Sol-Ark inverter ID
            plant_id: Sol-Ark plant ID (required for new navigation flow)
            
        Returns:
            bool: True if TOU is enabled, False if disabled, None if unable to determine
        """
        # If called from Playwright thread, execute directly
        if self._is_playwright_thread():
            return self._get_time_of_use_state_impl(inverter_id, plant_id)
        
        # Otherwise, queue the operation
        future = self._queue_operation('get_time_of_use_state', inverter_id, plant_id)
        try:
            return future.result(timeout=300)  # 5 minute timeout
        except Exception as e:
            # Re-raise NetworkError if that's what happened
            if isinstance(e, NetworkError):
                raise
            # Wrap other exceptions
            self.logger.error(f"Failed to read Time of Use state: {e}")
            return None


# Example usage and testing
def main():
    """Example usage of SolArkCloud class"""
    import sys
    
    solark = SolArkCloud()
    
    try:
        # Initialize browser
        if not solark.initialize():
            print("Failed to initialize browser")
            return
        
        # Login
        if not solark.login():
            print("Login failed")
            return
        
        # Test TOU toggle functionality
        test_inverter_id = "2207079903"  # Example inverter ID
        print(f"Testing TOU toggle for inverter {test_inverter_id}")
        
        # Test enabling TOU
        result = solark.toggle_time_of_use(True, test_inverter_id)
        print(f"TOU enable result: {result}")
        
        # Test disabling TOU
        result = solark.toggle_time_of_use(False, test_inverter_id)
        print(f"TOU disable result: {result}")
        
        # Note: sync_data() method not implemented - periodic syncing handled by SolArkIntegration
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            solark.cleanup()
        except Exception:
            pass  # Ignore cleanup errors


if __name__ == "__main__":
    main()
