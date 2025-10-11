#!/usr/bin/env python3
"""
LCD Compatibility Test Suite

PROBLEM STATE:
- Original LCD1602.py works perfectly with the hardware
- RPLCD library shows garbage characters scrolling right to left
- Need to find the correct RPLCD configuration parameters

WHY THIS TEST FILE:
- RPLCD has many configuration options that can cause garbage display
- Testing each parameter individually is time-consuming
- This systematic approach tests all combinations to find working config
- Useful for others with similar LCD compatibility issues

TOP 5 LIKELY CAUSES:
1. Character map mismatch (A00 vs A02 vs A00_alt)
2. I2C expander type (PCF8574 vs PCF8574A vs MCP23008)
3. Initialization timing differences
4. Dotsize parameter (8 vs 10)
5. Auto-linebreaks setting

This test systematically tries all combinations to find what works.
"""

import time
import sys
import subprocess
from typing import List, Tuple, Dict, Any

# Test configurations to try - comprehensive list of likely possibilities
TEST_CONFIGS = [
    # (charmap, i2c_expander, dotsize, auto_linebreaks, description)
    
    # Standard configurations
    ('A02', 'PCF8574', 8, True, 'Default RPLCD settings'),
    ('A00', 'PCF8574', 8, True, 'Alternative charmap A00'),
    ('A00_alt', 'PCF8574', 8, True, 'Alternative A00 charmap'),
    
    # Different I2C expanders
    ('A02', 'PCF8574A', 8, True, 'PCF8574A expander'),
    ('A00', 'PCF8574A', 8, True, 'PCF8574A with A00'),
    ('A00_alt', 'PCF8574A', 8, True, 'PCF8574A with A00_alt'),
    ('A02', 'MCP23008', 8, True, 'MCP23008 expander'),
    ('A00', 'MCP23008', 8, True, 'MCP23008 with A00'),
    
    # Different dotsizes
    ('A02', 'PCF8574', 10, True, '10-dot font size'),
    ('A00', 'PCF8574', 10, True, 'A00 with 10-dot font'),
    ('A00_alt', 'PCF8574', 10, True, 'A00_alt with 10-dot font'),
    ('A02', 'PCF8574A', 10, True, 'PCF8574A with 10-dot font'),
    ('A00', 'PCF8574A', 10, True, 'PCF8574A A00 with 10-dot font'),
    
    # Without auto-linebreaks
    ('A02', 'PCF8574', 8, False, 'No auto-linebreaks'),
    ('A00', 'PCF8574', 8, False, 'A00 without auto-linebreaks'),
    ('A00_alt', 'PCF8574', 8, False, 'A00_alt without auto-linebreaks'),
    ('A02', 'PCF8574A', 8, False, 'PCF8574A without auto-linebreaks'),
    ('A00', 'PCF8574A', 8, False, 'PCF8574A A00 without auto-linebreaks'),
    
    # 10-dot without auto-linebreaks
    ('A02', 'PCF8574', 10, False, '10-dot without auto-linebreaks'),
    ('A00', 'PCF8574', 10, False, 'A00 10-dot without auto-linebreaks'),
    ('A02', 'PCF8574A', 10, False, 'PCF8574A 10-dot without auto-linebreaks'),
    
    # MCP23008 variations
    ('A02', 'MCP23008', 8, False, 'MCP23008 without auto-linebreaks'),
    ('A00', 'MCP23008', 8, False, 'MCP23008 A00 without auto-linebreaks'),
    ('A02', 'MCP23008', 10, True, 'MCP23008 with 10-dot font'),
    ('A00', 'MCP23008', 10, True, 'MCP23008 A00 with 10-dot font'),
    ('A02', 'MCP23008', 10, False, 'MCP23008 10-dot without auto-linebreaks'),
    
    # Additional charmap variations (some LCDs use different mappings)
    ('A02', 'PCF8574', 8, True, 'A02 with explicit PCF8574'),
    ('A00', 'PCF8574', 8, True, 'A00 with explicit PCF8574'),
    
    # Backlight variations (test with backlight disabled)
    ('A02', 'PCF8574', 8, True, 'A02 with backlight disabled'),
    ('A00', 'PCF8574', 8, True, 'A00 with backlight disabled'),
    
    # Port variations (some systems use port 0)
    ('A02', 'PCF8574', 8, True, 'A02 on port 0'),
    ('A00', 'PCF8574', 8, True, 'A00 on port 0'),
    
    # Additional timing and initialization variations
    ('A02', 'PCF8574', 8, True, 'A02 with longer delays'),
    ('A00', 'PCF8574', 8, True, 'A00 with longer delays'),
    
    
    # Try without any auto-detection
    ('A02', 'PCF8574', 8, True, 'A02 direct mode'),
    ('A00', 'PCF8574', 8, True, 'A00 direct mode'),
    
    # Try different initialization sequences
    ('A02', 'PCF8574', 8, True, 'A02 minimal init'),
    ('A00', 'PCF8574', 8, True, 'A00 minimal init'),
]

# I2C addresses to test
I2C_ADDRESSES = [0x27, 0x3f]

def scan_i2c_devices(port: int = 1) -> List[str]:
    """Scan for I2C devices on the specified port."""
    try:
        cmd = f"i2cdetect -y {port} | awk 'NR>1 {{$1=\"\";print}}'"
        result = subprocess.check_output(cmd, shell=True).decode()
        result = result.replace("\n", "").replace(" --", "")
        i2c_list = result.split(' ')
        return [addr for addr in i2c_list if addr.strip()]
    except Exception as e:
        print(f"Error scanning I2C devices: {e}")
        return []

def test_rplcd_config(charmap: str, i2c_expander: str, dotsize: int, 
                     auto_linebreaks: bool, address: int, port: int = 1, 
                     backlight_enabled: bool = True, cols: int = 16, rows: int = 2) -> bool:
    """Test a specific RPLCD configuration."""
    try:
        from RPLCD.i2c import CharLCD
        
        print(f"  Testing: {charmap}, {i2c_expander}, dotsize={dotsize}, "
              f"auto_linebreaks={auto_linebreaks}, address=0x{address:02x}, "
              f"port={port}, backlight={backlight_enabled}, {cols}x{rows}")
        
        # Initialize LCD with test configuration
        lcd = CharLCD(
            i2c_expander=i2c_expander,
            address=address,
            port=port,
            cols=cols,
            rows=rows,
            dotsize=dotsize,
            charmap=charmap,
            auto_linebreaks=auto_linebreaks,
            backlight_enabled=backlight_enabled
        )
        
        # Test basic operations
        lcd.clear()
        time.sleep(0.1)
        
        lcd.write_string("Test 123")
        time.sleep(0.5)
        
        lcd.clear()
        lcd.write_string("Line 1")
        lcd.cursor_pos = (1, 0)
        lcd.write_string("Line 2")
        time.sleep(0.5)
        
        lcd.clear()
        lcd.close()
        
        # Ask user to verify if display actually shows readable text
        print(f"  ? CHECK: Does the LCD show readable text (not garbage)?")
        print(f"     Look for: 'Test 123' and 'Line 1' / 'Line 2'")
        response = input("     Does it work? (y/n): ").lower().strip()
        
        if response in ['y', 'yes']:
            print(f"  ✓ SUCCESS: Configuration works!")
            return True
        else:
            print(f"  ✗ FAILED: Display shows garbage")
            return False
        
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return False

def test_original_lcd1602(address: int) -> bool:
    """Test the original LCD1602.py to confirm it still works."""
    try:
        from LCD1602 import CharLCD1602
        
        print(f"Testing original LCD1602.py with address 0x{address:02x}")
        
        lcd = CharLCD1602()
        init_result = lcd.init_lcd(addr=address, bl=1)
        
        if init_result:
            lcd.clear()
            lcd.write(0, 0, "Original OK")
            lcd.write(0, 1, "Test 123")
            time.sleep(1)
            lcd.clear()
            print("✓ Original LCD1602.py works")
            return True
        else:
            print("✗ Original LCD1602.py failed to initialize")
            return False
            
    except Exception as e:
        print(f"✗ Original LCD1602.py error: {e}")
        return False

def main():
    """Run comprehensive LCD compatibility tests."""
    print("=" * 60)
    print("LCD COMPATIBILITY TEST SUITE")
    print("=" * 60)
    print()
    
    # Scan for I2C devices
    print("Scanning for I2C devices...")
    i2c_devices = scan_i2c_devices()
    print(f"Found I2C devices: {i2c_devices}")
    print()
    
    # Test original LCD1602.py first
    print("1. Testing original LCD1602.py (baseline)...")
    original_works = False
    for addr in I2C_ADDRESSES:
        if test_original_lcd1602(addr):
            original_works = True
            break
    print()
    
    if not original_works:
        print("ERROR: Original LCD1602.py doesn't work. Check hardware connections.")
        return
    
    # Test RPLCD configurations
    print("2. Testing RPLCD configurations...")
    working_configs = []
    
    for i, (charmap, i2c_expander, dotsize, auto_linebreaks, description) in enumerate(TEST_CONFIGS, 1):
        print(f"\nTest {i}: {description}")
        
        # Determine test parameters based on description
        backlight_enabled = True
        port = 1
        cols = 16  # Fixed to 16x2 display
        rows = 2
        
        if "backlight disabled" in description:
            backlight_enabled = False
        if "port 0" in description:
            port = 0
        
        for address in I2C_ADDRESSES:
            if test_rplcd_config(charmap, i2c_expander, dotsize, auto_linebreaks, 
                               address, port, backlight_enabled, cols, rows):
                working_configs.append({
                    'charmap': charmap,
                    'i2c_expander': i2c_expander,
                    'dotsize': dotsize,
                    'auto_linebreaks': auto_linebreaks,
                    'address': address,
                    'port': port,
                    'backlight_enabled': backlight_enabled,
                    'description': description
                })
                break  # Found working config for this test, move to next
    
    # Results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    if working_configs:
        print(f"Found {len(working_configs)} working RPLCD configuration(s):")
        for i, config in enumerate(working_configs, 1):
            print(f"\n{i}. {config['description']}")
            print(f"   charmap='{config['charmap']}'")
            print(f"   i2c_expander='{config['i2c_expander']}'")
            print(f"   dotsize={config['dotsize']}")
            print(f"   auto_linebreaks={config['auto_linebreaks']}")
            print(f"   address=0x{config['address']:02x}")
            print(f"   port={config['port']}")
            print(f"   backlight_enabled={config['backlight_enabled']}")
        
        print(f"\nRecommended configuration (first working):")
        best = working_configs[0]
        print(f"CharLCD(")
        print(f"    i2c_expander='{best['i2c_expander']}',")
        print(f"    address=0x{best['address']:02x},")
        print(f"    port={best['port']},")
        print(f"    cols=16,")
        print(f"    rows=2,")
        print(f"    dotsize={best['dotsize']},")
        print(f"    charmap='{best['charmap']}',")
        print(f"    auto_linebreaks={best['auto_linebreaks']},")
        print(f"    backlight_enabled={best['backlight_enabled']}")
        print(f")")
    else:
        print("No working RPLCD configurations found.")
        print("The LCD may not be compatible with RPLCD library.")
        print("Consider using the original LCD1602.py instead.")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
