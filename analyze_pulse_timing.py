#!/usr/bin/env python3
"""
Analyze pulse timing to determine actual AC frequency.
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

def analyze_pulse_timing():
    """Analyze the timing between pulses to determine actual frequency."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    print("🔍 Analyzing pulse timing to determine actual AC frequency")
    print("=" * 60)
    
    # Collect timing data for 5 seconds
    duration = 5.0
    print(f"Collecting pulse timing data for {duration} seconds...")
    
    start_time = time.time()
    pulse_times = []
    last_state = GPIO.input(pin)
    
    while time.time() - start_time < duration:
        current_state = GPIO.input(pin)
        
        # Detect falling edge
        if last_state == 1 and current_state == 0:
            pulse_times.append(time.time())
            
        last_state = current_state
        time.sleep(0.001)  # 1ms polling
    
    elapsed = time.time() - start_time
    print(f"Collected {len(pulse_times)} pulses in {elapsed:.2f}s")
    
    if len(pulse_times) < 2:
        print("❌ Not enough pulses detected")
        return
    
    # Calculate intervals between pulses
    intervals = []
    for i in range(1, len(pulse_times)):
        interval = pulse_times[i] - pulse_times[i-1]
        intervals.append(interval)
    
    # Calculate statistics
    avg_interval = statistics.mean(intervals)
    median_interval = statistics.median(intervals)
    min_interval = min(intervals)
    max_interval = max(intervals)
    
    # Calculate frequency from average interval
    frequency_from_avg = 1.0 / avg_interval
    frequency_from_median = 1.0 / median_interval
    
    print(f"\n📊 Pulse Timing Analysis:")
    print(f"Total pulses: {len(pulse_times)}")
    print(f"Average interval: {avg_interval:.4f}s")
    print(f"Median interval: {median_interval:.4f}s")
    print(f"Min interval: {min_interval:.4f}s")
    print(f"Max interval: {max_interval:.4f}s")
    
    print(f"\n📈 Frequency Analysis:")
    print(f"Frequency from average interval: {frequency_from_avg:.2f} Hz")
    print(f"Frequency from median interval: {frequency_from_median:.2f} Hz")
    
    # Check if this matches expected AC frequencies
    print(f"\n🔍 Analysis:")
    if 55 <= frequency_from_avg <= 65:
        print("✅ This looks like 60 Hz AC power")
    elif 45 <= frequency_from_avg <= 55:
        print("✅ This looks like 50 Hz AC power")
    else:
        print(f"⚠️  Frequency {frequency_from_avg:.2f} Hz doesn't match typical AC frequencies")
        print("   This might be:")
        print("   - A generator running at non-standard frequency")
        print("   - Signal conditioning affecting the frequency")
        print("   - A different type of AC source")
    
    # Show first few intervals for debugging
    print(f"\n🔍 First 10 intervals:")
    for i, interval in enumerate(intervals[:10]):
        print(f"  {i+1}: {interval:.4f}s ({1.0/interval:.2f} Hz)")

if __name__ == "__main__":
    analyze_pulse_timing()
