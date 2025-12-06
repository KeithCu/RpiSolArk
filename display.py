#!/usr/bin/env python3
"""
Display management for the frequency monitor.
Handles LCD display, LED controls, and simulation with graceful degradation.
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Deque
from collections import deque

# Hardware imports - using CharLCD1602 (working version)
from LCD1602 import CharLCD1602
LCD_AVAILABLE = True


def format_duration(seconds: float) -> str:
    """Format seconds into a readable days:hours:minutes:seconds format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string like "1d:2h:3m" (no seconds if days) or "2h:30m:15s" or "45s"
    """
    if seconds < 0:
        return "0s"
    
    # Convert to integer seconds for cleaner display
    total_seconds = int(seconds)
    
    # Calculate each time unit
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    # Build the formatted string, only showing non-zero components
    parts = []
    
    if days > 0:
        parts.append(f"{days}d")
        # When we have days, show hours and minutes but skip seconds to save space
        if hours > 0 or days > 0:  # Show hours if we have days or hours
            parts.append(f"{hours:02d}h")
        if minutes > 0 or hours > 0 or days > 0:  # Show minutes if we have any larger unit
            parts.append(f"{minutes:02d}m")
        # Skip seconds when we have days to save display space
    else:
        # No days - show hours, minutes, and seconds
        if hours > 0:
            parts.append(f"{hours:02d}h")
        if minutes > 0 or hours > 0:  # Show minutes if we have hours or minutes
            parts.append(f"{minutes:02d}m")
        if secs > 0 or not parts:  # Always show seconds if no other units, or if we have seconds
            # Use zero-padding only if we have other time units (for alignment)
            # Otherwise use single-digit format for cleaner display
            if parts:
                parts.append(f"{secs:02d}s")
            else:
                parts.append(f"{secs}s")
    
    return ":".join(parts)


class DisplayManager:
    """Manages LCD display, LED controls, and display logic with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger, hardware_manager=None):
        self.config = config
        self.logger = logger
        self.hardware_manager = hardware_manager
        
        # Flag to track if we should use simulated display (set automatically if hardware fails)
        self._use_simulated_display = False
        
        # Smart display management
        try:
            self.display_timeout_seconds = self.config['hardware']['display_timeout_seconds']
        except KeyError:
            self.display_timeout_seconds = 5  # Default fallback
        self.last_activity = datetime.now()
        self.display_on = True
        self.power_event_detected = False
        self.display_timeout_enabled = True
        
        # Emergency states that should keep display on
        self.emergency_states = ['off_grid', 'generator']
        
        # Button handler for manual display control
        self.button_handler = None
        self._setup_button()
        
        # Try to initialize hardware (will fall back to simulated if it fails)
        self._setup_display()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.cleanup()
        return False  # Don't suppress exceptions
    
    def _setup_display(self):
        """Setup LCD display - try hardware first, fall back to simulated if it fails."""
        # Try to initialize real hardware using CharLCD1602
        self.lcd_available = LCD_AVAILABLE
        self.lcd = None
        
        try:
            self.logger.info("Attempting to initialize CharLCD1602...")
            
            # Get LCD configuration from config.yaml
            try:
                lcd_address = self.config['hardware']['lcd_address']
            except KeyError as e:
                raise KeyError(f"Missing required hardware configuration key: {e}")
            
            self.logger.info(f"LCD config: address=0x{lcd_address:02x}")
            
            # Initialize with CharLCD1602 (working version)
            self.lcd = CharLCD1602()
            init_result = self.lcd.init_lcd(addr=lcd_address, bl=0)
            
            if not init_result:
                raise RuntimeError("LCD init_lcd() returned False - initialization failed")
            
            # Ensure backlight is on at startup
            self.lcd.set_backlight(True)
            self.logger.info("CharLCD1602 initialized successfully - using real hardware")
            self._use_simulated_display = False
                
        except Exception as e:
            self.logger.warning(f"Failed to initialize LCD hardware: {e}")
            self.logger.info("Automatically falling back to simulated LCD display")
            import traceback
            self.logger.debug(f"LCD initialization traceback: {traceback.format_exc()}")
            self.lcd_available = False
            self.lcd = None
            self._use_simulated_display = True
    
    def _setup_button(self):
        """Setup button handler for display control."""
        try:
            from button_handler import ButtonHandler
            # Read button pin from config
            try:
                button_pin = self.config['hardware']['button_pin']
            except KeyError:
                button_pin = 18  # Default fallback
                
            self.button_handler = ButtonHandler(
                button_pin=button_pin,
                display_manager=self,
                logger=self.logger
            )
            self.button_handler.start_monitoring()
            self.logger.info(f"Button handler initialized on GPIO {button_pin}")
        except Exception as e:
            self.logger.warning(f"Could not setup button handler: {e}")
            self.button_handler = None
    
    def update_display(self, line1: str, line2: str):
        """Update LCD display with smart timeout management."""
        # Use simulated display if hardware failed
        if self._use_simulated_display:
            self._simulate_display(line1, line2)
            return
        
        # Check if display should be turned on due to timeout
        self._check_display_timeout()
        
        # Try to use real LCD if available and display is on
        if not self.display_on:
            self.logger.debug("Display is off due to timeout")
            return
        
        if self.lcd_available and self.lcd:
            try:
                self.lcd.clear()
                self.lcd.write(0, 0, line1)
                self.lcd.write(0, 1, line2)
                self.logger.debug(f"LCD updated: '{line1}' | '{line2}'")
            except Exception as e:
                self.logger.error(f"Failed to update LCD: {e}")
                # Automatically fallback to simulated display on error
                self._use_simulated_display = True
                self._simulate_display(line1, line2)
        else:
            # No LCD available, automatically use simulated display
            self._use_simulated_display = True
            self._simulate_display(line1, line2)
    
    def _simulate_display(self, line1: str, line2: str):
        """Simulate LCD display output."""
        # Don't clear screen so we can see any errors
        print("\n" + "="*50)  # Just add a separator
        
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
        print(f"  Mode: {'SIMULATOR' if not self.lcd_available else 'HARDWARE'}")
        print(f"  LCD: {'SIMULATED' if not self.lcd_available else 'AVAILABLE'}")
        print("=" * 22)
        print("Press Ctrl+C to stop")
        print()
    
    def update_display_and_leds(self, freq: Optional[float], ug_indicator: str, 
                               state_machine, zero_voltage_duration: float = 0.0):
        """Update LCD display and LED indicators."""
        
        # Get state machine status
        state_info = state_machine.get_state_info()
        current_state = state_info['current_state']
        
        # Use state machine state for display (debounced and stable) instead of raw analysis result
        # Map state machine states to display indicators
        state_to_indicator = {
            'grid': 'Util',
            'generator': 'Gen',
            'off_grid': '?',
            'transitioning': '?'
        }
        
        # If there's no voltage, always show "?" regardless of state machine state
        # (state machine might not have transitioned yet)
        if freq is None:
            display_indicator = '?'
        else:
            display_indicator = state_to_indicator.get(current_state, '?')

        # Show time and frequency with power source indicator, updated once per second
        current_time = time.strftime("%H:%M:%S")
        
        line1 = f"{current_time}"
        if freq is not None:
            line2 = f"{freq:.2f} Hz {display_indicator}"
        else:
            formatted_duration = format_duration(zero_voltage_duration)
            line2 = f"0V {formatted_duration} {display_indicator}"
        
        # Update display
        self.update_display(line1, line2)

        # Update LEDs based on state machine state
        self.update_leds_for_state(current_state)
        
        # Check for power events that should keep display on
        self._check_power_events()
        
        # Check if we're in an emergency state that should keep display on
        self._check_emergency_state(current_state)
    
    def get_state_display_code(self, state: str) -> str:
        """Get display code for power state."""
        state_codes = {
            'off_grid': 'OFF-GRID',
            'grid': 'UTILITY',
            'generator': 'GENERATOR',
            'transitioning': 'DETECTING'
        }
        return state_codes.get(state, 'UNKNOWN')

    def update_leds_for_state(self, state: str):
        """Update LED indicators based on power state."""
        if self.hardware_manager is None:
            return  # No hardware available in simulator mode
            
        # Turn off all LEDs first
        self.hardware_manager.set_led('green', False)
        self.hardware_manager.set_led('red', False)

        # Set LEDs based on state
        if state == 'grid':
            self.hardware_manager.set_led('green', True)  # Green for grid power
        elif state == 'generator':
            self.hardware_manager.set_led('red', True)    # Red for generator power
        elif state == 'off_grid':
            # Both LEDs off for off-grid (power outage)
            pass
        elif state == 'transitioning':
            # Both LEDs on for transitioning (flashing/unclear state)
            self.hardware_manager.set_led('green', True)
            self.hardware_manager.set_led('red', True)
    
    
    def _check_display_timeout(self):
        """Check if display should be turned off due to timeout."""
        if not self.display_timeout_enabled or not self.lcd_available or not self.lcd:
            return
            
        if not self.display_on:
            return
            
        time_since_activity = datetime.now() - self.last_activity
        timeout_duration = timedelta(seconds=self.display_timeout_seconds)
        
        if time_since_activity > timeout_duration and not self.power_event_detected:
            self.logger.info("Display timeout reached - turning off display")
            self._turn_display_off()
            
    def _turn_display_off(self):
        """Turn the display off to save power."""
        if self.display_on:
            self.logger.info("Turning display off due to timeout")
            self.display_on = False
            try:
                if self.lcd_available and self.lcd:
                    # Clear the display and turn off backlight
                    self.lcd.clear()
                    self.lcd.set_backlight(False)
                    self.logger.debug("Display turned off - backlight disabled")
            except Exception as e:
                self.logger.debug(f"Error turning off display: {e}")
                
    def _turn_display_on(self):
        """Turn the display back on."""
        if not self.display_on:
            self.logger.info("Turning display back on")
            self.display_on = True
            try:
                if self.lcd_available and self.lcd:
                    # Turn on backlight and clear display
                    self.lcd.set_backlight(True)
                    self.lcd.clear()
                    self.logger.debug("Display turned on - backlight enabled")
            except Exception as e:
                self.logger.error(f"Error turning on display: {e}")
                
    def _check_power_events(self):
        """Check for power events that should keep display on."""
        # This is a placeholder - customize based on your system
        # Examples: grid loss/restore, generator on/off, etc.
        
        # For now, we'll detect power events based on frequency changes
        # You can implement actual power event detection here
        # For example:
        # - Check GPIO pins for power status
        # - Monitor network connectivity
        # - Check generator status
        # - Monitor voltage levels
        
        # Placeholder: always return False (no power events detected)
        # You should implement actual power event detection logic here
        return False
        
    def _check_emergency_state(self, current_state):
        """Check if we're in an emergency state that should keep display on."""
        if current_state in self.emergency_states:
            # We're in an emergency state - keep display on
            if not self.display_on:
                self.logger.info(f"Emergency state '{current_state}' detected - turning display on")
                self._turn_display_on()
            # Reset activity timer to keep display on
            self.last_activity = datetime.now()
            self.power_event_detected = True
        else:
            # Not in emergency state - allow normal timeout
            self.power_event_detected = False
        
    def force_display_on(self):
        """Force display to turn on (useful for power events)."""
        self.power_event_detected = True
        self.last_activity = datetime.now()
        if not self.display_on:
            self._turn_display_on()
            
    def reset_display_timeout(self):
        """Reset the display timeout timer."""
        self.last_activity = datetime.now()
        if not self.display_on:
            self._turn_display_on()
            
    def set_display_timeout(self, minutes: int):
        """Set the display timeout in minutes."""
        self.display_timeout_seconds = minutes * 60
        self.logger.info(f"Display timeout set to {minutes} minutes")
        
    def enable_display_timeout(self, enabled: bool):
        """Enable or disable display timeout."""
        self.display_timeout_enabled = enabled
        self.logger.info(f"Display timeout {'enabled' if enabled else 'disabled'}")
        
    def cleanup(self):
        """Cleanup display resources."""
        # Cleanup button handler
        if self.button_handler:
            try:
                self.button_handler.stop_monitoring()
                self.button_handler.cleanup()
                self.logger.info("Button handler cleanup completed")
            except Exception as e:
                self.logger.error(f"Button cleanup error: {e}")
        
        # Cleanup LCD
        if self.lcd_available and self.lcd:
            try:
                self.lcd.clear()
                self.logger.info("LCD cleanup completed")
            except Exception as e:
                self.logger.error(f"LCD cleanup error: {e}")
