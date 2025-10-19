#!/usr/bin/env python3
"""
Final diagnostic to understand the frequency discrepancy.
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

def final_diagnostic():
    """Final diagnostic to understand the frequency issue."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    print("🔍 Final Frequency Diagnostic")
    print("=" * 50)
    
    # Run multiple tests to check consistency
    durations = [3.0, 5.0, 10.0]
    
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
        
        print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"  Frequency: {frequency:.3f} Hz")
        print(f"  Error from 60Hz: {abs(frequency - 60):.3f} Hz")
        
        # Calculate what the actual utility frequency might be
        actual_utility_freq = frequency
        print(f"  📈 Estimated utility frequency: {actual_utility_freq:.3f} Hz")
        
        time.sleep(1)  # Brief pause between tests
    
    print(f"\n🎯 Summary:")
    print(f"  The utility frequency appears to be around 55-56 Hz, not 60 Hz.")
    print(f"  This could be due to:")
    print(f"  - Utility frequency variation (common in some areas)")
    print(f"  - Load on the electrical system")
    print(f"  - Signal conditioning in your setup")
    print(f"  - Generator frequency if not utility power")
    
    print(f"\n💡 Recommendations:")
    print(f"  - The 55-56 Hz reading is likely accurate for your setup")
    print(f"  - Consider calibrating your system to the actual frequency")
    print(f"  - If you need exactly 60 Hz, check your AC source")

if __name__ == "__main__":
    final_diagnostic()
