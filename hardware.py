#!/usr/bin/env python3
"""
Hardware management for the frequency monitor.
Handles GPIO, LCD display, and LED controls with graceful degradation.
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
                
                # Setup optocoupler if enabled
                if self.optocoupler_enabled:
                    self._setup_optocoupler()
                
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
                # Remove optocoupler event detection if it was set up
                if self.optocoupler_initialized:
                    GPIO.remove_event_detect(self.optocoupler_pin)
                    self.logger.info("Optocoupler event detection removed")
                
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
