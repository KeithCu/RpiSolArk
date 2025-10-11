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
        self.optocoupler_enabled = config.get('hardware.optocoupler.enabled', True)
        self.optocoupler_pin = config.get('hardware.optocoupler.gpio_pin', 18)
        self.optocoupler_pull_up = config.get('hardware.optocoupler.pull_up', True)
        self.pulses_per_cycle = config.get('hardware.optocoupler.pulses_per_cycle', 2)
        self.measurement_duration = config.get('hardware.optocoupler.measurement_duration', 1.0)
        
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
            
            # Configure GPIO pin for optocoupler input
            if self.optocoupler_pull_up:
                GPIO.setup(self.optocoupler_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                self.logger.info("Optocoupler configured with internal pull-up resistor")
            else:
                GPIO.setup(self.optocoupler_pin, GPIO.IN)
                self.logger.info("Optocoupler configured without pull-up resistor")
            
            # Add falling edge detection callback
            GPIO.add_event_detect(self.optocoupler_pin, GPIO.FALLING, callback=self._optocoupler_callback)
            self.logger.info("Optocoupler falling edge detection enabled")
            
            self.optocoupler_initialized = True
            
        except Exception as e:
            self.logger.error(f"Failed to setup optocoupler: {e}")
            self.optocoupler_initialized = False
    
    def _optocoupler_callback(self, channel):
        """Callback function for optocoupler falling edge detection."""
        with self.pulse_count_lock:
            self.pulse_count += 1
            self.logger.debug(f"Optocoupler pulse detected, count: {self.pulse_count}")
    
    def count_optocoupler_pulses(self, duration: float = None) -> int:
        """
        Count optocoupler pulses over specified duration.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            
        Returns:
            Number of pulses counted
        """
        if not self.optocoupler_initialized:
            self.logger.warning("Optocoupler not initialized, cannot count pulses")
            return 0
        
        if duration is None:
            duration = self.measurement_duration
        
        # Reset pulse counter
        with self.pulse_count_lock:
            self.pulse_count = 0
        
        # Wait for measurement duration
        time.sleep(duration)
        
        # Get final pulse count
        with self.pulse_count_lock:
            final_count = self.pulse_count
        
        self.logger.debug(f"Counted {final_count} pulses in {duration:.2f} seconds")
        return final_count
    
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
        
        self.logger.debug(f"Calculated frequency: {frequency:.2f} Hz from {pulse_count} pulses in {duration:.2f}s")
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
