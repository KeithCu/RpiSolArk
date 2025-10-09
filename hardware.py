#!/usr/bin/env python3
"""
Hardware management for the frequency monitor.
Handles GPIO, LCD display, and LED controls with graceful degradation.
"""

import logging
from typing import Optional

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available. Running in simulation mode.")

try:
    from rplcd.i2c import CharLCD
    LCD_AVAILABLE = True
except ImportError:
    LCD_AVAILABLE = False
    print("Warning: rplcd not available. LCD display disabled.")


class HardwareManager:
    """Manages hardware components with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.gpio_available = GPIO_AVAILABLE
        self.lcd_available = LCD_AVAILABLE
        self.lcd = None
        self._setup_hardware()
    
    def _setup_hardware(self):
        """Setup hardware components."""
        if self.gpio_available:
            try:
                GPIO.setmode(GPIO.BCM)
                self.gpio_pin = self.config.get('hardware.gpio_pin', 17)
                self.led_green = self.config.get('hardware.led_green', 18)
                self.led_red = self.config.get('hardware.led_red', 27)
                
                GPIO.setup(self.gpio_pin, GPIO.IN)
                GPIO.setup(self.led_green, GPIO.OUT, initial=GPIO.LOW)
                GPIO.setup(self.led_red, GPIO.OUT, initial=GPIO.LOW)

                # Setup reset button with pull-up resistor (active LOW)
                self.reset_button = self.config.get('hardware.reset_button', 22)
                GPIO.setup(self.reset_button, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                
                self.logger.info("GPIO hardware initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize GPIO: {e}")
                self.gpio_available = False
        
        if self.lcd_available:
            try:
                self.lcd = CharLCD(
                    i2c_expander='PCF8574',
                    address=self.config.get('hardware.lcd_address', 0x27),
                    port=self.config.get('hardware.lcd_port', 1),
                    cols=self.config.get('hardware.lcd_cols', 16),
                    rows=self.config.get('hardware.lcd_rows', 2)
                )
                self.logger.info("LCD hardware initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize LCD: {e}")
                self.lcd_available = False
                self.lcd = None
    
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
    
    def update_display(self, line1: str, line2: str):
        """Update LCD display."""
        # Always show simulation if configured to do so
        simulate_display = self.config.get('app.simulate_display', True)
        
        if not self.lcd_available or not self.lcd or simulate_display:
            self._simulate_display(line1, line2)
        
        # Also update real LCD if available and not forcing simulation
        if self.lcd_available and self.lcd and not simulate_display:
            try:
                self.lcd.clear()
                self.lcd.write_string(line1)
                self.lcd.cursor_pos = (1, 0)
                self.lcd.write_string(line2)
            except Exception as e:
                self.logger.error(f"Failed to update display: {e}")
    
    def _simulate_display(self, line1: str, line2: str):
        """Simulate LCD display output."""
        # Clear screen (simulate LCD clear)
        print("\033[2J\033[H", end="")  # Clear screen and move cursor to top-left
        
        # Display header
        print("=" * 22)
        print("  LCD DISPLAY SIMULATION")
        print("=" * 22)
        print()
        
        # Display the two lines as they would appear on LCD (16x2)
        print("+-----------------+")
        print(f"|{line1:<16}|")  # 16 characters wide (LCD width)
        print(f"|{line2:<16}|")
        print("+-----------------+")
        print()
        
        # Display additional info
        print("-" * 22)
        print("System Status:")
        print(f"  Mode: {'SIMULATOR' if not self.gpio_available else 'HARDWARE'}")
        print(f"  LCD: {'SIMULATED' if not self.lcd_available else 'AVAILABLE'}")
        print("=" * 22)
        print("Press Ctrl+C to stop")
        print()
    
    def cleanup(self):
        """Cleanup hardware resources."""
        if self.gpio_available:
            try:
                GPIO.cleanup()
                self.logger.info("GPIO cleanup completed")
            except Exception as e:
                self.logger.error(f"GPIO cleanup error: {e}")
        
        if self.lcd_available and self.lcd:
            try:
                self.lcd.clear()
                self.logger.info("LCD cleanup completed")
            except Exception as e:
                self.logger.error(f"LCD cleanup error: {e}")
