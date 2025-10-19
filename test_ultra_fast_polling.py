#!/usr/bin/env python3
"""
Test ultra-fast polling rates to get closer to 60Hz.
"""

import sys
import os
import time
import statistics

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

def test_ultra_fast_polling():
    """Test ultra-fast polling to get closer to 60Hz."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    print("🔍 Testing ultra-fast polling rates")
    print("=" * 50)
    
    # Test different ultra-fast intervals
    intervals = [
        0.00005,  # 0.05ms
        0.0001,   # 0.1ms  
        0.0002,   # 0.2ms
        0.0005,   # 0.5ms
    ]
    
    duration = 3.0  # 3 seconds for faster testing
    
    for interval in intervals:
        print(f"\nTesting {interval*1000:.2f}ms polling:")
        
        start_time = time.time()
        pulse_count = 0
        last_state = GPIO.input(pin)
        
        while time.time() - start_time < duration:
            current_state = GPIO.input(pin)
            
            # Detect falling edge
            if last_state == 1 and current_state == 0:
                pulse_count += 1
                
            last_state = current_state
            time.sleep(interval)
        
        elapsed = time.time() - start_time
        frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
        
        print(f"  Pulses: {pulse_count} in {elapsed:.2f}s")
        print(f"  Frequency: {frequency:.2f} Hz")
        print(f"  Error from 60Hz: {abs(frequency - 60):.2f} Hz")
        
        time.sleep(0.5)  # Brief pause

def test_no_sleep_polling():
    """Test polling with no sleep to see maximum possible frequency."""
    if not GPIO_AVAILABLE:
        return
    
    print(f"\n🚀 Testing NO SLEEP polling (maximum speed):")
    print("-" * 50)
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    duration = 2.0
    start_time = time.time()
    pulse_count = 0
    last_state = GPIO.input(pin)
    
    while time.time() - start_time < duration:
        current_state = GPIO.input(pin)
        
        # Detect falling edge
        if last_state == 1 and current_state == 0:
            pulse_count += 1
            
        last_state = current_state
        # No sleep - maximum speed
    
    elapsed = time.time() - start_time
    frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
    
    print(f"  Pulses: {pulse_count} in {elapsed:.2f}s")
    print(f"  Frequency: {frequency:.2f} Hz")
    print(f"  Error from 60Hz: {abs(frequency - 60):.2f} Hz")

if __name__ == "__main__":
    test_ultra_fast_polling()
    test_no_sleep_polling()
