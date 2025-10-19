#!/usr/bin/env python3
"""
Test the specific impact of debouncing on optocoupler measurements.
This will show if your setup has noise issues that debouncing can fix.
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

def test_debouncing_impact():
    """Test the impact of debouncing on measurement accuracy."""
    print("🔧 DEBOUNCING IMPACT TEST")
    print("=" * 50)
    print("Testing if debouncing helps with signal noise")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    duration = 10.0
    
    # Test 1: Without debouncing
    print(f"\n📊 Without debouncing:")
    start_time = time.perf_counter()
    pulse_count = 0
    last_state = GPIO.input(pin)
    
    while time.perf_counter() - start_time < duration:
        current_state = GPIO.input(pin)
        if last_state == 1 and current_state == 0:
            pulse_count += 1
        last_state = current_state
    
    elapsed = time.perf_counter() - start_time
    frequency = pulse_count / (elapsed * 2)
    error = abs(frequency - 60.01)
    accuracy = (1 - error / 60.01) * 100
    
    print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
    print(f"  Frequency: {frequency:.4f} Hz")
    print(f"  Error: {error:.4f} Hz")
    print(f"  Accuracy: {accuracy:.2f}%")
    
    # Test 2: With debouncing
    print(f"\n🎯 With 1ms debouncing:")
    start_time = time.perf_counter()
    pulse_count = 0
    last_state = GPIO.input(pin)
    last_change_time = start_time
    debounce_time = 0.001  # 1ms debouncing
    
    while time.perf_counter() - start_time < duration:
        current_state = GPIO.input(pin)
        current_time = time.perf_counter()
        
        # Detect falling edge with debouncing
        if current_state != last_state:
            if current_time - last_change_time > debounce_time:
                if last_state == 1 and current_state == 0:
                    pulse_count += 1
                last_change_time = current_time
                last_state = current_state
    
    elapsed = time.perf_counter() - start_time
    frequency = pulse_count / (elapsed * 2)
    error = abs(frequency - 60.01)
    accuracy = (1 - error / 60.01) * 100
    
    print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
    print(f"  Frequency: {frequency:.4f} Hz")
    print(f"  Error: {error:.4f} Hz")
    print(f"  Accuracy: {accuracy:.2f}%")
    
    # Test 3: With longer debouncing
    print(f"\n🔧 With 5ms debouncing:")
    start_time = time.perf_counter()
    pulse_count = 0
    last_state = GPIO.input(pin)
    last_change_time = start_time
    debounce_time = 0.005  # 5ms debouncing
    
    while time.perf_counter() - start_time < duration:
        current_state = GPIO.input(pin)
        current_time = time.perf_counter()
        
        # Detect falling edge with debouncing
        if current_state != last_state:
            if current_time - last_change_time > debounce_time:
                if last_state == 1 and current_state == 0:
                    pulse_count += 1
                last_change_time = current_time
                last_state = current_state
    
    elapsed = time.perf_counter() - start_time
    frequency = pulse_count / (elapsed * 2)
    error = abs(frequency - 60.01)
    accuracy = (1 - error / 60.01) * 100
    
    print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
    print(f"  Frequency: {frequency:.4f} Hz")
    print(f"  Error: {error:.4f} Hz")
    print(f"  Accuracy: {accuracy:.2f}%")
    
    print(f"\n💡 Debouncing analysis:")
    print(f"  • If debouncing improves accuracy significantly, your setup has noise issues")
    print(f"  • If debouncing makes no difference, your signal is already clean")
    print(f"  • Longer debouncing (5ms) may help with very noisy signals")

def test_signal_stability():
    """Test signal stability over time."""
    print(f"\n📈 SIGNAL STABILITY TEST")
    print("=" * 50)
    print("Testing how stable your signal is over multiple measurements")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    # Take 5 measurements
    frequencies = []
    
    for i in range(5):
        print(f"  Measurement {i+1}/5:")
        
        start_time = time.perf_counter()
        pulse_count = 0
        last_state = GPIO.input(pin)
        
        while time.perf_counter() - start_time < 5.0:  # 5s per measurement
            current_state = GPIO.input(pin)
            if last_state == 1 and current_state == 0:
                pulse_count += 1
            last_state = current_state
        
        elapsed = time.perf_counter() - start_time
        frequency = pulse_count / (elapsed * 2)
        frequencies.append(frequency)
        
        print(f"    Frequency: {frequency:.4f} Hz")
    
    # Calculate statistics
    import statistics
    mean_freq = statistics.mean(frequencies)
    std_dev = statistics.stdev(frequencies) if len(frequencies) > 1 else 0
    max_freq = max(frequencies)
    min_freq = min(frequencies)
    variation = max_freq - min_freq
    
    print(f"\n  Stability analysis:")
    print(f"    Mean frequency: {mean_freq:.4f} Hz")
    print(f"    Standard deviation: {std_dev:.4f} Hz")
    print(f"    Range: {min_freq:.4f} - {max_freq:.4f} Hz")
    print(f"    Total variation: {variation:.4f} Hz")
    
    print(f"\n💡 Stability analysis:")
    if std_dev < 0.1:
        print(f"  ✅ Very stable signal - averaging may not help much")
    elif std_dev < 0.5:
        print(f"  ✅ Reasonably stable - averaging might help slightly")
    else:
        print(f"  ⚠️  Unstable signal - averaging will definitely help")

def main():
    """Run debouncing impact tests."""
    print("🔧 DEBOUNCING AND SIGNAL STABILITY TESTING")
    print("=" * 60)
    print("Testing if debouncing and averaging help your specific setup")
    print("=" * 60)
    
    # Test debouncing impact
    test_debouncing_impact()
    
    # Test signal stability
    test_signal_stability()
    
    print(f"\n🏁 Testing completed!")
    print(f"💡 Use these results to decide which improvements are worth implementing")

if __name__ == "__main__":
    main()
