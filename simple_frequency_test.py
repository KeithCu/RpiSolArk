#!/usr/bin/env python3
"""
Simple frequency test to diagnose optocoupler issues.
"""

import sys
import os
import time
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

def simple_frequency_test():
    """Simple test to check basic optocoupler functionality."""
    print("🔧 Simple Optocoupler Frequency Test")
    print("=" * 40)
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    print("Setting up GPIO...")
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    # Test basic reading
    print(f"GPIO pin {pin} initial state: {GPIO.input(pin)}")
    
    # Quick test - 5 seconds
    print("\n📊 Quick test (5 seconds):")
    start_time = time.perf_counter()
    pulse_count = 0
    last_state = GPIO.input(pin)
    
    while time.perf_counter() - start_time < 5.0:
        current_state = GPIO.input(pin)
        if last_state == 1 and current_state == 0:
            pulse_count += 1
        last_state = current_state
    
    elapsed = time.perf_counter() - start_time
    frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
    error = abs(frequency - 60.01)
    accuracy = (1 - error / 60.01) * 100
    
    print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
    print(f"  Frequency: {frequency:.4f} Hz")
    print(f"  Error: {error:.4f} Hz")
    print(f"  Accuracy: {accuracy:.2f}%")
    
    if error < 0.1:
        print("  🎯 Excellent accuracy!")
    elif error < 0.5:
        print("  ✅ Good accuracy")
    else:
        print("  ⚠️  Could be improved")
    
    # Cleanup
    GPIO.cleanup()
    print("\n✅ Test completed")

if __name__ == "__main__":
    simple_frequency_test()

