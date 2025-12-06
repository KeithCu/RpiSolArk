#!/usr/bin/env python3
"""
Health check reporting module.
Sends periodic GET requests with system information to a configurable endpoint.
"""

import logging
import threading
import time
import urllib.parse
from typing import Dict, Any, Callable, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class HealthCheckReporter:
    """Reports system health status to a remote endpoint via GET requests."""
    
    def __init__(self, config, logger: logging.Logger, state_callback: Callable[[], Dict[str, Any]]):
        """
        Initialize health check reporter.
        
        Args:
            config: Configuration object
            logger: Logger instance
            state_callback: Callback function that returns current system state info
        """
        self.config = config
        self.logger = logger
        self.state_callback = state_callback
        
        # Check if enabled
        try:
            self.enabled = config.get('health_check.enabled', False)
        except KeyError:
            self.enabled = False
        
        if not self.enabled:
            self.logger.info("Health check reporting disabled")
            return
        
        if not REQUESTS_AVAILABLE:
            self.logger.warning("requests library not available, disabling health check reporting")
            self.enabled = False
            return
        
        # Get configuration
        try:
            self.endpoint_url = config.get('health_check.endpoint_url')
            self.interval_seconds = config.get('health_check.interval_seconds', 300)
            self.timeout_seconds = config.get('health_check.timeout_seconds', 10)
        except KeyError as e:
            self.logger.error(f"Missing required health_check configuration: {e}")
            self.enabled = False
            return
        
        if not self.endpoint_url:
            self.logger.warning("Health check endpoint_url not configured, disabling")
            self.enabled = False
            return
        
        self.running = True
        self.startup_time = time.time()
        
        # Start reporting thread
        self._start_reporting()
    
    def _start_reporting(self):
        """Start health check reporting thread."""
        if not self.enabled:
            return
        
        self.report_thread = threading.Thread(target=self._report_loop, daemon=True, name="health-check-reporter")
        self.report_thread.start()
        self.logger.info(f"Health check reporting started (endpoint: {self.endpoint_url}, interval: {self.interval_seconds}s)")
    
    def _report_loop(self):
        """Main health check reporting loop."""
        while self.running:
            try:
                # Get current state from callback
                state_info = self.state_callback()
                
                # Send health check
                self._send_health_check(state_info)
                
                # Sleep for interval
                time.sleep(self.interval_seconds)
                
            except Exception as e:
                self.logger.error(f"Health check reporting error: {e}", exc_info=True)
                # Sleep even on error to avoid tight error loop
                time.sleep(self.interval_seconds)
    
    def _send_health_check(self, state_info: Dict[str, Any]):
        """Send health check GET request with system information."""
        try:
            # Build query parameters from state info
            params = {
                'timestamp': time.time(),
                'uptime_seconds': time.time() - self.startup_time,
            }
            
            # Add state info fields
            if 'frequency' in state_info:
                params['frequency'] = state_info['frequency']
            if 'power_source' in state_info:
                params['power_source'] = state_info['power_source']
            if 'current_state' in state_info:
                params['current_state'] = state_info['current_state']
            if 'memory_mb' in state_info:
                params['memory_mb'] = state_info['memory_mb']
            if 'memory_percent' in state_info:
                params['memory_percent'] = state_info['memory_percent']
            if 'system_memory_percent' in state_info:
                params['system_memory_percent'] = state_info['system_memory_percent']
            if 'sample_count' in state_info:
                params['sample_count'] = state_info['sample_count']
            
            # Make GET request
            response = requests.get(
                self.endpoint_url,
                params=params,
                timeout=self.timeout_seconds
            )
            
            # Log result
            if response.status_code == 200:
                self.logger.debug(f"Health check sent successfully (status: {response.status_code})")
            else:
                self.logger.warning(f"Health check returned non-200 status: {response.status_code}")
                
        except requests.exceptions.Timeout:
            self.logger.warning(f"Health check request timed out after {self.timeout_seconds}s")
        except requests.exceptions.ConnectionError as e:
            self.logger.warning(f"Health check connection error: {e}")
        except Exception as e:
            self.logger.error(f"Failed to send health check: {e}", exc_info=True)
    
    def stop(self):
        """Stop health check reporting."""
        if not self.enabled:
            return
        
        self.running = False
        self.logger.info("Health check reporting stopped")
