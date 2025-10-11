#!/usr/bin/env python3
"""
Display management for the frequency monitor.
Handles LCD display and simulation with graceful degradation.
"""

import logging
from typing import Optional

# Hardware imports with graceful degradation
try:
    from LCD1602 import CharLCD1602
    LCD_AVAILABLE = True
except ImportError:
    LCD_AVAILABLE = False
    print("Warning: LCD1602 not available. LCD display disabled.")


class DisplayManager:
    """Manages LCD display with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.lcd_available = LCD_AVAILABLE
        self.lcd = None
        
        self._setup_display()
    
    def _setup_display(self):
        """Setup LCD display."""
        self.logger.info(f"LCD available: {self.lcd_available}")
        
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
    
    def cleanup(self):
        """Cleanup display resources."""
        if self.lcd_available and self.lcd:
            try:
                self.lcd.clear()
                self.logger.info("LCD cleanup completed")
            except Exception as e:
                self.logger.error(f"LCD cleanup error: {e}")
