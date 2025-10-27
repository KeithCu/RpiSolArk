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
import yaml
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError


class SolArkCloudError(Exception):
    """Custom exception for Sol-Ark cloud operations"""
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
        
        # Browser components
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
        self.cache_screenshots = self.solark_config.get('cache_screenshots', False)
        self.session_persistence = self.solark_config['session_persistence']
        self.session_file = self.solark_config['session_file']
        self.session_timeout = self.solark_config['session_timeout']
        
        if not self.username or not self.password:
            self.logger.warning("Sol-Ark credentials not configured in config.yaml")
    
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
            
            playwright = sync_playwright().start()
            self.browser = playwright.chromium.launch(
                headless=self.headless,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            
            self.context = self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
#                viewport={'width': 1920, 'height': 1080},
                java_script_enabled=True
            )
            
            self.page = self.context.new_page()
            
            # Set default timeout
            self.page.set_default_timeout(self.timeout)
            
            self.logger.info("Browser initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {e}")
            return False
    
    def cleanup(self):
        """Cleanup browser resources"""
        try:
            # Save session before closing browser
            if self.is_logged_in and self.session_persistence:
                self._save_session()
            
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            self.logger.info("Browser cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        finally:
            # Reset state
            self.page = None
            self.context = None
            self.browser = None
            self.is_logged_in = False
    
    def login(self) -> bool:
        """
        Login to Sol-Ark cloud platform
        
        Returns:
            bool: True if login successful
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
            
            self.logger.info("Attempting to login to Sol-Ark Cloud...")
            
            # Navigate directly to inverter page - if not logged in, will redirect to login
            inverter_url = f"{self.base_url}/device/inverter"
            self.page.goto(inverter_url)
            self.page.wait_for_load_state('networkidle')
            
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
            self.page.goto(self.base_url)
            self.page.wait_for_load_state('networkidle')
            
            # Restore localStorage and sessionStorage if available
            if local_storage or session_storage:
                try:
                    # Restore localStorage
                    if local_storage:
                        for key, value in local_storage.items():
                            self.page.evaluate(f"localStorage.setItem('{key}', '{value}')")
                        self.logger.info(f"Restored {len(local_storage)} localStorage items")
                    
                    # Restore sessionStorage
                    if session_storage:
                        for key, value in session_storage.items():
                            self.page.evaluate(f"sessionStorage.setItem('{key}', '{value}')")
                        self.logger.info(f"Restored {len(session_storage)} sessionStorage items")
                    
                    # Refresh the page to apply storage changes
                    self.page.reload()
                    self.page.wait_for_load_state('networkidle')
                    
                except Exception as e:
                    self.logger.warning(f"Failed to restore storage data: {e}")
            
            # Wait a moment for the page to fully load
            time.sleep(2)
            
            # Check if we're still logged in by looking for login indicators
            current_url = self.page.url
            if '/login' in current_url:
                self.logger.info("Session restored but still on login page - need to login")
                return False
            
            # Additional check - try to navigate to a protected page
            try:
                self.page.goto(f"{self.base_url}/device/inverter")
                self.page.wait_for_load_state('networkidle')
                time.sleep(1)
                
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
    
    
    
    
    def get_parameters(self) -> Dict[str, Any]:
        """
        Get current parameters from the selected plant
        
        Returns:
            Dictionary of parameter values
        """
        if not self.current_plant_id:
            self.logger.error("No plant selected")
            return {}
        
        try:
            self.logger.info("Fetching plant parameters...")
            
            # Navigate to parameters/settings page
            param_urls = [
                f"{self.base_url}/plant/{self.current_plant_id}/parameters",
                f"{self.base_url}/plant/{self.current_plant_id}/settings",
                f"{self.base_url}/plant/{self.current_plant_id}/config",
                f"{self.base_url}/device/{self.current_plant_id}/parameters"
            ]
            
            for url in param_urls:
                try:
                    self.page.goto(url)
                    self.page.wait_for_load_state('networkidle')
                    
                    # Check if page loaded successfully (not 404)
                    if "404" not in self.page.content():
                        break
                except Exception:
                    continue
            
            # Save parameters page
            if self.cache_pages:
                self._save_page_to_cache(f"parameters_{self.current_plant_id}.html")
            
            # Extract parameters from the page
            parameters = {}
            
            # Look for form inputs, selects, and other parameter elements
            form_elements = self.page.query_selector_all('input, select, textarea')
            
            for element in form_elements:
                try:
                    name = element.get_attribute('name')
                    element_type = element.get_attribute('type')
                    element_id = element.get_attribute('id')
                    
                    if name or element_id:
                        param_name = name or element_id
                        
                        if element_type in ['text', 'number', 'email', 'tel']:
                            value = element.input_value()
                        elif element_type == 'checkbox':
                            value = element.is_checked()
                        elif element_type == 'radio':
                            if element.is_checked():
                                value = element.get_attribute('value')
                            else:
                                continue
                        elif element.tag_name == 'select':
                            value = element.input_value()
                        else:
                            value = element.input_value()
                        
                        parameters[param_name] = value
                        
                except Exception as e:
                    self.logger.debug(f"Error extracting parameter: {e}")
                    continue
            
            self.logger.info(f"Extracted {len(parameters)} parameters")
            return parameters
            
        except Exception as e:
            self.logger.error(f"Failed to get parameters: {e}")
            return {}
    
    def set_parameter(self, param_name: str, value: Any) -> bool:
        """
        Set a specific parameter value
        
        Args:
            param_name: Name of the parameter
            value: Value to set
            
        Returns:
            bool: True if parameter set successfully
        """
        if not self.current_plant_id:
            self.logger.error("No plant selected")
            return False
        
        try:
            self.logger.info(f"Setting parameter {param_name} = {value}")
            
            # Find the parameter element
            element = self.page.query_selector(f'[name="{param_name}"], #{param_name}')
            
            if not element:
                self.logger.error(f"Parameter {param_name} not found")
                return False
            
            element_type = element.get_attribute('type')
            
            # Set the value based on element type
            if element_type in ['text', 'number', 'email', 'tel']:
                element.fill(str(value))
            elif element_type == 'checkbox':
                if value:
                    element.check()
                else:
                    element.uncheck()
            elif element_type == 'radio':
                element.check()
            elif element.tag_name == 'select':
                element.select_option(str(value))
            else:
                element.fill(str(value))
            
            self.logger.info(f"Parameter {param_name} set to {value}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to set parameter {param_name}: {e}")
            return False
    
    def save_parameters(self) -> bool:
        """
        Save current parameter changes
        
        Returns:
            bool: True if save successful
        """
        try:
            self.logger.info("Saving parameters...")
            
            # Look for save button
            save_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                '.save-btn',
                '#save-btn',
                'button:has-text("Save")',
                'button:has-text("Apply")',
                'button:has-text("Update")'
            ]
            
            save_button = None
            for selector in save_selectors:
                save_button = self.page.query_selector(selector)
                if save_button:
                    break
            
            if not save_button:
                self.logger.error("Save button not found")
                return False
            
            # Click save button
            save_button.click()
            
            # Wait for save confirmation or navigation
            try:
                self.page.wait_for_load_state('networkidle', timeout=10000)
                self.logger.info("Parameters saved successfully")
                return True
            except PlaywrightTimeoutError:
                # Check for success message
                success_indicators = [
                    '.success-message',
                    '.alert-success',
                    '.notification-success',
                    '[class*="success"]'
                ]
                
                for indicator in success_indicators:
                    if self.page.query_selector(indicator):
                        self.logger.info("Parameters saved successfully (success message found)")
                        return True
                
                self.logger.warning("Save completed but no confirmation found")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to save parameters: {e}")
            return False
    
    def sync_data(self) -> Dict[str, Any]:
        """
        Sync data with Sol-Ark cloud
        
        Returns:
            Dictionary containing sync results
        """
        if not self.solark_config['enabled']:
            self.logger.info("Sol-Ark cloud integration disabled")
            return {'status': 'disabled'}
        
        try:
            self.logger.info("Starting Sol-Ark cloud sync...")
            
            if not self.is_logged_in:
                if not self.login():
                    return {'status': 'error', 'message': 'Login failed'}
            
            # Get current parameters
            parameters = self.get_parameters()
            
            sync_result = {
                'status': 'success',
                'timestamp': datetime.now().isoformat(),
                'plant_id': self.current_plant_id,
                'parameters': parameters,
                'parameter_count': len(parameters)
            }
            
            self.last_sync = datetime.now()
            self.logger.info(f"Sync completed successfully - {len(parameters)} parameters")
            
            return sync_result
            
        except Exception as e:
            self.logger.error(f"Sync failed: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def toggle_time_of_use(self, enable: bool, inverter_id: str) -> bool:
        """
        Toggle Time of Use setting in inverter settings
        
        Args:
            enable: True to enable TOU, False to disable
            inverter_id: Sol-Ark inverter ID (required - should come from optocoupler config)
            
        Returns:
            bool: True if toggle successful
        """
        try:
            # Require inverter_id parameter - this should come from optocoupler config
            if not inverter_id:
                self.logger.error("inverter_id parameter is required - should be provided from optocoupler configuration")
                return False
            
            self.logger.info(f"Toggling Time of Use to {'ON' if enable else 'OFF'} "
                           f"for inverter {inverter_id}")
            
            if not self.is_logged_in:
                if not self.login():
                    return False
            
            # Navigate directly to the inverter device page (skip unnecessary redirects)
            inverter_url = f"{self.base_url}/device/inverter"
            
            self.logger.info(f"Navigating directly to inverter device page: {inverter_url}")
            self.page.goto(inverter_url)
            self.page.wait_for_load_state('networkidle')
            
            # Check if we got redirected to login page
            current_url = self.page.url
            if 'login' in current_url or 'signin' in current_url:
                self.logger.info("Redirected to login page, performing login...")
                if not self.login():
                    return False
                # After login, navigate back to inverter page
                self.logger.info("Login successful, navigating back to inverter page...")
                self.page.goto(inverter_url)
                self.page.wait_for_load_state('networkidle')
            
            # Wait for JavaScript to load the inverter list
            self.logger.info("Waiting for inverter list to load...")
            time.sleep(3)  # Give JS time to render
            
            # Download the rendered HTML for analysis
            html_content = self.page.content()
            html_file = self.cache_dir / f"inverter_page_{inverter_id}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"Downloaded rendered HTML to: {html_file}")
            
            # Save screenshot of inverter page
            self._save_screenshot_to_cache(f"inverter_page_{inverter_id}.png")
            
            # Verify we're on the correct page
            current_url = self.page.url
            if 'device/inverter' in current_url:
                self.logger.info(f"Successfully navigated to inverter device page")
            else:
                self.logger.error(f"Failed to navigate to inverter device page. Current URL: {current_url}")
                return False
            
            # Find the specific inverter row by SN
            self.logger.info(f"Looking for inverter {inverter_id}...")
            
            # Wait for the table to load
            self.page.wait_for_selector('.el-table__body', timeout=10000)
            
            # Find the inverter row by looking for the SN in the table
            inverter_row = None
            try:
                # Look for the specific inverter SN in the table
                sn_selector = f"text={inverter_id}"
                self.page.wait_for_selector(sn_selector, timeout=10000)
                
                # Find the row containing this SN
                inverter_row = self.page.query_selector(f"tr:has-text('{inverter_id}')")
                if inverter_row:
                    self.logger.info(f"Found inverter row for {inverter_id}")
                else:
                    self.logger.error(f"Could not find inverter row for {inverter_id}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Error finding inverter row: {e}")
                return False
            
            # Click on the "More" dropdown button for this inverter
            self.logger.info(f"Clicking on 'More' dropdown for inverter {inverter_id}...")
            
            try:
                # First, scroll the table to make sure the dropdown column is visible
                self.logger.info("Scrolling table to ensure dropdown is visible...")
                self.page.evaluate("document.querySelector('.el-table__body-wrapper').scrollLeft = 1000")
                time.sleep(1)
                
                # Find dropdown button in the specific inverter row
                dropdown_button = None
                try:
                    # Look for dropdowns in rows that contain our inverter ID
                    inverter_rows = self.page.query_selector_all(f'tr:has-text("{inverter_id}")')
                    self.logger.info(f"Found {len(inverter_rows)} rows containing inverter {inverter_id}")
                    
                    for i, row in enumerate(inverter_rows):
                        # Check if this row actually contains our inverter ID
                        row_text = row.text_content()
                        if inverter_id in row_text:
                            self.logger.info(f"Row {i+1} contains inverter {inverter_id}")
                            # Look for dropdown in this specific row
                            dropdown_in_row = row.query_selector('.w24.h30.flex-align-around.el-dropdown-selfdefine')
                            if dropdown_in_row and dropdown_in_row.is_visible():
                                dropdown_button = dropdown_in_row
                                self.logger.info(f"Found dropdown in row {i+1}")
                                break
                except Exception as e:
                    self.logger.error(f"Error finding dropdown in specific row: {e}")
                    return False
                
                if dropdown_button:
                    # Ensure the button is in view
                    dropdown_button.scroll_into_view_if_needed()
                    time.sleep(0.5)
                    
                    # Click the dropdown
                    dropdown_button.click()
                    self.logger.info("Clicked on 'More' dropdown")
                    time.sleep(2)  # Wait for dropdown to appear
                else:
                    self.logger.error("Could not find 'More' dropdown button with any selector")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Error clicking dropdown: {e}")
                return False
            
            # Navigate to "Parameters Setting" using keyboard navigation
            self.logger.info("Navigating to 'Parameters Setting' using keyboard...")
            
            try:
                # Wait for the dropdown menu to appear and be visible
                self.logger.info("Waiting for dropdown menu to appear...")
                
                # Wait a bit for the menu to appear
                time.sleep(2)
                
                # Check for dropdown menus
                all_menus = self.page.query_selector_all('.el-dropdown-menu')
                self.logger.info(f"Found {len(all_menus)} dropdown menus on page")
                
                visible_menu = None
                for i, menu in enumerate(all_menus):
                    try:
                        is_visible = menu.is_visible()
                        if is_visible and not visible_menu:
                            visible_menu = menu
                            self.logger.info(f"Found visible dropdown menu {i+1}")
                            break
                    except:
                        continue
                
                if not visible_menu:
                    self.logger.error("No visible dropdown menu found")
                    return False
                
                # Use keyboard navigation - much more reliable than DOM clicking
                self.logger.info("Using keyboard navigation to select 'Parameters Setting'...")
                
                # First arrow down to wake up the menu and highlight first item
                self.logger.info("Pressing ↓ to wake up menu...")
                self.page.keyboard.press('ArrowDown')
                time.sleep(0.5)
                
                # Second arrow down to go to Parameters Setting
                self.logger.info("Pressing ↓ once more to reach Parameters Setting...")
                self.page.keyboard.press('ArrowDown')
                time.sleep(0.5)
                
                # Press Enter to select Parameters Setting
                self.logger.info("Pressing Enter to select Parameters Setting...")
                self.page.keyboard.press('Enter')
                self.logger.info("Successfully navigated to 'Parameters Setting' using keyboard!")
                time.sleep(3)  # Wait for parameters page to load
                    
            except Exception as e:
                self.logger.error(f"Error clicking Parameters Setting: {e}")
                return False
            
            self.logger.info(f"Successfully navigated to parameters page for inverter {inverter_id}")
            
            # Save screenshot of parameters page
            self._save_screenshot_to_cache(f"parameters_page_{inverter_id}.png")
            
            # Wait for parameters page to load and look for iframe
            self.logger.info("Waiting for parameters page to load...")
            time.sleep(3)  # Wait for content to load
            
            # Look for the iframe that contains the actual settings
            self.logger.info("Looking for settings iframe...")
            try:
                iframe_element = self.page.query_selector('iframe.testiframe')
                if iframe_element:
                    iframe_src = iframe_element.get_attribute('src')
                    self.logger.info(f"Found iframe with URL: {iframe_src}")
                    
                    # Navigate directly to the iframe URL
                    self.logger.info("Navigating to iframe URL...")
                    self.page.goto(iframe_src)
                    time.sleep(3)  # Wait for iframe content to load
                    self.logger.info("Successfully navigated to iframe URL")
                    
                    # First, click on "System Work Mode" to access the TOU settings
                    self.logger.info("Looking for System Work Mode link...")
                    
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
                            self.logger.debug(f"Trying selector {i+1}/{len(system_work_mode_selectors)}: {selector}")
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
                        time.sleep(3)  # Wait for the page to load
                        self.logger.info("Successfully clicked System Work Mode link!")
                        
                        # Now look for TOU switch on the System Work Mode page
                        self.logger.info("Looking for TOU switch element...")
                        
                        # Specific selectors for the TOU switch we found in the HTML
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
                                self.logger.debug(f"Trying selector {i+1}/{len(tou_switch_selectors)}: {selector}")
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
                        self.logger.error("Could not find System Work Mode link")
                        return False
                else:
                    self.logger.error("Could not find iframe.testiframe")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Error handling iframe: {e}")
                return False
            
            if tou_element:
                self.logger.info(f"Found TOU switch using selector: {tou_found_selector}")
                
                # Check current state of the TOU switch
                try:
                    # Try to find the actual checkbox input
                    checkbox = self.page.query_selector('.el-switch__input')
                    
                    if checkbox:
                        is_checked = checkbox.is_checked()
                        self.logger.info(f"TOU switch current state: {'ON' if is_checked else 'OFF'}")
                        
                        # Save screenshot before TOU toggle
                        self._save_screenshot_to_cache(f"tou_before_{inverter_id}.png")
                        
                        # Toggle the TOU switch if needed
                        if (enable and not is_checked) or (not enable and is_checked):
                            self.logger.info("Toggling TOU switch...")
                            
                            # Try clicking the switch core instead of the checkbox input
                            switch_core = self.page.query_selector('.el-switch__core')
                            if switch_core:
                                self.logger.info("Clicking switch core...")
                                switch_core.click()
                            else:
                                self.logger.info("Clicking checkbox input...")
                                checkbox.click()
                            
                            # Wait for the switch to update and register the change
                            time.sleep(2)
                            
                            # Check new state
                            new_state = checkbox.is_checked()
                            self.logger.info(f"TOU switch new state: {'ON' if new_state else 'OFF'}")
                            
                            # Save screenshot after TOU toggle
                            self._save_screenshot_to_cache(f"tou_after_{inverter_id}.png")
                            
                            if new_state != is_checked:
                                self.logger.info("TOU switch successfully toggled!")
                            else:
                                self.logger.error("TOU switch did not change state")
                        else:
                            self.logger.info(f"TOU switch already in desired state ({'ON' if enable else 'OFF'})")
                    else:
                        self.logger.error("Could not find checkbox input for TOU switch")
                        # Try clicking the switch element directly
                        self.logger.info("Trying to click TOU switch element directly...")
                        tou_element.click()
                        time.sleep(1)
                        self.logger.info("Clicked TOU switch element")
                        
                except Exception as e:
                    self.logger.error(f"Error toggling TOU switch: {e}")
                
                # Now look for and click the Save button
                self.logger.info("Looking for Save button...")
                save_selectors = [
                    'button:has-text("Save")',
                    '.el-button--primary:has-text("Save")',
                    'button.el-button--primary',
                    '.save-btn'
                ]
                
                save_button = None
                for selector in save_selectors:
                    try:
                        save_button = self.page.query_selector(selector)
                        if save_button and save_button.is_visible():
                            self.logger.info(f"Found save button with selector: {selector}")
                            break
                    except:
                        continue
                
                if save_button:
                    self.logger.info("Clicking Save button...")
                    
                    # Ensure the button is visible and clickable
                    save_button.scroll_into_view_if_needed()
                    time.sleep(0.5)
                    
                    # Try multiple click methods for better reliability
                    try:
                        # Method 1: Regular click
                        save_button.click()
                        self.logger.info("Save button clicked (method 1)")
                    except Exception as e1:
                        self.logger.warning(f"Method 1 failed: {e1}")
                        try:
                            # Method 2: Force click
                            save_button.click(force=True)
                            self.logger.info("Save button clicked (method 2 - force)")
                        except Exception as e2:
                            self.logger.warning(f"Method 2 failed: {e2}")
                            try:
                                # Method 3: JavaScript click
                                save_button.evaluate('element => element.click()')
                                self.logger.info("Save button clicked (method 3 - JS)")
                            except Exception as e3:
                                self.logger.error(f"All click methods failed: {e3}")
                                return False
                    
                    # Wait longer for save to register and page to update
                    self.logger.info("Waiting for save operation to complete...")
                    time.sleep(5)  # Increased wait time
                    
                    # Check for success indicators
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
                    for indicator in success_indicators:
                        try:
                            success_element = self.page.query_selector(indicator)
                            if success_element and success_element.is_visible():
                                self.logger.info(f"Found success indicator: {indicator}")
                                save_success = True
                                break
                        except:
                            continue
                    
                    if save_success:
                        self.logger.info("✅ Save operation completed successfully!")
                    else:
                        self.logger.info("Save button clicked - no explicit success message found")
                    
                    # Verify the change was actually applied by checking the TOU state again
                    self.logger.info("Verifying TOU setting change...")
                    time.sleep(2)  # Wait for page to update
                    
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
            else:
                self.logger.error("Could not find TOU switch - may not be on System Work Mode page")
                return False
            
        except Exception as e:
            self.logger.error(f"Failed to toggle Time of Use: {e}")
            return False

    def toggle_time_of_use_threaded(self, enable: bool, inverter_id: str) -> bool:
        """
        Threaded Time of Use toggle - runs the synchronous method in a thread
        
        Args:
            enable: True to enable TOU, False to disable
            inverter_id: Sol-Ark inverter ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        result = [False]  # Use list to allow modification in thread
        
        def run_toggle():
            try:
                result[0] = self.toggle_time_of_use(enable, inverter_id)
            except Exception as e:
                self.logger.error(f"Error in threaded TOU toggle: {e}")
                result[0] = False
        
        thread = threading.Thread(target=run_toggle)
        thread.start()
        thread.join()
        
        return result[0]

    def apply_parameter_changes_threaded(self, changes: Dict[str, Any], inverter_id: str = None) -> bool:
        """
        Threaded parameter changes - runs the synchronous method in a thread
        
        Args:
            changes: Dictionary of parameter changes
            inverter_id: Sol-Ark inverter ID (optional, for logging)
            
        Returns:
            bool: True if successful, False otherwise
        """
        result = [False]  # Use list to allow modification in thread
        
        def run_changes():
            try:
                result[0] = self.apply_parameter_changes(changes)
            except Exception as e:
                self.logger.error(f"Error in threaded parameter changes: {e}")
                result[0] = False
        
        thread = threading.Thread(target=run_changes)
        thread.start()
        thread.join()
        
        return result[0]

    def apply_parameter_changes(self, changes: Dict[str, Any]) -> bool:
        """
        Apply multiple parameter changes
        
        Args:
            changes: Dictionary of parameter changes
            
        Returns:
            bool: True if all changes applied successfully
        """
        if not self.solark_config['parameter_changes']['enabled']:
            self.logger.info("Parameter changes disabled")
            return False
        
        dry_run = self.solark_config['parameter_changes']['dry_run']
        
        try:
            self.logger.info(f"Applying {len(changes)} parameter changes (dry_run={dry_run})")
            
            if not self.is_logged_in:
                if not self.login():
                    return False
            
            
            # Get current parameters for backup
            if self.solark_config['parameter_changes']['backup_before_change']:
                current_params = self.get_parameters()
                backup_file = self.cache_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(backup_file, 'w') as f:
                    json.dump(current_params, f, indent=2)
                self.logger.info(f"Backup saved to {backup_file}")
            
            # Apply changes
            success_count = 0
            for param_name, value in changes.items():
                if dry_run:
                    self.logger.info(f"DRY RUN: Would set {param_name} = {value}")
                    success_count += 1
                else:
                    if self.set_parameter(param_name, value):
                        success_count += 1
                    else:
                        self.logger.error(f"Failed to set parameter {param_name}")
            
            # Save changes if not dry run
            if not dry_run and success_count > 0:
                if self.save_parameters():
                    self.logger.info(f"Successfully applied {success_count}/{len(changes)} parameter changes")
                    return True
                else:
                    self.logger.error("Failed to save parameter changes")
                    return False
            else:
                self.logger.info(f"Dry run completed - {success_count}/{len(changes)} changes would be applied")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to apply parameter changes: {e}")
            return False
    


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
        
        # Sync data
        sync_result = solark.sync_data()
        print(f"Sync result: {sync_result}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            solark.cleanup()
        except Exception:
            pass  # Ignore cleanup errors


if __name__ == "__main__":
    main()
