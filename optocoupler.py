#!/usr/bin/env python3
"""
Optocoupler management for frequency measurement.
Handles pulse counting and frequency calculation with graceful degradation.
"""

import logging
import time
import threading
import os
import psutil
from typing import Optional, Tuple, List

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available. Running in simulation mode.")

# GIL-safe counter imports
try:
    from gil_safe_counter import create_counter
    COUNTER_AVAILABLE = True
except ImportError:
    COUNTER_AVAILABLE = False
    print("Warning: GIL-safe counter not available. Using fallback implementation.")


class SingleOptocoupler:
    """Manages a single optocoupler for frequency measurement."""
    
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
        
        # Initialize GIL-safe counter if available
        self.counter = None
        if COUNTER_AVAILABLE:
            try:
                self.counter = create_counter(self.logger)
                self.logger.info(f"GIL-safe counter initialized for {self.name}")
            except Exception as e:
                self.logger.warning(f"Failed to initialize GIL-safe counter: {e}")
                self.counter = None
        
        if self.gpio_available:
            self._setup_optocoupler()
    
    def _setup_optocoupler(self):
        """Setup optocoupler for falling edge detection."""
        if not self.gpio_available:
            self.logger.warning(f"GPIO not available, cannot setup {self.name} optocoupler")
            return
        
        try:
            self.logger.info(f"Setting up {self.name} optocoupler on GPIO pin {self.pin}")
            
            # Don't set GPIO mode here - let the main GPIO manager handle it
            # Just check if it's already set to BCM
            try:
                # Try to read a pin to see if GPIO is already initialized
                GPIO.input(self.pin)
                self.logger.debug("GPIO already initialized")
            except RuntimeError:
                # GPIO not initialized yet, set mode to BCM
                GPIO.setmode(GPIO.BCM)
                self.logger.info("GPIO mode set to BCM")
            
            # Configure GPIO pin for optocoupler input with pull-up resistor
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.logger.info(f"{self.name} optocoupler configured for input with pull-up resistor")
            
            # Test the pin to make sure it's working
            initial_state = GPIO.input(self.pin)
            self.logger.info(f"{self.name} optocoupler pin {self.pin} initial state: {initial_state}")
            
            # Set up interrupt-based pulse detection
            try:
                if self.counter and self.counter.gpio_available:
                    # Use GIL-safe counter for interrupt detection
                    if self.counter.setup_gpio_interrupt(self.pin):
                        self.logger.info(f"{self.name} optocoupler GIL-safe interrupt detection configured")
                    else:
                        raise Exception("GIL-safe counter setup failed")
                else:
                    # Fallback to Python callback (has GIL issues but works)
                    GPIO.add_event_detect(self.pin, GPIO.FALLING, callback=self._optocoupler_callback)
                    self.logger.info(f"{self.name} optocoupler Python interrupt detection configured")
            except Exception as e:
                self.logger.warning(f"Could not set up interrupt detection for {self.name}: {e}")
                self.logger.info(f"Will use polling method for {self.name} pulse detection")
            
            self.initialized = True
            self.logger.info(f"{self.name} optocoupler setup completed successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to setup {self.name} optocoupler: {e}")
            self.initialized = False
    
    def _optocoupler_callback(self, channel):
        """Callback function for optocoupler falling edge detection."""
        with self.pulse_count_lock:
            self.pulse_count += 1
            self.logger.debug(f"{self.name} optocoupler pulse detected, count: {self.pulse_count}")
    
    def count_optocoupler_pulses(self, duration: float = None, debounce_time: float = 0.0) -> int:
        """
        Count optocoupler pulses over specified duration using high-precision polling.
        Uses high-priority threading for maximum accuracy.
        NO AVERAGING - measures actual frequency changes.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            
        Returns:
            Number of pulses counted
        """
        if not self.initialized:
            self.logger.warning(f"{self.name} optocoupler not initialized, cannot count pulses")
            return 0
        
        if duration is None:
            duration = self.measurement_duration
        
        # Use high-precision timing for better accuracy
        pulse_count = 0
        start_time = time.perf_counter()
        last_state = GPIO.input(self.pin)
        last_change_time = start_time
        
        while time.perf_counter() - start_time < duration:
            current_state = GPIO.input(self.pin)
            current_time = time.perf_counter()
            
            # Detect only falling edges (1 -> 0) for optocoupler with debouncing
            if current_state != last_state:
                if current_time - last_change_time > debounce_time:
                    if last_state == 1 and current_state == 0:
                        pulse_count += 1
                    last_change_time = current_time
                    last_state = current_state
            # No sleep for maximum accuracy - let the system scheduler handle timing
        
        elapsed = time.perf_counter() - start_time
        self.logger.debug(f"{self.name} counted {pulse_count} pulses in {elapsed:.3f} seconds")
        return pulse_count
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None) -> Optional[float]:
        """
        Calculate AC frequency from pulse count.
        
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
        
        # Calculate frequency: pulses / (duration * pulses_per_cycle)
        # H11AA1 gives 2 pulses per AC cycle
        frequency = pulse_count / (duration * self.pulses_per_cycle)
        
        self.logger.debug(f"{self.name} calculated frequency: {frequency:.3f} Hz from {pulse_count} pulses in {duration:.2f}s")
        return frequency
    
    def cleanup(self):
        """Cleanup optocoupler resources."""
        if self.gpio_available and self.initialized:
            try:
                # Remove optocoupler event detection if it was set up
                GPIO.remove_event_detect(self.pin)
                self.logger.info(f"{self.name} optocoupler event detection removed")
            except Exception as e:
                self.logger.error(f"{self.name} optocoupler cleanup error: {e}")


class OptocouplerManager:
    """Manages one or more optocouplers for frequency measurement with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.gpio_available = GPIO_AVAILABLE
        
        # Auto-detect single vs dual mode based on secondary GPIO pin
        optocoupler_config = config.get('hardware', {}).get('optocoupler', {})
        secondary_config = optocoupler_config.get('secondary', {})
        secondary_pin = secondary_config.get('gpio_pin', -1)
        
        # If secondary GPIO pin is -1, it's single mode, otherwise dual mode
        self.dual_mode = secondary_pin != -1
        self.optocoupler_enabled = optocoupler_config.get('enabled', True)
        
        # Choose measurement method to avoid GIL issues
        self.measurement_method = optocoupler_config.get('measurement_method', 'interrupt')
        # Options: 'interrupt' (recommended), 'alternating' (fallback)
        
        # Initialize optocouplers
        self.optocouplers = {}
        self.optocoupler_initialized = False
        self.cpu_affinity_set = False
        
        # Thread priority optimization
        self._setup_thread_priority()
        
        if self.optocoupler_enabled:
            self._setup_optocouplers()
    
    def _setup_optocouplers(self):
        """Setup optocouplers based on configuration."""
        optocoupler_config = self.config.get('hardware', {}).get('optocoupler', {})
        
        # Always setup primary optocoupler
        primary_config = optocoupler_config.get('primary', {})
        if primary_config.get('enabled', True):
            primary_pin = primary_config.get('gpio_pin', 26)
            primary_pulses = primary_config.get('pulses_per_cycle', 2)
            primary_duration = primary_config.get('measurement_duration', 2.0)
            primary_name = primary_config.get('name', 'Primary')
            
            self.optocouplers['primary'] = SingleOptocoupler(
                self.config, self.logger, primary_name, primary_pin, 
                primary_pulses, primary_duration
            )
            self.logger.info(f"Primary optocoupler configured on pin {primary_pin}")
        
        # Setup secondary optocoupler only if dual mode (secondary pin != -1)
        if self.dual_mode:
            secondary_config = optocoupler_config.get('secondary', {})
            if secondary_config.get('enabled', True):
                secondary_pin = secondary_config.get('gpio_pin', 19)
                secondary_pulses = secondary_config.get('pulses_per_cycle', 2)
                secondary_duration = secondary_config.get('measurement_duration', 2.0)
                secondary_name = secondary_config.get('name', 'Secondary')
                
                self.optocouplers['secondary'] = SingleOptocoupler(
                    self.config, self.logger, secondary_name, secondary_pin, 
                    secondary_pulses, secondary_duration
                )
                self.logger.info(f"Secondary optocoupler configured on pin {secondary_pin}")
        
        # Check if any optocouplers were initialized
        self.optocoupler_initialized = any(opt.initialized for opt in self.optocouplers.values())
        mode_str = "dual" if self.dual_mode else "single"
        self.logger.info(f"{mode_str.capitalize()} optocoupler setup complete. Initialized: {self.optocoupler_initialized}")
    
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
        Count optocoupler pulses over specified duration using high-precision polling.
        Uses high-priority threading for maximum accuracy.
        NO AVERAGING - measures actual frequency changes.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            optocoupler_name: Name of optocoupler to use ('primary' or 'secondary')
            
        Returns:
            Number of pulses counted
        """
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return 0
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.count_optocoupler_pulses(duration, debounce_time)
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None, 
                                       optocoupler_name: str = 'primary') -> Optional[float]:
        """
        Calculate AC frequency from pulse count.
        
        Args:
            pulse_count: Number of pulses counted
            duration: Duration in seconds (uses config default if None)
            optocoupler_name: Name of optocoupler to use ('primary' or 'secondary')
            
        Returns:
            Calculated frequency in Hz, or None if invalid
        """
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return None
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
    
    def get_dual_frequencies(self, duration: float = None, debounce_time: float = 0.0) -> Tuple[Optional[float], Optional[float]]:
        """
        Get frequency readings from both optocouplers using interrupt-based counting.
        This avoids GIL issues by using GPIO interrupts instead of polling loops.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            
        Returns:
            Tuple of (primary_frequency, secondary_frequency) or (None, None) if not available
        """
        if not self.dual_mode:
            self.logger.warning("Dual mode not enabled, cannot get dual frequencies")
            return None, None
        
        if duration is None:
            duration = self.measurement_duration
        
        # Check if both optocouplers are available
        primary_available = ('primary' in self.optocouplers and self.optocouplers['primary'].initialized)
        secondary_available = ('secondary' in self.optocouplers and self.optocouplers['secondary'].initialized)
        
        if not primary_available and not secondary_available:
            self.logger.warning("No optocouplers available for dual measurement")
            return None, None
        
        # Choose measurement method based on configuration
        if self.measurement_method == 'interrupt':
            self.logger.debug("Using interrupt-based dual measurement (GIL-safe)")
            return self._get_dual_frequencies_interrupt_based(duration, debounce_time, primary_available, secondary_available)
        elif self.measurement_method == 'alternating':
            self.logger.debug("Using alternating dual measurement (GIL-safe fallback)")
            return self.get_dual_frequencies_alternating(duration, debounce_time)
        else:
            self.logger.warning(f"Unknown measurement method '{self.measurement_method}', using interrupt-based")
            return self._get_dual_frequencies_interrupt_based(duration, debounce_time, primary_available, secondary_available)
    
    def _get_dual_frequencies_interrupt_based(self, duration: float, debounce_time: float, 
                                            primary_available: bool, secondary_available: bool) -> Tuple[Optional[float], Optional[float]]:
        """
        Get dual frequencies using interrupt-based counting to avoid GIL issues.
        This method uses GPIO interrupts which are handled outside the Python GIL.
        """
        # Reset pulse counters
        if primary_available:
            optocoupler = self.optocouplers['primary']
            if optocoupler.counter:
                # Use GIL-safe counter
                optocoupler.counter.reset_count(optocoupler.pin)
            else:
                # Fallback to Python counter
                with optocoupler.pulse_count_lock:
                    optocoupler.pulse_count = 0
        
        if secondary_available:
            optocoupler = self.optocouplers['secondary']
            if optocoupler.counter:
                # Use GIL-safe counter
                optocoupler.counter.reset_count(optocoupler.pin)
            else:
                # Fallback to Python counter
                with optocoupler.pulse_count_lock:
                    optocoupler.pulse_count = 0
        
        # Start measurement period
        start_time = time.perf_counter()
        self.logger.debug(f"Starting dual optocoupler measurement for {duration:.2f}s")
        
        # Wait for measurement duration (interrupts handle counting)
        time.sleep(duration)
        
        # Get final counts
        primary_pulses = 0
        secondary_pulses = 0
        
        if primary_available:
            optocoupler = self.optocouplers['primary']
            if optocoupler.counter:
                # Use GIL-safe counter
                primary_pulses = optocoupler.counter.get_count(optocoupler.pin)
            else:
                # Fallback to Python counter
                with optocoupler.pulse_count_lock:
                    primary_pulses = optocoupler.pulse_count
        
        if secondary_available:
            optocoupler = self.optocouplers['secondary']
            if optocoupler.counter:
                # Use GIL-safe counter
                secondary_pulses = optocoupler.counter.get_count(optocoupler.pin)
            else:
                # Fallback to Python counter
                with optocoupler.pulse_count_lock:
                    secondary_pulses = optocoupler.pulse_count
        
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
    
    def get_dual_frequencies_alternating(self, duration: float = None, debounce_time: float = 0.0) -> Tuple[Optional[float], Optional[float]]:
        """
        Get frequency readings from both optocouplers using alternating measurement.
        This is a fallback method that avoids GIL issues by measuring one at a time.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (0.0 for clean signals)
            
        Returns:
            Tuple of (primary_frequency, secondary_frequency) or (None, None) if not available
        """
        if not self.dual_mode:
            self.logger.warning("Dual mode not enabled, cannot get dual frequencies")
            return None, None
        
        if duration is None:
            duration = self.measurement_duration
        
        # Check if both optocouplers are available
        primary_available = ('primary' in self.optocouplers and self.optocouplers['primary'].initialized)
        secondary_available = ('secondary' in self.optocouplers and self.optocouplers['secondary'].initialized)
        
        if not primary_available and not secondary_available:
            self.logger.warning("No optocouplers available for dual measurement")
            return None, None
        
        primary_freq = None
        secondary_freq = None
        
        # Measure primary first
        if primary_available:
            self.logger.debug("Measuring primary optocoupler...")
            primary_pulses = self.count_optocoupler_pulses(duration, debounce_time, 'primary')
            if primary_pulses > 0:
                primary_freq = self.calculate_frequency_from_pulses(primary_pulses, duration, 'primary')
        
        # Small delay to avoid interference
        time.sleep(0.1)
        
        # Measure secondary
        if secondary_available:
            self.logger.debug("Measuring secondary optocoupler...")
            secondary_pulses = self.count_optocoupler_pulses(duration, debounce_time, 'secondary')
            if secondary_pulses > 0:
                secondary_freq = self.calculate_frequency_from_pulses(secondary_pulses, duration, 'secondary')
        
        return primary_freq, secondary_freq
    
    def get_available_optocouplers(self) -> List[str]:
        """Get list of available optocoupler names."""
        return [name for name, opt in self.optocouplers.items() if opt.initialized]
    
    def is_dual_mode(self) -> bool:
        """Check if dual mode is enabled."""
        return self.dual_mode
    
    def is_dual_optocoupler_mode(self) -> bool:
        """Check if dual optocoupler mode is enabled (alias for backward compatibility)."""
        return self.dual_mode
    
    def cleanup(self):
        """Cleanup optocoupler resources."""
        for name, optocoupler in self.optocouplers.items():
            try:
                optocoupler.cleanup()
                self.logger.info(f"Cleaned up {name} optocoupler")
            except Exception as e:
                self.logger.error(f"Error cleaning up {name} optocoupler: {e}")
