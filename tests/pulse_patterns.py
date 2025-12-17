#!/usr/bin/env python3
"""
Pulse pattern generators for testing GPIO event counter.
Generates synthetic pulse patterns with nanosecond-precision timestamps.
"""

import time
import random
import math
from typing import List, Tuple


def generate_stable_60hz(duration: float, pulses_per_cycle: int = 2, start_time_ns: int = None) -> List[int]:
    """
    Generate stable 60Hz AC signal pulse timestamps.
    
    Args:
        duration: Duration in seconds
        pulses_per_cycle: Number of pulses per AC cycle (default: 2 for H11AA1 optocoupler)
        start_time_ns: Starting timestamp in nanoseconds (uses current time if None)
    
    Returns:
        List of nanosecond timestamps for rising edges
    """
    if start_time_ns is None:
        start_time_ns = int(time.perf_counter_ns())
    
    timestamps = []
    frequency_hz = 60.0
    pulse_frequency = frequency_hz * pulses_per_cycle  # 120 Hz for 2 pulses/cycle
    period_ns = int(1e9 / pulse_frequency)  # Period in nanoseconds
    
    num_pulses = int(duration * pulse_frequency)
    current_time_ns = start_time_ns
    
    for _ in range(num_pulses):
        timestamps.append(current_time_ns)
        current_time_ns += period_ns
    
    return timestamps


def generate_generator_hunting(duration: float, base_freq: float = 60.0, amplitude: float = 0.5, 
                                pulses_per_cycle: int = 2, start_time_ns: int = None) -> List[int]:
    """
    Generate generator hunting pattern (oscillating frequency).
    
    Args:
        duration: Duration in seconds
        base_freq: Base frequency in Hz (default: 60.0)
        amplitude: Frequency variation amplitude in Hz (default: 0.5)
        pulses_per_cycle: Number of pulses per AC cycle
        start_time_ns: Starting timestamp in nanoseconds
    
    Returns:
        List of nanosecond timestamps for rising edges
    """
    if start_time_ns is None:
        start_time_ns = int(time.perf_counter_ns())
    
    timestamps = []
    hunting_period = 2.0  # 2 second hunting cycle
    current_time_ns = start_time_ns
    elapsed = 0.0
    
    while elapsed < duration:
        # Calculate current frequency based on hunting pattern
        phase = (elapsed % hunting_period) / hunting_period * 2 * math.pi
        current_freq = base_freq + amplitude * math.sin(phase)
        
        # Clamp frequency to reasonable range
        current_freq = max(58.0, min(62.0, current_freq))
        
        pulse_frequency = current_freq * pulses_per_cycle
        period_ns = int(1e9 / pulse_frequency)
        
        # Generate one pulse
        timestamps.append(current_time_ns)
        current_time_ns += period_ns
        elapsed = (current_time_ns - start_time_ns) / 1e9
    
    return timestamps


def generate_noisy_signal(duration: float, base_freq: float = 60.0, noise_level: float = 0.01,
                          pulses_per_cycle: int = 2, start_time_ns: int = None) -> List[int]:
    """
    Generate signal with timing jitter/noise.
    
    Args:
        duration: Duration in seconds
        base_freq: Base frequency in Hz
        noise_level: Noise level as fraction of period (0.01 = 1% jitter)
        pulses_per_cycle: Number of pulses per AC cycle
        start_time_ns: Starting timestamp in nanoseconds
    
    Returns:
        List of nanosecond timestamps for rising edges
    """
    if start_time_ns is None:
        start_time_ns = int(time.perf_counter_ns())
    
    timestamps = []
    pulse_frequency = base_freq * pulses_per_cycle
    base_period_ns = int(1e9 / pulse_frequency)
    noise_amplitude_ns = int(base_period_ns * noise_level)
    
    num_pulses = int(duration * pulse_frequency)
    current_time_ns = start_time_ns
    
    for _ in range(num_pulses):
        timestamps.append(current_time_ns)
        
        # Add random jitter
        jitter_ns = random.randint(-noise_amplitude_ns, noise_amplitude_ns)
        current_time_ns += base_period_ns + jitter_ns
    
    return timestamps


def generate_with_gaps(duration: float, base_freq: float = 60.0, gap_probability: float = 0.01,
                       gap_duration_range: Tuple[float, float] = (0.1, 0.5),
                       pulses_per_cycle: int = 2, start_time_ns: int = None) -> List[int]:
    """
    Generate signal with random gaps (missing pulses).
    
    Args:
        duration: Duration in seconds
        base_freq: Base frequency in Hz
        gap_probability: Probability of a gap occurring (0.01 = 1%)
        gap_duration_range: Tuple of (min, max) gap duration in seconds
        pulses_per_cycle: Number of pulses per AC cycle
        start_time_ns: Starting timestamp in nanoseconds
    
    Returns:
        List of nanosecond timestamps for rising edges
    """
    if start_time_ns is None:
        start_time_ns = int(time.perf_counter_ns())
    
    timestamps = []
    pulse_frequency = base_freq * pulses_per_cycle
    period_ns = int(1e9 / pulse_frequency)
    
    num_pulses = int(duration * pulse_frequency)
    current_time_ns = start_time_ns
    
    for _ in range(num_pulses):
        # Check if we should create a gap
        if random.random() < gap_probability:
            # Skip pulses for gap duration
            gap_duration = random.uniform(*gap_duration_range)
            gap_pulses = int(gap_duration * pulse_frequency)
            current_time_ns += period_ns * gap_pulses
        else:
            timestamps.append(current_time_ns)
            current_time_ns += period_ns
    
    return timestamps


def generate_custom_pattern(frequencies: List[float], durations: List[float],
                           pulses_per_cycle: int = 2, start_time_ns: int = None) -> List[int]:
    """
    Generate custom frequency pattern over time.
    
    Args:
        frequencies: List of frequencies in Hz for each segment
        durations: List of durations in seconds for each segment
        pulses_per_cycle: Number of pulses per AC cycle
        start_time_ns: Starting timestamp in nanoseconds
    
    Returns:
        List of nanosecond timestamps for rising edges
    """
    if len(frequencies) != len(durations):
        raise ValueError("frequencies and durations must have same length")
    
    if start_time_ns is None:
        start_time_ns = int(time.perf_counter_ns())
    
    timestamps = []
    current_time_ns = start_time_ns
    
    for freq, duration in zip(frequencies, durations):
        pulse_frequency = freq * pulses_per_cycle
        period_ns = int(1e9 / pulse_frequency)
        num_pulses = int(duration * pulse_frequency)
        
        for _ in range(num_pulses):
            timestamps.append(current_time_ns)
            current_time_ns += period_ns
    
    return timestamps


def generate_zero_voltage(duration: float, start_time_ns: int = None) -> List[int]:
    """
    Generate zero voltage state (no pulses).
    
    Args:
        duration: Duration in seconds (for consistency with other generators)
        start_time_ns: Starting timestamp in nanoseconds
    
    Returns:
        Empty list (no pulses)
    """
    return []


def generate_high_frequency_burst(duration: float, burst_freq: float = 120.0, 
                                  burst_duration: float = 0.1, burst_interval: float = 1.0,
                                  pulses_per_cycle: int = 2, start_time_ns: int = None) -> List[int]:
    """
    Generate high-frequency bursts with intervals.
    
    Args:
        duration: Total duration in seconds
        burst_freq: Frequency during bursts in Hz
        burst_duration: Duration of each burst in seconds
        burst_interval: Interval between bursts in seconds
        pulses_per_cycle: Number of pulses per AC cycle
        start_time_ns: Starting timestamp in nanoseconds
    
    Returns:
        List of nanosecond timestamps for rising edges
    """
    if start_time_ns is None:
        start_time_ns = int(time.perf_counter_ns())
    
    timestamps = []
    current_time_ns = start_time_ns
    elapsed = 0.0
    
    while elapsed < duration:
        # Generate burst
        if elapsed + burst_duration <= duration:
            burst_pulse_freq = burst_freq * pulses_per_cycle
            burst_period_ns = int(1e9 / burst_pulse_freq)
            num_burst_pulses = int(burst_duration * burst_pulse_freq)
            
            for _ in range(num_burst_pulses):
                timestamps.append(current_time_ns)
                current_time_ns += burst_period_ns
            
            elapsed += burst_duration
        else:
            # Partial burst at end
            remaining = duration - elapsed
            burst_pulse_freq = burst_freq * pulses_per_cycle
            burst_period_ns = int(1e9 / burst_pulse_freq)
            num_burst_pulses = int(remaining * burst_pulse_freq)
            
            for _ in range(num_burst_pulses):
                timestamps.append(current_time_ns)
                current_time_ns += burst_period_ns
            break
        
        # Add interval between bursts
        if elapsed + burst_interval <= duration:
            interval_ns = int(burst_interval * 1e9)
            current_time_ns += interval_ns
            elapsed += burst_interval
        else:
            break
    
    return timestamps
