#!/usr/bin/env python3
"""
Quick test script to verify the optocoupler improvements are working.
"""

import sys
import os
import time
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from optocoupler import OptocouplerManager

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

def test_improvements():
    """Quick test of the optocoupler improvements."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup logger
    logger = logging.getLogger('test_improvements')
    logger.setLevel(logging.INFO)
    
    # Create test configuration
    config = {
        'hardware': {
            'optocoupler': {
                'enabled': True,
                'gpio_pin': 26,
                'pulses_per_cycle': 2,
                'measurement_duration': 1.0
            }
        }
    }
    
    # Initialize optocoupler manager
    optocoupler = OptocouplerManager(config, logger)
    
    print("🔧 Testing Optocoupler Improvements")
    print("=" * 40)
    
    # Test 1: Standard measurement with improvements
    print("\n📊 Test 1: Standard measurement (5s)")
    pulse_count = optocoupler.count_optocoupler_pulses(5.0, debounce_time=0.001)
    frequency = optocoupler.calculate_frequency_from_pulses(pulse_count, 5.0)
    
    if frequency is not None:
        error = abs(frequency - 60.01)
        accuracy = (1 - error / 60.01) * 100
        print(f"  Frequency: {frequency:.3f} Hz")
        print(f"  Error: {error:.3f} Hz")
        print(f"  Accuracy: {accuracy:.1f}%")
        
        if error < 0.1:
            print("  🎯 Excellent accuracy!")
        elif error < 0.5:
            print("  ✅ Good accuracy")
        else:
            print("  ⚠️  Could be improved")
    else:
        print("  ❌ Could not calculate frequency")
    
    # Test 2: Extended measurement
    print("\n📈 Test 2: Extended measurement (10s)")
    pulse_count = optocoupler.count_optocoupler_pulses(10.0, debounce_time=0.001)
    frequency = optocoupler.calculate_frequency_from_pulses(pulse_count, 10.0)
    
    if frequency is not None:
        error = abs(frequency - 60.01)
        accuracy = (1 - error / 60.01) * 100
        print(f"  Extended frequency: {frequency:.3f} Hz")
        print(f"  Error: {error:.3f} Hz")
        print(f"  Accuracy: {accuracy:.1f}%")
        
        if error < 0.05:
            print("  🎯 Excellent accuracy!")
        elif error < 0.1:
            print("  ✅ Very good accuracy")
        elif error < 0.5:
            print("  ✅ Good accuracy")
        else:
            print("  ⚠️  Could be improved")
    else:
        print("  ❌ Could not calculate frequency")
    
    print(f"\n💡 Improvements Applied:")
    print(f"  ✅ High-precision timing (time.perf_counter)")
    print(f"  ✅ Signal debouncing (1ms)")
    
    # Cleanup
    optocoupler.cleanup()

if __name__ == "__main__":
    test_improvements()
