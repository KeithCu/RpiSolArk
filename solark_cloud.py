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
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import asyncio
import psutil
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError


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
        self.current_plant_id = None
        self.last_sync = None
        
        # Configuration
        self.base_url = self.solark_config['base_url']
        self.username = self.solark_config['username']
        self.password = self.solark_config['password']
        self.plant_id = self.solark_config['plant_id']
        self.timeout = self.solark_config['timeout'] * 1000  # Convert to ms
        self.retry_attempts = self.solark_config['retry_attempts']
        self.headless = self.solark_config['headless']
        self.cache_pages = self.solark_config['cache_pages']
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
    
    async def initialize(self) -> bool:
        """
        Initialize browser and context
        
        Returns:
            bool: True if initialization successful
        """
        try:
            self.logger.info("Initializing Sol-Ark Cloud browser...")
            
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=self.headless,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            
            self.context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
#                viewport={'width': 1920, 'height': 1080},
                java_script_enabled=True
            )
            
            self.page = await self.context.new_page()
            
            # Set default timeout
            self.page.set_default_timeout(self.timeout)
            
            self.logger.info("Browser initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup browser resources"""
        try:
            # Save session before closing browser
            if self.is_logged_in and self.session_persistence:
                await self._save_session()
            
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            self.logger.info("Browser cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        finally:
            # Reset state
            self.page = None
            self.context = None
            self.browser = None
            self.is_logged_in = False
    
    async def login(self) -> bool:
        """
        Login to Sol-Ark cloud platform
        
        Returns:
            bool: True if login successful
        """
        if not self.username or not self.password:
            self.logger.error("Username or password not configured")
            return False
        
        try:
            # Try to restore existing session first
            if self.session_persistence:
                session_data = self._load_session()
                if session_data:
                    self.logger.info("Attempting to restore existing session...")
                    if await self._restore_session(session_data):
                        # Verify we're actually logged in
                        if await self._is_logged_in():
                            self.is_logged_in = True
                            self.logger.info("Successfully restored session - no login needed")
                            return True
                        else:
                            self.logger.info("Session restored but not logged in - proceeding with fresh login")
                    else:
                        self.logger.info("Failed to restore session - proceeding with fresh login")
            
            self.logger.info("Attempting to login to Sol-Ark Cloud...")
            
            # Navigate to login page
            await self.page.goto(f"{self.base_url}/login")
            await self.page.wait_for_load_state('networkidle')
            
            # Wait for JavaScript to load and form elements to be ready
            await self.page.wait_for_selector('input[placeholder="Please input your E-mail"]', timeout=10000)
            
            # Save login page for analysis
            if self.cache_pages:
                await self._save_page_to_cache("login.html")
            
            # Fill login form
            # Email field (no name attribute, just placeholder)
            await self.page.fill('input[placeholder="Please input your E-mail"]', self.username)
            # Password field
            await self.page.fill('input[name="txtPassword"]', self.password)
            
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
                    terms_checkbox = await self.page.query_selector(selector)
                    if terms_checkbox:
                        # Check if it's visible
                        is_visible = await terms_checkbox.is_visible()
                        if is_visible:
                            break
                        else:
                            # Try to make it visible by clicking the label
                            label = await self.page.query_selector('label.el-checkbox')
                            if label:
                                await label.click()
                                break
                except Exception:
                    continue
            
            if terms_checkbox:
                try:
                    await terms_checkbox.check()
                    self.logger.info("Terms checkbox checked")
                except Exception as e:
                    self.logger.warning(f"Could not check terms checkbox: {e}")
                    # Try clicking the label instead
                    try:
                        label = await self.page.query_selector('label.el-checkbox')
                        if label:
                            await label.click()
                            self.logger.info("Terms checkbox clicked via label")
                    except Exception as e2:
                        self.logger.warning(f"Could not click terms checkbox label: {e2}")
                
                # Wait a moment for the button to become enabled
                await self.page.wait_for_timeout(1000)
            
            # Look for and click login button
            login_button = await self.page.query_selector('button:has-text("Log In")')
            if login_button:
                # Check if button is enabled
                is_disabled = await login_button.get_attribute('disabled')
                if not is_disabled:
                    await login_button.click()
                else:
                    self.logger.error("Login button is disabled - terms agreement may not be checked")
                    return False
            else:
                self.logger.error("Login button not found")
                return False
            
            # Wait for navigation or success indicator
            try:
                await self.page.wait_for_url(f"{self.base_url}/dashboard", timeout=10000)
                self.is_logged_in = True
                self.logger.info("Login successful")
                
                # Save session after successful login
                if self.session_persistence:
                    await self._save_session()
                
                # Save dashboard page
                if self.cache_pages:
                    await self._save_page_to_cache("dashboard.html")
                
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
                        await self._save_session()
                    
                    return True
                    
        except Exception as e:
            self.logger.error(f"Login failed: {e}")
            return False
    
    async def _save_page_to_cache(self, filename: str):
        """Save current page content to cache directory"""
        try:
            content = await self.page.content()
            cache_file = self.cache_dir / filename
            with open(cache_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.debug(f"Saved page to cache: {cache_file}")
        except Exception as e:
            self.logger.error(f"Failed to save page to cache: {e}")
    
    async def _save_session(self):
        """Save current session data to file"""
        if not self.session_persistence or not self.context:
            return
        
        try:
            session_data = {
                'timestamp': datetime.now().isoformat(),
                'cookies': await self.context.cookies(),
                'base_url': self.base_url,
                'username': self.username
            }
            
            with open(self.session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            self.logger.info(f"Session saved to {self.session_file}")
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
    
    async def _restore_session(self, session_data: Dict[str, Any]) -> bool:
        """Restore session from saved data"""
        try:
            if not self.context:
                return False
            
            # Set cookies
            await self.context.add_cookies(session_data['cookies'])
            
            # Navigate to base URL to establish session
            await self.page.goto(self.base_url)
            await self.page.wait_for_load_state('networkidle')
            
            # Check if we're still logged in by looking for login indicators
            current_url = self.page.url
            if '/login' in current_url:
                self.logger.info("Session restored but still on login page - need to login")
                return False
            
            self.logger.info("Session restored successfully")
            return True
        except Exception as e:
            self.logger.warning(f"Failed to restore session: {e}")
            return False
    
    async def _is_logged_in(self) -> bool:
        """Check if currently logged in by looking for login indicators"""
        try:
            current_url = self.page.url
            if '/login' in current_url:
                return False
            
            # Look for elements that indicate we're logged in
            logged_in_indicators = [
                '.user-info',
                '.logout',
                '.profile',
                '[data-testid="user-menu"]',
                '.navbar .user'
            ]
            
            for indicator in logged_in_indicators:
                try:
                    element = await self.page.query_selector(indicator)
                    if element and await element.is_visible():
                        return True
                except:
                    continue
            
            # If we're on a page that requires login and no login indicators found, assume logged in
            if any(path in current_url for path in ['/plants', '/dashboard', '/overview']):
                return True
            
            return False
        except Exception as e:
            self.logger.debug(f"Error checking login status: {e}")
            return False
    
    def get_browser_memory_usage(self) -> Dict[str, Any]:
        """Get memory usage information for browser processes"""
        try:
            current_process = psutil.Process()
            process_memory = current_process.memory_info()
            
            # Find browser processes (Chrome/Chromium)
            browser_processes = []
            total_browser_memory = 0
            
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    proc_info = proc.info
                    if proc_info['name'] and any(browser in proc_info['name'].lower() 
                                               for browser in ['chrome', 'chromium', 'playwright']):
                        memory_mb = proc_info['memory_info'].rss / 1024 / 1024
                        browser_processes.append({
                            'pid': proc_info['pid'],
                            'name': proc_info['name'],
                            'memory_mb': round(memory_mb, 2)
                        })
                        total_browser_memory += memory_mb
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            return {
                'main_process_memory_mb': round(process_memory.rss / 1024 / 1024, 2),
                'browser_processes': browser_processes,
                'total_browser_memory_mb': round(total_browser_memory, 2),
                'total_memory_mb': round((process_memory.rss / 1024 / 1024) + total_browser_memory, 2)
            }
        except Exception as e:
            self.logger.error(f"Failed to get browser memory usage: {e}")
            return {}
    
    async def get_plants(self) -> List[Dict[str, Any]]:
        """
        Get list of available plants
        
        Returns:
            List of plant information dictionaries
        """
        if not self.is_logged_in:
            self.logger.error("Not logged in")
            return []
        
        try:
            self.logger.info("Fetching plant list...")
            
            # Start from current page (where login redirected us)
            current_url = self.page.url
            self.logger.info(f"Starting from current page: {current_url}")
            
            # If we're not on the plants page, navigate to it
            if '/plants' not in current_url:
                self.logger.info("Navigating to plants page...")
                await self.page.goto(f"{self.base_url}/plants")
                await self.page.wait_for_load_state('networkidle')
                current_url = self.page.url
                self.logger.info(f"Now on: {current_url}")
            else:
                # Wait for the page to be fully loaded
                await self.page.wait_for_load_state('networkidle')
            
            # Save plants page
            if self.cache_pages:
                await self._save_page_to_cache("plants_dashboard.html")
            
            # Look for plant elements or create from current page
            plants = []
            
            # If we're on a plant page, create a plant entry from the current page
            if '/plants' in current_url:
                import re
                # Try different URL patterns
                url_match = re.search(r'/plants/overview/(\d+)/(\d+)', current_url)
                if url_match:
                    plant_id = f"{url_match.group(1)}_{url_match.group(2)}"
                else:
                    # If we're just on /plants, try to find plant info from the page
                    plant_id = "default_plant"
                
                # Try to get plant name from the page
                plant_name = "Unknown Plant"
                try:
                    # Look for plant name in various places
                    name_selectors = [
                        '.breadcrumb .breadcrumb',
                        '.plant-info .name',
                        '.plant-name',
                        'h1',
                        'h2',
                        '.title'
                    ]
                    
                    for selector in name_selectors:
                        name_element = await self.page.query_selector(selector)
                        if name_element:
                            name_text = await name_element.text_content()
                            if name_text and len(name_text.strip()) > 0:
                                plant_name = name_text.strip()
                                break
                except Exception as e:
                    self.logger.debug(f"Could not extract plant name: {e}")
                
                # Create a virtual element for the current plant
                plants.append({
                    'id': plant_id,
                    'name': plant_name,
                    'element': None,  # No specific element since we're on the overview page
                    'selector': 'current_page',
                    'attributes': {'url': current_url}
                })
                
                self.logger.info(f"Created plant entry from current page: {plant_name} (ID: {plant_id})")
            
            # If no plants found from current page, try to find plant elements
            if not plants:
                # Try different selectors for plant elements
                plant_selectors = [
                    '.plant-item',
                    '.plant-card',
                    '.device-item',
                    '.inverter-item',
                    '[data-plant-id]',
                    '.plant-list .item',
                    '.device-list .item',
                    '.card',
                    '.list-item',
                    '[class*="plant"]',
                    '[class*="device"]',
                    '[class*="inverter"]'
                ]
                
                for selector in plant_selectors:
                    plant_elements = await self.page.query_selector_all(selector)
                    if plant_elements:
                        self.logger.info(f"Found {len(plant_elements)} elements with selector: {selector}")
                        for element in plant_elements:
                            try:
                                plant_id = await element.get_attribute('data-plant-id')
                                if not plant_id:
                                    plant_id = await element.get_attribute('data-device-id')
                                if not plant_id:
                                    plant_id = await element.get_attribute('data-id')
                                
                                plant_name = await element.text_content()
                                if plant_name:
                                    plant_name = plant_name.strip()
                                
                                # Get all attributes for debugging
                                all_attrs = {}
                                try:
                                    attrs = await self.page.evaluate('(element) => { const attrs = {}; for (let attr of element.attributes) { attrs[attr.name] = attr.value; } return attrs; }', element)
                                    all_attrs = attrs
                                except:
                                    pass
                                
                                if plant_name and len(plant_name) > 0:
                                    plants.append({
                                        'id': plant_id or f"unknown_{len(plants)}",
                                        'name': plant_name,
                                        'element': element,
                                        'selector': selector,
                                        'attributes': all_attrs
                                    })
                            except Exception as e:
                                self.logger.debug(f"Error parsing plant element: {e}")
                                continue
                        
                        if plants:
                            break
            
            self.logger.info(f"Found {len(plants)} plants")
            return plants
            
        except Exception as e:
            self.logger.error(f"Failed to get plants: {e}")
            return []
    
    async def select_plant(self, plant_id: str = None) -> bool:
        """
        Select a specific plant
        
        Args:
            plant_id: Plant ID to select (uses configured plant_id if None)
            
        Returns:
            bool: True if plant selected successfully
        """
        if not plant_id:
            plant_id = self.plant_id
        
        if not plant_id:
            self.logger.error("No plant ID provided")
            return False
        
        try:
            self.logger.info(f"Selecting plant: {plant_id}")
            
            plants = await self.get_plants()
            target_plant = None
            
            for plant in plants:
                if plant['id'] == plant_id:
                    target_plant = plant
                    break
            
            if not target_plant:
                self.logger.error(f"Plant {plant_id} not found")
                return False
            
            # If we're already on the plant page (element is None), just set the current plant
            if target_plant['element'] is None:
                self.current_plant_id = plant_id
                self.logger.info(f"Already on plant page: {plant_id}")
                return True
            
            # Click on the plant element
            await target_plant['element'].click()
            await self.page.wait_for_load_state('networkidle')
            
            self.current_plant_id = plant_id
            self.logger.info(f"Successfully selected plant: {plant_id}")
            
            # Save plant page
            if self.cache_pages:
                await self._save_page_to_cache(f"plant_{plant_id}.html")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to select plant {plant_id}: {e}")
            return False
    
    async def get_parameters(self) -> Dict[str, Any]:
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
                    await self.page.goto(url)
                    await self.page.wait_for_load_state('networkidle')
                    
                    # Check if page loaded successfully (not 404)
                    if "404" not in await self.page.content():
                        break
                except Exception:
                    continue
            
            # Save parameters page
            if self.cache_pages:
                await self._save_page_to_cache(f"parameters_{self.current_plant_id}.html")
            
            # Extract parameters from the page
            parameters = {}
            
            # Look for form inputs, selects, and other parameter elements
            form_elements = await self.page.query_selector_all('input, select, textarea')
            
            for element in form_elements:
                try:
                    name = await element.get_attribute('name')
                    element_type = await element.get_attribute('type')
                    element_id = await element.get_attribute('id')
                    
                    if name or element_id:
                        param_name = name or element_id
                        
                        if element_type in ['text', 'number', 'email', 'tel']:
                            value = await element.input_value()
                        elif element_type == 'checkbox':
                            value = await element.is_checked()
                        elif element_type == 'radio':
                            if await element.is_checked():
                                value = await element.get_attribute('value')
                            else:
                                continue
                        elif element.tag_name == 'select':
                            value = await element.input_value()
                        else:
                            value = await element.input_value()
                        
                        parameters[param_name] = value
                        
                except Exception as e:
                    self.logger.debug(f"Error extracting parameter: {e}")
                    continue
            
            self.logger.info(f"Extracted {len(parameters)} parameters")
            return parameters
            
        except Exception as e:
            self.logger.error(f"Failed to get parameters: {e}")
            return {}
    
    async def set_parameter(self, param_name: str, value: Any) -> bool:
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
            element = await self.page.query_selector(f'[name="{param_name}"], #{param_name}')
            
            if not element:
                self.logger.error(f"Parameter {param_name} not found")
                return False
            
            element_type = await element.get_attribute('type')
            
            # Set the value based on element type
            if element_type in ['text', 'number', 'email', 'tel']:
                await element.fill(str(value))
            elif element_type == 'checkbox':
                if value:
                    await element.check()
                else:
                    await element.uncheck()
            elif element_type == 'radio':
                await element.check()
            elif element.tag_name == 'select':
                await element.select_option(str(value))
            else:
                await element.fill(str(value))
            
            self.logger.info(f"Parameter {param_name} set to {value}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to set parameter {param_name}: {e}")
            return False
    
    async def save_parameters(self) -> bool:
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
                save_button = await self.page.query_selector(selector)
                if save_button:
                    break
            
            if not save_button:
                self.logger.error("Save button not found")
                return False
            
            # Click save button
            await save_button.click()
            
            # Wait for save confirmation or navigation
            try:
                await self.page.wait_for_load_state('networkidle', timeout=10000)
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
                    if await self.page.query_selector(indicator):
                        self.logger.info("Parameters saved successfully (success message found)")
                        return True
                
                self.logger.warning("Save completed but no confirmation found")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to save parameters: {e}")
            return False
    
    async def sync_data(self) -> Dict[str, Any]:
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
                if not await self.login():
                    return {'status': 'error', 'message': 'Login failed'}
            
            # Get current parameters
            parameters = await self.get_parameters()
            
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
    
    async def apply_parameter_changes(self, changes: Dict[str, Any]) -> bool:
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
                if not await self.login():
                    return False
            
            if not self.current_plant_id:
                if not await self.select_plant():
                    return False
            
            # Get current parameters for backup
            if self.solark_config['parameter_changes']['backup_before_change']:
                current_params = await self.get_parameters()
                backup_file = self.cache_dir / f"backup_{self.current_plant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
                    if await self.set_parameter(param_name, value):
                        success_count += 1
                    else:
                        self.logger.error(f"Failed to set parameter {param_name}")
            
            # Save changes if not dry run
            if not dry_run and success_count > 0:
                if await self.save_parameters():
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
    
    async def interactive_explore(self):
        """
        Interactive exploration mode - keeps browser open for manual navigation
        """
        if not self.is_logged_in:
            self.logger.error("Not logged in")
            return False
        
        try:
            self.logger.info("Starting interactive exploration mode...")
            self.logger.info("Browser will stay open for manual navigation")
            self.logger.info("Press Ctrl+C to exit")
            
            # Get current page info
            current_url = self.page.url
            page_title = await self.page.title()
            self.logger.info(f"Current page: {page_title} - {current_url}")
            
            # Save current page
            if self.cache_pages:
                await self._save_page_to_cache("interactive_explore.html")
            
            # Keep browser open and wait for user input
            import asyncio
            while True:
                try:
                    await asyncio.sleep(1)
                    # Check if page changed
                    new_url = self.page.url
                    if new_url != current_url:
                        current_url = new_url
                        page_title = await self.page.title()
                        self.logger.info(f"Page changed to: {page_title} - {current_url}")
                        
                        # Save the new page
                        if self.cache_pages:
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            await self._save_page_to_cache(f"explore_{timestamp}.html")
                except KeyboardInterrupt:
                    self.logger.info("Interactive exploration ended by user")
                    break
                except Exception as e:
                    self.logger.error(f"Error in interactive mode: {e}")
                    break
            
            return True
            
        except Exception as e:
            self.logger.error(f"Interactive exploration failed: {e}")
            return False
    
    async def explore_plants_interactive(self):
        """
        Login, get plants, and start interactive exploration
        """
        try:
            # Initialize browser
            if not await self.initialize():
                return False
            
            # Login
            if not await self.login():
                return False
            
            # Get plants
            plants = await self.get_plants()
            if plants:
                self.logger.info(f"Found {len(plants)} plants:")
                for i, plant in enumerate(plants, 1):
                    self.logger.info(f"  {i}. {plant['name']} (ID: {plant['id']})")
            else:
                self.logger.info("No plants found - starting interactive exploration")
            
            # Start interactive mode
            await self.interactive_explore()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Plant exploration failed: {e}")
            return False
        finally:
            # Don't cleanup automatically in interactive mode
            pass


# Example usage and testing
async def main():
    """Example usage of SolArkCloud class"""
    import sys
    
    solark = SolArkCloud()
    
    try:
        # Check if interactive mode is requested
        if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
            print("Starting interactive plant exploration...")
            await solark.explore_plants_interactive()
        else:
            # Standard test mode
            # Initialize browser
            if not await solark.initialize():
                print("Failed to initialize browser")
                return
            
            # Login
            if not await solark.login():
                print("Login failed")
                return
            
            # Get plants
            plants = await solark.get_plants()
            print(f"Found {len(plants)} plants:")
            for plant in plants:
                print(f"  - {plant['name']} (ID: {plant['id']})")
            
            # Select first plant if available
            if plants:
                plant_id = plants[0]['id']
                if await solark.select_plant(plant_id):
                    # Get parameters
                    params = await solark.get_parameters()
                    print(f"Found {len(params)} parameters:")
                    for name, value in list(params.items())[:10]:  # Show first 10
                        print(f"  - {name}: {value}")
            
            # Sync data
            sync_result = await solark.sync_data()
            print(f"Sync result: {sync_result}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if len(sys.argv) <= 1 or sys.argv[1] != "--interactive":
            try:
                await solark.cleanup()
            except Exception:
                pass  # Ignore cleanup errors


if __name__ == "__main__":
    asyncio.run(main())
