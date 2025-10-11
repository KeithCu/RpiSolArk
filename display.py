#!/usr/bin/env python3
"""
Display management for the frequency monitor.
Handles LCD display, LED controls, and simulation with graceful degradation.
"""

import logging
import time
from typing import Optional, Deque
from collections import deque

# Hardware imports
from lcd_rplcd import LCD1602_RPLCD
LCD_AVAILABLE = True


class DisplayManager:
    """Manages LCD display, LED controls, and display logic with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger, hardware_manager=None):
        self.config = config
        self.logger = logger
        self.hardware_manager = hardware_manager
        self.lcd_available = LCD_AVAILABLE
        self.lcd = None
        
        self._setup_display()
    
    def _setup_display(self):
        """Setup LCD display."""
        self.logger.info(f"LCD available: {self.lcd_available}")
        
        if self.lcd_available:
            try:
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

        # Show time and frequency with power source indicator, updated once per second
        current_time = time.strftime("%H:%M:%S")
        line1 = f"{current_time}"

        if freq is not None:
            line2 = f"{freq:.2f} Hz {ug_indicator}"
        else:
            line2 = f"0V ({zero_voltage_duration:.0f}s) {ug_indicator}"

        # Update display
        self.update_display(line1, line2)

        # Update LEDs based on state machine state
        self.update_leds_for_state(current_state)
    
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
                self.lcd.close()
                self.logger.info("LCD cleanup completed")
            except Exception as e:
                self.logger.error(f"LCD cleanup error: {e}")
