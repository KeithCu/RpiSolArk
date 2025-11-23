#!/usr/bin/env python3
"""
Sol-Ark Integration Module

This module integrates the Sol-Ark cloud functionality with the existing
frequency monitoring system. It provides automatic parameter updates based
on power source detection and system status.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
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
        self.operation_lock = threading.Lock()  # Global lock for single operation at a time
        self.active_toggle_thread = None  # Track active toggle operation thread
        
        # Optocoupler to plant mapping
        self.optocoupler_plants = self._build_optocoupler_plant_mapping()
        
        # Validate configuration
        self.validate_configuration()
        
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
    
    def validate_configuration(self) -> bool:
        """
        Validate that optocoupler configuration is present
        
        Returns:
            bool: True if configuration is valid
            
        Raises:
            ValueError: If required optocoupler configuration is missing
        """
        try:
            optocoupler_config = self.config['hardware']['optocoupler']
            
            # Check that primary optocoupler has required fields
            primary_config = optocoupler_config['primary']
            if 'name' not in primary_config:
                raise ValueError("Primary optocoupler missing 'name' field")
            
            self.logger.info("Configuration validation passed")
            return True
            
        except KeyError as e:
            raise ValueError(f"Missing required optocoupler configuration: {e}")
    
    def _build_optocoupler_plant_mapping(self) -> Dict[str, List[str]]:
        """
        Build mapping from optocoupler names to Sol-Ark inverter IDs (now supports multiple inverters per optocoupler)
        
        Returns:
            Dict mapping optocoupler name to list of inverter IDs
            
        Raises:
            ValueError: If optocoupler name doesn't match configured inverter
        """
        mapping = {}
        
        try:
            optocoupler_config = self.config['hardware']['optocoupler']
            
            # Process primary optocoupler
            primary_config = optocoupler_config['primary']
            primary_name = primary_config['name']
            
            # Handle new multi-inverter format
            primary_inverters = primary_config.get('inverters')
            
            # Handle backward compatibility - if old format exists, convert it
            if 'solark_inverter_id' in primary_config and primary_config['solark_inverter_id']:
                primary_inverters = [{
                    'id': primary_config['solark_inverter_id'],
                    'name': f"{primary_name} Inverter",
                    'enabled': True
                }]
                self.logger.info("Converted legacy single inverter config to new multi-inverter format")
            
            primary_inverter_ids = []
            for inverter in primary_inverters:
                if inverter.get('id') and inverter.get('enabled', True):
                    primary_inverter_ids.append(inverter['id'])
                    self.logger.info(f"Mapped optocoupler '{primary_name}' to inverter ID '{inverter['id']}' ({inverter.get('name', 'Unnamed')})")
            
            if primary_inverter_ids:
                mapping[primary_name] = primary_inverter_ids
            
            if not mapping:
                self.logger.warning("No optocoupler-to-inverter mappings configured")
            
            return mapping
            
        except KeyError as e:
            raise ValueError(f"Missing required optocoupler configuration: {e}")
    
    
    
    def on_power_source_change(self, power_source: str, frequency_data: Dict[str, Any], optocoupler_name: str = None):
        """
        Handle power source change events for multiple inverters per optocoupler
        
        Args:
            power_source: 'grid', 'generator', or 'off_grid'
            frequency_data: Dictionary containing frequency analysis data
            optocoupler_name: Name of the optocoupler that detected the change
        """
        if not self.enabled or not self.parameter_changes_enabled:
            return
        
        # If no optocoupler name provided, use the first configured one
        if not optocoupler_name and self.optocoupler_plants:
            optocoupler_name = list(self.optocoupler_plants.keys())[0]
            self.logger.debug(f"No optocoupler name provided, using first configured: {optocoupler_name}")
        
        # Skip if no plant mapping for this optocoupler
        if optocoupler_name and not self.optocoupler_plants.get(optocoupler_name):
            self.logger.debug(f"No plant mapping for optocoupler '{optocoupler_name}', skipping Sol-Ark changes")
            return
        
        # Create state key that includes optocoupler name
        state_key = f"{power_source}_{optocoupler_name}" if optocoupler_name else power_source
        
        if state_key == self.last_power_source:
            return  # No change
        
        self.logger.info(f"Power source changed from {self.last_power_source} to {state_key}")
        
        # Get parameters for new power source
        new_parameters = self.power_source_parameters.get(power_source, {})
        
        if not new_parameters:
            self.logger.warning(f"No parameters defined for power source: {power_source}")
            return
        
        # Get all inverters for this optocoupler
        inverter_ids = self.optocoupler_plants.get(optocoupler_name, [])
        
        if not inverter_ids:
            self.logger.warning(f"No inverters configured for optocoupler '{optocoupler_name}'")
            return
        
        # Apply changes to all inverters for this optocoupler
        self.logger.info(f"Applying power source changes to {len(inverter_ids)} inverters: {inverter_ids}")
        
        # Handle TOU toggle specifically for all inverters (sequential)
        if 'time_of_use_enabled' in new_parameters:
            self._toggle_time_of_use(new_parameters['time_of_use_enabled'], inverter_ids, power_source, optocoupler_name)
        
        self.last_power_source = state_key
    
    
    def _toggle_time_of_use(self, enable: bool, inverter_ids: List[str], power_source: str, optocoupler_name: str):
        """
        Toggle Time of Use setting for multiple inverters sequentially with thread safety
        
        Args:
            enable: True to enable TOU, False to disable
            inverter_ids: List of inverter IDs to update
            power_source: Current power source for logging
            optocoupler_name: Name of the optocoupler
        """
        if not self.time_of_use_enabled:
            self.logger.debug("TOU automation disabled in configuration")
            return
        
        # Check if there's an active thread and handle timeout
        if self.active_toggle_thread is not None and self.active_toggle_thread.is_alive():
            # Check if thread has been running too long (timeout after 60 seconds)
            thread_start_time = getattr(self.active_toggle_thread, 'start_time', None)
            if thread_start_time is not None and (time.time() - thread_start_time) > 60:
                self.logger.warning("Previous TOU toggle thread has been running > 60 seconds, allowing new thread")
                self.active_toggle_thread = None
            else:
                self.logger.debug("TOU toggle operation already in progress, skipping duplicate request")
                return
        
        def do_toggle_with_lock():
            # Acquire lock to ensure only one operation at a time
            with self.operation_lock:
                try:
                    success_count = 0
                    total_count = len(inverter_ids)
                    
                    for inverter_id in inverter_ids:
                        try:
                            # Use synchronous Sol-Ark cloud method
                            result = self.solark_cloud.toggle_time_of_use(enable, inverter_id)
                            
                            if result:
                                success_count += 1
                                self.logger.info(f"Successfully {'enabled' if enable else 'disabled'} TOU for inverter {inverter_id}")
                            else:
                                self.logger.error(f"Failed to {'enable' if enable else 'disable'} TOU for inverter {inverter_id}")
                                
                        except Exception as e:
                            self.logger.error(f"Error toggling TOU for inverter {inverter_id}: {e}")
                    
                    # Log overall result
                    if success_count == total_count:
                        self.logger.info(f"Successfully {'enabled' if enable else 'disabled'} TOU for all {total_count} inverters "
                                       f"(optocoupler: {optocoupler_name}, power source: {power_source})")
                    elif success_count > 0:
                        self.logger.warning(f"Partially {'enabled' if enable else 'disabled'} TOU: {success_count}/{total_count} inverters "
                                          f"(optocoupler: {optocoupler_name}, power source: {power_source})")
                    else:
                        self.logger.error(f"Failed to {'enable' if enable else 'disable'} TOU for any inverters "
                                        f"(optocoupler: {optocoupler_name}, power source: {power_source})")
                        
                except Exception as e:
                    self.logger.error(f"Error in TOU toggle operation: {e}")
                finally:
                    # Clear thread reference when operation completes
                    self.active_toggle_thread = None
        
        # Run in separate thread to avoid blocking
        thread = threading.Thread(target=do_toggle_with_lock, daemon=True)
        thread.start_time = time.time()  # Track thread start time for timeout detection
        self.active_toggle_thread = thread
        thread.start()
    
    
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get integration status
        
        Returns:
            Dictionary containing status information
        """
        return {
            'enabled': self.enabled,
            'last_power_source': self.last_power_source,
            'parameter_changes_enabled': self.parameter_changes_enabled,
            'time_of_use_enabled': self.time_of_use_enabled,
            'username_configured': bool(self.solark_cloud.username),
            'password_configured': bool(self.solark_cloud.password),
            'optocoupler_mappings': {name: len(inverters) for name, inverters in self.optocoupler_plants.items()}
        }
    
    


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
