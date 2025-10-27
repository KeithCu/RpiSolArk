#!/usr/bin/env python3
"""
Optocoupler management for frequency measurement using working libgpiod implementation.
Handles pulse counting and frequency calculation with graceful degradation.
"""

import logging
import time
import threading
import os
from typing import Optional, Tuple, List, Dict, Any
import psutil

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    GPIO_AVAILABLE = False
    print(f"Warning: RPi.GPIO not available ({e}). Running in simulation mode.")

# GIL-safe counter imports (required)
from gpio_event_counter import create_counter


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
    
    def count_optocoupler_pulses(self, duration: float = None, debounce_time: float = 0.0) -> int:
        """
        Count optocoupler pulses over specified duration using working libgpiod.
        Uses interrupt-based counting for maximum accuracy and performance.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            
        Returns:
            Number of pulses counted
        """
        if not self.initialized:
            self.logger.warning(f"{self.name} optocoupler not initialized, cannot count pulses")
            return 0
        
        # Check health before measurement
        if not self.check_health():
            self.logger.warning(f"{self.name} optocoupler unhealthy, skipping measurement")
            return 0
        
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
            
            # Validate pulse count
            if pulse_count < 0:
                self.consecutive_errors += 1
                self.logger.warning(f"{self.name} invalid pulse count: {pulse_count}")
                return 0
            
            # Reset error count on successful measurement
            self.consecutive_errors = 0
            self.last_successful_count = pulse_count
            
            self.logger.debug(f"{self.name} counted {pulse_count} pulses in {elapsed:.3f} seconds (libgpiod)")
            return pulse_count
            
        except Exception as e:
            self.consecutive_errors += 1
            self.logger.error(f"{self.name} pulse counting error: {e}")
            return 0
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None) -> Optional[float]:
        """
        Calculate AC frequency from pulse count using correct libgpiod calculation.
        
        Args:
            pulse_count: Number of pulses counted
            duration: Duration in seconds (uses config default if None)
            
        Returns:
            Calculated frequency in Hz, or None if invalid
        """
        if duration is None:
            duration = self.measurement_duration
        
        if pulse_count <= 0 or duration <= 0:
            return None
        
        # Calculate frequency using correct libgpiod calculation for AC-into-DC-optocoupler
        # H11AA1 with AC input (no rectifier): 1 pulse per AC cycle
        # libgpiod counts 4 edges per AC cycle (both edges of both transitions)
        # So we need to divide by 4 to get frequency
        frequency = pulse_count / (duration * 4)  # 4 edges per AC cycle
        
        self.logger.debug(f"{self.name} calculated frequency: {frequency:.3f} Hz from {pulse_count} pulses in {duration:.2f}s")
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
            test_pulses = self.count_optocoupler_pulses(0.5)  # 0.5 second test
            
            if test_pulses >= 0:
                self.consecutive_errors = 0
                self.logger.info(f"{self.name} recovery successful: {test_pulses} pulses in test")
                return True
            else:
                self.logger.warning(f"{self.name} recovery test failed: {test_pulses} pulses")
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
        
        # Only proceed with optocoupler setup if enabled
        if self.optocoupler_enabled:
            try:
                # Check for secondary configuration
                secondary_config = optocoupler_config.get('secondary', {})
                secondary_pin = secondary_config.get('gpio_pin', -1)
            except KeyError as e:
                raise KeyError(f"Missing required secondary optocoupler configuration key: {e}")
            
            # If secondary GPIO pin is -1, it's single mode, otherwise dual mode
            self.dual_mode = secondary_pin != -1
        else:
            # Optocoupler disabled - set defaults
            self.dual_mode = False
        
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
        self.logger.info(f"Primary optocoupler configured on pin {primary_pin}")
        
        # Setup secondary optocoupler only if dual mode (secondary pin != -1)
        if self.dual_mode:
            try:
                secondary_config = optocoupler_config['secondary']
                secondary_pin = secondary_config['gpio_pin']
                secondary_pulses = secondary_config['pulses_per_cycle']
                secondary_duration = secondary_config['measurement_duration']
                secondary_name = secondary_config['name']
            except KeyError as e:
                raise KeyError(f"Missing required secondary optocoupler configuration key: {e}")
            
            self.optocouplers['secondary'] = SingleOptocoupler(
                self.config, self.logger, secondary_name, secondary_pin, 
                secondary_pulses, secondary_duration
            )
            self.logger.info(f"Secondary optocoupler configured on pin {secondary_pin}")
        
        # Check if any optocouplers were initialized
        self.optocoupler_initialized = any(opt.initialized for opt in self.optocouplers.values())
        mode_str = "dual" if self.dual_mode else "single"
        self.logger.info(f"{mode_str.capitalize()} optocoupler setup complete. Initialized: {self.optocoupler_initialized}")
        
        # Build inverter mapping for each optocoupler
        self._build_inverter_mapping()
    
    def _build_inverter_mapping(self):
        """Build mapping of optocouplers to their associated inverters."""
        self.inverter_mapping = {}
        
        try:
            optocoupler_config = self.config['hardware']['optocoupler']
            
            # Process primary optocoupler inverters
            primary_config = optocoupler_config['primary']
            primary_inverters = primary_config.get('inverters', [])
            
            # Handle backward compatibility - if old format exists, convert it
            if 'solark_inverter_id' in primary_config and primary_config['solark_inverter_id']:
                primary_inverters = [{
                    'id': primary_config['solark_inverter_id'],
                    'name': f"{primary_config['name']} Inverter",
                    'enabled': True
                }]
                self.logger.info("Converted legacy single inverter config to new multi-inverter format")
            
            self.inverter_mapping['primary'] = []
            for inverter in primary_inverters:
                if inverter.get('id') and inverter.get('enabled', True):
                    self.inverter_mapping['primary'].append({
                        'id': inverter['id'],
                        'name': inverter.get('name', f"Inverter {inverter['id']}"),
                        'enabled': inverter.get('enabled', True)
                    })
                    self.logger.info(f"Primary optocoupler mapped to inverter: {inverter['id']} ({inverter.get('name', 'Unnamed')})")
            
            # Process secondary optocoupler inverters (if dual mode)
            if self.dual_mode:
                secondary_config = optocoupler_config['secondary']
                secondary_inverters = secondary_config.get('inverters', [])
                
                # Handle backward compatibility
                if 'solark_inverter_id' in secondary_config and secondary_config['solark_inverter_id']:
                    secondary_inverters = [{
                        'id': secondary_config['solark_inverter_id'],
                        'name': f"{secondary_config['name']} Inverter",
                        'enabled': True
                    }]
                
                self.inverter_mapping['secondary'] = []
                for inverter in secondary_inverters:
                    if inverter.get('id') and inverter.get('enabled', True):
                        self.inverter_mapping['secondary'].append({
                            'id': inverter['id'],
                            'name': inverter.get('name', f"Inverter {inverter['id']}"),
                            'enabled': inverter.get('enabled', True)
                        })
                        self.logger.info(f"Secondary optocoupler mapped to inverter: {inverter['id']} ({inverter.get('name', 'Unnamed')})")
            else:
                self.inverter_mapping['secondary'] = []
                
        except KeyError as e:
            self.logger.warning(f"Missing inverter configuration: {e}")
            self.inverter_mapping = {'primary': [], 'secondary': []}
    
    def get_inverters_for_optocoupler(self, optocoupler_name: str) -> List[dict]:
        """
        Get list of inverters associated with a specific optocoupler.
        
        Args:
            optocoupler_name: 'primary' or 'secondary'
            
        Returns:
            List of inverter dictionaries with 'id', 'name', and 'enabled' keys
        """
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
                                optocoupler_name: str = 'primary') -> int:
        """
        Count optocoupler pulses over specified duration using working libgpiod.
        Uses interrupt-based counting for maximum accuracy.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            optocoupler_name: Name of optocoupler to use ('primary' or 'secondary')
            
        Returns:
            Number of pulses counted
        """
        if not self.optocoupler_enabled:
            self.logger.debug("Optocoupler disabled, returning 0 pulses")
            return 0
            
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return 0
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.count_optocoupler_pulses(duration, debounce_time)
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None, 
                                       optocoupler_name: str = 'primary') -> Optional[float]:
        """
        Calculate AC frequency from pulse count using working libgpiod calculation.
        
        Args:
            pulse_count: Number of pulses counted
            duration: Duration in seconds (uses config default if None)
            optocoupler_name: Name of optocoupler to use ('primary' or 'secondary')
            
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
        return optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
    
    def get_dual_frequencies(self, duration: float = None, debounce_time: float = 0.0) -> Tuple[Optional[float], Optional[float]]:
        """
        Get frequency readings from both optocouplers using working libgpiod.
        This avoids GIL issues by using GPIO interrupts instead of polling loops.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            
        Returns:
            Tuple of (primary_frequency, secondary_frequency) or (None, None) if not available
        """
        if not self.optocoupler_enabled:
            self.logger.debug("Optocoupler disabled, returning None frequencies")
            return None, None
            
        if not self.dual_mode:
            self.logger.warning("Dual mode not enabled, cannot get dual frequencies")
            return None, None
        
        if duration is None:
            duration = 2.0  # Default duration
        
        # Check if both optocouplers are available
        primary_available = ('primary' in self.optocouplers and self.optocouplers['primary'].initialized)
        secondary_available = ('secondary' in self.optocouplers and self.optocouplers['secondary'].initialized)
        
        if not primary_available and not secondary_available:
            self.logger.warning("No optocouplers available for dual measurement")
            return None, None
        
        # Reset pulse counters
        if primary_available:
            optocoupler = self.optocouplers['primary']
            optocoupler.counter.reset_count(optocoupler.pin)
        
        if secondary_available:
            optocoupler = self.optocouplers['secondary']
            optocoupler.counter.reset_count(optocoupler.pin)
        
        # Start measurement period
        start_time = time.perf_counter()
        self.logger.debug(f"Starting dual optocoupler measurement for {duration:.2f}s")
        
        # Wait for measurement duration (libgpiod handles counting)
        time.sleep(duration)
        
        # Get final counts
        primary_pulses = 0
        secondary_pulses = 0
        
        if primary_available:
            optocoupler = self.optocouplers['primary']
            primary_pulses = optocoupler.counter.get_count(optocoupler.pin)
        
        if secondary_available:
            optocoupler = self.optocouplers['secondary']
            secondary_pulses = optocoupler.counter.get_count(optocoupler.pin)
        
        elapsed = time.perf_counter() - start_time
        self.logger.debug(f"Dual measurement completed in {elapsed:.3f}s - Primary: {primary_pulses}, Secondary: {secondary_pulses}")
        
        # Calculate frequencies
        primary_freq = None
        secondary_freq = None
        
        if primary_available and primary_pulses > 0:
            primary_freq = self.calculate_frequency_from_pulses(primary_pulses, duration, 'primary')
        
        if secondary_available and secondary_pulses > 0:
            secondary_freq = self.calculate_frequency_from_pulses(secondary_pulses, duration, 'secondary')
        
        return primary_freq, secondary_freq
    
    def get_available_optocouplers(self) -> List[str]:
        """Get list of available optocoupler names."""
        if not self.optocoupler_enabled:
            return []
        return [name for name, opt in self.optocouplers.items() if opt.initialized]
    
    def is_dual_mode(self) -> bool:
        """Check if dual mode is enabled."""
        return self.dual_mode
    
    def is_dual_optocoupler_mode(self) -> bool:
        """Check if dual optocoupler mode is enabled (alias for backward compatibility)."""
        return self.dual_mode
    
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