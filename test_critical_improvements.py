#!/usr/bin/env python3
"""
Test the most critical optocoupler improvements individually.
This focuses on the improvements that are most likely to help.
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

def test_original_vs_precision_timing():
    """Compare original timing vs high-precision timing."""
    print("🕐 CRITICAL TEST 1: TIMING PRECISION")
    print("=" * 50)
    print("Comparing time.time() vs time.perf_counter()")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    duration = 10.0
    
    # Test 1: Original timing
    print(f"\n📊 Original method (time.time()):")
    start_time = time.time()
    pulse_count = 0
    last_state = GPIO.input(pin)
    
    while time.time() - start_time < duration:
        current_state = GPIO.input(pin)
        if last_state == 1 and current_state == 0:
            pulse_count += 1
        last_state = current_state
    
    elapsed = time.time() - start_time
    frequency = pulse_count / (elapsed * 2)
    error = abs(frequency - 60.01)
    accuracy = (1 - error / 60.01) * 100
    
    print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
    print(f"  Frequency: {frequency:.4f} Hz")
    print(f"  Error: {error:.4f} Hz")
    print(f"  Accuracy: {accuracy:.2f}%")
    
    # Test 2: High-precision timing
    print(f"\n🎯 High-precision method (time.perf_counter()):")
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
    
    print(f"\n💡 Timing improvement: {'✅ HELPFUL' if error < 0.5 else '⚠️  MINIMAL IMPACT'}")

def test_signal_quality():
    """Test signal quality and stability."""
    print("\n📊 CRITICAL TEST 2: SIGNAL QUALITY")
    print("=" * 50)
    print("Testing signal stability and quality")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    duration = 10.0
    
    # Test signal quality
    print(f"\n📊 Signal quality test:")
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
    
    print(f"  Frequency: {frequency:.4f} Hz")
    print(f"  Error: {error:.4f} Hz")
    print(f"  Accuracy: {accuracy:.2f}%")
    
    print(f"\n💡 Signal quality: {'✅ GOOD' if error < 0.5 else '⚠️  NEEDS IMPROVEMENT'}")

def test_consistency():
    """Test measurement consistency."""
    print("\n📈 CRITICAL TEST 3: CONSISTENCY")
    print("=" * 50)
    print("Testing measurement consistency over multiple readings")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    # Test consistency with multiple measurements
    print(f"\n📊 Consistency test (5 measurements, 10s each):")
    import statistics
    
    frequencies = []
    for i in range(5):
        print(f"  Measurement {i+1}/5:")
        start_time = time.perf_counter()
        pulse_count = 0
        last_state = GPIO.input(pin)
        
        while time.perf_counter() - start_time < 10.0:
            current_state = GPIO.input(pin)
            if last_state == 1 and current_state == 0:
                pulse_count += 1
            last_state = current_state
        
        elapsed = time.perf_counter() - start_time
        frequency = pulse_count / (elapsed * 2)
        frequencies.append(frequency)
        print(f"    Result: {frequency:.4f} Hz")
    
    avg_frequency = statistics.mean(frequencies)
    std_dev = statistics.stdev(frequencies) if len(frequencies) > 1 else 0
    error = abs(avg_frequency - 60.01)
    accuracy = (1 - error / 60.01) * 100
    
    print(f"\n  Consistency analysis:")
    print(f"    Average frequency: {avg_frequency:.4f} Hz")
    print(f"    Standard deviation: {std_dev:.4f} Hz")
    print(f"    Error: {error:.4f} Hz")
    print(f"    Accuracy: {accuracy:.2f}%")
    
    print(f"\n💡 Consistency: {'✅ GOOD' if std_dev < 0.5 else '⚠️  VARIABLE'}")

def main():
    """Run critical improvement tests."""
    print("🎯 CRITICAL OPTCOUPLER IMPROVEMENT TESTING")
    print("=" * 60)
    print("Testing the most important improvements individually")
    print("Target: 60.01 Hz")
    print("=" * 60)
    
    # Test 1: Timing precision
    test_original_vs_precision_timing()
    
    # Test 2: Signal quality
    test_signal_quality()
    
    # Test 3: Consistency
    test_consistency()
    
    print(f"\n🏁 Critical testing completed!")
    print(f"💡 Look for tests marked as 'HELPFUL' - those are worth keeping")
    print(f"💡 Tests marked as 'MINIMAL IMPACT' might not be necessary for your setup")

if __name__ == "__main__":
    main()
