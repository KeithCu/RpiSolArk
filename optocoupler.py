#!/usr/bin/env python3
"""
Optocoupler management for frequency measurement using working libgpiod implementation.
Handles pulse counting and frequency calculation with graceful degradation.
"""

import logging
import time
import threading
import os
import statistics
from typing import Optional, Tuple, List, Dict, Any
import psutil
import numpy as np

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    GPIO_AVAILABLE = False
    print(f"Warning: RPi.GPIO not available ({e}). Running in simulation mode.")

# GIL-safe counter imports (required)
from gpio_event_counter import create_counter

# Global flags for regression-based frequency calculation
# Set ENABLE_REGRESSION_COMPARISON = True to calculate and log regression results alongside standard results
ENABLE_REGRESSION_COMPARISON = True
# Set USE_REGRESSION_FOR_RESULT = True to return regression result instead of standard result
USE_REGRESSION_FOR_RESULT = False


class SingleOptocoupler:
    """Manages a single optocoupler for frequency measurement using working libgpiod."""
    
    def __init__(self, config, logger: logging.Logger, name: str, pin: int, 
                 pulses_per_cycle: int = 2, measurement_duration: float = 2.0):
        self.config = config
        self.logger = logger
        self.name = name
        self.pin = pin
        self.pulses_per_cycle = pulses_per_cycle
        self.measurement_duration = measurement_duration
        self.gpio_available = GPIO_AVAILABLE
        
        # Optocoupler pulse counting
        self.pulse_count = 0
        self.pulse_count_lock = threading.Lock()
        self.last_timestamps = []
        self.initialized = False
        
        # Error tracking and recovery
        self.consecutive_errors = 0
        self.max_consecutive_errors = config.get('hardware.optocoupler.max_consecutive_errors')
        self.last_successful_count = 0
        self.last_health_check = time.time()
        self.health_check_interval = config.get('hardware.optocoupler.health_check_interval')  # seconds
        self.recovery_attempts = 0
        self.max_recovery_attempts = config.get('hardware.optocoupler.max_recovery_attempts')
        
        # Initialize GIL-safe counter (required)
        self.counter = create_counter(self.logger)
        self.logger.info(f"GIL-safe counter initialized for {self.name}")
        
        if self.gpio_available:
            self._setup_optocoupler()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.cleanup()
        return False  # Don't suppress exceptions
    
    def _setup_optocoupler(self):
        """Setup optocoupler for edge detection using working libgpiod only."""
        if not self.gpio_available:
            self.logger.warning(f"GPIO not available, cannot setup {self.name} optocoupler")
            return
        
        try:
            self.logger.info(f"Setting up {self.name} optocoupler on GPIO pin {self.pin}")
            
            # Use libgpiod only - don't mix with RPi.GPIO to avoid conflicts
            # Set up GIL-free interrupt detection using working libgpiod
            try:
                if self.counter.register_pin(self.pin):
                    self.logger.info(f"{self.name} optocoupler libgpiod interrupt detection configured")
                    self.initialized = True
                else:
                    raise Exception("libgpiod counter setup failed")
            except Exception as e:
                self.logger.warning(f"Could not set up libgpiod interrupt detection for {self.name}: {e}")
                self.logger.info(f"Will use polling method for {self.name} pulse detection")
                # Still mark as initialized for polling fallback
                self.initialized = True
            
            self.logger.info(f"{self.name} optocoupler setup completed successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to setup {self.name} optocoupler: {e}")
            self.initialized = False
    
    def count_optocoupler_pulses(self, duration: float = None, debounce_time: float = 0.0) -> Tuple[int, float]:
        """
        Count optocoupler pulses over specified duration using working libgpiod.
        Uses interrupt-based counting for maximum accuracy and performance.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            
        Returns:
            Tuple of (pulse_count, actual_elapsed_time) where:
            - pulse_count: Number of pulses counted
            - actual_elapsed_time: Actual elapsed time in seconds (measured with time.perf_counter())
        """
        if not self.initialized:
            self.logger.warning(f"{self.name} optocoupler not initialized, cannot count pulses")
            return (0, 0.0)
        
        # Check health before measurement
        if not self.check_health():
            self.logger.warning(f"{self.name} optocoupler unhealthy, skipping measurement")
            return (0, 0.0)
        
        if duration is None:
            duration = self.measurement_duration
        
        try:
            # Reset counter before measurement
            self.counter.reset_count(self.pin)
            
            # Use libgpiod interrupt counting
            start_time = time.perf_counter()
            
            # Wait for the specified duration - libgpiod handles counting in background
            time.sleep(duration)
            
            # Get final count from libgpiod
            pulse_count = self.counter.get_count(self.pin)
            elapsed = time.perf_counter() - start_time
            
            # Retrieve frequency stats (count, first, last) directly to avoid list copy overhead
            stat_count, t_first, t_last = self.counter.get_frequency_info(self.pin)
            
            # Validate pulse count
            if pulse_count < 0:
                self.consecutive_errors += 1
                self.logger.warning(f"{self.name} invalid pulse count: {pulse_count}")
                return (0, elapsed)
            
            # Reset error count on successful measurement
            self.consecutive_errors = 0
            self.last_successful_count = pulse_count
            
            self.logger.debug(f"{self.name} counted {pulse_count} pulses in {elapsed:.3f} seconds (libgpiod)")
            return (pulse_count, elapsed)
            
        except Exception as e:
            self.consecutive_errors += 1
            self.logger.error(f"{self.name} pulse counting error: {e}")
            return (0, 0.0)
    
    def calculate_frequency_regression(self, pulse_count: int, duration: float = None) -> Optional[float]:
        """
        Calculate AC frequency using linear regression on all pulse timestamps.
        This method uses all timestamps to reduce the impact of individual timestamp jitter.
        
        Args:
            pulse_count: Number of pulses counted (used for validation)
            duration: Requested duration in seconds (used for logging)
            
        Returns:
            Calculated frequency in Hz, or None if invalid
        """
        if pulse_count < 2:
            return None
        
        try:
            # Retrieve full list of timestamps
            timestamps_ns = self.counter.get_timestamps(self.pin)
            
            if len(timestamps_ns) < 2:
                return None
            
            # Convert timestamps to relative time in seconds (starting from 0)
            t_first = timestamps_ns[0]
            times_sec = np.array([(ts - t_first) / 1e9 for ts in timestamps_ns])
            
            # Create pulse indices (0, 1, 2, ..., n-1)
            pulse_indices = np.arange(len(timestamps_ns))
            
            # Perform linear regression: time = slope * index + intercept
            # We want to find the slope (seconds per pulse interval)
            try:
                slope, intercept = np.polyfit(pulse_indices, times_sec, 1)
            except Exception as e:
                self.logger.warning(f"{self.name} regression polyfit failed: {e}")
                return None
            
            # Slope represents seconds per pulse interval
            # Frequency = 1 / (slope * pulses_per_cycle)
            if slope <= 0:
                self.logger.warning(f"{self.name} invalid regression slope: {slope}")
                return None
            
            frequency = 1.0 / (slope * self.pulses_per_cycle)
            
            # Sanity check (40-80Hz range) to prevent gross outliers
            if 40 <= frequency <= 80:
                self.logger.debug(f"{self.name} regression frequency: {frequency:.3f} Hz (from {len(timestamps_ns)} timestamps)")
                return frequency
            else:
                self.logger.warning(f"{self.name} regression frequency {frequency:.3f} Hz out of range")
                return None
                
        except Exception as e:
            self.logger.warning(f"{self.name} regression calculation failed: {e}")
            return None
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None, actual_duration: float = None) -> Optional[float]:
        """
        Calculate AC frequency from pulse count using correct libgpiod calculation.
        
        Args:
            pulse_count: Number of pulses counted
            duration: Requested duration in seconds (uses config default if None, used for logging)
            actual_duration: Actual measured duration in seconds (if None, uses duration parameter)
                           Use this for accurate frequency calculation based on actual elapsed time
            
        Returns:
            Calculated frequency in Hz, or None if invalid
        """
        if duration is None:
            duration = self.measurement_duration
        
        # Use actual_duration if provided, otherwise fall back to requested duration
        measurement_duration = actual_duration if actual_duration is not None else duration
        
        if pulse_count <= 0 or measurement_duration <= 0:
            return None
        
        # Calculate regression-based frequency if enabled for comparison
        freq_regression = None
        if ENABLE_REGRESSION_COMPARISON:
            freq_regression = self.calculate_frequency_regression(pulse_count, duration)
        
        # METHOD 1: Precise Timestamp Interval Analysis
        # This method eliminates synchronization errors between CPU sleep time and pulse arrival.
        # It calculates frequency based on the exact time elapsed between the first and last pulse.
        # Frequency = (Count - 1) / (Last_Timestamp - First_Timestamp)
        # This is the "raw" frequency of the observed pulse train without any median filtering.
        
        # Use the stats retrieved in count_optocoupler_pulses if available
        # (This assumes count_optocoupler_pulses was called just before this)
        freq_first_last = None
        try:
            stat_count, t_first, t_last = self.counter.get_frequency_info(self.pin)
            self.logger.debug(f"Timestamp debug: count={stat_count}, duration_ns={t_last - t_first if stat_count > 1 else 0}")
            
            if stat_count >= 2:
                # Calculate total duration of the observed pulses
                duration_ns = t_last - t_first
                
                # Calculate number of full intervals observed
                # If we have N pulses, we have N-1 intervals between them
                num_intervals = stat_count - 1
                
                if duration_ns > 0 and num_intervals > 0:
                    # Calculate frequency: Intervals / Duration
                    # Convert duration from ns to seconds (1e9)
                    # We use a divisor of 2 because:
                    # 1. H11AA1 generates 2 zero-crossing pulses per AC cycle (0 deg and 180 deg)
                    # 2. The pulses are very narrow (~33us).
                    # 3. Our 0.2ms debounce filters out the falling edge of each pulse.
                    # 4. Therefore, we count exactly 1 rising edge per zero-crossing.
                    # Total: 2 events per AC cycle.
                    freq_first_last = (num_intervals * 1e9) / (duration_ns * self.pulses_per_cycle)
                    
                    # Sanity check (40-80Hz range) to prevent gross outliers from single glitches
                    if 40 <= freq_first_last <= 80:
                        self.logger.debug(f"{self.name} precision frequency: {freq_first_last:.3f} Hz (from {stat_count} pulses over {duration_ns/1e9:.3f}s)")
                    else:
                        self.logger.warning(f"{self.name} precision frequency {freq_first_last:.3f} Hz out of range, falling back to average")
                        freq_first_last = None
        except Exception as e:
            self.logger.warning(f"{self.name} timestamp analysis failed: {e}")
        
        # Log comparison if both methods succeeded and comparison is enabled
        if ENABLE_REGRESSION_COMPARISON and freq_first_last is not None and freq_regression is not None:
            diff = abs(freq_regression - freq_first_last)
            diff_pct = (diff / freq_first_last) * 100 if freq_first_last > 0 else 0
            self.logger.info(f"{self.name} frequency comparison: First/Last={freq_first_last:.6f} Hz, Regression={freq_regression:.6f} Hz, Diff={diff:.6f} Hz ({diff_pct:.3f}%)")
        
        # Use regression result if enabled and available, otherwise use first/last
        if USE_REGRESSION_FOR_RESULT and freq_regression is not None:
            return freq_regression
        elif freq_first_last is not None:
            return freq_first_last

        # METHOD 2: Average Frequency (Fallback)
        # Calculate frequency using correct libgpiod calculation for AC-into-DC-optocoupler
        # H11AA1 with AC input: optocoupler output is a square wave that transitions on each zero-crossing
        # libgpiod counts BOTH rising and falling edges (Edge.BOTH detection)
        # For 60 Hz AC: we get 4 edges per cycle (rising at +zero, falling at -zero, rising at +zero, falling at -zero)
        # Actual measurement confirms: 240 edges/second = 60 Hz * 4 edges/cycle
        # So we divide by 4 to convert edge count to frequency
        # UPDATE: With 0.2ms debounce, we filter the falling edge (pulse width ~33us).
        # So we count 2 edges per cycle.
        frequency = pulse_count / (measurement_duration * self.pulses_per_cycle)  # 2 edges per AC cycle (Debounced)
        
        if actual_duration is not None and abs(actual_duration - duration) > 0.001:
            self.logger.debug(f"{self.name} calculated frequency: {frequency:.3f} Hz from {pulse_count} pulses in {actual_duration:.3f}s (requested: {duration:.3f}s)")
        else:
            self.logger.debug(f"{self.name} calculated frequency: {frequency:.3f} Hz from {pulse_count} pulses in {measurement_duration:.2f}s")
        return frequency
    
    def check_health(self) -> bool:
        """Check optocoupler health and attempt recovery if needed."""
        current_time = time.time()
        
        # Only check health periodically
        if current_time - self.last_health_check < self.health_check_interval:
            return True
        
        self.last_health_check = current_time
        
        try:
            # Perform a quick test read
            test_count = self.counter.get_count(self.pin)
            
            # Check if counter is responding
            if test_count >= 0:  # Valid count
                self.consecutive_errors = 0
                self.logger.debug(f"{self.name} health check passed: count={test_count}")
                return True
            else:
                self.consecutive_errors += 1
                self.logger.warning(f"{self.name} health check failed: invalid count={test_count}")
                
        except Exception as e:
            self.consecutive_errors += 1
            self.logger.warning(f"{self.name} health check failed: {e}")
        
        # Attempt recovery if too many consecutive errors
        if self.consecutive_errors >= self.max_consecutive_errors:
            return self._attempt_recovery()
        
        return True
    
    def _attempt_recovery(self) -> bool:
        """Attempt to recover from optocoupler failure."""
        if self.recovery_attempts >= self.max_recovery_attempts:
            self.logger.critical(f"{self.name} optocoupler recovery failed after {self.max_recovery_attempts} attempts")
            return False
        
        self.recovery_attempts += 1
        self.logger.warning(f"{self.name} attempting recovery (attempt {self.recovery_attempts}/{self.max_recovery_attempts})")
        
        try:
            # Reset counter
            self.counter.reset_count(self.pin)
            
            # Re-setup optocoupler
            self._setup_optocoupler()
            
            # Test with a short measurement
            try:
                test_pulses, test_elapsed = self.count_optocoupler_pulses(0.5)  # 0.5 second test

                if test_pulses >= 0:
                    self.consecutive_errors = 0
                    self.logger.info(f"{self.name} recovery successful: {test_pulses} pulses in {test_elapsed:.3f}s")
                    return True
                else:
                    self.logger.warning(f"{self.name} recovery test failed: {test_pulses} pulses")
                    return False
            except Exception as e:
                self.logger.error(f"{self.name} recovery test failed with exception: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"{self.name} recovery attempt failed: {e}")
            return False
    
    def is_healthy(self) -> bool:
        """Check if optocoupler is currently healthy."""
        return self.consecutive_errors < self.max_consecutive_errors and self.initialized
    
    def cleanup(self):
        """Cleanup optocoupler resources."""
        if self.gpio_available and self.initialized:
            try:
                # Cleanup libgpiod counter
                if self.counter:
                    self.counter.cleanup()
                self.logger.info(f"{self.name} optocoupler cleanup completed")
            except Exception as e:
                self.logger.error(f"{self.name} optocoupler cleanup error: {e}")


class OptocouplerManager:
    """Manages one or more optocouplers for frequency measurement with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.gpio_available = GPIO_AVAILABLE
        
        # Get optocoupler configuration
        try:
            optocoupler_config = config['hardware']['optocoupler']
            self.optocoupler_enabled = optocoupler_config['enabled']
        except KeyError as e:
            raise KeyError(f"Missing required configuration key: {e}")
        
        
        # Initialize optocouplers
        self.optocouplers = {}
        self.optocoupler_initialized = False
        self.cpu_affinity_set = False
        
        # Thread priority optimization
        self._setup_thread_priority()
        
        if self.optocoupler_enabled:
            self._setup_optocouplers()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.cleanup()
        return False  # Don't suppress exceptions
    
    def _setup_optocouplers(self):
        """Setup optocouplers based on configuration."""
        if not self.optocoupler_enabled:
            self.logger.info("Optocoupler disabled, skipping setup")
            return
            
        try:
            optocoupler_config = self.config['hardware']['optocoupler']
            
            # Always setup primary optocoupler
            primary_config = optocoupler_config['primary']
            primary_pin = primary_config['gpio_pin']
            primary_pulses = primary_config['pulses_per_cycle']
            primary_duration = primary_config['measurement_duration']
            primary_name = primary_config['name']
        except KeyError as e:
            raise KeyError(f"Missing required configuration key: {e}")
        
        self.optocouplers['primary'] = SingleOptocoupler(
            self.config, self.logger, primary_name, primary_pin, 
            primary_pulses, primary_duration
        )
        self.logger.info(f"Optocoupler configured on pin {primary_pin}")
        
        # Check if optocoupler was initialized
        self.optocoupler_initialized = self.optocouplers['primary'].initialized
        self.logger.info(f"Optocoupler setup complete. Initialized: {self.optocoupler_initialized}")
        
        # Build inverter mapping for each optocoupler
        self._build_inverter_mapping()
    
    def _build_inverter_mapping(self):
        """Build mapping of optocouplers to their associated inverters."""
        self.inverter_mapping = {}
        
        try:
            optocoupler_config = self.config['hardware']['optocoupler']
            
            # Process primary optocoupler inverters
            primary_config = optocoupler_config['primary']
            primary_inverters = primary_config.get('inverters')
            
            # Handle backward compatibility - if old format exists, convert it
            if 'solark_inverter_id' in primary_config and primary_config['solark_inverter_id']:
                primary_inverters = [{
                    'id': primary_config['solark_inverter_id'],
                    'name': f"{primary_config['name']} Inverter",
                    'enabled': True
                }]
                self.logger.info("Converted legacy single inverter config to new multi-inverter format")
            
            self.inverter_mapping['primary'] = []
            if primary_inverters:
                for inverter in primary_inverters:
                    if inverter.get('id') and inverter.get('enabled', True):
                        self.inverter_mapping['primary'].append({
                            'id': inverter['id'],
                            'name': inverter.get('name', f"Inverter {inverter['id']}"),
                            'enabled': inverter.get('enabled', True)
                        })
                        self.logger.info(f"Optocoupler mapped to inverter: {inverter['id']} ({inverter.get('name', 'Unnamed')})")
                
        except KeyError as e:
            self.logger.warning(f"Missing inverter configuration: {e}")
            self.inverter_mapping = {'primary': []}
    
    def get_inverters_for_optocoupler(self, optocoupler_name: str) -> List[dict]:
        """
        Get list of inverters associated with a specific optocoupler.
        
        Args:
            optocoupler_name: 'primary' (only primary is supported)
            
        Returns:
            List of inverter dictionaries with 'id', 'name', and 'enabled' keys
        """
        if optocoupler_name != 'primary':
            self.logger.warning(f"Only 'primary' optocoupler is supported, got '{optocoupler_name}'")
            return []
        return self.inverter_mapping.get(optocoupler_name, [])
    
    def get_all_inverters(self) -> List[dict]:
        """
        Get all inverters from all optocouplers.
        
        Returns:
            List of all inverter dictionaries with optocoupler context
        """
        all_inverters = []
        
        for optocoupler_name, inverters in self.inverter_mapping.items():
            for inverter in inverters:
                inverter_with_context = inverter.copy()
                inverter_with_context['optocoupler'] = optocoupler_name
                all_inverters.append(inverter_with_context)
        
        return all_inverters
    
    def get_enabled_inverters(self) -> List[dict]:
        """
        Get all enabled inverters from all optocouplers.
        
        Returns:
            List of enabled inverter dictionaries with optocoupler context
        """
        return [inv for inv in self.get_all_inverters() if inv.get('enabled', True)]
    
    def _setup_thread_priority(self):
        """Setup high-priority threading and CPU affinity for optocoupler measurements."""
        try:
            # Set current process to high priority (safe for RPi 4)
            current_process = psutil.Process()
            
            # Set process priority to high (but not realtime to avoid system issues)
            if hasattr(psutil, 'HIGH_PRIORITY_CLASS'):
                current_process.nice(psutil.HIGH_PRIORITY_CLASS)
                self.logger.info("Set process priority to HIGH")
            else:
                # On Linux, use nice value (-10 to 19, lower = higher priority)
                # Use -5 for high priority (safe for RPi 4)
                os.nice(-5)
                self.logger.info("Set process nice value to -5 (high priority)")
            
            # Set CPU affinity to single core for consistent timing (RPi4 optimization)
            if not self.cpu_affinity_set:
                try:
                    # Pin to CPU core 3 (last core) to avoid interference with system processes
                    current_process.cpu_affinity([3])
                    self.cpu_affinity_set = True
                    self.logger.info("Set CPU affinity to core 3 for consistent timing")
                except (OSError, ValueError) as e:
                    self.logger.warning(f"Could not set CPU affinity: {e}")
                    # Try core 2 as fallback
                    try:
                        current_process.cpu_affinity([2])
                        self.cpu_affinity_set = True
                        self.logger.info("Set CPU affinity to core 2 for consistent timing")
                    except (OSError, ValueError):
                        self.logger.warning("Could not set CPU affinity, continuing with default")
                
        except (PermissionError, OSError) as e:
            self.logger.warning(f"Could not set high priority: {e}")
            self.logger.info("Continuing with normal priority")
        except Exception as e:
            self.logger.warning(f"Thread priority setup failed: {e}")
    
    def count_optocoupler_pulses(self, duration: float = None, debounce_time: float = 0.0, 
                                optocoupler_name: str = 'primary') -> Tuple[int, float]:
        """
        Count optocoupler pulses over specified duration using working libgpiod.
        Uses interrupt-based counting for maximum accuracy.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            optocoupler_name: Name of optocoupler to use ('primary' only)
            
        Returns:
            Tuple of (pulse_count, actual_elapsed_time)
        """
        if not self.optocoupler_enabled:
            self.logger.debug("Optocoupler disabled, returning 0 pulses")
            return (0, 0.0)
            
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return (0, 0.0)
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.count_optocoupler_pulses(duration, debounce_time)
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None, 
                                       optocoupler_name: str = 'primary', actual_duration: float = None) -> Optional[float]:
        """
        Calculate AC frequency from pulse count using working libgpiod calculation.
        
        Args:
            pulse_count: Number of pulses counted
            duration: Requested duration in seconds (uses config default if None, used for logging)
            optocoupler_name: Name of optocoupler to use ('primary' only)
            actual_duration: Actual measured duration in seconds (if None, uses duration parameter)
                           Use this for accurate frequency calculation based on actual elapsed time
            
        Returns:
            Calculated frequency in Hz, or None if invalid
        """
        if not self.optocoupler_enabled:
            self.logger.debug("Optocoupler disabled, returning None frequency")
            return None
            
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return None
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.calculate_frequency_from_pulses(pulse_count, duration, actual_duration)
    
    def get_available_optocouplers(self) -> List[str]:
        """Get list of available optocoupler names."""
        if not self.optocoupler_enabled:
            return []
        return [name for name, opt in self.optocouplers.items() if opt.initialized]
    
    def check_all_health(self) -> Dict[str, bool]:
        """Check health of all optocouplers."""
        health_status = {}
        for name, optocoupler in self.optocouplers.items():
            health_status[name] = optocoupler.check_health()
        return health_status
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status of all optocouplers."""
        status = {}
        for name, optocoupler in self.optocouplers.items():
            status[name] = {
                'healthy': optocoupler.is_healthy(),
                'initialized': optocoupler.initialized,
                'consecutive_errors': optocoupler.consecutive_errors,
                'max_consecutive_errors': optocoupler.max_consecutive_errors,
                'recovery_attempts': optocoupler.recovery_attempts,
                'last_successful_count': optocoupler.last_successful_count
            }
        return status
    
    def cleanup(self):
        """Cleanup optocoupler resources."""
        for name, optocoupler in self.optocouplers.items():
            try:
                optocoupler.cleanup()
                self.logger.info(f"Cleaned up {name} optocoupler")
            except Exception as e:
                self.logger.error(f"Error cleaning up {name} optocoupler: {e}")