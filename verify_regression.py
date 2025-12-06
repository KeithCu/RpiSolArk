#!/usr/bin/env python3
"""
Verification script for regression-based frequency calculation.
Tests the accuracy of linear regression method vs first/last timestamp method
using synthetic data with known jitter.
"""

import numpy as np
import time
from typing import List, Tuple, Optional


def calculate_frequency_first_last(timestamps_ns: List[int], pulses_per_cycle: int = 2) -> Optional[float]:
    """
    Calculate frequency using first and last timestamps (current method).
    
    Args:
        timestamps_ns: List of timestamps in nanoseconds
        pulses_per_cycle: Number of pulses per AC cycle (default: 2)
    
    Returns:
        Frequency in Hz, or None if invalid
    """
    if len(timestamps_ns) < 2:
        return None
    
    t_first = timestamps_ns[0]
    t_last = timestamps_ns[-1]
    duration_ns = t_last - t_first
    num_intervals = len(timestamps_ns) - 1
    
    if duration_ns <= 0 or num_intervals <= 0:
        return None
    
    # Calculate frequency: Intervals / Duration / pulses_per_cycle
    frequency = (num_intervals * 1e9) / (duration_ns * pulses_per_cycle)
    
    # Sanity check
    if 40 <= frequency <= 80:
        return frequency
    return None


def calculate_frequency_regression(timestamps_ns: List[int], pulses_per_cycle: int = 2) -> Optional[float]:
    """
    Calculate frequency using linear regression on all timestamps (new method).
    
    Args:
        timestamps_ns: List of timestamps in nanoseconds
        pulses_per_cycle: Number of pulses per AC cycle (default: 2)
    
    Returns:
        Frequency in Hz, or None if invalid
    """
    if len(timestamps_ns) < 2:
        return None
    
    # Convert timestamps to relative time in seconds (starting from 0)
    t_first = timestamps_ns[0]
    times_sec = [(ts - t_first) / 1e9 for ts in timestamps_ns]
    
    # Create pulse indices (0, 1, 2, ..., n-1)
    pulse_indices = np.arange(len(timestamps_ns))
    
    # Perform linear regression: time = slope * index + intercept
    # We want to find the slope (seconds per pulse)
    try:
        slope, intercept = np.polyfit(pulse_indices, times_sec, 1)
    except Exception:
        return None
    
    # Slope represents seconds per pulse interval
    # Frequency = 1 / (slope * pulses_per_cycle)
    if slope <= 0:
        return None
    
    frequency = 1.0 / (slope * pulses_per_cycle)
    
    # Sanity check
    if 40 <= frequency <= 80:
        return frequency
    return None


def generate_synthetic_timestamps(
    base_frequency: float,
    duration_sec: float,
    pulses_per_cycle: int = 2,
    jitter_std_ns: float = 0.0,
    sample_rate_hz: float = 60.0
) -> List[int]:
    """
    Generate synthetic pulse timestamps with optional jitter.
    
    Args:
        base_frequency: Base AC frequency in Hz
        duration_sec: Measurement duration in seconds
        pulses_per_cycle: Number of pulses per AC cycle
        jitter_std_ns: Standard deviation of jitter in nanoseconds (0 = perfect)
        sample_rate_hz: AC frequency for pulse generation
    
    Returns:
        List of timestamps in nanoseconds
    """
    # Calculate expected pulse interval
    pulse_interval_sec = 1.0 / (base_frequency * pulses_per_cycle)
    pulse_interval_ns = pulse_interval_sec * 1e9
    
    # Generate timestamps
    timestamps = []
    current_time_ns = 0
    
    # Generate pulses for the duration
    while current_time_ns < duration_sec * 1e9:
        timestamps.append(int(current_time_ns))
        
        # Add jitter if specified
        if jitter_std_ns > 0:
            jitter = np.random.normal(0, jitter_std_ns)
        else:
            jitter = 0
        
        # Move to next pulse
        current_time_ns += pulse_interval_ns + jitter
    
    return timestamps


def test_accuracy_comparison():
    """Test and compare accuracy of both methods."""
    print("=" * 80)
    print("Frequency Calculation Accuracy Comparison")
    print("=" * 80)
    print()
    
    test_cases = [
        {
            "name": "Perfect 60.0 Hz (no jitter)",
            "base_freq": 60.0,
            "duration": 2.0,
            "jitter_ns": 0.0
        },
        {
            "name": "60.0 Hz with small jitter (100ns std)",
            "base_freq": 60.0,
            "duration": 2.0,
            "jitter_ns": 100.0
        },
        {
            "name": "60.0 Hz with moderate jitter (1000ns std)",
            "base_freq": 60.0,
            "duration": 2.0,
            "jitter_ns": 1000.0
        },
        {
            "name": "60.0 Hz with large jitter (10000ns std)",
            "base_freq": 60.0,
            "duration": 2.0,
            "jitter_ns": 10000.0
        },
        {
            "name": "59.5 Hz (generator-like) with jitter (5000ns std)",
            "base_freq": 59.5,
            "duration": 2.0,
            "jitter_ns": 5000.0
        },
        {
            "name": "60.1 Hz (slightly high) with jitter (2000ns std)",
            "base_freq": 60.1,
            "duration": 2.0,
            "jitter_ns": 2000.0
        }
    ]
    
    results = []
    
    for test_case in test_cases:
        print(f"\nTest: {test_case['name']}")
        print("-" * 80)
        
        # Generate timestamps multiple times and average results
        first_last_errors = []
        regression_errors = []
        
        num_runs = 10 if test_case['jitter_ns'] > 0 else 1
        
        for run in range(num_runs):
            timestamps = generate_synthetic_timestamps(
                base_frequency=test_case['base_freq'],
                duration_sec=test_case['duration'],
                pulses_per_cycle=2,
                jitter_std_ns=test_case['jitter_ns']
            )
            
            # Calculate frequencies
            freq_first_last = calculate_frequency_first_last(timestamps, pulses_per_cycle=2)
            freq_regression = calculate_frequency_regression(timestamps, pulses_per_cycle=2)
            
            if freq_first_last is not None:
                error_first_last = abs(freq_first_last - test_case['base_freq'])
                first_last_errors.append(error_first_last)
            
            if freq_regression is not None:
                error_regression = abs(freq_regression - test_case['base_freq'])
                regression_errors.append(error_regression)
        
        # Calculate statistics
        if first_last_errors:
            avg_error_first_last = np.mean(first_last_errors)
            max_error_first_last = np.max(first_last_errors)
        else:
            avg_error_first_last = None
            max_error_first_last = None
        
        if regression_errors:
            avg_error_regression = np.mean(regression_errors)
            max_error_regression = np.max(regression_errors)
        else:
            avg_error_regression = None
            max_error_regression = None
        
        # Print results
        print(f"  Base frequency: {test_case['base_freq']:.3f} Hz")
        print(f"  Pulses generated: {len(timestamps)}")
        print(f"  Duration: {test_case['duration']:.2f} s")
        print(f"  Jitter: {test_case['jitter_ns']:.1f} ns std")
        print()
        
        if avg_error_first_last is not None:
            print(f"  First/Last Method:")
            print(f"    Average error: {avg_error_first_last:.6f} Hz")
            print(f"    Max error: {max_error_first_last:.6f} Hz")
        else:
            print(f"  First/Last Method: Failed")
        
        if avg_error_regression is not None:
            print(f"  Regression Method:")
            print(f"    Average error: {avg_error_regression:.6f} Hz")
            print(f"    Max error: {max_error_regression:.6f} Hz")
        else:
            print(f"  Regression Method: Failed")
        
        # Compare
        if avg_error_first_last is not None and avg_error_regression is not None:
            improvement = ((avg_error_first_last - avg_error_regression) / avg_error_first_last) * 100
            print()
            if improvement > 0:
                print(f"  ✅ Regression method is {improvement:.1f}% more accurate on average")
            elif improvement < 0:
                print(f"  ⚠️  First/Last method is {abs(improvement):.1f}% more accurate on average")
            else:
                print(f"  ➡️  Methods are equally accurate")
        
        results.append({
            'test': test_case['name'],
            'base_freq': test_case['base_freq'],
            'first_last_avg_error': avg_error_first_last,
            'regression_avg_error': avg_error_regression,
            'improvement_pct': improvement if (avg_error_first_last and avg_error_regression) else None
        })
    
    # Summary
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    
    improvements = [r['improvement_pct'] for r in results if r['improvement_pct'] is not None]
    if improvements:
        avg_improvement = np.mean(improvements)
        print(f"\nAverage accuracy improvement: {avg_improvement:.1f}%")
        
        if avg_improvement > 0:
            print("✅ Regression method shows consistent improvement over First/Last method")
        else:
            print("⚠️  Regression method does not show consistent improvement")
    
    print("\n" + "=" * 80)
    print("Conclusion")
    print("=" * 80)
    print("The regression method should be more accurate when there is jitter/noise")
    print("in the pulse timestamps, as it uses all data points rather than just two.")
    print("=" * 80)


if __name__ == "__main__":
    # Set random seed for reproducibility
    np.random.seed(42)
    
    test_accuracy_comparison()
