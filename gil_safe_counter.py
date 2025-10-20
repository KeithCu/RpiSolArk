#!/usr/bin/env python3
"""
GIL-safe pulse counter using C extension.
Avoids Python GIL issues in GPIO interrupt callbacks.
"""

import os
import sys
import logging
from typing import Optional, Dict

# Try to import the C extension
try:
    import pulse_counter
    C_COUNTER_AVAILABLE = True
except ImportError:
    C_COUNTER_AVAILABLE = False

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
        self.c_counter_available = C_COUNTER_AVAILABLE
        self.registered_pins = {}  # pin -> slot mapping
        
        if not self.c_counter_available:
            self.logger.warning("C counter extension not available, falling back to Python implementation")
        else:
            self.logger.info("C counter extension loaded - GIL-safe operation enabled")
    
    def register_pin(self, pin: int) -> bool:
        """Register a GPIO pin for GIL-safe counting."""
        if not self.gpio_available:
            self.logger.warning(f"GPIO not available, cannot register pin {pin}")
            return False
        
        if not self.c_counter_available:
            self.logger.warning(f"C counter not available, cannot register pin {pin}")
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
        """Setup GPIO interrupt for a pin using GIL-safe callback."""
        if not self.gpio_available:
            self.logger.warning(f"GPIO not available, cannot setup interrupt for pin {pin}")
            return False
        
        if not self.c_counter_available:
            self.logger.warning(f"C counter not available, cannot setup interrupt for pin {pin}")
            return False
        
        try:
            # Register pin with C counter
            if not self.register_pin(pin):
                return False
            
            # Setup GPIO interrupt with minimal Python callback
            GPIO.add_event_detect(pin, GPIO.FALLING, callback=self._gil_safe_callback)
            self.logger.info(f"GPIO interrupt setup for pin {pin} with GIL-safe callback")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup GPIO interrupt for pin {pin}: {e}")
            return False
    
    def _gil_safe_callback(self, channel):
        """Minimal callback that just increments C counter (GIL-safe)."""
        try:
            # This is the only Python code in the callback - minimal GIL impact
            pulse_counter.increment_count(channel)
        except Exception:
            # Don't log in interrupt context - just silently fail
            pass
    
    def cleanup(self):
        """Cleanup counter resources."""
        for pin in list(self.registered_pins.keys()):
            try:
                if self.gpio_available:
                    GPIO.remove_event_detect(pin)
                self.logger.debug(f"Cleaned up counter for pin {pin}")
            except Exception as e:
                self.logger.error(f"Error cleaning up pin {pin}: {e}")


class PythonFallbackCounter:
    """Fallback Python implementation when C extension is not available."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.gpio_available = GPIO_AVAILABLE
        self.counters = {}  # pin -> count mapping
        self.locks = {}     # pin -> lock mapping
    
    def register_pin(self, pin: int) -> bool:
        """Register a pin for counting (Python fallback)."""
        if not self.gpio_available:
            return False
        
        try:
            import threading
            self.counters[pin] = 0
            self.locks[pin] = threading.Lock()
            self.logger.info(f"Registered pin {pin} for Python fallback counting")
            return True
        except Exception as e:
            self.logger.error(f"Failed to register pin {pin}: {e}")
            return False
    
    def get_count(self, pin: int) -> int:
        """Get current count for a pin."""
        if pin not in self.counters:
            return 0
        
        with self.locks[pin]:
            return self.counters[pin]
    
    def reset_count(self, pin: int) -> bool:
        """Reset count for a pin."""
        if pin not in self.counters:
            return False
        
        with self.locks[pin]:
            self.counters[pin] = 0
        return True
    
    def setup_gpio_interrupt(self, pin: int) -> bool:
        """Setup GPIO interrupt with Python callback."""
        if not self.gpio_available:
            return False
        
        try:
            if not self.register_pin(pin):
                return False
            
            GPIO.add_event_detect(pin, GPIO.FALLING, callback=self._python_callback)
            self.logger.info(f"GPIO interrupt setup for pin {pin} with Python callback")
            return True
        except Exception as e:
            self.logger.error(f"Failed to setup GPIO interrupt for pin {pin}: {e}")
            return False
    
    def _python_callback(self, channel):
        """Python callback (has GIL issues but works as fallback)."""
        if channel in self.counters:
            with self.locks[channel]:
                self.counters[channel] += 1
    
    def cleanup(self):
        """Cleanup fallback counter."""
        for pin in list(self.counters.keys()):
            try:
                if self.gpio_available:
                    GPIO.remove_event_detect(pin)
            except Exception as e:
                self.logger.error(f"Error cleaning up pin {pin}: {e}")


def create_counter(logger: logging.Logger):
    """Create the best available counter implementation."""
    if C_COUNTER_AVAILABLE:
        logger.info("Using GIL-safe C counter implementation")
        return GILSafeCounter(logger)
    else:
        logger.warning("Using Python fallback counter (may have GIL issues)")
        return PythonFallbackCounter(logger)
