#!/usr/bin/env python3
"""
GIL-safe pulse counter using C extension.
Avoids Python GIL issues in GPIO interrupt callbacks.
"""

import os
import sys
import logging
from typing import Optional, Dict

# Import the C extension - fail if not available
try:
    import pulse_counter
except ImportError:
    raise ImportError("pulse_counter C extension is required but not available. Please compile the C extension first.")

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

class GILSafeCounter:
    """GIL-safe pulse counter using C extension for maximum performance."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.gpio_available = GPIO_AVAILABLE
        self.registered_pins = {}  # pin -> slot mapping
        
        self.logger.info("C counter extension loaded - GIL-safe operation enabled")
    
    def register_pin(self, pin: int) -> bool:
        """Register a GPIO pin for GIL-safe counting."""
        if not self.gpio_available:
            self.logger.warning(f"GPIO not available, cannot register pin {pin}")
            return False
        
        try:
            slot = pulse_counter.register_pin(pin)
            if slot == -1:
                self.logger.error(f"Failed to register pin {pin} - no available slots")
                return False
            
            self.registered_pins[pin] = slot
            self.logger.info(f"Registered pin {pin} for GIL-safe counting (slot {slot})")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to register pin {pin}: {e}")
            return False
    
    def get_count(self, pin: int) -> int:
        """Get current pulse count for a pin."""
        if pin not in self.registered_pins:
            self.logger.warning(f"Pin {pin} not registered")
            return 0
        
        try:
            count = pulse_counter.get_count(pin)
            return count
        except Exception as e:
            self.logger.error(f"Failed to get count for pin {pin}: {e}")
            return 0
    
    def reset_count(self, pin: int) -> bool:
        """Reset pulse count for a pin."""
        if pin not in self.registered_pins:
            self.logger.warning(f"Pin {pin} not registered")
            return False
        
        try:
            pulse_counter.reset_count(pin)
            self.logger.debug(f"Reset count for pin {pin}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to reset count for pin {pin}: {e}")
            return False
    
    def setup_gpio_interrupt(self, pin: int) -> bool:
        """Setup GPIO interrupt for a pin using direct C GPIO handling (truly GIL-free)."""
        if not self.gpio_available:
            self.logger.warning(f"GPIO not available, cannot setup interrupt for pin {pin}")
            return False
        
        try:
            # Register pin with C counter (this now sets up GPIO directly in C)
            if not self.register_pin(pin):
                return False
            
            self.logger.info(f"GPIO interrupt setup for pin {pin} with direct C handling (GIL-free)")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup GPIO interrupt for pin {pin}: {e}")
            return False
    
    def check_interrupts(self):
        """Check for GPIO interrupts and update counters (GIL-free)."""
        try:
            pulse_counter.check_interrupts()
        except Exception as e:
            self.logger.error(f"Failed to check interrupts: {e}")
    
    def cleanup(self):
        """Cleanup counter resources."""
        try:
            # Cleanup C extension resources
            pulse_counter.cleanup()
            self.registered_pins.clear()
            self.logger.debug("Cleaned up C extension resources")
        except Exception as e:
            self.logger.error(f"Error cleaning up C extension: {e}")


def create_counter(logger: logging.Logger):
    """Create the GIL-safe counter implementation (C extension required)."""
    logger.info("Using GIL-safe C counter implementation")
    return GILSafeCounter(logger)
