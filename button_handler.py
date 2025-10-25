#!/usr/bin/env python3
"""
Button handler for display control.
Handles tactile push button to turn display on for 5 minutes.
"""

import time
import threading
import logging
from datetime import datetime, timedelta

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available. Button functionality disabled.")

class ButtonHandler:
    """Handles tactile push button for display control."""
    
    def __init__(self, button_pin=18, display_manager=None, logger=None):
        self.button_pin = button_pin
        self.display_manager = display_manager
        self.logger = logger or logging.getLogger(__name__)
        self.gpio_available = GPIO_AVAILABLE
        self.running = False
        self.button_thread = None
        
        # Button state
        self.button_pressed = False
        self.last_press_time = 0
        self.debounce_time = 0.05  # 50ms debounce
        
        if self.gpio_available:
            self._setup_gpio()
        else:
            self.logger.warning("GPIO not available - button functionality disabled")
    
    def _setup_gpio(self):
        """Setup GPIO for button."""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            
            # Note: Edge detection often fails, so we'll use manual polling instead
            self.logger.info(f"Button setup on GPIO {self.button_pin} (polling mode)")
        except Exception as e:
            self.logger.error(f"Failed to setup button GPIO: {e}")
            self.gpio_available = False
    
    def _button_callback(self, channel):
        """Callback for button press."""
        current_time = time.time()
        
        # Debounce check
        if current_time - self.last_press_time < self.debounce_time:
            return
            
        self.last_press_time = current_time
        self.button_pressed = True
        self.logger.info("Button pressed!")
        
        # Handle button press
        self._handle_button_press()
    
    def _handle_button_press(self):
        """Handle button press - turn display on for configured timeout duration."""
        if self.display_manager:
            # Get the configured timeout from the display manager
            timeout_seconds = self.display_manager.display_timeout_seconds
            timeout_minutes = timeout_seconds / 60  # Convert to minutes for the method
            
            self.logger.info(f"Button pressed - turning display on for {timeout_minutes:.1f} minutes")
            self.display_manager.reset_display_timeout()  # Reset activity timer and turn on display
            self.logger.info(f"Display timeout reset to {timeout_minutes:.1f} minutes")
        else:
            self.logger.warning("No display manager connected")
    
    def start_monitoring(self):
        """Start button monitoring thread."""
        if not self.gpio_available:
            self.logger.warning("Cannot start button monitoring - GPIO not available")
            return
            
        if self.running:
            self.logger.warning("Button monitoring already running")
            return
            
        self.running = True
        self.button_thread = threading.Thread(target=self._monitor_button, daemon=True)
        self.button_thread.start()
        self.logger.info("Button monitoring started")
    
    def _monitor_button(self):
        """Monitor button in separate thread using manual polling."""
        last_state = GPIO.input(self.button_pin)
        
        while self.running:
            try:
                # Read current button state
                current_state = GPIO.input(self.button_pin)
                
                # Detect button press (falling edge: 1 -> 0)
                if last_state == 1 and current_state == 0:
                    self._handle_button_press()
                
                last_state = current_state
                time.sleep(0.01)  # 10ms polling (very responsive)
                
            except Exception as e:
                self.logger.error(f"Button monitoring error: {e}")
                time.sleep(1)
    
    def stop_monitoring(self):
        """Stop button monitoring."""
        self.running = False
        if self.button_thread:
            self.button_thread.join(timeout=1)
        self.logger.info("Button monitoring stopped")
    
    def cleanup(self):
        """Cleanup GPIO resources."""
        if self.gpio_available:
            try:
                GPIO.cleanup()
                self.logger.info("Button GPIO cleanup completed")
            except Exception as e:
                self.logger.error(f"Button cleanup error: {e}")

def test_button():
    """Test button functionality."""
    print("Button Test")
    print("===========")
    print("Wiring:")
    print("  GPIO 18 ──── Button ──── GND")
    print("  (or use 3.3V ──── 10kΩ ──── GPIO 18 ──── Button ──── GND)")
    print()
    print("Press the button to test...")
    print("Press Ctrl+C to exit")
    
    button = ButtonHandler(button_pin=18)
    
    if not button.gpio_available:
        print("GPIO not available - cannot test button")
        return
    
    try:
        button.start_monitoring()
        
        while True:
            if button.button_pressed:
                print("✓ Button press detected!")
                button.button_pressed = False
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nStopping button test...")
    finally:
        button.stop_monitoring()
        button.cleanup()

if __name__ == '__main__':
    test_button()
