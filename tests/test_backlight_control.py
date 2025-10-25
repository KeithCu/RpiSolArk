#!/usr/bin/env python3
"""
Test script for LCD backlight control functionality.
Tests the backlight on/off functionality and display timeout.
"""

import time
import logging
import sys
import os

# Add the current directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from LCD1602 import CharLCD1602
from display import DisplayManager
from button_handler import ButtonHandler
import yaml

def setup_logging():
    """Setup logging for the test."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def load_config():
    """Load configuration from config.yaml."""
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        print(f"Error loading config: {e}")
        # Return default config
        return {
            'hardware': {
                'lcd_address': 0x27,
                'button_pin': 18,
                'display_timeout_seconds': 5
            }
        }

def test_lcd_backlight_control():
    """Test basic LCD backlight control."""
    print("=" * 60)
    print("TESTING LCD BACKLIGHT CONTROL")
    print("=" * 60)
    
    logger = setup_logging()
    
    # Create LCD instance
    lcd = CharLCD1602()
    
    print("1. Initializing LCD...")
    try:
        result = lcd.init_lcd(addr=0x27, bl=1)
        if result:
            print("   ✓ LCD initialized successfully")
        else:
            print("   ✗ LCD initialization failed")
            return False
    except Exception as e:
        print(f"   ✗ LCD initialization error: {e}")
        return False
    
    print("\n2. Testing backlight control...")
    
    # Test backlight on
    print("   Turning backlight ON...")
    try:
        lcd.set_backlight(True)
        print("   ✓ Backlight turned on")
        time.sleep(2)
    except Exception as e:
        print(f"   ✗ Error turning backlight on: {e}")
        return False
    
    # Test backlight off
    print("   Turning backlight OFF...")
    try:
        lcd.set_backlight(False)
        print("   ✓ Backlight turned off")
        time.sleep(2)
    except Exception as e:
        print(f"   ✗ Error turning backlight off: {e}")
        return False
    
    # Test backlight on again
    print("   Turning backlight ON again...")
    try:
        lcd.set_backlight(True)
        print("   ✓ Backlight turned on again")
        time.sleep(2)
    except Exception as e:
        print(f"   ✗ Error turning backlight on again: {e}")
        return False
    
    print("\n3. Testing display with backlight...")
    try:
        lcd.clear()
        lcd.write(0, 0, "Backlight Test")
        lcd.write(0, 1, "Backlight ON")
        print("   ✓ Display updated with backlight on")
        time.sleep(3)
    except Exception as e:
        print(f"   ✗ Error updating display: {e}")
        return False
    
    print("\n4. Testing display with backlight off...")
    try:
        lcd.set_backlight(False)
        lcd.clear()
        lcd.write(0, 0, "Backlight OFF")
        lcd.write(0, 1, "Should be dark")
        print("   ✓ Display updated with backlight off (should be dark)")
        time.sleep(3)
    except Exception as e:
        print(f"   ✗ Error updating display with backlight off: {e}")
        return False
    
    # Turn backlight on for final test
    lcd.set_backlight(True)
    lcd.clear()
    lcd.write(0, 0, "Test Complete")
    lcd.write(0, 1, "Backlight ON")
    
    print("\n✓ LCD backlight control test completed successfully!")
    return True

def test_display_manager_timeout():
    """Test display manager timeout functionality."""
    print("\n" + "=" * 60)
    print("TESTING DISPLAY MANAGER TIMEOUT")
    print("=" * 60)
    
    logger = setup_logging()
    config = load_config()
    
    print("1. Creating DisplayManager...")
    try:
        display_manager = DisplayManager(config, logger)
        print("   ✓ DisplayManager created successfully")
    except Exception as e:
        print(f"   ✗ Error creating DisplayManager: {e}")
        return False
    
    print("\n2. Testing display timeout...")
    print("   Setting timeout to 3 seconds...")
    display_manager.set_display_timeout(0.05)  # 3 seconds (0.05 minutes)
    
    print("   Updating display (should reset timeout)...")
    display_manager.update_display("Timeout Test", "3 sec timeout")
    time.sleep(1)
    
    print("   Waiting for timeout...")
    time.sleep(4)  # Wait longer than timeout
    
    print("   Checking if display is off...")
    if not display_manager.display_on:
        print("   ✓ Display timeout working - display is off")
    else:
        print("   ✗ Display timeout not working - display is still on")
        return False
    
    print("\n3. Testing manual display on...")
    print("   Manually turning display on...")
    display_manager.force_display_on()
    
    if display_manager.display_on:
        print("   ✓ Manual display on working")
    else:
        print("   ✗ Manual display on not working")
        return False
    
    print("\n✓ Display manager timeout test completed successfully!")
    return True

def test_button_handler():
    """Test button handler functionality."""
    print("\n" + "=" * 60)
    print("TESTING BUTTON HANDLER")
    print("=" * 60)
    
    logger = setup_logging()
    config = load_config()
    
    print("1. Creating DisplayManager and ButtonHandler...")
    try:
        display_manager = DisplayManager(config, logger)
        button_handler = ButtonHandler(
            button_pin=config['hardware']['button_pin'],
            display_manager=display_manager,
            logger=logger
        )
        print("   ✓ DisplayManager and ButtonHandler created successfully")
    except Exception as e:
        print(f"   ✗ Error creating components: {e}")
        return False
    
    print("\n2. Testing button handler setup...")
    if button_handler.gpio_available:
        print("   ✓ GPIO available - button handler should work")
    else:
        print("   ⚠ GPIO not available - button handler in simulation mode")
    
    print("\n3. Starting button monitoring...")
    try:
        button_handler.start_monitoring()
        print("   ✓ Button monitoring started")
        print("   Press the button on GPIO {} to test...".format(config['hardware']['button_pin']))
        print("   (Button should turn display on for 5 minutes)")
        print("   Press Ctrl+C to stop test")
        
        # Monitor for button presses
        start_time = time.time()
        while time.time() - start_time < 30:  # Test for 30 seconds
            if button_handler.button_pressed:
                print("   ✓ Button press detected!")
                button_handler.button_pressed = False
            time.sleep(0.1)
        
    except KeyboardInterrupt:
        print("\n   Test interrupted by user")
    except Exception as e:
        print(f"   ✗ Error during button monitoring: {e}")
        return False
    finally:
        print("   Stopping button monitoring...")
        button_handler.stop_monitoring()
        button_handler.cleanup()
        print("   ✓ Button monitoring stopped")
    
    print("\n✓ Button handler test completed!")
    return True

def test_integrated_backlight_control():
    """Test integrated backlight control with display manager."""
    print("\n" + "=" * 60)
    print("TESTING INTEGRATED BACKLIGHT CONTROL")
    print("=" * 60)
    
    logger = setup_logging()
    config = load_config()
    
    print("1. Creating DisplayManager...")
    try:
        display_manager = DisplayManager(config, logger)
        print("   ✓ DisplayManager created successfully")
    except Exception as e:
        print(f"   ✗ Error creating DisplayManager: {e}")
        return False
    
    print("\n2. Testing display updates with backlight...")
    try:
        # Update display - should turn on backlight
        display_manager.update_display("Test Line 1", "Test Line 2")
        print("   ✓ Display updated")
        time.sleep(2)
        
        # Test timeout
        print("   Setting short timeout...")
        display_manager.set_display_timeout(0.05)  # 3 seconds
        time.sleep(4)  # Wait for timeout
        
        if not display_manager.display_on:
            print("   ✓ Display timeout working - backlight should be off")
        else:
            print("   ✗ Display timeout not working")
            return False
        
        # Test manual turn on
        print("   Manually turning display on...")
        display_manager.force_display_on()
        display_manager.update_display("Manual On", "Backlight ON")
        print("   ✓ Display manually turned on")
        time.sleep(2)
        
    except Exception as e:
        print(f"   ✗ Error during integrated test: {e}")
        return False
    
    print("\n✓ Integrated backlight control test completed successfully!")
    return True

def main():
    """Run all backlight control tests."""
    print("LCD BACKLIGHT CONTROL TEST SUITE")
    print("=" * 60)
    print("This test suite will verify that backlight control is working properly.")
    print("Make sure your LCD is connected and working before running these tests.")
    print()
    
    tests = [
        ("LCD Backlight Control", test_lcd_backlight_control),
        ("Display Manager Timeout", test_display_manager_timeout),
        ("Button Handler", test_button_handler),
        ("Integrated Control", test_integrated_backlight_control)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\nRunning test: {test_name}")
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                print(f"✓ {test_name} PASSED")
            else:
                print(f"✗ {test_name} FAILED")
        except Exception as e:
            print(f"✗ {test_name} ERROR: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "PASSED" if result else "FAILED"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Backlight control is working properly.")
    else:
        print("⚠ Some tests failed. Check the output above for details.")
    
    return passed == total

if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        sys.exit(1)
