#!/usr/bin/env python3
"""
Precise frequency measurement to understand the 60Hz issue.
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

def precise_frequency_measurement():
    """Make precise frequency measurements to understand the 60Hz issue."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    print("🔍 Precise Frequency Measurement")
    print("=" * 50)
    
    # Test 1: No sleep polling for maximum accuracy
    print("Test 1: No sleep polling (maximum speed)")
    duration = 5.0
    start_time = time.time()
    pulse_count = 0
    last_state = GPIO.input(pin)
    
    while time.time() - start_time < duration:
        current_state = GPIO.input(pin)
        
        # Detect falling edge
        if last_state == 1 and current_state == 0:
            pulse_count += 1
            
        last_state = current_state
        # No sleep for maximum speed
    
    elapsed = time.time() - start_time
    frequency_2_pulses = pulse_count / (elapsed * 2)  # 2 pulses per cycle
    frequency_1_pulse = pulse_count / elapsed        # 1 pulse per cycle
    
    print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
    print(f"  Frequency (2 pulses/cycle): {frequency_2_pulses:.3f} Hz")
    print(f"  Frequency (1 pulse/cycle): {frequency_1_pulse:.3f} Hz")
    print(f"  Error from 60Hz (2 pulses): {abs(frequency_2_pulses - 60):.3f} Hz")
    print(f"  Error from 60Hz (1 pulse): {abs(frequency_1_pulse - 60):.3f} Hz")
    
    # Test 2: Calculate what the actual AC frequency should be
    print(f"\nTest 2: Analysis")
    print(f"  If AC is exactly 60Hz:")
    print(f"    - With 2 pulses/cycle: {60 * 2 * elapsed:.0f} pulses expected")
    print(f"    - With 1 pulse/cycle: {60 * elapsed:.0f} pulses expected")
    print(f"  Actual pulses: {pulse_count}")
    
    # Test 3: Check if there's a systematic error
    print(f"\nTest 3: Systematic Error Analysis")
    expected_60hz_2p = 60 * 2 * elapsed
    expected_60hz_1p = 60 * elapsed
    
    error_2p = abs(pulse_count - expected_60hz_2p)
    error_1p = abs(pulse_count - expected_60hz_1p)
    
    print(f"  Error with 2 pulses/cycle: {error_2p:.1f} pulses ({error_2p/expected_60hz_2p*100:.1f}%)")
    print(f"  Error with 1 pulse/cycle: {error_1p:.1f} pulses ({error_1p/expected_60hz_1p*100:.1f}%)")
    
    # Determine which is more likely
    if error_2p < error_1p:
        print(f"  ✅ 2 pulses/cycle is more accurate")
        print(f"  📊 Actual AC frequency: {pulse_count / (elapsed * 2):.3f} Hz")
    else:
        print(f"  ✅ 1 pulse/cycle is more accurate")
        print(f"  📊 Actual AC frequency: {pulse_count / elapsed:.3f} Hz")

if __name__ == "__main__":
    precise_frequency_measurement()
