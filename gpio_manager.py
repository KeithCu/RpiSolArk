#!/usr/bin/env python3
"""
GPIO management for the frequency monitor.
Handles basic GPIO operations, LED controls, and reset button with graceful degradation.
"""

import logging

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    GPIO_AVAILABLE = False
    print(f"Warning: RPi.GPIO not available ({e}). Running in simulation mode.")


class GPIOManager:
    """Manages GPIO operations with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.gpio_available = GPIO_AVAILABLE
        
        # GPIO pin configuration
        self.gpio_pin = self.config.get('hardware.gpio_pin', 17)
        self.led_green = self.config.get('hardware.led_green', 18)
        self.led_red = self.config.get('hardware.led_red', 27)
        self.reset_button = self.config.get('hardware.reset_button', 22)
        
        self._setup_gpio()
    
    def _setup_gpio(self):
        """Setup GPIO pins."""
        self.logger.info(f"GPIO available: {self.gpio_available}")
        
        if self.gpio_available:
            try:
                self.logger.info("Initializing GPIO...")
                GPIO.setmode(GPIO.BCM)
                
                GPIO.setup(self.gpio_pin, GPIO.IN)
                GPIO.setup(self.led_green, GPIO.OUT, initial=GPIO.LOW)
                GPIO.setup(self.led_red, GPIO.OUT, initial=GPIO.LOW)

                # Setup reset button with pull-up resistor (active LOW)
                GPIO.setup(self.reset_button, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                
                self.logger.info("GPIO hardware initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize GPIO: {e}")
                self.gpio_available = False
        else:
            self.logger.info("GPIO not available, skipping GPIO setup")
    
    def read_gpio(self) -> int:
        """Read GPIO pin state."""
        if self.gpio_available:
            return GPIO.input(self.gpio_pin)
        return 0

    def check_reset_button(self) -> bool:
        """Check if reset button is pressed (active LOW)."""
        if self.gpio_available:
            # Button is active LOW (pressed = 0, released = 1 due to pull-up)
            return GPIO.input(self.reset_button) == 0
        return False

    def set_led(self, led: str, state: bool):
        """Set LED state."""
        if not self.gpio_available:
            return
        
        pin = self.led_green if led == 'green' else self.led_red
        GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
    
    def cleanup(self):
        """Cleanup GPIO resources."""
        if self.gpio_available:
            try:
                GPIO.cleanup()
                self.logger.info("GPIO cleanup completed")
            except Exception as e:
                self.logger.error(f"GPIO cleanup error: {e}")
