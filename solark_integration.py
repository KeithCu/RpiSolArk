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

from solark_cloud import SolArkCloud, SolArkCloudError, NetworkError


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
        self.active_threads = []  # Track all active threads for proper cleanup
        
        # TOU state file path
        self.tou_state_file = self.solark_config.get('tou_state_file', 'solark_tou_state.json')
        self.tou_cooldown_seconds = self.solark_config.get('tou_cooldown_seconds', 300)  # Default 5 minutes
        self.tou_state = {}  # In-memory cache of TOU state
        
        # Network retry configuration
        self.network_retry_interval_seconds = self.solark_config.get('network_retry_interval_seconds', 300)  # Default 5 minutes
        
        # Pending operations tracking (for network failures)
        self.pending_operations = {}  # Key: inverter_id, Value: dict with operation details
        self.pending_operations_lock = threading.Lock()  # Lock for pending operations
        
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
        self.logger.info("Cleaning up Sol-Ark integration...")
        # Stop retry thread
        self.retry_thread_running = False
        if self.retry_thread and self.retry_thread.is_alive():
            self.logger.info("Waiting for retry thread to stop...")
            # With interruptible sleep, thread should stop within 1-2 seconds
            self.retry_thread.join(timeout=3.0)
            if self.retry_thread.is_alive():
                self.logger.warning("Retry thread did not stop within timeout, continuing cleanup")
        
        # Wait for any active toggle threads to complete (with timeout)
        with self.operation_lock:
            active_count = len([t for t in self.active_threads if t.is_alive()])
            if active_count > 0:
                self.logger.info(f"Waiting for {active_count} active toggle thread(s) to complete...")
                for thread in self.active_threads[:]:  # Copy list to avoid modification during iteration
                    if thread.is_alive():
                        thread.join(timeout=2.0)
                        if thread.is_alive():
                            self.logger.warning(f"Thread {thread.name} did not complete within timeout")
        
        # Cleanup Sol-Ark cloud resources
        if self.solark_cloud:
            try:
                self.solark_cloud.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up Sol-Ark cloud: {e}")
        
        self.logger.info("Sol-Ark integration cleanup completed")
    
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
            self.logger.info(f"Loaded TOU state for {inverter_count} inverter(s) and {pending_count} pending operation(s) from {self.tou_state_file}")
            
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
        try:
            # Get current pending operations
            with self.pending_operations_lock:
                pending_ops = self.pending_operations.copy()
            
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
    
    def _add_pending_operation(self, inverter_id: str, enable: bool, power_source: str, optocoupler_name: str):
        """
        Add a pending operation to the queue for network retry.
        
        Args:
            inverter_id: Inverter ID
            enable: Desired TOU state
            power_source: Power source that triggered this change
            optocoupler_name: Name of the optocoupler
        """
        with self.pending_operations_lock:
            self.pending_operations[inverter_id] = {
                'enable': enable,
                'power_source': power_source,
                'optocoupler_name': optocoupler_name,
                'first_failure_time': time.time(),
                'retry_count': self.pending_operations.get(inverter_id, {}).get('retry_count', 0) + 1
            }
            # Update TOU state file with pending operations
            self.tou_state['pending_operations'] = self.pending_operations.copy()
            self._save_tou_state()
        
        self.logger.info(f"Added pending operation for inverter {inverter_id}: TOU={'ON' if enable else 'OFF'} "
                        f"(power_source: {power_source}, retry_count: {self.pending_operations[inverter_id]['retry_count']})")
    
    def _remove_pending_operation(self, inverter_id: str):
        """
        Remove a pending operation from the queue.
        
        Args:
            inverter_id: Inverter ID to remove
        """
        with self.pending_operations_lock:
            if inverter_id in self.pending_operations:
                del self.pending_operations[inverter_id]
                # Update TOU state file
                self.tou_state['pending_operations'] = self.pending_operations.copy()
                self._save_tou_state()
                self.logger.info(f"Removed pending operation for inverter {inverter_id}")
    
    def _retry_pending_operations_loop(self):
        """
        Background thread that retries pending operations every network_retry_interval_seconds.
        This runs independently of the cooldown mechanism.
        """
        while self.retry_thread_running:
            try:
                # Sleep for the retry interval, but check flag frequently for quick shutdown
                # Sleep in 1-second chunks so we can respond to shutdown quickly
                sleep_remaining = self.network_retry_interval_seconds
                while sleep_remaining > 0 and self.retry_thread_running:
                    sleep_chunk = min(1.0, sleep_remaining)  # Sleep in 1-second chunks
                    time.sleep(sleep_chunk)
                    sleep_remaining -= sleep_chunk
                
                # Check if we should exit after sleep
                if not self.retry_thread_running:
                    break
                
                # Check if there are any pending operations
                with self.pending_operations_lock:
                    pending_ops = list(self.pending_operations.items())
                
                if not pending_ops:
                    continue  # No pending operations, continue waiting
                
                self.logger.info(f"Retrying {len(pending_ops)} pending operation(s) due to network failures")
                
                # Retry each pending operation
                for inverter_id, op_data in pending_ops:
                    try:
                        enable = op_data['enable']
                        power_source = op_data['power_source']
                        optocoupler_name = op_data.get('optocoupler_name', 'Unknown')
                        retry_count = op_data.get('retry_count', 0)
                        
                        self.logger.info(f"Retrying TOU toggle for inverter {inverter_id}: "
                                       f"TOU={'ON' if enable else 'OFF'} "
                                       f"(attempt {retry_count + 1}, power_source: {power_source})")
                        
                        # Attempt the operation
                        result = self.solark_cloud.toggle_time_of_use(enable, inverter_id)
                        
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
                        
            except Exception as e:
                self.logger.error(f"Error in retry thread loop: {e}")
                # Continue the loop even if there's an error
    
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
        current_active_thread = self.active_toggle_thread
        if current_active_thread is not None and current_active_thread.is_alive():
            # Check if thread has been running too long (timeout after 60 seconds)
            thread_start_time = getattr(current_active_thread, 'start_time', None)
            if thread_start_time is not None and (time.time() - thread_start_time) > 60:
                self.logger.warning("Previous TOU toggle thread has been running > 60 seconds, allowing new thread")
                # Don't set to None - keep reference for cleanup tracking
                # The thread will complete on its own, we just allow a new one to start
            else:
                self.logger.debug("TOU toggle operation already in progress, skipping duplicate request")
                return
        
        def do_toggle_with_lock():
            # Acquire lock to ensure only one operation at a time
            current_thread = threading.current_thread()
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
                            
                            # Use synchronous Sol-Ark cloud method
                            try:
                                result = self.solark_cloud.toggle_time_of_use(enable, inverter_id)
                                
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
                                # Network failure - add to pending queue for retry
                                self.logger.warning(f"Network error toggling TOU for inverter {inverter_id}: {e}. "
                                                  f"Adding to pending operations queue for retry every {self.network_retry_interval_seconds}s")
                                self._add_pending_operation(inverter_id, enable, power_source, optocoupler_name)
                                # Don't count as success, but don't fail completely either
                                # The retry thread will handle it
                                
                            except Exception as e:
                                # Other unexpected errors
                                self.logger.error(f"Unexpected error toggling TOU for inverter {inverter_id}: {e}")
                                # Don't add to pending queue for unexpected errors
                                
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
                    # Clear thread reference when operation completes (while lock is still held)
                    if self.active_toggle_thread == current_thread:
                        self.active_toggle_thread = None
                    # Remove from active threads list (lock is still held from outer 'with' block)
                    if current_thread in self.active_threads:
                        self.active_threads.remove(current_thread)
        
        # Run in separate thread to avoid blocking
        thread = threading.Thread(target=do_toggle_with_lock, daemon=True)
        thread.start_time = time.time()  # Track thread start time for timeout detection
        self.active_toggle_thread = thread
        # Track thread for cleanup
        with self.operation_lock:
            self.active_threads.append(thread)
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
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create integration
    integration = SolArkIntegration()
    
    try:
        # Simulate power source changes
        print("Simulating power source changes...")
        
        # Grid power
        integration.on_power_source_change('grid', {'frequency': 60.0, 'stability': 'high'})
        time.sleep(2)
        
        # Generator power
        integration.on_power_source_change('generator', {'frequency': 59.8, 'stability': 'low'})
        time.sleep(2)
        
        # Back to grid
        integration.on_power_source_change('grid', {'frequency': 60.0, 'stability': 'high'})
        time.sleep(2)
        
        # Show status
        status = integration.get_status()
        print(f"Integration status: {status}")
        
        # Keep running for a bit to let background threads work
        time.sleep(10)
        
    except KeyboardInterrupt:
        print("Stopping integration...")
    finally:
        integration.cleanup()


if __name__ == "__main__":
    main()
