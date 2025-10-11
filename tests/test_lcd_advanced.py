#!/usr/bin/env python3
"""
Advanced LCD Test - Alternative Approaches

Since RPLCD showed no working configurations, let's try:
1. Adafruit_CharLCD library
2. Direct smbus communication (like original LCD1602.py)
3. Different timing approaches
4. Power cycling techniques
"""

import time
import sys
import subprocess

def test_adafruit_library():
    """Test using Adafruit_CharLCD library as alternative to RPLCD."""
    print("Testing Adafruit_CharLCD library...")
    try:
        from Adafruit_CharLCD import Adafruit_CharLCD
        
        # Initialize LCD
        lcd = Adafruit_CharLCD(rs=26, en=19, d4=13, d5=6, d6=5, d7=11, cols=16, lines=2)
        
        lcd.clear()
        lcd.message('Adafruit Test')
        time.sleep(1)
        
        lcd.clear()
        lcd.message('Line 1\nLine 2')
        time.sleep(1)
        
        lcd.clear()
        print("  ? CHECK: Does Adafruit library show readable text?")
        response = input("     Does it work? (y/n): ").lower().strip()
        
        if response in ['y', 'yes']:
            print("  ✓ SUCCESS: Adafruit library works!")
            return True
        else:
            print("  ✗ FAILED: Adafruit library shows garbage")
            return False
            
    except ImportError:
        print("  ✗ Adafruit_CharLCD not installed")
        return False
    except Exception as e:
        print(f"  ✗ Adafruit library error: {e}")
        return False

def test_direct_smbus():
    """Test direct smbus communication like original LCD1602.py."""
    print("Testing direct smbus communication...")
    try:
        import smbus
        
        bus = smbus.SMBus(1)
        address = 0x27
        
        # Send initialization sequence (like original LCD1602.py)
        def write_word(addr, data):
            temp = data | 0x08  # Backlight on
            bus.write_byte(addr, temp)
        
        def send_command(comm):
            # Send bit7-4 firstly
            buf = comm & 0xF0
            buf |= 0x04  # RS = 0, RW = 0, EN = 1
            write_word(address, buf)
            time.sleep(0.002)
            buf &= 0xFB  # Make EN = 0
            write_word(address, buf)
            # Send bit3-0 secondly
            buf = (comm & 0x0F) << 4
            buf |= 0x04  # RS = 0, RW = 0, EN = 1
            write_word(address, buf)
            time.sleep(0.002)
            buf &= 0xFB  # Make EN = 0
            write_word(address, buf)
        
        def send_data(data):
            # Send bit7-4 firstly
            buf = data & 0xF0
            buf |= 0x05  # RS = 1, RW = 0, EN = 1
            write_word(address, buf)
            time.sleep(0.002)
            buf &= 0xFB  # Make EN = 0
            write_word(address, buf)
            # Send bit3-0 secondly
            buf = (data & 0x0F) << 4
            buf |= 0x05  # RS = 1, RW = 0, EN = 1
            write_word(address, buf)
            time.sleep(0.002)
            buf &= 0xFB  # Make EN = 0
            write_word(address, buf)
        
        # Initialize LCD (exact sequence from original LCD1602.py)
        send_command(0x33)  # Must initialize to 8-line mode at first
        time.sleep(0.005)
        send_command(0x32)  # Then initialize to 4-line mode
        time.sleep(0.005)
        send_command(0x28)  # 2 Lines & 5*7 dots
        time.sleep(0.005)
        send_command(0x0C)  # Enable display without cursor
        time.sleep(0.005)
        send_command(0x01)  # Clear Screen
        bus.write_byte(address, 0x08)
        
        # Test display
        time.sleep(0.1)
        send_command(0x80)  # Move to line 1
        for char in "Direct Test":
            send_data(ord(char))
        
        send_command(0xC0)  # Move to line 2
        for char in "Smbus OK":
            send_data(ord(char))
        
        time.sleep(1)
        
        # Clear
        send_command(0x01)
        bus.write_byte(address, 0x08)
        
        print("  ? CHECK: Does direct smbus show readable text?")
        response = input("     Does it work? (y/n): ").lower().strip()
        
        if response in ['y', 'yes']:
            print("  ✓ SUCCESS: Direct smbus works!")
            return True
        else:
            print("  ✗ FAILED: Direct smbus shows garbage")
            return False
            
    except Exception as e:
        print(f"  ✗ Direct smbus error: {e}")
        return False

def test_power_cycle():
    """Test power cycling the LCD before initialization."""
    print("Testing power cycle approach...")
    try:
        from RPLCD.i2c import CharLCD
        
        # Try to "power cycle" by closing and reopening
        print("  Attempting power cycle...")
        
        # First, try to clear any existing state
        try:
            lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, cols=16, rows=2)
            lcd.clear()
            lcd.close()
        except:
            pass
        
        time.sleep(1)  # Wait for "power cycle"
        
        # Now try fresh initialization
        lcd = CharLCD(
            i2c_expander='PCF8574',
            address=0x27,
            port=1,
            cols=16,
            rows=2,
            dotsize=8,
            charmap='A02',
            auto_linebreaks=False,
            backlight_enabled=True
        )
        
        lcd.clear()
        time.sleep(0.1)
        lcd.write_string("Power Cycle")
        time.sleep(0.5)
        
        lcd.clear()
        lcd.write_string("Test OK")
        time.sleep(0.5)
        
        lcd.clear()
        lcd.close()
        
        print("  ? CHECK: Does power cycle approach show readable text?")
        response = input("     Does it work? (y/n): ").lower().strip()
        
        if response in ['y', 'yes']:
            print("  ✓ SUCCESS: Power cycle approach works!")
            return True
        else:
            print("  ✗ FAILED: Power cycle shows garbage")
            return False
            
    except Exception as e:
        print(f"  ✗ Power cycle error: {e}")
        return False

def test_timing_variations():
    """Test different timing approaches."""
    print("Testing timing variations...")
    try:
        from RPLCD.i2c import CharLCD
        
        # Try with very slow timing
        lcd = CharLCD(
            i2c_expander='PCF8574',
            address=0x27,
            port=1,
            cols=16,
            rows=2,
            dotsize=8,
            charmap='A02',
            auto_linebreaks=False,
            backlight_enabled=True
        )
        
        # Add extra delays
        lcd.clear()
        time.sleep(0.5)  # Extra long delay
        
        lcd.write_string("Slow Timing")
        time.sleep(1)
        
        lcd.clear()
        time.sleep(0.5)
        
        lcd.write_string("Test")
        time.sleep(0.5)
        lcd.cursor_pos = (1, 0)
        lcd.write_string("OK")
        time.sleep(1)
        
        lcd.clear()
        lcd.close()
        
        print("  ? CHECK: Does slow timing show readable text?")
        response = input("     Does it work? (y/n): ").lower().strip()
        
        if response in ['y', 'yes']:
            print("  ✓ SUCCESS: Slow timing works!")
            return True
        else:
            print("  ✗ FAILED: Slow timing shows garbage")
            return False
            
    except Exception as e:
        print(f"  ✗ Timing variation error: {e}")
        return False

def main():
    """Run advanced LCD tests."""
    print("=" * 60)
    print("ADVANCED LCD TESTING")
    print("=" * 60)
    print()
    
    working_solutions = []
    
    # Test 1: Adafruit library
    if test_adafruit_library():
        working_solutions.append("Adafruit_CharLCD library")
    print()
    
    # Test 2: Direct smbus
    if test_direct_smbus():
        working_solutions.append("Direct smbus communication")
    print()
    
    # Test 3: Power cycle
    if test_power_cycle():
        working_solutions.append("Power cycle approach")
    print()
    
    # Test 4: Timing variations
    if test_timing_variations():
        working_solutions.append("Slow timing approach")
    print()
    
    # Results
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    if working_solutions:
        print(f"Found {len(working_solutions)} working solution(s):")
        for i, solution in enumerate(working_solutions, 1):
            print(f"{i}. {solution}")
    else:
        print("No working solutions found.")
        print("Recommendation: Use the original LCD1602.py which you know works.")
        print("The LCD may not be compatible with modern libraries.")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
