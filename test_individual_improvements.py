#!/usr/bin/env python3
"""
Test each optocoupler improvement individually to see which ones are necessary.
This will help determine which optimizations actually improve accuracy.
"""

import sys
import os
import time
import logging
import statistics

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from optocoupler import OptocouplerManager

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

def test_baseline():
    """Test baseline performance without any improvements."""
    print("🔧 Test 1: BASELINE (Original Method)")
    print("=" * 50)
    print("Using: time.time(), no debouncing, no calibration")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return None
    
    # Setup GPIO directly (bypass optocoupler manager)
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    results = []
    
    for duration in [5.0, 10.0]:
        print(f"\n  Testing {duration}s measurement:")
        
        # Original method: time.time(), no debouncing
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
        
        print(f"    Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"    Frequency: {frequency:.4f} Hz")
        print(f"    Error: {error:.4f} Hz")
        print(f"    Accuracy: {accuracy:.2f}%")
        
        results.append((duration, frequency, error, accuracy))
    
    return results

def test_precision_timing():
    """Test improvement 1: High-precision timing with time.perf_counter()."""
    print("\n🎯 Test 2: HIGH-PRECISION TIMING")
    print("=" * 50)
    print("Using: time.perf_counter(), no debouncing, no calibration")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return None
    
    # Setup GPIO directly
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    results = []
    
    for duration in [5.0, 10.0]:
        print(f"\n  Testing {duration}s measurement:")
        
        # Improved method: time.perf_counter(), no debouncing
        start_time = time.perf_counter()
        pulse_count = 0
        last_state = GPIO.input(pin)
        
        while time.perf_counter() - start_time < duration:
            current_state = GPIO.input(pin)
            
            # Detect falling edge
            if last_state == 1 and current_state == 0:
                pulse_count += 1
                
            last_state = current_state
        
        elapsed = time.perf_counter() - start_time
        frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
        
        error = abs(frequency - 60.01)
        accuracy = (1 - error / 60.01) * 100
        
        print(f"    Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"    Frequency: {frequency:.4f} Hz")
        print(f"    Error: {error:.4f} Hz")
        print(f"    Accuracy: {accuracy:.2f}%")
        
        results.append((duration, frequency, error, accuracy))
    
    return results

def test_debouncing():
    """Test improvement 2: Signal debouncing."""
    print("\n🔧 Test 3: SIGNAL DEBOUNCING")
    print("=" * 50)
    print("Using: time.perf_counter() + 1ms debouncing, no calibration")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return None
    
    # Setup GPIO directly
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    results = []
    
    for duration in [5.0, 10.0]:
        print(f"\n  Testing {duration}s measurement:")
        
        # Improved method: time.perf_counter() + debouncing
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
        frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
        
        error = abs(frequency - 60.01)
        accuracy = (1 - error / 60.01) * 100
        
        print(f"    Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"    Frequency: {frequency:.4f} Hz")
        print(f"    Error: {error:.4f} Hz")
        print(f"    Accuracy: {accuracy:.2f}%")
        
        results.append((duration, frequency, error, accuracy))
    
    return results

def test_signal_quality():
    """Test improvement 3: Signal quality assessment."""
    print("\n📊 Test 4: SIGNAL QUALITY ASSESSMENT")
    print("=" * 50)
    print("Using: time.perf_counter() + debouncing")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return None
    
    # Setup GPIO directly
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    results = []
    
    for duration in [5.0, 10.0]:
        print(f"\n  Testing {duration}s measurement:")
        
        # Improved method: time.perf_counter() + debouncing
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
        frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
        
        error = abs(frequency - 60.01)
        accuracy = (1 - error / 60.01) * 100
        
        print(f"    Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"    Frequency: {frequency:.4f} Hz")
        print(f"    Error: {error:.4f} Hz")
        print(f"    Accuracy: {accuracy:.2f}%")
        
        results.append((duration, frequency, error, accuracy))
    
    return results

def test_consistency():
    """Test improvement 4: Consistency analysis."""
    print("\n📈 Test 5: CONSISTENCY ANALYSIS")
    print("=" * 50)
    print("Using: time.perf_counter() + debouncing")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return None
    
    # Setup GPIO directly
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    # Test consistency
    duration = 10.0
    samples = 5
    
    print(f"\n  Testing {duration}s measurement, {samples} times for consistency:")
    
    frequencies = []
    
    for i in range(samples):
        print(f"    Measurement {i+1}/{samples}:")
        
        # Single measurement with improvements
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
        frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
        
        frequencies.append(frequency)
        print(f"      Measurement {i+1}: {frequency:.4f} Hz")
    
    # Calculate statistics
    avg_frequency = statistics.mean(frequencies)
    std_dev = statistics.stdev(frequencies) if len(frequencies) > 1 else 0
    error = abs(avg_frequency - 60.01)
    accuracy = (1 - error / 60.01) * 100
    
    print(f"\n  Results:")
    print(f"    Individual measurements: {[f'{f:.4f}' for f in frequencies]}")
    print(f"    Average frequency: {avg_frequency:.4f} Hz")
    print(f"    Standard deviation: {std_dev:.4f} Hz")
    print(f"    Error: {error:.4f} Hz")
    print(f"    Accuracy: {accuracy:.2f}%")
    
    return [(duration, avg_frequency, error, accuracy)]

def compare_results(all_results):
    """Compare results from all tests."""
    print("\n📊 COMPARISON OF ALL IMPROVEMENTS")
    print("=" * 60)
    
    test_names = [
        "Baseline (Original)",
        "High-Precision Timing",
        "Signal Debouncing", 
        "Signal Quality",
        "Consistency Analysis"
    ]
    
    print(f"{'Test':<25} {'10s Error (Hz)':<15} {'10s Accuracy (%)':<15}")
    print("-" * 60)
    
    for i, (name, results) in enumerate(zip(test_names, all_results)):
        if results and len(results) >= 2:
            # Use 10s measurement result
            duration, frequency, error, accuracy = results[1]
            print(f"{name:<25} {error:<15.4f} {accuracy:<15.2f}")
        else:
            print(f"{name:<25} {'N/A':<15} {'N/A':<15}")
    
    print("\n💡 RECOMMENDATIONS:")
    print("  • Look for the test with the LOWEST error and HIGHEST accuracy")
    print("  • If baseline is already good, some improvements may not be necessary")
    print("  • If moving average shows much better results, it's worth using")
    print("  • If calibration makes a big difference, your system needs it")

def main():
    """Run all individual improvement tests."""
    print("🧪 INDIVIDUAL OPTCOUPLER IMPROVEMENT TESTING")
    print("=" * 60)
    print("Testing each improvement separately to see which ones help")
    print("Target: 60.01 Hz")
    print("=" * 60)
    
    all_results = []
    
    # Test 1: Baseline
    baseline_results = test_baseline()
    all_results.append(baseline_results)
    
    # Test 2: Precision timing
    timing_results = test_precision_timing()
    all_results.append(timing_results)
    
    # Test 3: Debouncing
    debouncing_results = test_debouncing()
    all_results.append(debouncing_results)
    
    # Test 4: Signal quality
    signal_results = test_signal_quality()
    all_results.append(signal_results)
    
    # Test 5: Consistency analysis
    consistency_results = test_consistency()
    all_results.append(consistency_results)
    
    # Compare all results
    compare_results(all_results)
    
    print(f"\n🏁 Testing completed!")
    print(f"Check the results above to see which improvements actually help your setup.")

if __name__ == "__main__":
    main()
