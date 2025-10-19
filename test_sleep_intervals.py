#!/usr/bin/env python3
"""
Test different sleep intervals to find optimal polling rate.
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

def test_sleep_interval(sleep_interval, duration=2.0):
    """Test pulse detection with a specific sleep interval."""
    if not GPIO_AVAILABLE:
        return None
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    print(f"Testing sleep interval: {sleep_interval*1000:.1f}ms")
    
    start_time = time.time()
    pulse_count = 0
    last_state = GPIO.input(pin)
    
    while time.time() - start_time < duration:
        current_state = GPIO.input(pin)
        
        # Detect falling edge
        if last_state == 1 and current_state == 0:
            pulse_count += 1
            
        last_state = current_state
        time.sleep(sleep_interval)
    
    elapsed = time.time() - start_time
    frequency = pulse_count / (elapsed * 2)  # Assuming 2 pulses per cycle
    
    print(f"  Pulses: {pulse_count} in {elapsed:.2f}s")
    print(f"  Frequency: {frequency:.2f} Hz")
    
    return pulse_count, frequency

def test_all_intervals():
    """Test different sleep intervals to find optimal rate."""
    print("🔍 Testing different sleep intervals for pulse detection")
    print("=" * 60)
    
    # Test different sleep intervals
    sleep_intervals = [
        0.0001,  # 0.1ms
        0.0005,  # 0.5ms
        0.001,   # 1ms
        0.002,   # 2ms
        0.005,   # 5ms
        0.01,    # 10ms
        0.02,    # 20ms
    ]
    
    results = []
    
    for interval in sleep_intervals:
        try:
            pulse_count, frequency = test_sleep_interval(interval, duration=2.0)
            if pulse_count is not None:
                results.append({
                    'interval': interval,
                    'pulse_count': pulse_count,
                    'frequency': frequency
                })
            time.sleep(0.5)  # Brief pause between tests
        except Exception as e:
            print(f"  ❌ Error with {interval*1000:.1f}ms: {e}")
    
    print(f"\n📊 Results Summary:")
    print(f"{'Interval (ms)':<12} {'Pulses':<8} {'Frequency (Hz)':<15} {'Quality'}")
    print("-" * 50)
    
    for result in results:
        interval_ms = result['interval'] * 1000
        pulses = result['pulse_count']
        freq = result['frequency']
        
        # Determine quality based on consistency with 60Hz
        if 55 <= freq <= 65:
            quality = "✅ Good"
        elif 45 <= freq <= 75:
            quality = "⚠️  OK"
        else:
            quality = "❌ Poor"
            
        print(f"{interval_ms:<12.1f} {pulses:<8} {freq:<15.2f} {quality}")
    
    # Find best interval
    if results:
        # Look for frequency closest to 60Hz
        best_result = min(results, key=lambda x: abs(x['frequency'] - 60))
        print(f"\n🏆 Best interval: {best_result['interval']*1000:.1f}ms")
        print(f"   Frequency: {best_result['frequency']:.2f} Hz")

if __name__ == "__main__":
    test_all_intervals()
