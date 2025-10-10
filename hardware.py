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
    from LCD1602 import CharLCD1602
    LCD_AVAILABLE = True
except ImportError:
    LCD_AVAILABLE = False
    print("Warning: LCD1602 not available. LCD display disabled.")


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
        self.logger.info("Starting hardware setup...")
        self.logger.info(f"GPIO available: {self.gpio_available}")
        self.logger.info(f"LCD available: {self.lcd_available}")
        
        if self.gpio_available:
            try:
                self.logger.info("Initializing GPIO...")
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
                
                self.logger.info("GPIO hardware initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize GPIO: {e}")
                self.gpio_available = False
        else:
            self.logger.info("GPIO not available, skipping GPIO setup")
        
        if self.lcd_available:
            try:
                self.logger.info("Creating LCD1602 object...")
                self.lcd = CharLCD1602()
                self.logger.info("LCD1602 object created successfully")
                
                # Initialize the LCD
                self.logger.info("Attempting to initialize LCD...")
                init_result = self.lcd.init_lcd()
                self.logger.info(f"LCD init_lcd() returned: {init_result}")
                
                if init_result:
                    self.logger.info("LCD hardware initialized successfully")
                else:
                    self.logger.error("LCD init_lcd() returned False - initialization failed")
                    self.lcd_available = False
                    self.lcd = None
            except Exception as e:
                self.logger.error(f"Failed to initialize LCD: {e}")
                import traceback
                self.logger.error(f"LCD initialization traceback: {traceback.format_exc()}")
                self.lcd_available = False
                self.lcd = None
        else:
            self.logger.info("LCD not available, skipping LCD setup")
        
        self.logger.info(f"Hardware setup complete - GPIO: {self.gpio_available}, LCD: {self.lcd_available}")
    
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
        
        self.logger.debug(f"update_display called: simulate_display={simulate_display}, lcd_available={self.lcd_available}, lcd={self.lcd is not None}")
        
        if not self.lcd_available or not self.lcd or simulate_display:
            self.logger.debug("Using simulated display")
            self._simulate_display(line1, line2)
        
        # Also update real LCD if available and not forcing simulation
        if self.lcd_available and self.lcd and not simulate_display:
            self.logger.debug("Updating real LCD display")
            try:
                self.lcd.clear()
                self.lcd.write(0, 0, line1)  # Write to line 1, column 0
                self.lcd.write(0, 1, line2)  # Write to line 2, column 0
                self.logger.debug(f"LCD updated successfully: '{line1}' | '{line2}'")
            except Exception as e:
                self.logger.error(f"Failed to update display: {e}")
                import traceback
                self.logger.error(f"Display update traceback: {traceback.format_exc()}")
    
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
