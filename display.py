#!/usr/bin/env python3
"""
Display management for the frequency monitor.
Handles LCD display, LED controls, and simulation with graceful degradation.
"""

import logging
import time
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
        
        self._setup_display()
    
    def _setup_display(self):
        """Setup LCD display."""
        self.logger.info(f"LCD available: {self.lcd_available}")
        
        if self.lcd_available:
            try:
                if USE_RPLCD:
                    self.logger.info("Creating LCD1602_RPLCD object...")
                    
                    # Get LCD configuration from config.yaml
                    lcd_address = self.config.get('hardware.lcd_address', 0x27)
                    lcd_port = self.config.get('hardware.lcd_port', 1)
                    lcd_cols = self.config.get('hardware.lcd_cols', 16)
                    lcd_rows = self.config.get('hardware.lcd_rows', 2)
                    
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
                    lcd_address = self.config.get('hardware.lcd_address', 0x27)
                    
                    self.logger.info(f"LCD config: address=0x{lcd_address:02x}")
                    
                    # Initialize with the old working method
                    self.lcd = CharLCD1602()
                    init_result = self.lcd.init_lcd(addr=lcd_address, bl=1)
                    
                    if init_result:
                        self.logger.info("Original LCD1602 initialized successfully")
                    else:
                        self.logger.error("LCD init_lcd() returned False - initialization failed")
                        self.lcd_available = False
                        self.lcd = None
                        return
                
                self.logger.info("LCD hardware initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize LCD: {e}")
                import traceback
                self.logger.error(f"LCD initialization traceback: {traceback.format_exc()}")
                self.lcd_available = False
                self.lcd = None
        else:
            self.logger.info("LCD not available, skipping LCD setup")
    
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
            self._cycle_dual_display(freq, secondary_freq, ug_indicator, zero_voltage_duration, current_time)
        else:
            # Single optocoupler mode - original display
            self.dual_mode = False
            line1 = f"{current_time}"
            if freq is not None:
                line2 = f"{freq:.2f} Hz {ug_indicator}"
            else:
                line2 = f"0V ({zero_voltage_duration:.0f}s) {ug_indicator}"
            
            # Update display
            self.update_display(line1, line2)

        # Update LEDs based on state machine state
        self.update_leds_for_state(current_state)
    
    def _cycle_dual_display(self, primary_freq: Optional[float], secondary_freq: Optional[float], 
                           ug_indicator: str, zero_voltage_duration: float, current_time: str):
        """Cycle between primary and secondary optocoupler displays."""
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
        
        # Display the current optocoupler
        if self.current_display_optocoupler == 'primary':
            # Show primary optocoupler
            line1 = f"{current_time}"
            if primary_freq is not None:
                line2 = f"{primary_name}: {primary_freq:.1f}Hz {ug_indicator}"
            else:
                line2 = f"{primary_name}: 0V {ug_indicator}"
        else:
            # Show secondary optocoupler
            line1 = f"{current_time}"
            if secondary_freq is not None:
                line2 = f"{secondary_name}: {secondary_freq:.1f}Hz {ug_indicator}"
            else:
                line2 = f"{secondary_name}: 0V {ug_indicator}"
        
        # Update display
        self.update_display(line1, line2)
    
    def _get_optocoupler_name(self, optocoupler_type: str) -> str:
        """Get the display name for an optocoupler from configuration."""
        try:
            if hasattr(self.hardware_manager, 'config'):
                config = self.hardware_manager.config
                if hasattr(config, 'get'):
                    name = config.get(f'hardware.optocoupler.{optocoupler_type}.name', optocoupler_type.capitalize())
                    return name
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
    
    
    def cleanup(self):
        """Cleanup display resources."""
        if self.lcd_available and self.lcd:
            try:
                self.lcd.clear()
                # Only call close() if it's the RPLCD version (has close method)
                if USE_RPLCD and hasattr(self.lcd, 'close'):
                    self.lcd.close()
                self.logger.info("LCD cleanup completed")
            except Exception as e:
                self.logger.error(f"LCD cleanup error: {e}")
