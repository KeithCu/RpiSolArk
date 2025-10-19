#!/usr/bin/env python3
"""
Precise test to get as close as possible to 60.01 Hz using improved methods.
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

def precise_60hz_test():
    """Test to get as close as possible to 60.01 Hz using improved methods."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup logger
    logger = logging.getLogger('precise_test')
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
    
    print("🎯 Enhanced Precise 60.01 Hz Test")
    print("=" * 50)
    
    # Test different measurement durations with improved methods
    durations = [5.0, 10.0, 15.0, 20.0, 30.0]
    
    for duration in durations:
        print(f"\n📊 Testing {duration}s measurement with high precision:")
        
        # Use improved pulse counting with debouncing
        pulse_count = optocoupler.count_optocoupler_pulses(duration, debounce_time=0.001)
        
        # Calculate frequency
        frequency = optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
        
        if frequency is not None:
            error = abs(frequency - 60.01)
            accuracy = (1 - error / 60.01) * 100
            
            print(f"  Pulses: {pulse_count} in {duration:.1f}s")
            print(f"  Frequency: {frequency:.4f} Hz")
            print(f"  Error from 60.01 Hz: {error:.4f} Hz")
            print(f"  Accuracy: {accuracy:.2f}%")
            
            # Check if this is very close to 60.01 Hz
            if error < 0.05:
                print(f"  🎯 Excellent - very close to 60.01 Hz!")
            elif error < 0.1:
                print(f"  ✅ Very close to 60.01 Hz!")
            elif error < 0.5:
                print(f"  ✅ Close to 60.01 Hz")
            else:
                print(f"  ⚠️  Somewhat off from 60.01 Hz")
        else:
            print(f"  ❌ Could not calculate frequency")
        
        time.sleep(1)  # Brief pause between tests
    
    # Test averaged measurement for best accuracy
    print(f"\n📈 Testing averaged measurement (10s, 5 samples):")
    avg_frequency = optocoupler.averaged_frequency_measurement(10.0, 5)
    
    if avg_frequency is not None:
        error = abs(avg_frequency - 60.01)
        accuracy = (1 - error / 60.01) * 100
        
        print(f"  Averaged frequency: {avg_frequency:.4f} Hz")
        print(f"  Error from 60.01 Hz: {error:.4f} Hz")
        print(f"  Accuracy: {accuracy:.2f}%")
        
        if error < 0.05:
            print(f"  🎯 Excellent accuracy - very close to 60.01 Hz!")
        elif error < 0.1:
            print(f"  ✅ Very good accuracy")
        elif error < 0.5:
            print(f"  ✅ Good accuracy")
        else:
            print(f"  ⚠️  Could be improved")
    
    print(f"\n💡 Analysis:")
    print(f"  The averaged measurement should provide the most accurate result")
    print(f"  Calibration factor helps compensate for systematic errors")
    print(f"  High-precision timing and debouncing reduce measurement noise")
    
    # Cleanup
    optocoupler.cleanup()

if __name__ == "__main__":
    precise_60hz_test()
