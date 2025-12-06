#!/usr/bin/env python3
"""
Hardware management for the frequency monitor.
Coordinates all hardware components with graceful degradation.
"""

import logging
from typing import Optional, Tuple

# Import hardware component managers
from display import DisplayManager
from gpio_manager import GPIOManager
from optocoupler import OptocouplerManager


class HardwareManager:
    """Manages hardware components with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Initialize component managers
        self.gpio = GPIOManager(config, logger)
        self.optocoupler = OptocouplerManager(config, logger)
        self.display = DisplayManager(config, logger, self)
        
        # Expose availability flags for backward compatibility
        self.gpio_available = self.gpio.gpio_available
        self.lcd_available = self.display.lcd_available
        self.optocoupler_initialized = self.optocoupler.optocoupler_initialized
    
    def _setup_hardware(self):
        """Setup hardware components."""
        self.logger.info("Starting hardware setup...")
        self.logger.info(f"GPIO available: {self.gpio_available}")
        self.logger.info(f"LCD available: {self.lcd_available}")
        self.logger.info(f"Hardware setup complete - GPIO: {self.gpio_available}, LCD: {self.lcd_available}")
    
    # Delegate methods to component managers for backward compatibility
    
    def start_measurement(self, duration: float = None, optocoupler_name: str = 'primary') -> bool:
        """Start a non-blocking measurement window.
        
        Returns:
            True if measurement started successfully, False otherwise
        """
        return self.optocoupler.start_measurement(duration, optocoupler_name)
    
    def check_measurement(self, optocoupler_name: str = 'primary') -> Tuple[bool, Optional[int], Optional[float]]:
        """Check if the current measurement window has elapsed.
        
        Returns:
            Tuple of (is_complete, pulse_count, actual_elapsed_time)
        """
        return self.optocoupler.check_measurement(optocoupler_name)
    
    def count_optocoupler_pulses(self, duration: float = None, debounce_time: float = 0.0, 
                                 optocoupler_name: str = 'primary') -> Tuple[int, float]:
        """Count optocoupler pulses over specified duration.
        BLOCKING VERSION - Use start_measurement()/check_measurement() for non-blocking operation.
        
        Returns:
            Tuple of (pulse_count, actual_elapsed_time)
        """
        return self.optocoupler.count_optocoupler_pulses(duration, debounce_time, optocoupler_name)
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None, 
                                       optocoupler_name: str = 'primary', actual_duration: float = None) -> Optional[float]:
        """Calculate AC frequency from pulse count."""
        return self.optocoupler.calculate_frequency_from_pulses(pulse_count, duration, optocoupler_name, actual_duration)
    
    def get_available_optocouplers(self) -> list:
        """Get list of available optocoupler names."""
        return self.optocoupler.get_available_optocouplers()
    
    def read_gpio(self) -> int:
        """Read GPIO pin state."""
        return self.gpio.read_gpio()

    def check_reset_button(self) -> bool:
        """Check if reset button is pressed (active LOW)."""
        return self.gpio.check_reset_button()

    def set_led(self, led: str, state: bool):
        """Set LED state."""
        self.gpio.set_led(led, state)
    
    def update_display(self, line1: str, line2: str):
        """Update LCD display."""
        self.display.update_display(line1, line2)
    
    def cleanup(self):
        """Cleanup hardware resources."""
        self.display.cleanup()
        self.gpio.cleanup()
        self.optocoupler.cleanup()
