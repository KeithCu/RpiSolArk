#!/usr/bin/env python3
"""
Test utilities for GPIO event counter testing with mock libgpiod.
Reuses analysis code from debug_pulse_test.py.
"""

import sys
import os
import time
import logging
from typing import Optional, List, Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.mock_gpiod import MockEdgeEvent, mock_gpiod
from tests.pulse_patterns import generate_stable_60hz, generate_generator_hunting, generate_noisy_signal
from gpio_event_counter import GPIOEventCounter


def is_raspberry_pi() -> bool:
    """Check if running on a Raspberry Pi."""
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().strip()
            if 'Raspberry Pi' in model:
                return True
    except (IOError, FileNotFoundError):
        pass
    
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'Raspberry Pi' in cpuinfo or 'BCM' in cpuinfo:
                return True
    except (IOError, FileNotFoundError):
        pass
    
    return False


def setup_mock_gpiod(monkeypatch=None):
    """
    Setup mock gpiod module for testing.
    
    Args:
        monkeypatch: pytest monkeypatch fixture (if None, patches sys.modules directly)
    
    Returns:
        Mock gpiod module instance
    """
    if monkeypatch:
        # Use pytest monkeypatch
        monkeypatch.setattr('gpiod', mock_gpiod)
        monkeypatch.setattr('gpio_event_counter.gpiod', mock_gpiod)
    else:
        # Direct module patching (for non-pytest usage)
        import gpio_event_counter
        sys.modules['gpiod'] = mock_gpiod
        gpio_event_counter.gpiod = mock_gpiod
    
    return mock_gpiod


def inject_pulses(mock_chip, pin: int, timestamps: List[int], edge_type: str = "rising"):
    """
    Inject pulse events into mock gpiod.
    
    Args:
        mock_chip: MockChip instance (or MockRequest instance for direct injection)
        pin: GPIO pin number
        timestamps: List of nanosecond timestamps for events
        edge_type: Type of edge ("rising", "falling", "both")
    """
    # If mock_chip is actually a MockRequest, inject directly
    if hasattr(mock_chip, 'inject_event'):
        for ts_ns in timestamps:
            event = MockEdgeEvent(
                line_offset=pin,
                timestamp_ns=ts_ns,
                event_type=edge_type
            )
            mock_chip.inject_event(event)
    else:
        # Otherwise, use chip's method to inject to all requests
        for ts_ns in timestamps:
            event = MockEdgeEvent(
                line_offset=pin,
                timestamp_ns=ts_ns,
                event_type=edge_type
            )
            mock_chip.inject_event_to_all_requests(event)


def verify_frequency(timestamps: List[int], expected_freq: float, tolerance: float = 0.1,
                    pulses_per_cycle: int = 2, duration: Optional[float] = None) -> Dict[str, Any]:
    """
    Verify calculated frequency from timestamps.
    Reuses logic from debug_pulse_test.py.
    
    Args:
        timestamps: List of nanosecond timestamps
        expected_freq: Expected frequency in Hz
        tolerance: Acceptable error in Hz
        pulses_per_cycle: Number of pulses per AC cycle
        duration: Duration in seconds (calculated from timestamps if None)
    
    Returns:
        Dictionary with verification results
    """
    if len(timestamps) < 2:
        return {
            'valid': False,
            'error': 'Insufficient timestamps',
            'calculated_freq': None
        }
    
    # Calculate duration from timestamps if not provided
    if duration is None:
        duration = (timestamps[-1] - timestamps[0]) / 1e9
    
    # Calculate frequency using count method
    pulse_count = len(timestamps)
    freq_from_count = pulse_count / (duration * pulses_per_cycle)
    
    # Calculate frequency from interval mean
    intervals_ns = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
    avg_interval_ns = sum(intervals_ns) / len(intervals_ns)
    avg_interval_sec = avg_interval_ns / 1e9
    pulse_freq = 1.0 / avg_interval_sec
    freq_from_intervals = pulse_freq / pulses_per_cycle
    
    # Use interval-based frequency as it's more accurate
    calculated_freq = freq_from_intervals
    error = abs(calculated_freq - expected_freq)
    valid = error <= tolerance
    
    return {
        'valid': valid,
        'calculated_freq': calculated_freq,
        'freq_from_count': freq_from_count,
        'freq_from_intervals': freq_from_intervals,
        'error': error,
        'tolerance': tolerance,
        'pulse_count': pulse_count,
        'duration': duration,
        'expected_pulses': int(duration * expected_freq * pulses_per_cycle),
        'pulse_loss': int(duration * expected_freq * pulses_per_cycle) - pulse_count
    }


def analyze_pulse_data(counter: GPIOEventCounter, pin: int, duration: float,
                      pulses_per_cycle: int = 2) -> Dict[str, Any]:
    """
    Analyze pulse data from counter (reuses analysis from debug_pulse_test.py).
    
    Args:
        counter: GPIOEventCounter instance
        pin: GPIO pin number
        duration: Measurement duration in seconds
        pulses_per_cycle: Number of pulses per AC cycle
    
    Returns:
        Dictionary with analysis results
    """
    pulse_count = counter.get_count(pin)
    timestamps = counter.get_timestamps(pin)
    event_stats = counter.get_event_statistics(pin, include_intervals=True)
    
    result = {
        'pulse_count': pulse_count,
        'timestamp_count': len(timestamps),
        'duration': duration,
        'pulse_rate': pulse_count / duration if duration > 0 else 0,
        'expected_rate': 60.0 * pulses_per_cycle,  # 120 pulses/second for 60Hz
        'event_stats': event_stats
    }
    
    # Frequency calculations
    if pulse_count > 0 and duration > 0:
        freq_from_count = pulse_count / (duration * pulses_per_cycle)
        result['freq_from_count'] = freq_from_count
        
        if len(timestamps) > 1:
            intervals_ns = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
            avg_interval_ns = sum(intervals_ns) / len(intervals_ns)
            avg_interval_sec = avg_interval_ns / 1e9
            pulse_freq = 1.0 / avg_interval_sec
            freq_from_intervals = pulse_freq / pulses_per_cycle
            result['freq_from_intervals'] = freq_from_intervals
            result['calculated_freq'] = freq_from_intervals
        else:
            result['freq_from_intervals'] = None
            result['calculated_freq'] = freq_from_count
        
        # Pulse loss analysis
        expected_pulses = int(duration * 60 * pulses_per_cycle)
        result['expected_pulses'] = expected_pulses
        result['pulse_loss'] = expected_pulses - pulse_count
        result['pulse_loss_pct'] = ((expected_pulses - pulse_count) / expected_pulses * 100) if expected_pulses > 0 else 0
    else:
        result['freq_from_count'] = None
        result['freq_from_intervals'] = None
        result['calculated_freq'] = None
        result['expected_pulses'] = 0
        result['pulse_loss'] = 0
        result['pulse_loss_pct'] = 0
    
    # Interval statistics (if available)
    if event_stats and event_stats.get('intervals'):
        intervals = event_stats['intervals']
        result['interval_stats'] = {
            'count': intervals['count'],
            'min_us': intervals['min_us'],
            'max_us': intervals['max_us'],
            'mean_us': intervals['mean_us'],
            'median_us': intervals['median_us'],
            'std_dev_us': intervals['std_dev_us']
        }
        
        # Expected interval for 60Hz AC
        expected_interval_us = 1_000_000 / (60 * pulses_per_cycle)  # 8333.33 μs for 120 Hz
        result['interval_stats']['expected_us'] = expected_interval_us
        result['interval_stats']['error_pct'] = abs(intervals['mean_us'] - expected_interval_us) / expected_interval_us * 100
    else:
        result['interval_stats'] = None
    
    return result


def create_test_counter(logger: Optional[logging.Logger] = None, use_mock: bool = True,
                        monkeypatch=None) -> tuple:
    """
    Create GPIOEventCounter instance with optional mock gpiod.
    
    Args:
        logger: Logger instance (creates one if None)
        use_mock: Whether to use mock gpiod
        monkeypatch: pytest monkeypatch fixture (optional, for explicit patching)
    
    Returns:
        Tuple of (counter, mock_chip) or (counter, None) if not using mock
    """
    if logger is None:
        logger = logging.getLogger('test')
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
    
    mock_chip = None
    if use_mock:
        # Setup mock if not already done
        if monkeypatch:
            mock_gpiod_module = setup_mock_gpiod(monkeypatch)
        else:
            # Try to setup without monkeypatch (for non-pytest usage)
            try:
                mock_gpiod_module = setup_mock_gpiod(None)
            except:
                # If already patched, just get the module
                from tests.mock_gpiod import mock_gpiod as mock_gpiod_module
        mock_chip = mock_gpiod_module.Chip("/dev/gpiochip0")
    
    counter = GPIOEventCounter(logger)
    return counter, mock_chip


def run_pulse_analysis(counter: GPIOEventCounter, pin: int, duration: float,
                      logger: Optional[logging.Logger] = None,
                      pulses_per_cycle: int = 2) -> Dict[str, Any]:
    """
    Run complete pulse analysis (reuses code from debug_pulse_test.py).
    
    Args:
        counter: GPIOEventCounter instance
        pin: GPIO pin number
        duration: Measurement duration
        logger: Logger for output
        pulses_per_cycle: Number of pulses per AC cycle
    
    Returns:
        Analysis results dictionary
    """
    if logger:
        logger.info("=" * 80)
        logger.info("PULSE ANALYSIS")
        logger.info("=" * 80)
    
    analysis = analyze_pulse_data(counter, pin, duration, pulses_per_cycle)
    
    if logger:
        logger.info(f"  Duration: {analysis['duration']:.3f} seconds")
        logger.info(f"  Pulse count: {analysis['pulse_count']}")
        logger.info(f"  Pulse rate: {analysis['pulse_rate']:.3f} pulses/second")
        logger.info(f"  Expected rate: {analysis['expected_rate']:.1f} pulses/second")
        logger.info(f"  Timestamps collected: {analysis['timestamp_count']}")
        
        if analysis['event_stats']:
            logger.info(f"  Events received: {analysis['event_stats']['received']}")
            logger.info(f"  Events debounced: {analysis['event_stats']['debounced']}")
            logger.info(f"  Events accepted: {analysis['event_stats']['accepted']}")
        
        if analysis['calculated_freq']:
            logger.info(f"  Calculated frequency: {analysis['calculated_freq']:.3f} Hz")
            logger.info(f"  Expected pulses: {analysis['expected_pulses']}")
            logger.info(f"  Pulse loss: {analysis['pulse_loss']} ({analysis['pulse_loss_pct']:.1f}%)")
        
        if analysis['interval_stats']:
            stats = analysis['interval_stats']
            logger.info(f"  Mean interval: {stats['mean_us']:.1f} μs")
            logger.info(f"  Interval error: {stats['error_pct']:.2f}%")
    
    return analysis
