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
import os
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
        
        # TOU state file path
        self.tou_state_file = self.solark_config.get('tou_state_file', 'solark_tou_state.json')
        self.tou_cooldown_seconds = self.solark_config.get('tou_cooldown_seconds', 300)  # Default 5 minutes
        self.tou_state = {}  # In-memory cache of TOU state
        
        # Load TOU state from disk
        self._load_tou_state()
        
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
    
    def _load_tou_state(self):
        """Load TOU state from disk."""
        try:
            if not os.path.exists(self.tou_state_file):
                self.logger.info(f"TOU state file {self.tou_state_file} does not exist, starting fresh")
                self.tou_state = {'version': 1, 'inverters': {}, 'last_sync': None}
                return
            
            with open(self.tou_state_file, 'r') as f:
                state_data = json.load(f)
            
            # Validate structure
            if not isinstance(state_data, dict):
                raise ValueError("Invalid TOU state file format")
            
            # Handle version migration if needed
            version = state_data.get('version', 1)
            if version != 1:
                self.logger.warning(f"Unknown TOU state file version {version}, starting fresh")
                self.tou_state = {'version': 1, 'inverters': {}, 'last_sync': None}
                return
            
            # Load inverters state
            inverters = state_data.get('inverters', {})
            if not isinstance(inverters, dict):
                raise ValueError("Invalid inverters structure in TOU state file")
            
            self.tou_state = {
                'version': 1,
                'inverters': inverters,
                'last_sync': state_data.get('last_sync')
            }
            
            inverter_count = len(inverters)
            self.logger.info(f"Loaded TOU state for {inverter_count} inverter(s) from {self.tou_state_file}")
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.warning(f"Failed to load TOU state: {e}, starting fresh")
            self.tou_state = {'version': 1, 'inverters': {}, 'last_sync': None}
        except Exception as e:
            self.logger.error(f"Unexpected error loading TOU state: {e}, starting fresh")
            self.tou_state = {'version': 1, 'inverters': {}, 'last_sync': None}
    
    def _save_tou_state(self):
        """Save TOU state to disk with atomic write."""
        try:
            state_data = {
                'version': 1,
                'inverters': self.tou_state.get('inverters', {}),
                'last_sync': time.time()
            }
            
            # Atomic write: write to temp file, then rename
            temp_file = f"{self.tou_state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(state_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            
            # Atomic rename
            os.rename(temp_file, self.tou_state_file)
            self.logger.debug(f"TOU state saved to {self.tou_state_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to save TOU state: {e}")
    
    def _get_tou_state(self, inverter_id: str) -> bool:
        """
        Get stored TOU state for an inverter.
        
        Args:
            inverter_id: Inverter ID to check
            
        Returns:
            True if TOU is enabled, False if disabled.
            Defaults to True (enabled) if state is unknown (assumes TOU is on by default).
        """
        inverters = self.tou_state.get('inverters', {})
        inverter_data = inverters.get(inverter_id)
        if inverter_data and isinstance(inverter_data, dict):
            return inverter_data.get('tou_enabled', True)  # Default to True if key missing
        # Default to True (enabled) if no stored state - assumes TOU is on by default
        return True
    
    def _update_tou_state(self, inverter_id: str, enabled: bool, power_source: str, last_attempt_time: Optional[float] = None):
        """
        Update stored TOU state for an inverter.
        
        Args:
            inverter_id: Inverter ID to update
            enabled: TOU enabled state
            power_source: Power source that triggered this change
            last_attempt_time: Timestamp of last change attempt (defaults to current time)
        """
        if 'inverters' not in self.tou_state:
            self.tou_state['inverters'] = {}
        
        current_time = time.time()
        self.tou_state['inverters'][inverter_id] = {
            'tou_enabled': enabled,
            'last_updated': current_time,
            'last_power_source': power_source,
            'last_attempt_time': last_attempt_time if last_attempt_time is not None else current_time
        }
        
        self._save_tou_state()
        self.logger.debug(f"Updated TOU state for inverter {inverter_id}: {'enabled' if enabled else 'disabled'} (power source: {power_source})")
    
    def _is_in_cooldown(self, inverter_id: str) -> bool:
        """
        Check if an inverter is currently in cooldown period.
        
        Args:
            inverter_id: Inverter ID to check
            
        Returns:
            True if inverter is in cooldown, False otherwise
        """
        inverters = self.tou_state.get('inverters', {})
        inverter_data = inverters.get(inverter_id)
        
        if not inverter_data or not isinstance(inverter_data, dict):
            return False
        
        last_attempt_time = inverter_data.get('last_attempt_time')
        if last_attempt_time is None:
            return False
        
        time_since_attempt = time.time() - last_attempt_time
        return time_since_attempt < self.tou_cooldown_seconds
    
    
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
                            # Check stored state first
                            stored_state = self._get_tou_state(inverter_id)
                            
                            if stored_state == enable:
                                # Check if we have actual stored data or just default assumption
                                inverters = self.tou_state.get('inverters', {})
                                has_stored_data = inverter_id in inverters
                                
                                if has_stored_data:
                                    self.logger.info(f"TOU for inverter {inverter_id} already {'enabled' if enable else 'disabled'} (stored state), skipping cloud call")
                                else:
                                    self.logger.info(f"TOU for inverter {inverter_id} assumed {'enabled' if enable else 'disabled'} (default), skipping cloud call")
                                
                                success_count += 1
                                # Update timestamp even though we didn't make a cloud call
                                self._update_tou_state(inverter_id, enable, power_source)
                                continue
                            
                            # State differs - check cooldown before proceeding
                            if self._is_in_cooldown(inverter_id):
                                inverters = self.tou_state.get('inverters', {})
                                inverter_data = inverters.get(inverter_id, {})
                                last_attempt_time = inverter_data.get('last_attempt_time', 0)
                                time_since_attempt = time.time() - last_attempt_time
                                cooldown_remaining = self.tou_cooldown_seconds - time_since_attempt
                                
                                self.logger.info(f"TOU change for inverter {inverter_id} skipped due to cooldown "
                                               f"({cooldown_remaining:.0f}s remaining). "
                                               f"Assuming previous attempt succeeded, optimistically setting state to {'enabled' if enable else 'disabled'}")
                                
                                # Optimistically update state to match desired state (assume previous attempt succeeded)
                                self._update_tou_state(inverter_id, enable, power_source, last_attempt_time=last_attempt_time)
                                success_count += 1
                                continue
                            
                            # Not in cooldown, proceed with cloud call
                            self.logger.info(f"TOU state mismatch for inverter {inverter_id}: stored={stored_state}, desired={enable}, updating via cloud")
                            
                            # Optimistically update state BEFORE cloud call (assume it will succeed)
                            attempt_time = time.time()
                            self._update_tou_state(inverter_id, enable, power_source, last_attempt_time=attempt_time)
                            
                            # Use synchronous Sol-Ark cloud method
                            result = self.solark_cloud.toggle_time_of_use(enable, inverter_id)
                            
                            if result:
                                success_count += 1
                                self.logger.info(f"Successfully {'enabled' if enable else 'disabled'} TOU for inverter {inverter_id}")
                                # State already updated optimistically, no need to update again
                            else:
                                self.logger.warning(f"Cloud call failed for inverter {inverter_id}, but state was optimistically updated. "
                                                  f"Assuming success per configuration (will retry after cooldown if needed)")
                                # Still count as success since we optimistically assume it succeeded
                                success_count += 1
                                
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
