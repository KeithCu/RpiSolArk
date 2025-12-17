#!/usr/bin/env python3
"""
Comprehensive test suite for gpio_event_counter.py using mock libgpiod.
Tests core logic without requiring Raspberry Pi hardware.
"""

import pytest
import time
import logging
import threading
from typing import List

from tests.test_utils_gpio import (
    setup_mock_gpiod, inject_pulses, verify_frequency, analyze_pulse_data,
    create_test_counter, run_pulse_analysis
)
from tests.pulse_patterns import (
    generate_stable_60hz, generate_generator_hunting, generate_noisy_signal,
    generate_with_gaps, generate_zero_voltage, generate_high_frequency_burst
)
from gpio_event_counter import GPIOEventCounter


@pytest.fixture
def logger():
    """Create a logger for testing."""
    logger = logging.getLogger('test_gpio_event_counter')
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger


@pytest.fixture
def mock_gpiod_setup(monkeypatch):
    """Setup mock gpiod for all tests."""
    return setup_mock_gpiod(monkeypatch)


@pytest.fixture
def counter_and_chip(logger, mock_gpiod_setup):
    """Create counter and mock chip for testing."""
    counter, mock_chip = create_test_counter(logger, use_mock=True)
    yield counter, mock_chip
    counter.cleanup()


class TestBasicFunctionality:
    """Test basic GPIO event counter functionality."""
    
    def test_pin_registration(self, counter_and_chip):
        """Test pin registration."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        result = counter.register_pin(pin)
        assert result is True
        assert pin in counter.registered_pins
    
    def test_event_counting(self, counter_and_chip):
        """Test basic event counting."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        # Generate and inject pulses
        timestamps = generate_stable_60hz(duration=1.0, pulses_per_cycle=2)
        inject_pulses(mock_chip, pin, timestamps)
        
        # Wait for events to be processed
        time.sleep(0.5)
        
        count = counter.get_count(pin)
        assert count > 0
        assert count == len(timestamps)  # Should match injected pulses
    
    def test_timestamp_collection(self, counter_and_chip):
        """Test timestamp collection."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        # Generate pulses
        timestamps = generate_stable_60hz(duration=0.5, pulses_per_cycle=2)
        inject_pulses(mock_chip, pin, timestamps)
        
        time.sleep(0.3)
        
        collected_timestamps = counter.get_timestamps(pin)
        assert len(collected_timestamps) > 0
        assert len(collected_timestamps) == len(timestamps)
    
    def test_count_reset(self, counter_and_chip):
        """Test count reset functionality."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        # Inject some pulses
        timestamps = generate_stable_60hz(duration=0.5, pulses_per_cycle=2)
        inject_pulses(mock_chip, pin, timestamps)
        time.sleep(0.3)
        
        count_before = counter.get_count(pin)
        assert count_before > 0
        
        # Reset
        counter.reset_count(pin)
        count_after = counter.get_count(pin)
        assert count_after == 0
        
        # Timestamps should also be cleared
        timestamps_after = counter.get_timestamps(pin)
        assert len(timestamps_after) == 0


class TestDebouncing:
    """Test debouncing functionality."""
    
    def test_debounce_rejects_rapid_events(self, counter_and_chip):
        """Test that events below debounce threshold are rejected."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        # Use very short debounce (0.1ms)
        counter.register_pin(pin, debounce_ns=100000)  # 0.1ms
        counter.reset_count(pin)
        
        # Generate rapid pulses (faster than debounce threshold)
        start_time_ns = time.perf_counter_ns()
        rapid_timestamps = []
        for i in range(10):
            # 0.05ms intervals (faster than 0.1ms debounce)
            rapid_timestamps.append(start_time_ns + i * 50000)  # 50μs intervals
        
        inject_pulses(mock_chip, pin, rapid_timestamps)
        time.sleep(0.2)
        
        # Should reject some events due to debouncing
        stats = counter.get_event_statistics(pin)
        assert stats['debounced'] > 0
        assert stats['accepted'] < stats['received']
    
    def test_debounce_accepts_valid_events(self, counter_and_chip):
        """Test that events above debounce threshold are accepted."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        # Use standard debounce (0.2ms)
        counter.register_pin(pin, debounce_ns=200000)  # 0.2ms
        counter.reset_count(pin)
        
        # Generate pulses at 60Hz (8.33ms intervals - well above debounce)
        timestamps = generate_stable_60hz(duration=0.5, pulses_per_cycle=2)
        inject_pulses(mock_chip, pin, timestamps)
        time.sleep(0.3)
        
        # Should accept all events
        stats = counter.get_event_statistics(pin)
        assert stats['debounced'] == 0 or stats['debounced'] < stats['received'] * 0.1  # <10% debounced
        assert stats['accepted'] == stats['received'] or stats['accepted'] > stats['received'] * 0.9


class TestFrequencyCalculation:
    """Test frequency calculation from timestamps."""
    
    def test_stable_60hz_signal(self, counter_and_chip):
        """Test frequency calculation with stable 60Hz signal."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        duration = 2.0
        # Generate timestamps with current time as base
        start_time_ns = time.perf_counter_ns()
        timestamps = generate_stable_60hz(duration=duration, pulses_per_cycle=2, start_time_ns=start_time_ns)
        
        # Inject all pulses at once (mock handles timing)
        inject_pulses(mock_chip, pin, timestamps)
        
        # Wait for events to be processed
        time.sleep(0.5)
        
        collected_timestamps = counter.get_timestamps(pin)
        result = verify_frequency(collected_timestamps, expected_freq=60.0, tolerance=0.5, 
                                pulses_per_cycle=2, duration=duration)
        
        assert result['valid'] is True
        assert 59.5 <= result['calculated_freq'] <= 60.5
    
    def test_generator_hunting_detection(self, counter_and_chip):
        """Test frequency variation detection with generator hunting."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        duration = 3.0
        start_time_ns = time.perf_counter_ns()
        timestamps = generate_generator_hunting(duration=duration, base_freq=60.0, amplitude=0.5,
                                               start_time_ns=start_time_ns)
        
        # Inject all pulses
        inject_pulses(mock_chip, pin, timestamps)
        time.sleep(0.5)
        
        collected_timestamps = counter.get_timestamps(pin)
        # Generator hunting should show frequency variation
        if len(collected_timestamps) > 10:
            intervals = [collected_timestamps[i] - collected_timestamps[i-1] 
                        for i in range(1, len(collected_timestamps))]
            # Check for variation in intervals
            if len(intervals) > 0:
                avg_interval = sum(intervals) / len(intervals)
                interval_variation = (max(intervals) - min(intervals)) / avg_interval if avg_interval > 0 else 0
                assert interval_variation > 0.01  # Should have >1% variation


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_zero_voltage_state(self, counter_and_chip):
        """Test handling of zero voltage (no pulses)."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        # No pulses injected
        time.sleep(1.0)
        
        count = counter.get_count(pin)
        timestamps = counter.get_timestamps(pin)
        
        assert count == 0
        assert len(timestamps) == 0
    
    def test_high_frequency_bursts(self, counter_and_chip):
        """Test handling of high-frequency bursts."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin, debounce_ns=200000)  # 0.2ms debounce
        counter.reset_count(pin)
        
        # Generate high-frequency bursts
        timestamps = generate_high_frequency_burst(
            duration=1.0, burst_freq=120.0, burst_duration=0.1, burst_interval=0.5
        )
        
        inject_pulses(mock_chip, pin, timestamps)
        time.sleep(0.5)
        
        count = counter.get_count(pin)
        assert count > 0
        
        # Check debouncing handled rapid events
        stats = counter.get_event_statistics(pin)
        # Some events may be debounced during bursts
        assert stats['received'] >= stats['accepted']
    
    def test_large_gaps(self, counter_and_chip):
        """Test handling of large gaps between pulses."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        # Generate signal with gaps
        start_time_ns = time.perf_counter_ns()
        timestamps = generate_with_gaps(duration=2.0, base_freq=60.0, gap_probability=0.1,
                                        start_time_ns=start_time_ns)
        
        # Inject all pulses
        inject_pulses(mock_chip, pin, timestamps)
        time.sleep(0.5)
        
        count = counter.get_count(pin)
        # Should match injected pulses (gaps are already in the timestamp list)
        assert count == len(timestamps)
    
    def test_multiple_pins(self, counter_and_chip):
        """Test multiple pins simultaneously."""
        counter, mock_chip = counter_and_chip
        pin1 = 26
        pin2 = 27
        
        counter.register_pin(pin1)
        counter.register_pin(pin2)
        counter.reset_count(pin1)
        counter.reset_count(pin2)
        
        # Generate pulses for both pins
        timestamps1 = generate_stable_60hz(duration=0.5, pulses_per_cycle=2)
        timestamps2 = generate_stable_60hz(duration=0.5, pulses_per_cycle=2)
        
        inject_pulses(mock_chip, pin1, timestamps1)
        inject_pulses(mock_chip, pin2, timestamps2)
        time.sleep(0.3)
        
        count1 = counter.get_count(pin1)
        count2 = counter.get_count(pin2)
        
        assert count1 > 0
        assert count2 > 0
        assert count1 == len(timestamps1)
        assert count2 == len(timestamps2)


class TestEventStatistics:
    """Test event statistics collection."""
    
    def test_event_statistics_collection(self, counter_and_chip):
        """Test collection of event statistics."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        timestamps = generate_stable_60hz(duration=1.0, pulses_per_cycle=2)
        inject_pulses(mock_chip, pin, timestamps)
        time.sleep(0.5)
        
        stats = counter.get_event_statistics(pin, include_intervals=True)
        
        assert stats is not None
        assert 'received' in stats
        assert 'accepted' in stats
        assert 'debounced' in stats
        assert 'count' in stats
        assert stats['received'] >= stats['accepted']
        assert stats['accepted'] == stats['count']
    
    def test_interval_statistics(self, counter_and_chip):
        """Test interval statistics calculation."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        timestamps = generate_stable_60hz(duration=1.0, pulses_per_cycle=2)
        inject_pulses(mock_chip, pin, timestamps)
        time.sleep(0.5)
        
        stats = counter.get_event_statistics(pin, include_intervals=True)
        
        if stats and stats.get('intervals'):
            intervals = stats['intervals']
            assert 'min_us' in intervals
            assert 'max_us' in intervals
            assert 'mean_us' in intervals
            assert 'std_dev_us' in intervals
            
            # For 60Hz (120 pulses/sec), expected interval is ~8333 μs
            expected_interval_us = 1_000_000 / 120  # 8333.33 μs
            assert 7000 <= intervals['mean_us'] <= 10000  # Allow some tolerance


class TestThreadSafety:
    """Test thread safety of counter operations."""
    
    def test_concurrent_reads(self, counter_and_chip):
        """Test concurrent reads during event injection."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        start_time_ns = time.perf_counter_ns()
        timestamps = generate_stable_60hz(duration=1.0, pulses_per_cycle=2, start_time_ns=start_time_ns)
        
        read_results = []
        
        def read_thread():
            for _ in range(10):
                count = counter.get_count(pin)
                read_results.append(count)
                time.sleep(0.1)
        
        # Start reading thread
        read_thread_obj = threading.Thread(target=read_thread)
        read_thread_obj.start()
        
        # Inject all pulses at once
        inject_pulses(mock_chip, pin, timestamps)
        
        read_thread_obj.join()
        
        # Should have read increasing counts
        assert len(read_results) > 0
        assert max(read_results) > 0
    
    def test_reset_during_counting(self, counter_and_chip):
        """Test reset during active counting."""
        counter, mock_chip = counter_and_chip
        pin = 26
        
        counter.register_pin(pin)
        counter.reset_count(pin)
        
        start_time_ns = time.perf_counter_ns()
        timestamps = generate_stable_60hz(duration=2.0, pulses_per_cycle=2, start_time_ns=start_time_ns)
        
        # Inject first half of pulses
        first_half = timestamps[:len(timestamps)//2]
        inject_pulses(mock_chip, pin, first_half)
        time.sleep(0.2)
        
        # Reset during counting
        count_before_reset = counter.get_count(pin)
        counter.reset_count(pin)
        count_after_reset = counter.get_count(pin)
        
        # Inject remaining pulses
        second_half = timestamps[len(timestamps)//2:]
        inject_pulses(mock_chip, pin, second_half)
        time.sleep(0.2)
        
        assert count_before_reset > 0
        assert count_after_reset == 0
