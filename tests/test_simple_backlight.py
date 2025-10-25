#!/usr/bin/env python3
"""
Simple test for LCD backlight control.
This is a quick test to verify backlight on/off functionality.
"""

import time
import sys
import os

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from LCD1602 import CharLCD1602

def test_simple_backlight():
    """Simple backlight test."""
    print("Simple LCD Backlight Test")
    print("=" * 30)
    
    # Create LCD instance
    lcd = CharLCD1602()
    
    print("Initializing LCD...")
    try:
        result = lcd.init_lcd(addr=0x27, bl=1)
        if not result:
            print("LCD initialization failed!")
            return False
        print("LCD initialized successfully")
    except Exception as e:
        print(f"LCD initialization error: {e}")
        return False
    
    print("\nTesting backlight control...")
    
    # Test sequence
    for i in range(3):
        print(f"\nCycle {i+1}/3:")
        
        # Turn on backlight
        print("  Turning backlight ON...")
        lcd.set_backlight(True)
        lcd.clear()
        lcd.write(0, 0, f"Backlight ON {i+1}")
        lcd.write(0, 1, "Should be bright")
        time.sleep(2)
        
        # Turn off backlight
        print("  Turning backlight OFF...")
        lcd.set_backlight(False)
        lcd.clear()
        lcd.write(0, 0, f"Backlight OFF {i+1}")
        lcd.write(0, 1, "Should be dark")
        time.sleep(2)
    
    # Final state - backlight on
    print("\nFinal state - backlight ON")
    lcd.set_backlight(True)
    lcd.clear()
    lcd.write(0, 0, "Test Complete")
    lcd.write(0, 1, "Backlight ON")
    
    print("\n✓ Simple backlight test completed!")
    print("If you could see the display turning on and off, the backlight control is working.")
    
    return True

if __name__ == '__main__':
    try:
        test_simple_backlight()
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    except Exception as e:
        print(f"Error: {e}")
