#!/usr/bin/env python3
"""
Sol-Ark Integration Module

This module integrates the Sol-Ark cloud functionality with the existing
frequency monitoring system. It provides automatic parameter updates based
on power source detection and system status.
"""

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from pathlib import Path
import json

from solark_cloud import SolArkCloud, SolArkCloudError


class SolArkIntegration:
    """
    Integration class that connects Sol-Ark cloud with the frequency monitor
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize Sol-Ark integration
        
        Args:
            config_path: Path to configuration file
        """
        self.logger = logging.getLogger(__name__)
        self.config_path = config_path
        
        # Load configuration
        self.solark_cloud = SolArkCloud(config_path)
        self.config = self.solark_cloud.config
        self.solark_config = self.solark_cloud.solark_config
        
        # Integration settings
        self.enabled = self.solark_config['enabled']
        self.sync_interval = self.solark_config['sync_interval']  # 5 minutes
        self.parameter_changes_enabled = self.solark_config['parameter_changes']['enabled']
        self.time_of_use_enabled = self.solark_config['parameter_changes'].get('time_of_use_enabled', True)
        
        # State tracking
        self.last_power_source = None
        self.last_sync_time = None
        self.sync_thread = None
        self.running = False
        
        # Parameter mapping for different power sources
        self.power_source_parameters = {
            'grid': {
                'time_of_use_enabled': True  # Enable TOU on grid power
            },
            'generator': {
                'time_of_use_enabled': False  # Disable TOU on generator
            },
            'off_grid': {
                'time_of_use_enabled': False  # Disable TOU off-grid
            }
        }
        
        self.logger.info(f"Sol-Ark integration initialized (enabled: {self.enabled})")
    
    def start(self):
        """Start the Sol-Ark integration"""
        if not self.enabled:
            self.logger.info("Sol-Ark integration disabled")
            return
        
        if self.running:
            self.logger.warning("Sol-Ark integration already running")
            return
        
        self.running = True
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()
        self.logger.info("Sol-Ark integration started")
    
    def stop(self):
        """Stop the Sol-Ark integration"""
        if not self.running:
            return
        
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)
        
        # Cleanup browser
        asyncio.run(self.solark_cloud.cleanup())
        self.logger.info("Sol-Ark integration stopped")
    
    def _sync_loop(self):
        """Main sync loop running in background thread"""
        while self.running:
            try:
                # Run async sync in new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    loop.run_until_complete(self._perform_sync())
                finally:
                    loop.close()
                
                # Wait for next sync
                time.sleep(self.sync_interval)
                
            except Exception as e:
                self.logger.error(f"Error in sync loop: {e}")
                time.sleep(60)  # Wait 1 minute before retrying
    
    async def _perform_sync(self):
        """Perform synchronization with Sol-Ark cloud"""
        try:
            self.logger.debug("Starting Sol-Ark sync...")
            
            # Sync data
            sync_result = await self.solark_cloud.sync_data()
            
            if sync_result.get('status') == 'success':
                self.last_sync_time = datetime.now()
                self.logger.debug("Sol-Ark sync completed successfully")
            else:
                self.logger.warning(f"Sol-Ark sync failed: {sync_result.get('message')}")
                
        except Exception as e:
            self.logger.error(f"Sol-Ark sync error: {e}")
    
    def on_power_source_change(self, power_source: str, frequency_data: Dict[str, Any]):
        """
        Handle power source change events
        
        Args:
            power_source: 'grid', 'generator', or 'off_grid'
            frequency_data: Dictionary containing frequency analysis data
        """
        if not self.enabled or not self.parameter_changes_enabled:
            return
        
        if power_source == self.last_power_source:
            return  # No change
        
        self.logger.info(f"Power source changed from {self.last_power_source} to {power_source}")
        
        # Get parameters for new power source
        new_parameters = self.power_source_parameters.get(power_source, {})
        
        if not new_parameters:
            self.logger.warning(f"No parameters defined for power source: {power_source}")
            return
        
        # Handle TOU toggle specifically
        if 'time_of_use_enabled' in new_parameters:
            self._toggle_time_of_use(new_parameters['time_of_use_enabled'], power_source)
        
        # Apply other parameter changes if any
        other_parameters = {k: v for k, v in new_parameters.items() if k != 'time_of_use_enabled'}
        if other_parameters:
            self._apply_parameter_changes(other_parameters, power_source)
        
        self.last_power_source = power_source
    
    def _toggle_time_of_use(self, enable: bool, power_source: str):
        """
        Toggle Time of Use setting asynchronously
        
        Args:
            enable: True to enable TOU, False to disable
            power_source: Current power source for logging
        """
        if not self.time_of_use_enabled:
            self.logger.debug("TOU automation disabled in configuration")
            return
            
        def do_toggle():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    result = loop.run_until_complete(
                        self.solark_cloud.toggle_time_of_use(enable)
                    )
                    
                    if result:
                        self.logger.info(f"Successfully {'enabled' if enable else 'disabled'} TOU for {power_source}")
                    else:
                        self.logger.error(f"Failed to {'enable' if enable else 'disable'} TOU for {power_source}")
                        
                finally:
                    loop.close()
                    
            except Exception as e:
                self.logger.error(f"Error toggling TOU: {e}")
        
        # Run in separate thread to avoid blocking
        thread = threading.Thread(target=do_toggle, daemon=True)
        thread.start()
    
    def _apply_parameter_changes(self, parameters: Dict[str, Any], power_source: str):
        """
        Apply parameter changes asynchronously
        
        Args:
            parameters: Dictionary of parameters to change
            power_source: Current power source for logging
        """
        def apply_changes():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    result = loop.run_until_complete(
                        self.solark_cloud.apply_parameter_changes(parameters)
                    )
                    
                    if result:
                        self.logger.info(f"Successfully applied {len(parameters)} parameter changes for {power_source}")
                    else:
                        self.logger.error(f"Failed to apply parameter changes for {power_source}")
                        
                finally:
                    loop.close()
                    
            except Exception as e:
                self.logger.error(f"Error applying parameter changes: {e}")
        
        # Run in separate thread to avoid blocking
        thread = threading.Thread(target=apply_changes, daemon=True)
        thread.start()
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get integration status
        
        Returns:
            Dictionary containing status information
        """
        return {
            'enabled': self.enabled,
            'running': self.running,
            'last_sync_time': self.last_sync_time.isoformat() if self.last_sync_time else None,
            'last_power_source': self.last_power_source,
            'sync_interval': self.sync_interval,
            'parameter_changes_enabled': self.parameter_changes_enabled,
            'username_configured': bool(self.solark_cloud.username),
            'password_configured': bool(self.solark_cloud.password)
        }
    
    def manual_sync(self) -> bool:
        """
        Trigger manual synchronization
        
        Returns:
            bool: True if sync initiated successfully
        """
        if not self.enabled:
            self.logger.warning("Sol-Ark integration disabled")
            return False
        
        def do_sync():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    loop.run_until_complete(self._perform_sync())
                    self.logger.info("Manual sync completed")
                finally:
                    loop.close()
                    
            except Exception as e:
                self.logger.error(f"Manual sync failed: {e}")
        
        thread = threading.Thread(target=do_sync, daemon=True)
        thread.start()
        return True
    
    def set_parameter(self, param_name: str, value: Any) -> bool:
        """
        Manually set a parameter
        
        Args:
            param_name: Name of the parameter
            value: Value to set
            
        Returns:
            bool: True if parameter change initiated successfully
        """
        if not self.enabled:
            self.logger.warning("Sol-Ark integration disabled")
            return False
        
        def do_set_parameter():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    result = loop.run_until_complete(
                        self.solark_cloud.apply_parameter_changes({param_name: value})
                    )
                    
                    if result:
                        self.logger.info(f"Successfully set parameter {param_name} = {value}")
                    else:
                        self.logger.error(f"Failed to set parameter {param_name}")
                        
                finally:
                    loop.close()
                    
            except Exception as e:
                self.logger.error(f"Error setting parameter: {e}")
        
        thread = threading.Thread(target=do_set_parameter, daemon=True)
        thread.start()
        return True


# Example usage
def main():
    """Example usage of SolArkIntegration"""
    import yaml
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create integration
    integration = SolArkIntegration()
    
    try:
        # Start integration
        integration.start()
        
        # Simulate power source changes
        print("Simulating power source changes...")
        
        # Utility power
        integration.on_power_source_change('utility', {'frequency': 60.0, 'stability': 'high'})
        time.sleep(2)
        
        # Generator power
        integration.on_power_source_change('generator', {'frequency': 59.8, 'stability': 'low'})
        time.sleep(2)
        
        # Back to utility
        integration.on_power_source_change('utility', {'frequency': 60.0, 'stability': 'high'})
        time.sleep(2)
        
        # Show status
        status = integration.get_status()
        print(f"Integration status: {status}")
        
        # Keep running for a bit
        time.sleep(10)
        
    except KeyboardInterrupt:
        print("Stopping integration...")
    finally:
        integration.stop()


if __name__ == "__main__":
    main()
