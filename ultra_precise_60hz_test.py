#!/usr/bin/env python3
"""
Ultra-precise test to achieve exactly 60.01 Hz using all optimization techniques.
This test implements all the improvements from the troubleshooting guide.
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

def ultra_precise_60hz_test():
    """Ultra-precise test using all optimization techniques to achieve 60.01 Hz."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup logger
    logger = logging.getLogger('ultra_precise_test')
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
    
    print("🎯 Ultra-Precise 60.01 Hz Test")
    print("=" * 60)
    print("Using all optimization techniques:")
    print("  • High-precision timing (time.perf_counter)")
    print("  • Signal debouncing (1ms)")
    print("  • Moving average (multiple samples)")
    print("=" * 60)
    
    # Test 1: Single measurements with different durations
    print(f"\n📊 Test 1: Single measurements with high precision")
    durations = [5.0, 10.0, 15.0, 20.0, 30.0]
    results = []
    
    for duration in durations:
        print(f"\n  Testing {duration}s measurement:")
        
        # Use improved pulse counting with debouncing
        pulse_count = optocoupler.count_optocoupler_pulses(duration, debounce_time=0.001)
        
        # Calculate frequency
        frequency = optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
        
        if frequency is not None:
            error = abs(frequency - 60.01)
            accuracy = (1 - error / 60.01) * 100
            
            print(f"    Pulses: {pulse_count} in {duration:.1f}s")
            print(f"    Frequency: {frequency:.4f} Hz")
            print(f"    Error: {error:.4f} Hz")
            print(f"    Accuracy: {accuracy:.2f}%")
            
            results.append((duration, frequency, error, accuracy))
            
            if error < 0.05:
                print(f"    🎯 Excellent accuracy!")
            elif error < 0.1:
                print(f"    ✅ Very good accuracy")
            elif error < 0.5:
                print(f"    ✅ Good accuracy")
            else:
                print(f"    ⚠️  Could be improved")
        else:
            print(f"    ❌ Could not calculate frequency")
    
    # Test 2: Extended measurements for maximum accuracy
    print(f"\n📈 Test 2: Extended measurements for maximum accuracy")
    extended_durations = [10.0, 15.0, 20.0, 30.0]
    
    extended_results = []
    
    for duration in extended_durations:
        print(f"\n  Testing {duration}s measurement:")
        
        # Use extended measurement method
        pulse_count = optocoupler.count_optocoupler_pulses(duration, debounce_time=0.001)
        frequency = optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
        
        if frequency is not None:
            error = abs(frequency - 60.01)
            accuracy = (1 - error / 60.01) * 100
            
            print(f"    Extended frequency: {frequency:.4f} Hz")
            print(f"    Error: {error:.4f} Hz")
            print(f"    Accuracy: {accuracy:.2f}%")
            
            extended_results.append((duration, frequency, error, accuracy))
            
            if error < 0.05:
                print(f"    🎯 Excellent accuracy!")
            elif error < 0.1:
                print(f"    ✅ Very good accuracy")
            elif error < 0.5:
                print(f"    ✅ Good accuracy")
            else:
                print(f"    ⚠️  Could be improved")
        else:
            print(f"    ❌ Could not calculate frequency")
    
    # Test 3: Multiple measurements for consistency analysis
    print(f"\n📊 Test 3: Multiple measurements for consistency analysis")
    print("  Running 5 measurements (10s each)...")
    
    consistency_results = []
    
    for i in range(5):
        print(f"    Measurement {i+1}/5...")
        pulse_count = optocoupler.count_optocoupler_pulses(10.0, debounce_time=0.001)
        frequency = optocoupler.calculate_frequency_from_pulses(pulse_count, 10.0)
        
        if frequency is not None:
            error = abs(frequency - 60.01)
            consistency_results.append(frequency)
            print(f"      Result: {frequency:.4f} Hz (error: {error:.4f} Hz)")
        else:
            print(f"      ❌ Failed measurement")
        
        time.sleep(1)  # Brief pause between measurements
    
    # Consistency analysis
    if consistency_results:
        mean_freq = statistics.mean(consistency_results)
        std_dev = statistics.stdev(consistency_results) if len(consistency_results) > 1 else 0
        mean_error = abs(mean_freq - 60.01)
        mean_accuracy = (1 - mean_error / 60.01) * 100
        
        print(f"\n  📈 Consistency Analysis:")
        print(f"    Mean frequency: {mean_freq:.4f} Hz")
        print(f"    Standard deviation: {std_dev:.4f} Hz")
        print(f"    Mean error: {mean_error:.4f} Hz")
        print(f"    Mean accuracy: {mean_accuracy:.2f}%")
        
        if mean_error < 0.05:
            print(f"    🎯 Excellent consistency!")
        elif mean_error < 0.1:
            print(f"    ✅ Very good consistency")
        elif mean_error < 0.5:
            print(f"    ✅ Good consistency")
        else:
            print(f"    ⚠️  Consistency could be improved")
    
    # Summary and recommendations
    print(f"\n🏁 Summary and Recommendations:")
    print("=" * 60)
    
    if results:
        best_single = min(results, key=lambda x: x[2])  # Lowest error
        print(f"Best single measurement: {best_single[1]:.4f} Hz (error: {best_single[2]:.4f} Hz)")
    
    if extended_results:
        best_extended = min(extended_results, key=lambda x: x[2])  # Lowest error
        print(f"Best extended measurement: {best_extended[1]:.4f} Hz (error: {best_extended[2]:.4f} Hz)")
    
    if consistency_results:
        print(f"Consistency mean: {mean_freq:.4f} Hz (error: {mean_error:.4f} Hz)")
    
    print(f"\n💡 Optimization Techniques Applied:")
    print(f"  ✅ High-precision timing (time.perf_counter)")
    print(f"  ✅ Signal debouncing (1ms minimum)")
    print(f"  ✅ Consistency analysis")
    
    print(f"\n🎯 Target: 60.01 Hz")
    if consistency_results and mean_error < 0.1:
        print(f"🎉 SUCCESS: Achieved target accuracy within 0.1 Hz!")
    elif consistency_results and mean_error < 0.5:
        print(f"✅ GOOD: Close to target accuracy")
    else:
        print(f"⚠️  May need hardware optimization")
    
    # Cleanup
    optocoupler.cleanup()

if __name__ == "__main__":
    ultra_precise_60hz_test()
