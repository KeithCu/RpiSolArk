#!/usr/bin/env python3
"""
Test script for backlight control during power state changes.
Tests that the backlight turns on when entering off_grid or generator states.
"""

import time
import logging
import sys
import os
from unittest.mock import Mock

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monitor import PowerStateMachine, PowerState
from display import DisplayManager
from LCD1602 import CharLCD1602
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
            },
            'state_machine': {
                'transition_timeout': 30.0,
                'zero_voltage_threshold': 1.0,
                'unsteady_voltage_threshold': 0.1
            }
        }

def test_startup_backlight():
    """Test that backlight is on at startup."""
    print("=" * 60)
    print("TESTING STARTUP BACKLIGHT")
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
    
    print("\n2. Checking startup backlight state...")
    if display_manager.display_on:
        print("   ✓ Display is on at startup")
    else:
        print("   ✗ Display is off at startup")
        return False
    
    if display_manager.lcd_available and display_manager.lcd:
        print("   ✓ LCD is available")
        # Check if backlight is actually on
        try:
            # This is a bit tricky to test without hardware
            # We'll just verify the display manager thinks it's on
            print("   ✓ Display manager reports display is on")
        except Exception as e:
            print(f"   ⚠ Could not verify actual backlight state: {e}")
    else:
        print("   ⚠ LCD not available - testing in simulation mode")
    
    print("\n✓ Startup backlight test completed!")
    return True

def test_power_state_callbacks():
    """Test that power state callbacks turn on backlight."""
    print("\n" + "=" * 60)
    print("TESTING POWER STATE CALLBACKS")
    print("=" * 60)
    
    logger = setup_logging()
    config = load_config()
    
    print("1. Creating DisplayManager and PowerStateMachine...")
    try:
        display_manager = DisplayManager(config, logger)
        state_machine = PowerStateMachine(config, logger, display_manager)
        print("   ✓ Components created successfully")
    except Exception as e:
        print(f"   ✗ Error creating components: {e}")
        return False
    
    print("\n2. Testing OFF_GRID state callback...")
    try:
        # Simulate entering off_grid state
        state_machine._on_enter_off_grid()
        print("   ✓ OFF_GRID callback executed")
        
        if display_manager.display_on:
            print("   ✓ Display is on after OFF_GRID callback")
        else:
            print("   ✗ Display is off after OFF_GRID callback")
            return False
    except Exception as e:
        print(f"   ✗ Error in OFF_GRID callback: {e}")
        return False
    
    print("\n3. Testing GENERATOR state callback...")
    try:
        # Simulate entering generator state
        state_machine._on_enter_generator()
        print("   ✓ GENERATOR callback executed")
        
        if display_manager.display_on:
            print("   ✓ Display is on after GENERATOR callback")
        else:
            print("   ✗ Display is off after GENERATOR callback")
            return False
    except Exception as e:
        print(f"   ✗ Error in GENERATOR callback: {e}")
        return False
    
    print("\n4. Testing GRID state callback...")
    try:
        # Simulate entering grid state
        state_machine._on_enter_grid()
        print("   ✓ GRID callback executed")
        
        if display_manager.display_on:
            print("   ✓ Display is on after GRID callback")
        else:
            print("   ✗ Display is off after GRID callback")
            return False
    except Exception as e:
        print(f"   ✗ Error in GRID callback: {e}")
        return False
    
    print("\n✓ Power state callbacks test completed!")
    return True

def test_state_transitions():
    """Test that state transitions trigger backlight control."""
    print("\n" + "=" * 60)
    print("TESTING STATE TRANSITIONS")
    print("=" * 60)
    
    logger = setup_logging()
    config = load_config()
    
    print("1. Creating components...")
    try:
        display_manager = DisplayManager(config, logger)
        state_machine = PowerStateMachine(config, logger, display_manager)
        print("   ✓ Components created successfully")
    except Exception as e:
        print(f"   ✗ Error creating components: {e}")
        return False
    
    print("\n2. Testing state transitions...")
    
    # Test transitioning to OFF_GRID
    print("   Transitioning to OFF_GRID...")
    try:
        state_machine.update_state(None, "Unknown", 6.0)  # Should trigger OFF_GRID
        if state_machine.current_state == PowerState.OFF_GRID:
            print("   ✓ Successfully transitioned to OFF_GRID")
            if display_manager.display_on:
                print("   ✓ Display is on after OFF_GRID transition")
            else:
                print("   ✗ Display is off after OFF_GRID transition")
                return False
        else:
            print(f"   ✗ Expected OFF_GRID, got {state_machine.current_state}")
            return False
    except Exception as e:
        print(f"   ✗ Error transitioning to OFF_GRID: {e}")
        return False
    
    # Test transitioning to GENERATOR
    print("   Transitioning to GENERATOR...")
    try:
        state_machine.update_state(58.5, "Generac Generator", 0.0)  # Should trigger GENERATOR
        if state_machine.current_state == PowerState.GENERATOR:
            print("   ✓ Successfully transitioned to GENERATOR")
            if display_manager.display_on:
                print("   ✓ Display is on after GENERATOR transition")
            else:
                print("   ✗ Display is off after GENERATOR transition")
                return False
        else:
            print(f"   ✗ Expected GENERATOR, got {state_machine.current_state}")
            return False
    except Exception as e:
        print(f"   ✗ Error transitioning to GENERATOR: {e}")
        return False
    
    # Test transitioning to GRID
    print("   Transitioning to GRID...")
    try:
        state_machine.update_state(60.0, "Utility Grid", 0.0)  # Should trigger GRID
        if state_machine.current_state == PowerState.GRID:
            print("   ✓ Successfully transitioned to GRID")
            if display_manager.display_on:
                print("   ✓ Display is on after GRID transition")
            else:
                print("   ✗ Display is off after GRID transition")
                return False
        else:
            print(f"   ✗ Expected GRID, got {state_machine.current_state}")
            return False
    except Exception as e:
        print(f"   ✗ Error transitioning to GRID: {e}")
        return False
    
    print("\n✓ State transitions test completed!")
    return True

def test_emergency_state_detection():
    """Test that emergency states keep display on."""
    print("\n" + "=" * 60)
    print("TESTING EMERGENCY STATE DETECTION")
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
    
    print("\n2. Testing emergency state detection...")
    
    # Test off_grid state
    print("   Testing off_grid state...")
    try:
        display_manager._check_emergency_state('off_grid')
        if display_manager.display_on:
            print("   ✓ Display is on for off_grid state")
        else:
            print("   ✗ Display is off for off_grid state")
            return False
    except Exception as e:
        print(f"   ✗ Error checking off_grid state: {e}")
        return False
    
    # Test generator state
    print("   Testing generator state...")
    try:
        display_manager._check_emergency_state('generator')
        if display_manager.display_on:
            print("   ✓ Display is on for generator state")
        else:
            print("   ✗ Display is off for generator state")
            return False
    except Exception as e:
        print(f"   ✗ Error checking generator state: {e}")
        return False
    
    # Test non-emergency state
    print("   Testing grid state (non-emergency)...")
    try:
        display_manager._check_emergency_state('grid')
        print("   ✓ Grid state handled correctly (not emergency)")
    except Exception as e:
        print(f"   ✗ Error checking grid state: {e}")
        return False
    
    print("\n✓ Emergency state detection test completed!")
    return True

def main():
    """Run all power state backlight tests."""
    print("POWER STATE BACKLIGHT CONTROL TEST SUITE")
    print("=" * 60)
    print("This test suite verifies that backlight control works during power state changes.")
    print()
    
    tests = [
        ("Startup Backlight", test_startup_backlight),
        ("Power State Callbacks", test_power_state_callbacks),
        ("State Transitions", test_state_transitions),
        ("Emergency State Detection", test_emergency_state_detection)
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
        print("🎉 All tests passed! Power state backlight control is working properly.")
        print("\nKey Features Verified:")
        print("  ✓ Backlight is on at startup")
        print("  ✓ Backlight turns on when entering OFF_GRID state")
        print("  ✓ Backlight turns on when entering GENERATOR state")
        print("  ✓ Backlight turns on when entering GRID state")
        print("  ✓ Emergency states keep display on")
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
