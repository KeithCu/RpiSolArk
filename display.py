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

# Global flag to switch between LCD implementations
USE_RPLCD = False  # Set to True to use RPLCD, False to use original LCD1602.py

# Hardware imports
if USE_RPLCD:
    from lcd_rplcd import LCD1602_RPLCD
    LCD_AVAILABLE = True
else:
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
            parts.append(f"{secs:02d}s")
    
    return ":".join(parts)


class DisplayManager:
    """Manages LCD display, LED controls, and display logic with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger, hardware_manager=None):
        self.config = config
        self.logger = logger
        self.hardware_manager = hardware_manager
        self.lcd_available = LCD_AVAILABLE
        self.lcd = None
        
        # Cycling display state for dual optocoupler mode
        self.dual_mode = False
        self.current_display_optocoupler = 'primary'  # 'primary' or 'secondary'
        self.last_cycle_time = 0
        self.cycle_interval = 2.0  # Switch every 2 seconds
        
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
        
        self._setup_display()
    
    def _setup_display(self):
        """Setup LCD display."""
        self.logger.info(f"LCD available: {self.lcd_available}")
        
        if self.lcd_available:
            try:
                if USE_RPLCD:
                    self.logger.info("Creating LCD1602_RPLCD object...")
                    
                    # Get LCD configuration from config.yaml
                    try:
                        lcd_address = self.config['hardware']['lcd_address']
                        lcd_port = self.config['hardware']['lcd_port']
                        lcd_cols = self.config['hardware']['lcd_cols']
                        lcd_rows = self.config['hardware']['lcd_rows']
                    except KeyError as e:
                        raise KeyError(f"Missing required hardware configuration key: {e}")
                    
                    self.logger.info(f"LCD config: address=0x{lcd_address:02x}, port={lcd_port}, cols={lcd_cols}, rows={lcd_rows}")
                    
                    # Initialize with configured settings
                    self.lcd = LCD1602_RPLCD(
                        address=lcd_address,
                        port=lcd_port,
                        cols=lcd_cols,
                        rows=lcd_rows,
                        backlight_enabled=True
                    )
                    self.logger.info("LCD1602_RPLCD object created successfully")
                else:
                    self.logger.info("Creating original LCD1602 object...")
                    
                    # Get LCD configuration from config.yaml
                    try:
                        lcd_address = self.config['hardware']['lcd_address']
                    except KeyError as e:
                        raise KeyError(f"Missing required hardware configuration key: {e}")
                    
                    self.logger.info(f"LCD config: address=0x{lcd_address:02x}")
                    
                    # Initialize with the old working method
                    self.lcd = CharLCD1602()
                    init_result = self.lcd.init_lcd(addr=lcd_address, bl=0)
                    
                    if init_result:
                        self.logger.info("Original LCD1602 initialized successfully")
                    else:
                        self.logger.error("LCD init_lcd() returned False - initialization failed")
                        self.lcd_available = False
                        self.lcd = None
                        return
                
                self.logger.info("LCD hardware initialized successfully")
                # Ensure backlight is on at startup
                if self.lcd:
                    self.lcd.set_backlight(True)
                    self.logger.info("Display backlight turned on at startup")
            except Exception as e:
                self.logger.error(f"Failed to initialize LCD: {e}")
                import traceback
                self.logger.error(f"LCD initialization traceback: {traceback.format_exc()}")
                self.lcd_available = False
                self.lcd = None
        else:
            self.logger.info("LCD not available, skipping LCD setup")
    
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
        # Check if display should be turned on due to timeout
        self._check_display_timeout()
        
        # Try to use real LCD if available and display is on
        if self.lcd_available and self.lcd and self.display_on:
            self.logger.debug("Updating real LCD display")
            try:
                self.lcd.clear()
                self.lcd.write(0, 0, line1)  # Write to line 1, column 0
                self.lcd.write(0, 1, line2)  # Write to line 2, column 0
                self.logger.debug(f"LCD updated successfully: '{line1}' | '{line2}'")
            except Exception as e:
                self.logger.error(f"Failed to update LCD display: {e}")
                import traceback
                self.logger.error(f"Display update traceback: {traceback.format_exc()}")
                # Fallback to console display
                self.logger.info("Falling back to console display")
                self._simulate_display(line1, line2)
        elif not self.display_on:
            # Display is off due to timeout
            self.logger.debug("Display is off due to timeout")
        else:
            # No LCD available, use console display
            self.logger.debug("No LCD available, using console display")
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
                               state_machine, zero_voltage_duration: float = 0.0,
                               secondary_freq: Optional[float] = None):
        """Update LCD display and LED indicators."""
        
        # Get state machine status
        state_info = state_machine.get_state_info()
        current_state = state_info['current_state']

        # Show time and frequency with power source indicator, updated once per second
        current_time = time.strftime("%H:%M:%S")
        
        # Check if we have dual optocoupler readings
        if secondary_freq is not None:
            # Dual optocoupler mode - cycle between the two
            self.dual_mode = True
            self._cycle_dual_display(freq, secondary_freq, ug_indicator, state_machine, None, zero_voltage_duration, current_time)
        else:
            # Single optocoupler mode - original display
            self.dual_mode = False
            line1 = f"{current_time}"
            if freq is not None:
                line2 = f"{freq:.2f} Hz {ug_indicator}"
            else:
                formatted_duration = format_duration(zero_voltage_duration)
                line2 = f"0V {formatted_duration} {ug_indicator}"
            
            # Update display
            self.update_display(line1, line2)

        # Update LEDs based on state machine state
        self.update_leds_for_state(current_state)
        
        # Check for power events that should keep display on
        self._check_power_events()
        
        # Check if we're in an emergency state that should keep display on
        self._check_emergency_state(current_state)
    
    def update_display_and_leds_with_state_machines(self, freq: Optional[float], ug_indicator: str, 
                                                   primary_state_machine, secondary_state_machine=None,
                                                   zero_voltage_duration: float = 0.0,
                                                   secondary_freq: Optional[float] = None):
        """Update LCD display and LED indicators with separate state machines for each optocoupler."""
        
        # Check if we have dual optocoupler readings
        if secondary_freq is not None and secondary_state_machine is not None:
            # Dual optocoupler mode - cycle between the two
            self.dual_mode = True
            self._cycle_dual_display(freq, secondary_freq, ug_indicator, 
                                   primary_state_machine, secondary_state_machine,
                                   zero_voltage_duration)
        else:
            # Single optocoupler mode - original display
            self.dual_mode = False
            self.update_display_and_leds(freq, ug_indicator, primary_state_machine, zero_voltage_duration, secondary_freq)
    
    def _cycle_dual_display(self, primary_freq: Optional[float], secondary_freq: Optional[float], 
                           ug_indicator: str, primary_state_machine, secondary_state_machine,
                           zero_voltage_duration: float):
        """Cycle between primary and secondary optocoupler displays with separate state machines."""
        current_time_float = time.time()
        
        # Check if it's time to cycle to the next optocoupler
        if current_time_float - self.last_cycle_time >= self.cycle_interval:
            # Switch to the other optocoupler
            if self.current_display_optocoupler == 'primary':
                self.current_display_optocoupler = 'secondary'
            else:
                self.current_display_optocoupler = 'primary'
            self.last_cycle_time = current_time_float
        
        # Get optocoupler names from configuration
        primary_name = self._get_optocoupler_name('primary')
        secondary_name = self._get_optocoupler_name('secondary')
        
        # Display the current optocoupler with its state machine
        if self.current_display_optocoupler == 'primary':
            # Show primary optocoupler
            current_time = time.strftime("%H:%M:%S")
            line1 = f"{current_time}"
            if primary_freq is not None:
                line2 = f"{primary_name}: {primary_freq:.1f}Hz {ug_indicator}"
            else:
                line2 = f"{primary_name}: 0V {ug_indicator}"
            
            # Update display
            self.update_display(line1, line2)
            
            # Update LEDs based on primary state machine
            primary_state_info = primary_state_machine.get_state_info()
            self.update_leds_for_state(primary_state_info['current_state'])
            
            # Check for emergency state
            self._check_emergency_state(primary_state_info['current_state'])
        else:
            # Show secondary optocoupler
            current_time = time.strftime("%H:%M:%S")
            line1 = f"{current_time}"
            if secondary_freq is not None:
                line2 = f"{secondary_name}: {secondary_freq:.1f}Hz {ug_indicator}"
            else:
                line2 = f"{secondary_name}: 0V {ug_indicator}"
            
            # Update display
            self.update_display(line1, line2)
            
            # Update LEDs based on secondary state machine
            secondary_state_info = secondary_state_machine.get_state_info()
            self.update_leds_for_state(secondary_state_info['current_state'])
            
            # Check for emergency state
            self._check_emergency_state(secondary_state_info['current_state'])
    
    
    def _get_optocoupler_name(self, optocoupler_type: str) -> str:
        """Get the display name for an optocoupler from configuration."""
        try:
            if hasattr(self.hardware_manager, 'config'):
                config = self.hardware_manager.config
                if hasattr(config, 'get'):
                    try:
                        name = config[f'hardware']['optocoupler'][optocoupler_type]['name']
                        return name
                    except KeyError:
                        return optocoupler_type.capitalize()
        except Exception as e:
            self.logger.debug(f"Could not get optocoupler name: {e}")
        
        # Fallback to default names
        return "Mechanical" if optocoupler_type == 'primary' else "Lights"
    
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
                # Only call close() if it's the RPLCD version (has close method)
                if USE_RPLCD and hasattr(self.lcd, 'close'):
                    self.lcd.close()
                self.logger.info("LCD cleanup completed")
            except Exception as e:
                self.logger.error(f"LCD cleanup error: {e}")
