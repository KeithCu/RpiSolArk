#!/usr/bin/env python3
"""
Precise test to get as close as possible to 60.01 Hz.
"""

import sys
import os
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

def precise_60hz_test():
    """Test to get as close as possible to 60.01 Hz."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    print("🎯 Precise 60.01 Hz Test")
    print("=" * 50)
    
    # Test different measurement durations to find the most accurate
    durations = [5.0, 10.0, 15.0, 20.0, 30.0]
    
    for duration in durations:
        print(f"\n📊 Testing {duration}s measurement:")
        
        start_time = time.time()
        pulse_count = 0
        last_state = GPIO.input(pin)
        
        while time.time() - start_time < duration:
            current_state = GPIO.input(pin)
            
            # Detect falling edge
            if last_state == 1 and current_state == 0:
                pulse_count += 1
                
            last_state = current_state
            # No sleep for maximum accuracy
        
        elapsed = time.time() - start_time
        frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
        
        error = abs(frequency - 60.01)
        accuracy = (1 - error / 60.01) * 100
        
        print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"  Frequency: {frequency:.4f} Hz")
        print(f"  Error from 60.01 Hz: {error:.4f} Hz")
        print(f"  Accuracy: {accuracy:.2f}%")
        
        # Check if this is very close to 60.01 Hz
        if error < 0.1:
            print(f"  ✅ Very close to 60.01 Hz!")
        elif error < 0.5:
            print(f"  ✅ Close to 60.01 Hz")
        else:
            print(f"  ⚠️  Somewhat off from 60.01 Hz")
        
        time.sleep(1)  # Brief pause between tests
    
    print(f"\n💡 Analysis:")
    print(f"  The most accurate measurement should be the one with the highest accuracy %")
    print(f"  Longer measurements generally give more accurate results")

if __name__ == "__main__":
    precise_60hz_test()
