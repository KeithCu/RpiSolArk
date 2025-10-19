#!/usr/bin/env python3
"""
Optocoupler management for frequency measurement.
Handles pulse counting and frequency calculation with graceful degradation.
"""

import logging
import time
import threading
from typing import Optional

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available. Running in simulation mode.")


class OptocouplerManager:
    """Manages optocoupler for frequency measurement with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.gpio_available = GPIO_AVAILABLE
        
        # Optocoupler configuration
        self.optocoupler_enabled = config.get('hardware', {}).get('optocoupler', {}).get('enabled', True)
        self.optocoupler_pin = config.get('hardware', {}).get('optocoupler', {}).get('gpio_pin', 18)
        self.pulses_per_cycle = config.get('hardware', {}).get('optocoupler', {}).get('pulses_per_cycle', 2)
        self.measurement_duration = config.get('hardware', {}).get('optocoupler', {}).get('measurement_duration', 1.0)
        
        # Optocoupler pulse counting
        self.pulse_count = 0
        self.pulse_count_lock = threading.Lock()
        self.optocoupler_initialized = False
        
        if self.optocoupler_enabled:
            self._setup_optocoupler()
    
    def _setup_optocoupler(self):
        """Setup optocoupler for falling edge detection."""
        if not self.gpio_available:
            self.logger.warning("GPIO not available, cannot setup optocoupler")
            return
        
        try:
            self.logger.info(f"Setting up optocoupler on GPIO pin {self.optocoupler_pin}")
            
            # Don't set GPIO mode here - let the main GPIO manager handle it
            # Just check if it's already set to BCM
            try:
                # Try to read a pin to see if GPIO is already initialized
                GPIO.input(self.optocoupler_pin)
                self.logger.debug("GPIO already initialized")
            except RuntimeError:
                # GPIO not initialized yet, set mode to BCM
                GPIO.setmode(GPIO.BCM)
                self.logger.info("GPIO mode set to BCM")
            
            # Configure GPIO pin for optocoupler input with pull-up resistor
            GPIO.setup(self.optocoupler_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.logger.info("Optocoupler configured for input with pull-up resistor")
            
            # Test the pin to make sure it's working
            initial_state = GPIO.input(self.optocoupler_pin)
            self.logger.info(f"Optocoupler pin {self.optocoupler_pin} initial state: {initial_state}")
            
            # Set up interrupt-based pulse detection
            try:
                GPIO.add_event_detect(self.optocoupler_pin, GPIO.FALLING, callback=self._optocoupler_callback)
                self.logger.info("Optocoupler interrupt detection configured for falling edges")
            except Exception as e:
                self.logger.warning(f"Could not set up interrupt detection: {e}")
                self.logger.info("Will use polling method for pulse detection")
            
            self.optocoupler_initialized = True
            self.logger.info("Optocoupler setup completed successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to setup optocoupler: {e}")
            self.optocoupler_initialized = False
    
    def _optocoupler_callback(self, channel):
        """Callback function for optocoupler falling edge detection."""
        with self.pulse_count_lock:
            self.pulse_count += 1
            self.logger.debug(f"Optocoupler pulse detected, count: {self.pulse_count}")
    
    def count_optocoupler_pulses(self, duration: float = None, debounce_time: float = 0.001) -> int:
        """
        Count optocoupler pulses over specified duration using high-precision polling with debouncing.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            debounce_time: Minimum time between state changes to filter noise (default 1ms)
            
        Returns:
            Number of pulses counted
        """
        if not self.optocoupler_initialized:
            self.logger.warning("Optocoupler not initialized, cannot count pulses")
            return 0
        
        if duration is None:
            duration = self.measurement_duration
        
        # Use high-precision timing for better accuracy
        pulse_count = 0
        start_time = time.perf_counter()
        last_state = GPIO.input(self.optocoupler_pin)
        last_change_time = start_time
        
        while time.perf_counter() - start_time < duration:
            current_state = GPIO.input(self.optocoupler_pin)
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
        self.logger.debug(f"Counted {pulse_count} pulses in {elapsed:.3f} seconds")
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
        
        self.logger.debug(f"Calculated frequency: {frequency:.3f} Hz from {pulse_count} pulses in {duration:.2f}s")
        return frequency
    
    def cleanup(self):
        """Cleanup optocoupler resources."""
        if self.gpio_available and self.optocoupler_initialized:
            try:
                # Remove optocoupler event detection if it was set up
                GPIO.remove_event_detect(self.optocoupler_pin)
                self.logger.info("Optocoupler event detection removed")
            except Exception as e:
                self.logger.error(f"Optocoupler cleanup error: {e}")
