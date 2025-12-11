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
import argparse
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path
import json

from solark_cloud import SolArkCloud, SolArkCloudError, NetworkError

# Module-specific log level override (empty string or None to use default from config.yaml)
MODULE_LOG_LEVEL = "INFO"  # Override default log level for this module


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
        
        # Apply module-specific log level if set
        if MODULE_LOG_LEVEL and MODULE_LOG_LEVEL.strip():
            try:
                log_level = getattr(logging, MODULE_LOG_LEVEL.strip().upper())
                self.logger.setLevel(log_level)
            except AttributeError:
                self.logger.warning(f"Invalid MODULE_LOG_LEVEL '{MODULE_LOG_LEVEL}', using default")
        
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
        self.operation_lock = threading.RLock()  # Reentrant lock for single operation at a time
        self.active_toggle_thread = None  # Track active toggle operation thread
        self.active_threads = []  # Track all active threads for proper cleanup
        
        # Operation timeout configuration
        self.max_operation_timeout = self.solark_config.get('max_operation_timeout', 120)  # Default 2 minutes max for any operation
        
        # TOU state file path
        self.tou_state_file = self.solark_config.get('tou_state_file', 'solark_tou_state.json')
        self.tou_cooldown_seconds = self.solark_config.get('tou_cooldown_seconds', 300)  # Default 5 minutes
        self.tou_state = {}  # In-memory cache of TOU state
        
        # Network retry configuration
        self.network_retry_interval_seconds = self.solark_config.get('network_retry_interval_seconds', 300)  # Default 5 minutes
        
        # Pending operations tracking (for network failures)
        self.pending_operations = {}  # Key: inverter_id, Value: dict with operation details
        self.pending_operations_lock = threading.RLock()  # Reentrant lock for pending operations (needed for nested calls)
        
        # Load TOU state from disk (includes pending operations)
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
        
        # Start background retry thread for network failures
        self.retry_thread_running = True
        self.retry_thread = threading.Thread(target=self._retry_pending_operations_loop, daemon=True)
        self.retry_thread.start()
        self.logger.info(f"Started network retry thread (interval: {self.network_retry_interval_seconds}s)")
        
        self.logger.info(f"Sol-Ark integration initialized (enabled: {self.enabled})")
    
    def cleanup(self):
        """Stop background threads and cleanup resources."""
        self.logger.info("Starting Sol-Ark integration cleanup...")
        # Stop retry thread
        self.logger.info("Stopping retry thread...")
        self.retry_thread_running = False
        if self.retry_thread and self.retry_thread.is_alive():
            self.logger.info("Waiting for retry thread to stop (timeout: 3s)...")
            # With interruptible sleep, thread should stop within 1-2 seconds
            self.retry_thread.join(timeout=3.0)
            if self.retry_thread.is_alive():
                self.logger.warning("Retry thread did not stop within timeout, continuing cleanup")
            else:
                self.logger.info("Retry thread stopped successfully")
        else:
            self.logger.info("Retry thread is not running or already stopped")
        
        # Try to acquire lock with timeout (Solution 3: Non-blocking cleanup)
        self.logger.info("Acquiring operation lock for cleanup (timeout: 5s)...")
        lock_acquired = False
        active_threads = []
        try:
            # Try to acquire lock with 5 second timeout (blocks for up to 5s, returns False if timeout)
            lock_acquired = self.operation_lock.acquire(blocking=True, timeout=5.0)
            if not lock_acquired:
                self.logger.warning("Could not acquire operation lock within 5s timeout, "
                                  "some threads may still be running. Continuing cleanup without lock.")
                # Copy thread list without lock (may be incomplete, but threads are daemon anyway)
                active_threads = self.active_threads.copy() if hasattr(self, 'active_threads') else []
            else:
                self.logger.info("Successfully acquired operation lock")
                # Successfully acquired lock, get accurate thread list
                active_threads = self.active_threads.copy()
        except Exception as e:
            self.logger.error(f"Error acquiring operation lock during cleanup: {e}")
            # Continue cleanup without lock
            active_threads = self.active_threads.copy() if hasattr(self, 'active_threads') else []
        finally:
            if lock_acquired:
                self.operation_lock.release()
                self.logger.info("Released operation lock")
        
        # Wait for threads without holding lock (Solution 3)
        if active_threads:
            active_count = len([t for t in active_threads if t.is_alive()])
            if active_count > 0:
                self.logger.info(f"Waiting for {active_count} active toggle thread(s) to complete (timeout: 2s per thread)...")
                for thread in active_threads:
                    if thread.is_alive():
                        self.logger.info(f"Waiting for thread {thread.name} to complete...")
                        thread.join(timeout=2.0)
                        if thread.is_alive():
                            self.logger.warning(f"Thread {thread.name} did not complete within timeout")
                        else:
                            self.logger.info(f"Thread {thread.name} completed successfully")
            else:
                self.logger.info("No active threads found, skipping thread wait")
        else:
            self.logger.info("No threads to wait for")
        
        # Cleanup Sol-Ark cloud resources
        if self.solark_cloud:
            self.logger.info("Cleaning up Sol-Ark cloud resources...")
            try:
                self.solark_cloud.cleanup()
                self.logger.info("Sol-Ark cloud cleanup completed")
            except Exception as e:
                self.logger.error(f"Error cleaning up Sol-Ark cloud: {e}")
        else:
            self.logger.info("No Sol-Ark cloud instance to cleanup")
        
        self.logger.info("Sol-Ark integration cleanup completed successfully")
    
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
    
    def _build_optocoupler_plant_mapping(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Build mapping from optocoupler names to Sol-Ark inverter info (now supports multiple inverters per optocoupler)
        
        Returns:
            Dict mapping optocoupler name to list of inverter info dicts with 'id' and 'plant_id'
            
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
                    'enabled': True,
                    'plant_id': primary_config.get('plant_id', '')
                }]
                self.logger.info("Converted legacy single inverter config to new multi-inverter format")
            
            primary_inverter_info = []
            for inverter in primary_inverters:
                if inverter.get('id') and inverter.get('enabled', True):
                    inverter_info = {
                        'id': inverter['id'],
                        'plant_id': inverter.get('plant_id', '')
                    }
                    primary_inverter_info.append(inverter_info)
                    plant_id_str = f" (plant_id: {inverter_info['plant_id']})" if inverter_info['plant_id'] else " (no plant_id)"
                    self.logger.info(f"Mapped optocoupler '{primary_name}' to inverter ID '{inverter['id']}' ({inverter.get('name', 'Unnamed')}){plant_id_str}")
            
            if primary_inverter_info:
                mapping[primary_name] = primary_inverter_info
            
            if not mapping:
                self.logger.warning("No optocoupler-to-inverter mappings configured")
            
            return mapping
            
        except KeyError as e:
            raise ValueError(f"Missing required optocoupler configuration: {e}")
    
    def _load_tou_state(self):
        """Load TOU state from disk."""
        self.logger.info(f"Loading TOU state from {self.tou_state_file}...")
        try:
            if not os.path.exists(self.tou_state_file):
                self.logger.info(f"TOU state file {self.tou_state_file} does not exist, starting fresh")
                self.tou_state = {'version': 1, 'inverters': {}, 'last_sync': None, 'pending_operations': {}}
                self.pending_operations = {}
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
                self.logger.info(f"Migrating from version {version} to version 1, initializing fresh state")
                self.tou_state = {'version': 1, 'inverters': {}, 'last_sync': None, 'pending_operations': {}}
                self.pending_operations = {}
                return
            
            # Load inverters state
            inverters = state_data.get('inverters', {})
            if not isinstance(inverters, dict):
                raise ValueError("Invalid inverters structure in TOU state file")
            
            # Load pending operations
            pending_ops = state_data.get('pending_operations', {})
            if not isinstance(pending_ops, dict):
                pending_ops = {}
            
            self.tou_state = {
                'version': 1,
                'inverters': inverters,
                'last_sync': state_data.get('last_sync'),
                'pending_operations': pending_ops
            }
            
            # Load pending operations into in-memory dict
            with self.pending_operations_lock:
                self.pending_operations = pending_ops.copy()
            
            inverter_count = len(inverters)
            pending_count = len(pending_ops)
            self.logger.info(f"Successfully loaded TOU state for {inverter_count} inverter(s) and {pending_count} pending operation(s) from {self.tou_state_file}")
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.warning(f"Failed to load TOU state: {e}, starting fresh")
            self.tou_state = {'version': 1, 'inverters': {}, 'last_sync': None, 'pending_operations': {}}
            self.pending_operations = {}
        except Exception as e:
            self.logger.error(f"Unexpected error loading TOU state: {e}, starting fresh")
            self.tou_state = {'version': 1, 'inverters': {}, 'last_sync': None, 'pending_operations': {}}
            self.pending_operations = {}
    
    def _save_tou_state(self):
        """Save TOU state to disk with atomic write."""
        self.logger.info(f"Saving TOU state to {self.tou_state_file}...")
        try:
            # Get current pending operations
            with self.pending_operations_lock:
                pending_ops = self.pending_operations.copy()
            
            inverter_count = len(self.tou_state.get('inverters', {}))
            pending_count = len(pending_ops)
            state_data = {
                'version': 1,
                'inverters': self.tou_state.get('inverters', {}),
                'last_sync': time.time(),
                'pending_operations': pending_ops
            }
            
            # Atomic write: write to temp file, then rename
            temp_file = f"{self.tou_state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(state_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            
            # Atomic rename
            os.rename(temp_file, self.tou_state_file)
            self.logger.info(f"Successfully saved TOU state to {self.tou_state_file} ({inverter_count} inverter(s), {pending_count} pending operation(s))")
            
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
        self.logger.info(f"Retrieving stored TOU state for inverter {inverter_id}...")
        inverters = self.tou_state.get('inverters', {})
        inverter_data = inverters.get(inverter_id)
        if inverter_data and isinstance(inverter_data, dict):
            state = inverter_data.get('tou_enabled', True)  # Default to True if key missing
            self.logger.info(f"Retrieved stored TOU state for inverter {inverter_id}: {'ON' if state else 'OFF'}")
            return state
        # Default to True (enabled) if no stored state - assumes TOU is on by default
        self.logger.info(f"No stored state found for inverter {inverter_id}, defaulting to ON (enabled)")
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
        self.logger.info(f"Updating TOU state for inverter {inverter_id}: {'ON' if enabled else 'OFF'} (power source: {power_source})")
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
        self.logger.info(f"Successfully updated TOU state for inverter {inverter_id}: {'enabled' if enabled else 'disabled'} (power source: {power_source})")
    
    def _add_pending_operation(self, inverter_id: str, enable: bool, power_source: str, optocoupler_name: str, plant_id: str = ""):
        """
        Add a pending operation to the queue for network retry.
        
        Args:
            inverter_id: Inverter ID
            enable: Desired TOU state
            power_source: Power source that triggered this change
            optocoupler_name: Name of the optocoupler
            plant_id: Plant ID for the inverter
        """
        self.logger.info(f"Adding pending operation for inverter {inverter_id}: TOU={'ON' if enable else 'OFF'} "
                        f"(power_source: {power_source}, optocoupler: {optocoupler_name}, plant_id: {plant_id})")
        with self.pending_operations_lock:
            existing_retry_count = self.pending_operations.get(inverter_id, {}).get('retry_count', 0)
            self.pending_operations[inverter_id] = {
                'enable': enable,
                'power_source': power_source,
                'optocoupler_name': optocoupler_name,
                'plant_id': plant_id,
                'first_failure_time': time.time(),
                'retry_count': existing_retry_count + 1
            }
            # Update TOU state file with pending operations
            self.tou_state['pending_operations'] = self.pending_operations.copy()
            self._save_tou_state()
        
        self.logger.info(f"Successfully added pending operation for inverter {inverter_id}: TOU={'ON' if enable else 'OFF'} "
                        f"(power_source: {power_source}, plant_id: {plant_id}, retry_count: {self.pending_operations[inverter_id]['retry_count']})")
    
    def _remove_pending_operation(self, inverter_id: str):
        """
        Remove a pending operation from the queue.
        
        Args:
            inverter_id: Inverter ID to remove
        """
        self.logger.info(f"Removing pending operation for inverter {inverter_id}...")
        with self.pending_operations_lock:
            if inverter_id in self.pending_operations:
                del self.pending_operations[inverter_id]
                # Update TOU state file
                self.tou_state['pending_operations'] = self.pending_operations.copy()
                self._save_tou_state()
                self.logger.info(f"Successfully removed pending operation for inverter {inverter_id}")
            else:
                self.logger.info(f"No pending operation found for inverter {inverter_id}, nothing to remove")
    
    def _retry_pending_operations_loop(self):
        """
        Background thread that retries pending operations every network_retry_interval_seconds.
        This runs independently of the cooldown mechanism.
        """
        self.logger.info("Retry operations loop thread started")
        while self.retry_thread_running:
            try:
                # Sleep for the retry interval, but check flag frequently for quick shutdown
                # Sleep in 1-second chunks so we can respond to shutdown quickly
                self.logger.info(f"Entering sleep period for {self.network_retry_interval_seconds}s before checking pending operations...")
                sleep_remaining = self.network_retry_interval_seconds
                while sleep_remaining > 0 and self.retry_thread_running:
                    sleep_chunk = min(1.0, sleep_remaining)  # Sleep in 1-second chunks
                    time.sleep(sleep_chunk)
                    sleep_remaining -= sleep_chunk
                
                # Check if we should exit after sleep
                if not self.retry_thread_running:
                    self.logger.info("Retry thread stopping (retry_thread_running=False)")
                    break
                
                self.logger.info("Waking from sleep, checking for pending operations...")
                
                # Check if there are any pending operations
                with self.pending_operations_lock:
                    pending_ops = list(self.pending_operations.items())
                
                if not pending_ops:
                    self.logger.info("No pending operations found, continuing to wait...")
                    continue  # No pending operations, continue waiting
                
                self.logger.info(f"Starting retry batch: {len(pending_ops)} pending operation(s) due to network failures")
                
                # Retry each pending operation
                for inverter_id, op_data in pending_ops:
                    try:
                        enable = op_data['enable']
                        power_source = op_data['power_source']
                        optocoupler_name = op_data.get('optocoupler_name', 'Unknown')
                        plant_id = op_data.get('plant_id', '')
                        retry_count = op_data.get('retry_count', 0)
                        
                        self.logger.info(f"Retrying TOU toggle for inverter {inverter_id}: "
                                       f"TOU={'ON' if enable else 'OFF'} "
                                       f"(attempt {retry_count + 1}, power_source: {power_source}, plant_id: {plant_id})")
                        
                        # Attempt the operation
                        result = self.solark_cloud.toggle_time_of_use(enable, inverter_id, plant_id)
                        
                        if result:
                            # Success! Remove from pending queue and update state
                            self.logger.info(f"Successfully retried TOU toggle for inverter {inverter_id} "
                                           f"after {retry_count} failed attempts")
                            self._remove_pending_operation(inverter_id)
                            # Update TOU state to reflect success
                            self._update_tou_state(inverter_id, enable, power_source)
                        else:
                            # Still failed, but not a network error - might be other issue
                            # Keep it in pending queue for next retry
                            self.logger.warning(f"Retry failed for inverter {inverter_id} (non-network error), "
                                              f"will retry again in {self.network_retry_interval_seconds}s")
                            
                    except NetworkError as e:
                        # Network still down, keep in pending queue and increment retry count
                        with self.pending_operations_lock:
                            if inverter_id in self.pending_operations:
                                self.pending_operations[inverter_id]['retry_count'] = \
                                    self.pending_operations[inverter_id].get('retry_count', 0) + 1
                                retry_count = self.pending_operations[inverter_id]['retry_count']
                                # Update TOU state file
                                self.tou_state['pending_operations'] = self.pending_operations.copy()
                                self._save_tou_state()
                            else:
                                retry_count = op_data.get('retry_count', 0)
                        
                        first_failure_time = op_data.get('first_failure_time', time.time())
                        time_since_first_failure = time.time() - first_failure_time
                        
                        self.logger.warning(f"Network still unavailable for inverter {inverter_id} "
                                          f"(retry {retry_count}, "
                                          f"down for {time_since_first_failure/60:.1f} minutes): {e}")
                        # Operation stays in pending queue for next retry
                        
                    except Exception as e:
                        # Unexpected error, log it but keep retrying
                        self.logger.error(f"Unexpected error retrying operation for inverter {inverter_id}: {e}")
                        # Operation stays in pending queue for next retry
                
                self.logger.info(f"Retry batch completed: processed {len(pending_ops)} operation(s)")
                        
            except Exception as e:
                self.logger.error(f"Error in retry thread loop: {e}")
                # Continue the loop even if there's an error
        
        self.logger.info("Retry operations loop thread stopped")
    
    def _is_in_cooldown(self, inverter_id: str) -> bool:
        """
        Check if an inverter is currently in cooldown period.
        
        Args:
            inverter_id: Inverter ID to check
            
        Returns:
            True if inverter is in cooldown, False otherwise
        """
        self.logger.info(f"Checking cooldown status for inverter {inverter_id}...")
        inverters = self.tou_state.get('inverters', {})
        inverter_data = inverters.get(inverter_id)
        
        if not inverter_data or not isinstance(inverter_data, dict):
            self.logger.info(f"No stored state found for inverter {inverter_id}, not in cooldown")
            return False
        
        last_attempt_time = inverter_data.get('last_attempt_time')
        if last_attempt_time is None:
            self.logger.info(f"No last_attempt_time found for inverter {inverter_id}, not in cooldown")
            return False
        
        time_since_attempt = time.time() - last_attempt_time
        in_cooldown = time_since_attempt < self.tou_cooldown_seconds
        
        if in_cooldown:
            cooldown_remaining = self.tou_cooldown_seconds - time_since_attempt
            self.logger.info(f"Inverter {inverter_id} is in cooldown: {cooldown_remaining:.0f}s remaining (cooldown period: {self.tou_cooldown_seconds}s)")
        else:
            self.logger.info(f"Inverter {inverter_id} is not in cooldown (last attempt was {time_since_attempt:.0f}s ago, cooldown period: {self.tou_cooldown_seconds}s)")
        
        return in_cooldown
    
    
    def on_power_source_change(self, power_source: str, frequency_data: Dict[str, Any], optocoupler_name: str = None):
        """
        Handle power source change events for multiple inverters per optocoupler
        
        Args:
            power_source: 'grid', 'generator', or 'off_grid'
            frequency_data: Dictionary containing frequency analysis data
            optocoupler_name: Name of the optocoupler that detected the change
        """
        self.logger.info(f"on_power_source_change called: power_source={power_source}, optocoupler_name={optocoupler_name}, enabled={self.enabled}, parameter_changes_enabled={self.parameter_changes_enabled}")
        
        if not self.enabled:
            self.logger.info("Integration is disabled, skipping power source change handling")
            return
        
        if not self.parameter_changes_enabled:
            self.logger.info("Parameter changes are disabled, skipping power source change handling")
            return
        
        # If no optocoupler name provided, use the first configured one
        if not optocoupler_name and self.optocoupler_plants:
            optocoupler_name = list(self.optocoupler_plants.keys())[0]
            self.logger.info(f"No optocoupler name provided, using first configured: {optocoupler_name}")
        
        # Skip if no plant mapping for this optocoupler
        if optocoupler_name and not self.optocoupler_plants.get(optocoupler_name):
            self.logger.info(f"No plant mapping for optocoupler '{optocoupler_name}', skipping Sol-Ark changes")
            return
        
        # Create state key that includes optocoupler name
        state_key = f"{power_source}_{optocoupler_name}" if optocoupler_name else power_source
        
        if state_key == self.last_power_source:
            self.logger.info(f"Power source state unchanged: {state_key} (same as last_power_source), skipping")
            return  # No change
        
        self.logger.info(f"Power source changed from {self.last_power_source} to {state_key}")
        
        # Get parameters for new power source
        new_parameters = self.power_source_parameters.get(power_source, {})
        
        if not new_parameters:
            self.logger.warning(f"No parameters defined for power source: {power_source}")
            return
        
        # Get all inverters for this optocoupler
        inverter_infos = self.optocoupler_plants.get(optocoupler_name, [])
        
        if not inverter_infos:
            self.logger.warning(f"No inverters configured for optocoupler '{optocoupler_name}'")
            return
        
        # Apply changes to all inverters for this optocoupler
        inverter_ids = [inv['id'] for inv in inverter_infos]
        self.logger.info(f"Applying power source changes to {len(inverter_infos)} inverters: {inverter_ids}")
        
        # Handle TOU toggle specifically for all inverters (sequential)
        if 'time_of_use_enabled' in new_parameters:
            tou_enable = new_parameters['time_of_use_enabled']
            self.logger.info(f"TOU parameter found in new_parameters: time_of_use_enabled={tou_enable}, calling _toggle_time_of_use...")
            self._toggle_time_of_use(tou_enable, inverter_infos, power_source, optocoupler_name)
            self.logger.info("_toggle_time_of_use call completed")
        else:
            self.logger.info("No time_of_use_enabled parameter in new_parameters, skipping TOU toggle")
        
        self.last_power_source = state_key
    
    
    def _toggle_time_of_use(self, enable: bool, inverter_infos: List[Dict[str, str]], power_source: str, optocoupler_name: str):
        """
        Toggle Time of Use setting for multiple inverters sequentially with thread safety
        
        Args:
            enable: True to enable TOU, False to disable
            inverter_infos: List of inverter info dicts with 'id' and 'plant_id'
            power_source: Current power source for logging
            optocoupler_name: Name of the optocoupler
        """
        self.logger.info(f"_toggle_time_of_use called: enable={enable}, inverters={len(inverter_infos)}, power_source={power_source}, optocoupler={optocoupler_name}")
        
        if not self.time_of_use_enabled:
            self.logger.info("TOU automation disabled in configuration, returning early")
            return
        
        # Create thread function that will be registered before starting
        def do_toggle_with_lock():
            self.logger.info("do_toggle_with_lock thread function started")
            current_thread = threading.current_thread()
            operation_start = time.time()  # Track operation start time (Solution 5)
            
            # Acquire lock only for initial state checks and thread registration check
            with self.operation_lock:
                # Verify this thread is still the active one (may have been replaced due to timeout)
                if self.active_toggle_thread != current_thread:
                    self.logger.info("This thread is no longer the active toggle thread, exiting")
                    return
                
                success_count = 0
                total_count = len(inverter_infos)
                self.logger.info(f"Starting TOU toggle for {total_count} inverters (enable={enable})")
            
            # RELEASE LOCK - Process inverters without holding lock
            try:
                for idx, inverter_info in enumerate(inverter_infos, 1):
                    self.logger.info(f"Processing inverter {idx}/{total_count}: {inverter_info.get('id', 'unknown')}")
                    inverter_id = inverter_info['id']
                    plant_id = inverter_info.get('plant_id', '')
                    self.logger.info(f"Inverter {idx}/{total_count}: inverter_id={inverter_id}, plant_id={plant_id}")
                    
                    # Check operation timeout (Solution 5)
                    elapsed_time = time.time() - operation_start
                    if elapsed_time > self.max_operation_timeout:
                        self.logger.error(f"Operation timeout exceeded {self.max_operation_timeout}s (elapsed: {elapsed_time:.1f}s), aborting remaining inverters")
                        break
                    else:
                        self.logger.info(f"Operation time so far: {elapsed_time:.1f}s (timeout: {self.max_operation_timeout}s)")
                    
                    try:
                        # Always read current state from cloud first to ensure accuracy
                        self.logger.info(f"Inverter {idx}/{total_count}: Reading current TOU state from cloud for inverter {inverter_id}...")
                        read_start_time = time.time()
                        current_state = self.solark_cloud.get_time_of_use_state(inverter_id, plant_id)
                        read_duration = time.time() - read_start_time
                        self.logger.info(f"Inverter {idx}/{total_count}: TOU state read completed in {read_duration:.1f}s, result: {current_state}")
                        
                        if current_state is None:
                            self.logger.warning(f"Could not read TOU state from cloud for inverter {inverter_id}, using stored state as fallback")
                            # Fallback to stored state if cloud read fails
                            current_state = self._get_tou_state(inverter_id)
                            if current_state is None:
                                self.logger.warning(f"No stored state available for inverter {inverter_id}, assuming toggle needed")
                                # If we can't determine current state, proceed with toggle
                                current_state = not enable  # Assume opposite of desired to trigger toggle
                        
                        self.logger.info(f"Current TOU state for inverter {inverter_id}: {'ON' if current_state else 'OFF'}, desired: {'ON' if enable else 'OFF'}")
                        
                        if current_state == enable:
                            self.logger.info(f"TOU for inverter {inverter_id} already {'enabled' if enable else 'disabled'}, no change needed")
                            # Update stored state to match cloud state (requires lock)
                            with self.operation_lock:
                                self._update_tou_state(inverter_id, enable, power_source)
                            success_count += 1
                            continue
                        
                        # State differs - check cooldown before proceeding (requires lock)
                        with self.operation_lock:
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
                        
                        # Not in cooldown, proceed with cloud toggle
                        self.logger.info(f"Inverter {idx}/{total_count}: TOU state mismatch for inverter {inverter_id}: current={current_state}, desired={enable}, toggling via cloud")
                        
                        # NETWORK CALL WITHOUT LOCK HELD (Solution 1)
                        try:
                            self.logger.info(f"Inverter {idx}/{total_count}: Calling toggle_time_of_use(enable={enable}, inverter_id={inverter_id}, plant_id={plant_id})...")
                            toggle_start_time = time.time()
                            result = self.solark_cloud.toggle_time_of_use(enable, inverter_id, plant_id)
                            toggle_duration = time.time() - toggle_start_time
                            self.logger.info(f"Inverter {idx}/{total_count}: toggle_time_of_use completed in {toggle_duration:.1f}s, result: {result}")
                            
                            # Update state after network call (requires lock)
                            with self.operation_lock:
                                if result:
                                    success_count += 1
                                    self.logger.info(f"Successfully {'enabled' if enable else 'disabled'} TOU for inverter {inverter_id}")
                                    # Update state after successful cloud call
                                    attempt_time = time.time()
                                    self._update_tou_state(inverter_id, enable, power_source, last_attempt_time=attempt_time)
                                    # Remove from pending operations if it was there
                                    self._remove_pending_operation(inverter_id)
                                else:
                                    # Non-network failure (e.g., element not found, authentication issue)
                                    self.logger.warning(f"Cloud call failed for inverter {inverter_id} (non-network error)")
                                    # Don't add to pending queue for non-network errors
                                    # Still update attempt time for cooldown
                                    attempt_time = time.time()
                                    self._update_tou_state(inverter_id, enable, power_source, last_attempt_time=attempt_time)
                                    
                        except NetworkError as e:
                            # Network failure - add to pending queue for retry (requires lock)
                            with self.operation_lock:
                                self.logger.warning(f"Network error toggling TOU for inverter {inverter_id}: {e}. "
                                                  f"Adding to pending operations queue for retry every {self.network_retry_interval_seconds}s")
                                self._add_pending_operation(inverter_id, enable, power_source, optocoupler_name, plant_id)
                            # Don't count as success, but don't fail completely either
                            # The retry thread will handle it
                            
                        except Exception as e:
                            # Other unexpected errors
                            self.logger.error(f"Unexpected error toggling TOU for inverter {inverter_id}: {e}")
                            # Don't add to pending queue for unexpected errors
                            
                    except Exception as e:
                        self.logger.error(f"Error toggling TOU for inverter {inverter_id}: {e}")
                
                # Log overall result
                operation_duration = time.time() - operation_start
                if operation_duration > 60:
                    self.logger.warning(f"Operation took {operation_duration:.1f}s (longer than expected)")
                
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
                # Clear thread reference when operation completes (requires lock)
                self.logger.info("do_toggle_with_lock thread completing, cleaning up thread references...")
                with self.operation_lock:
                    if self.active_toggle_thread == current_thread:
                        self.active_toggle_thread = None
                        self.logger.info("Cleared active_toggle_thread reference")
                    # Remove from active threads list
                    if current_thread in self.active_threads:
                        self.active_threads.remove(current_thread)
                        self.logger.info("Removed thread from active_threads list")
                self.logger.info("do_toggle_with_lock thread cleanup completed")
        
        # Check if there's an active thread and handle timeout (Solution 4: register before starting)
        self.logger.info("Checking for existing active TOU toggle thread...")
        with self.operation_lock:
            current_active_thread = self.active_toggle_thread
            if current_active_thread is not None and current_active_thread.is_alive():
                # Check if thread has been running too long (timeout after max_operation_timeout)
                thread_start_time = getattr(current_active_thread, 'start_time', None)
                if thread_start_time is not None:
                    thread_runtime = time.time() - thread_start_time
                    if thread_runtime > self.max_operation_timeout:
                        self.logger.warning(f"Previous TOU toggle thread has been running > {self.max_operation_timeout}s (runtime: {thread_runtime:.1f}s), allowing new thread")
                        # Don't set to None - keep reference for cleanup tracking
                        # The thread will complete on its own, we just allow a new one to start
                    else:
                        self.logger.info(f"TOU toggle operation already in progress (thread runtime: {thread_runtime:.1f}s, timeout: {self.max_operation_timeout}s), skipping duplicate request")
                        return
                else:
                    self.logger.info("TOU toggle operation already in progress (no start_time available), skipping duplicate request")
                    return
            
            # Create and register thread BEFORE starting (Solution 4)
            self.logger.info("Creating TOU toggle thread...")
            thread = threading.Thread(target=do_toggle_with_lock, daemon=True)
            thread.start_time = time.time()  # Track thread start time for timeout detection
            self.active_toggle_thread = thread
            self.active_threads.append(thread)
            self.logger.info(f"TOU toggle thread created and registered, starting thread...")
        
        # Start thread AFTER registration (Solution 4)
        thread.start()
        self.logger.info("TOU toggle thread started successfully")
    
    
    
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
    """Example usage of SolArkIntegration with TOU state verification"""
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Sol-Ark TOU Integration Test')
    parser.add_argument('--read-only', action='store_true',
                        help='Read TOU values only, do not attempt to adjust them')
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create integration
    integration = SolArkIntegration()
    
    # For testing: reduce cooldown to allow faster testing (only if not read-only)
    if not args.read_only:
        print("NOTE: Reducing TOU cooldown to 5 seconds for testing...")
        integration.tou_cooldown_seconds = 5
    
    if not integration.enabled:
        print("ERROR: Sol-Ark integration is disabled in config.yaml")
        return
    
    if not integration.parameter_changes_enabled:
        print("ERROR: Parameter changes are disabled in config.yaml")
        return
    
    if not args.read_only:
        if not integration.time_of_use_enabled:
            print("ERROR: TOU automation is disabled in config.yaml")
            return
    
    # Get all configured inverters
    optocoupler_name = list(integration.optocoupler_plants.keys())[0] if integration.optocoupler_plants else None
    if not optocoupler_name:
        print("ERROR: No optocoupler-to-inverter mappings configured")
        return
    
    inverter_infos = integration.optocoupler_plants.get(optocoupler_name, [])
    if not inverter_infos:
        print("ERROR: No inverters configured for optocoupler")
        return
    
    inverter_ids = [inv['id'] for inv in inverter_infos]
    inverter_plant_map = {inv['id']: inv.get('plant_id', '') for inv in inverter_infos}
    
    print("=" * 70)
    if args.read_only:
        print("TOU State Read-Only Mode")
    else:
        print("TOU Toggle Operation")
    print("=" * 70)
    print(f"\nProcessing {len(inverter_infos)} inverter(s): {', '.join(inverter_ids)}")
    print(f"Optocoupler: {optocoupler_name}\n")
    
    # Initialize browser for state reading
    print("Initializing browser for state verification...")
    if not integration.solark_cloud.initialize():
        print("ERROR: Failed to initialize browser")
        return
    
    if not integration.solark_cloud.login():
        print("ERROR: Failed to login to Sol-Ark cloud")
        integration.solark_cloud.cleanup()
        return
    
    print("✓ Browser initialized and logged in\n")
    
    try:
        # Read initial TOU state for all inverters
        print("Reading initial TOU state from cloud...")
        initial_states = {}
        for inverter_id in inverter_ids:
            plant_id = inverter_plant_map.get(inverter_id, '')
            if not plant_id:
                print(f"  Inverter {inverter_id}: No plant_id configured, skipping")
                continue
            state = integration.solark_cloud.get_time_of_use_state(inverter_id, plant_id)
            initial_states[inverter_id] = state
            if state is not None:
                print(f"  Inverter {inverter_id}: TOU is {'ON' if state else 'OFF'}")
            else:
                print(f"  Inverter {inverter_id}: Unable to read state")
        print()
        
        # If read-only mode, just show current state and exit
        if args.read_only:
            print("Read-only mode: Current TOU state displayed above.")
            print("No changes will be made to inverter settings.\n")
            return
        
        # Determine desired state for each inverter (toggle: ON→OFF, OFF→ON)
        print("Determining toggle actions...")
        inverters_to_enable = []
        inverters_to_disable = []
        inverters_unknown_ids = set()
        
        for inverter_info in inverter_infos:
            inverter_id = inverter_info['id']
            current_state = initial_states.get(inverter_id)
            
            if current_state is None:
                print(f"  Inverter {inverter_id}: Unknown state, skipping")
                inverters_unknown_ids.add(inverter_id)
                continue
            elif current_state:
                # Currently ON, toggle to OFF
                print(f"  Inverter {inverter_id}: Currently ON → will toggle to OFF")
                inverters_to_disable.append(inverter_info)
            else:
                # Currently OFF, toggle to ON
                print(f"  Inverter {inverter_id}: Currently OFF → will toggle to ON")
                inverters_to_enable.append(inverter_info)
        print()
        
        if not inverters_to_enable and not inverters_to_disable:
            print("No inverters need to be toggled (all are unknown state or already in desired state).")
            return
        
        # Perform toggle operations
        print("=" * 70)
        print("TOGGLING TOU STATE")
        print("=" * 70)
        
        def wait_for_toggle_completion(operation_name: str, max_wait_time: int = 120):
            """Wait for toggle operation to complete"""
            print(f"\nWaiting for {operation_name} to complete...")
            wait_interval = 1  # Check every second
            elapsed = 0
            
            while elapsed < max_wait_time:
                with integration.operation_lock:
                    if integration.active_toggle_thread is None or not integration.active_toggle_thread.is_alive():
                        # Operation completed
                        break
                time.sleep(wait_interval)
                elapsed += wait_interval
                if elapsed % 10 == 0:
                    print(f"  Still waiting... ({elapsed}s elapsed)")
            
            if elapsed >= max_wait_time:
                print(f"WARNING: {operation_name} did not complete within timeout period")
                return False
            else:
                print(f"{operation_name} completed in {elapsed}s")
                return True
        
        # Toggle inverters that need to be enabled
        if inverters_to_enable:
            print(f"\nEnabling TOU for {len(inverters_to_enable)} inverter(s)...")
            integration._toggle_time_of_use(True, inverters_to_enable, "manual_toggle", optocoupler_name)
            wait_for_toggle_completion("Enable operation")
        
        # Toggle inverters that need to be disabled
        if inverters_to_disable:
            print(f"\nDisabling TOU for {len(inverters_to_disable)} inverter(s)...")
            integration._toggle_time_of_use(False, inverters_to_disable, "manual_toggle", optocoupler_name)
            wait_for_toggle_completion("Disable operation")
        
        # Wait a bit more for cloud to sync
        print("Waiting 5 seconds for cloud to sync...")
        time.sleep(5)
        
        # Verify final state
        print(f"\n{'='*70}")
        print("VERIFICATION")
        print(f"{'='*70}")
        print("\nReading final TOU state from cloud...")
        
        all_correct = True
        for inverter_info in inverter_infos:
            inverter_id = inverter_info['id']
            plant_id = inverter_info.get('plant_id', '')
            
            if not plant_id:
                print(f"  Inverter {inverter_id}: No plant_id configured, skipping verification")
                continue
            
            if inverter_id in inverters_unknown_ids:
                print(f"  Inverter {inverter_id}: Skipped (unknown initial state)")
                continue
            
            initial_state = initial_states.get(inverter_id)
            expected_state = not initial_state if initial_state is not None else None
            
            final_state = integration.solark_cloud.get_time_of_use_state(inverter_id, plant_id)
            
            if final_state is not None:
                if expected_state is not None and final_state == expected_state:
                    print(f"  ✓ Inverter {inverter_id}: TOU is {'ON' if final_state else 'OFF'} (CORRECT - toggled from {'ON' if initial_state else 'OFF'})")
                elif expected_state is not None:
                    print(f"  ✗ Inverter {inverter_id}: TOU is {'ON' if final_state else 'OFF'} (EXPECTED: {'ON' if expected_state else 'OFF'})")
                    all_correct = False
                else:
                    print(f"  ? Inverter {inverter_id}: TOU is {'ON' if final_state else 'OFF'} (initial state was unknown)")
            else:
                print(f"  ? Inverter {inverter_id}: Unable to read final state")
                all_correct = False
        
        print()
        if all_correct:
            print("✓ SUCCESS: All inverters have been toggled correctly")
        else:
            print("✗ WARNING: Some inverters may not have been toggled correctly")
        
        print(f"\n{'='*70}")
        print("Toggle operation completed!")
        print(f"{'='*70}\n")
        
    except KeyboardInterrupt:
        print("\n\nStopping integration...")
    except Exception as e:
        print(f"\n\nERROR during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        integration.cleanup()
        integration.solark_cloud.cleanup()


if __name__ == "__main__":
    main()
