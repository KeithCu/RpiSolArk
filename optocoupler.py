#!/usr/bin/env python3
"""
Optocoupler management for frequency measurement using working libgpiod implementation.
Handles pulse counting and frequency calculation with graceful degradation.
"""

import logging
import time
import threading
import os
import statistics
from typing import Optional, Tuple, List, Dict, Any
import psutil
import numpy as np

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    GPIO_AVAILABLE = False
    print(f"Warning: RPi.GPIO not available ({e}). Running in simulation mode.")

# GIL-safe counter imports (required)
from gpio_event_counter import create_counter

# Global flags for regression-based frequency calculation
# Set ENABLE_REGRESSION_COMPARISON = True to calculate and log regression results alongside standard results
ENABLE_REGRESSION_COMPARISON = True
# Set USE_REGRESSION_FOR_RESULT = True to return regression result instead of standard result
USE_REGRESSION_FOR_RESULT = False


class SingleOptocoupler:
    """Manages a single optocoupler for frequency measurement using working libgpiod."""
    
    def __init__(self, config, logger: logging.Logger, name: str, pin: int, 
                 pulses_per_cycle: int = 2, measurement_duration: float = 2.0):
        self.config = config
        self.logger = logger
        self.name = name
        self.pin = pin
        self.pulses_per_cycle = pulses_per_cycle
        self.measurement_duration = measurement_duration
        self.gpio_available = GPIO_AVAILABLE
        
        # Optocoupler pulse counting
        self.pulse_count = 0
        self.pulse_count_lock = threading.Lock()
        self.last_timestamps = []
        self.initialized = False
        
        # Error tracking and recovery
        self.consecutive_errors = 0
        self.max_consecutive_errors = config.get('hardware.optocoupler.max_consecutive_errors')
        self.last_successful_count = 0
        self.last_health_check = time.time()
        self.health_check_interval = config.get('hardware.optocoupler.health_check_interval')  # seconds
        self.recovery_attempts = 0
        self.max_recovery_attempts = config.get('hardware.optocoupler.max_recovery_attempts')
        
        # Non-blocking measurement state
        self.measurement_active = False
        self.measurement_start_time = None
        self.measurement_duration = None
        self.measurement_lock = threading.Lock()
        
        # Initialize GIL-safe counter (required)
        counter_start = time.perf_counter()
        self.counter = create_counter(self.logger)
        counter_duration = (time.perf_counter() - counter_start) * 1000
        self.logger.info(f"[COUNTER_INIT] GIL-safe counter initialized for {self.name} in {counter_duration:.1f}ms")
        
        if self.gpio_available:
            self._setup_optocoupler()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.cleanup()
        return False  # Don't suppress exceptions
    
    def _setup_optocoupler(self):
        """Setup optocoupler for edge detection using working libgpiod only."""
        if not self.gpio_available:
            self.logger.warning(f"GPIO not available, cannot setup {self.name} optocoupler")
            return
        
        try:
            setup_start = time.perf_counter()
            self.logger.info(f"[OPTO_SETUP] Setting up {self.name} optocoupler on GPIO pin {self.pin}, pulses_per_cycle={self.pulses_per_cycle}, measurement_duration={self.measurement_duration}s")
            
            # Use libgpiod only - don't mix with RPi.GPIO to avoid conflicts
            # Set up GIL-free interrupt detection using working libgpiod
            register_start = time.perf_counter()
            if self.counter.register_pin(self.pin):
                register_duration = (time.perf_counter() - register_start) * 1000
                self.logger.info(f"[OPTO_SETUP] {self.name} pin registered in {register_duration:.1f}ms")
                self.initialized = True
            else:
                raise Exception("libgpiod counter setup failed")
            
            setup_duration = (time.perf_counter() - setup_start) * 1000
            self.logger.info(f"[OPTO_SETUP] {self.name} optocoupler setup completed in {setup_duration:.1f}ms")
            
        except Exception as e:
            self.logger.error(f"[OPTO_SETUP] Failed to setup {self.name} optocoupler: {e}")
            self.initialized = False
    
    def start_measurement(self, duration: float = None) -> bool:
        """
        Start a non-blocking measurement window.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            
        Returns:
            True if measurement started successfully, False otherwise
        """
        if not self.initialized:
            self.logger.warning(f"{self.name} optocoupler not initialized, cannot start measurement")
            return False
        
        # Check health before measurement
        if not self.check_health():
            self.logger.warning(f"{self.name} optocoupler unhealthy, cannot start measurement")
            return False
        
        if duration is None:
            duration = self.measurement_duration
        
        # Calculate expected pulse count for comparison
        expected_pulses = int(duration * 60 * self.pulses_per_cycle)  # 60Hz * pulses_per_cycle * duration
        
        # Track lock acquisition time
        lock_start = time.perf_counter()
        with self.measurement_lock:
            lock_duration = (time.perf_counter() - lock_start) * 1000
            if lock_duration > 10.0:  # Warn if >10ms
                self.logger.warning(f"[NB_MEASURE] {self.name} measurement_lock acquisition took {lock_duration:.2f}ms - possible contention")
            
            # If a measurement is already active, don't start a new one
            if self.measurement_active:
                self.logger.debug(f"[NB_MEASURE] {self.name} measurement already active, skipping start")
                return False
            
            try:
                # Get pulse count before reset
                pulse_count_before_reset = self.counter.get_count(self.pin)
                start_time = time.perf_counter()
                self.logger.info(f"[NB_MEASURE_START] {self.name} duration={duration:.2f}s expected_pulses=~{expected_pulses} count_before_reset={pulse_count_before_reset} time={start_time:.3f}")
                
                # Reset counter before measurement
                reset_start = time.perf_counter()
                self.counter.reset_count(self.pin)
                reset_end = time.perf_counter()
                reset_duration_ms = (reset_end - reset_start) * 1000
                self.logger.info(f"[NB_RESET_COMPLETE] {self.name} reset_took={reset_duration_ms:.2f}ms")
                
                # Get pulse count immediately after reset (should be 0)
                pulse_count_after_reset = self.counter.get_count(self.pin)
                if pulse_count_after_reset != 0:
                    self.logger.warning(f"[NB_RESET_VERIFY] {self.name} count after reset is {pulse_count_after_reset}, expected 0!")
                
                # Record measurement start time and duration
                self.measurement_start_time = time.perf_counter()
                self.measurement_duration = duration
                self.measurement_active = True
                
                time_since_reset = (self.measurement_start_time - reset_end) * 1000
                self.logger.info(f"[NB_MEASURE_ACTIVE] {self.name} measurement started, time_since_reset={time_since_reset:.2f}ms")
                return True
                
            except Exception as e:
                self.logger.error(f"[NB_MEASURE] {self.name} failed to start measurement: {e}")
                self.measurement_active = False
                return False
    
    def check_measurement(self) -> Tuple[bool, Optional[int], Optional[float]]:
        """
        Check if the current measurement window has elapsed.
        
        Returns:
            Tuple of (is_complete, pulse_count, actual_elapsed_time):
            - is_complete: True if measurement is complete, False if still in progress
            - pulse_count: Number of pulses counted (None if not complete)
            - actual_elapsed_time: Actual elapsed time in seconds (None if not complete)
        """
        with self.measurement_lock:
            if not self.measurement_active:
                return (False, None, None)
            
            current_time = time.perf_counter()
            elapsed = current_time - self.measurement_start_time
            
            # Check if measurement window has elapsed
            if elapsed < self.measurement_duration:
                # Still in progress
                return (False, None, None)
            
            # Measurement complete - retrieve results
            try:
                # Calculate expected pulse count for comparison
                expected_pulses = int(self.measurement_duration * 60 * self.pulses_per_cycle)
                
                count_start = time.perf_counter()
                pulse_count = self.counter.get_count(self.pin)
                count_end = time.perf_counter()
                count_duration_ms = (count_end - count_start) * 1000
                
                # Get frequency stats for additional logging
                stat_count, t_first, t_last = self.counter.get_frequency_info(self.pin)
                
                # Get event statistics for detailed analysis (skip expensive interval calculations for performance)
                # Only include intervals if debug logging is enabled
                include_intervals = self.logger.isEnabledFor(logging.DEBUG)
                event_stats = self.counter.get_event_statistics(self.pin, include_intervals=include_intervals)
                
                self.logger.debug(f"[NB_COUNT_READ] {self.name} count={pulse_count} expected=~{expected_pulses} elapsed={elapsed:.3f}s count_took={count_duration_ms:.2f}ms")
                
                if stat_count > 0:
                    stat_duration_ms = (t_last - t_first) / 1e6
                    self.logger.info(f"[NB_FREQ_STATS] {self.name} stat_count={stat_count} duration={stat_duration_ms:.2f}ms first_ts={t_first} last_ts={t_last}")
                else:
                    self.logger.warning(f"[NB_FREQ_STATS] {self.name} NO TIMESTAMPS COLLECTED!")
                
                # Log event statistics if available
                if event_stats:
                    self.logger.info(f"[NB_EVENT_STATS] {self.name} received={event_stats['received']} debounced={event_stats['debounced']} accepted={event_stats['accepted']} count={event_stats['count']} timestamp_count={event_stats['timestamp_count']}")
                    
                    # Compare pulse_count vs stat_count
                    if pulse_count != stat_count:
                        self.logger.warning(f"[NB_COUNT_MISMATCH] {self.name} pulse_count={pulse_count} != stat_count={stat_count} (diff={abs(pulse_count - stat_count)})")
                    
                    # Log interval statistics if available
                    if event_stats.get('intervals'):
                        intervals = event_stats['intervals']
                        self.logger.info(f"[NB_INTERVAL_STATS] {self.name} count={intervals['count']} min={intervals['min_us']:.1f}us max={intervals['max_us']:.1f}us mean={intervals['mean_us']:.1f}us median={intervals['median_us']:.1f}us std_dev={intervals['std_dev_us']:.1f}us")
                
                # Validate pulse count
                if pulse_count < 0:
                    self.consecutive_errors += 1
                    self.logger.warning(f"{self.name} invalid pulse count: {pulse_count}")
                    self.measurement_active = False
                    return (True, 0, elapsed)
                
                # Warn if count is much lower than expected
                if pulse_count < expected_pulses * 0.5:
                    self.logger.warning(f"[NB_COUNT_LOW] {self.name} count={pulse_count} is less than 50% of expected={expected_pulses}")
                
                # Calculate pulse loss percentage
                pulse_loss_pct = (1.0 - (pulse_count / expected_pulses)) * 100 if expected_pulses > 0 else 0
                if pulse_loss_pct > 5.0:  # Warn if more than 5% loss
                    self.logger.warning(f"[NB_PULSE_LOSS] {self.name} pulse_loss={pulse_loss_pct:.1f}% (expected={expected_pulses} got={pulse_count})")
                
                # Reset error count on successful measurement
                self.consecutive_errors = 0
                self.last_successful_count = pulse_count
                
                rate = pulse_count / elapsed if elapsed > 0 else 0
                self.logger.info(f"[NB_MEASURE_END] {self.name} count={pulse_count} elapsed={elapsed:.3f}s rate={rate:.1f}/s expected_rate=120.0/s loss={pulse_loss_pct:.1f}%")
                
                # Mark measurement as complete
                self.measurement_active = False
                
                return (True, pulse_count, elapsed)
                
            except Exception as e:
                self.consecutive_errors += 1
                self.logger.error(f"[NB_MEASURE] {self.name} error checking measurement: {e}")
                self.measurement_active = False
                return (True, 0, elapsed)
    
    def count_optocoupler_pulses(self, duration: float = None) -> Tuple[int, float]:
        """
        Count optocoupler pulses over specified duration using working libgpiod.
        BLOCKING VERSION - Use start_measurement()/check_measurement() for non-blocking operation.
        Uses interrupt-based counting for maximum accuracy and performance.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            
        Returns:
            Tuple of (pulse_count, actual_elapsed_time) where:
            - pulse_count: Number of pulses counted
            - actual_elapsed_time: Actual elapsed time in seconds (measured with time.perf_counter())
        """
        if not self.initialized:
            self.logger.warning(f"{self.name} optocoupler not initialized, cannot count pulses")
            return (0, 0.0)
        
        # Check health before measurement
        if not self.check_health():
            self.logger.warning(f"{self.name} optocoupler unhealthy, skipping measurement")
            return (0, 0.0)
        
        if duration is None:
            duration = self.measurement_duration
        
        # Calculate expected pulse count for comparison
        expected_pulses = int(duration * 60 * self.pulses_per_cycle)  # 60Hz * pulses_per_cycle * duration
        
        try:
            # Log before reset
            pulse_count_before_reset = self.counter.get_count(self.pin)
            measure_start = time.perf_counter()
            self.logger.info(f"[MEASURE_START] {self.name} duration={duration:.2f}s expected_pulses=~{expected_pulses} count_before_reset={pulse_count_before_reset} time={measure_start:.3f}")
            
            # Reset counter before measurement
            reset_start = time.perf_counter()
            self.counter.reset_count(self.pin)
            reset_end = time.perf_counter()
            reset_duration_ms = (reset_end - reset_start) * 1000
            self.logger.info(f"[RESET_COMPLETE] {self.name} reset_took={reset_duration_ms:.2f}ms")
            
            # Get pulse count immediately after reset (should be 0)
            pulse_count_after_reset = self.counter.get_count(self.pin)
            if pulse_count_after_reset != 0:
                self.logger.warning(f"[RESET_VERIFY] {self.name} count after reset is {pulse_count_after_reset}, expected 0!")
            
            # Use libgpiod interrupt counting
            sleep_start = time.perf_counter()
            time_since_reset = (sleep_start - reset_end) * 1000
            self.logger.info(f"[SLEEP_START] {self.name} time_since_reset={time_since_reset:.2f}ms, sleeping for {duration:.2f}s")
            
            # Wait for the specified duration - libgpiod handles counting in background
            time.sleep(duration)
            
            sleep_end = time.perf_counter()
            actual_sleep = (sleep_end - sleep_start) * 1000
            sleep_deviation = actual_sleep - (duration * 1000)
            self.logger.info(f"[SLEEP_END] {self.name} actual_sleep={actual_sleep:.2f}ms expected={duration*1000:.2f}ms deviation={sleep_deviation:.2f}ms")
            
            # Get final count from libgpiod
            count_start = time.perf_counter()
            pulse_count = self.counter.get_count(self.pin)
            count_end = time.perf_counter()
            count_duration_ms = (count_end - count_start) * 1000
            total_time_since_reset = (count_end - reset_start) * 1000
            
            self.logger.info(f"[COUNT_READ] {self.name} count={pulse_count} expected=~{expected_pulses} time_since_reset={total_time_since_reset:.2f}ms count_took={count_duration_ms:.2f}ms")
            
            # Retrieve frequency stats (count, first, last) directly to avoid list copy overhead
            stat_count, t_first, t_last = self.counter.get_frequency_info(self.pin)
            
            # Get event statistics for detailed analysis (skip expensive interval calculations for performance)
            # Only include intervals if debug logging is enabled
            include_intervals = self.logger.isEnabledFor(logging.DEBUG)
            event_stats = self.counter.get_event_statistics(self.pin, include_intervals=include_intervals)
            
            # Log frequency stats
            if stat_count > 0:
                stat_duration_ms = (t_last - t_first) / 1e6
                self.logger.info(f"[FREQ_STATS] {self.name} stat_count={stat_count} duration={stat_duration_ms:.2f}ms first_ts={t_first} last_ts={t_last}")
                
                # Calculate timing precision: reset to first pulse, last pulse to count read
                # Convert reset_end to nanoseconds (approximate, using perf_counter reference)
                # Note: t_first and t_last are in nanoseconds from kernel, reset_end is perf_counter
                # We can't directly compare, but we can calculate dead time from measurement window
                reset_to_first_ms = "N/A"  # Can't directly compare perf_counter to kernel timestamps
                last_to_count_ms = "N/A"
                
                # Calculate dead time: time before first pulse and after last pulse within measurement window
                # Measurement window: reset_end to count_end
                measurement_window_ns = (count_end - reset_end) * 1e9
                pulse_window_ns = t_last - t_first
                dead_time_before_ns = t_first - (reset_end * 1e9)  # Approximate, may be negative if first pulse before reset
                dead_time_after_ns = (count_end * 1e9) - t_last
                
                self.logger.debug(f"[TIMING_ANALYSIS] {self.name} measurement_window={measurement_window_ns/1e6:.2f}ms pulse_window={pulse_window_ns/1e6:.2f}ms dead_time_before={dead_time_before_ns/1e6:.2f}ms dead_time_after={dead_time_after_ns/1e6:.2f}ms")
            else:
                self.logger.warning(f"[FREQ_STATS] {self.name} NO TIMESTAMPS COLLECTED!")
            
            # Log event statistics if available
            if event_stats:
                self.logger.info(f"[EVENT_STATS] {self.name} received={event_stats['received']} debounced={event_stats['debounced']} accepted={event_stats['accepted']} count={event_stats['count']} timestamp_count={event_stats['timestamp_count']}")
                
                # Compare pulse_count vs stat_count
                if pulse_count != stat_count:
                    self.logger.warning(f"[COUNT_MISMATCH] {self.name} pulse_count={pulse_count} != stat_count={stat_count} (diff={abs(pulse_count - stat_count)})")
                
                # Log interval statistics if available
                if event_stats.get('intervals'):
                    intervals = event_stats['intervals']
                    self.logger.info(f"[INTERVAL_STATS] {self.name} count={intervals['count']} min={intervals['min_us']:.1f}us max={intervals['max_us']:.1f}us mean={intervals['mean_us']:.1f}us median={intervals['median_us']:.1f}us std_dev={intervals['std_dev_us']:.1f}us")
                    
                    # Calculate expected interval for 60Hz AC (120 pulses/second = 8333.33us per pulse)
                    expected_interval_60hz_us = 1_000_000 / 120  # 8333.33us
                    interval_error_pct = abs(intervals['mean_us'] - expected_interval_60hz_us) / expected_interval_60hz_us * 100
                    self.logger.debug(f"[INTERVAL_ANALYSIS] {self.name} expected_60hz_interval={expected_interval_60hz_us:.2f}us actual_mean={intervals['mean_us']:.2f}us error={interval_error_pct:.2f}%")
            
            # Validate pulse count
            if pulse_count < 0:
                self.consecutive_errors += 1
                self.logger.warning(f"{self.name} invalid pulse count: {pulse_count}")
                return (0, (count_end - sleep_start))
            
            # Warn if count is much lower than expected
            if pulse_count < expected_pulses * 0.5:
                self.logger.warning(f"[COUNT_LOW] {self.name} count={pulse_count} is less than 50% of expected={expected_pulses}")
            
            # Calculate pulse loss percentage
            pulse_loss_pct = (1.0 - (pulse_count / expected_pulses)) * 100 if expected_pulses > 0 else 0
            if pulse_loss_pct > 5.0:  # Warn if more than 5% loss
                self.logger.warning(f"[PULSE_LOSS] {self.name} pulse_loss={pulse_loss_pct:.1f}% (expected={expected_pulses} got={pulse_count})")
            
            # Reset error count on successful measurement
            self.consecutive_errors = 0
            self.last_successful_count = pulse_count
            
            elapsed = count_end - sleep_start
            self.logger.info(f"[MEASURE_END] {self.name} count={pulse_count} elapsed={elapsed:.3f}s rate={pulse_count/elapsed:.1f}/s expected_rate=120.0/s loss={pulse_loss_pct:.1f}%")
            return (pulse_count, elapsed)
            
        except Exception as e:
            self.consecutive_errors += 1
            self.logger.error(f"{self.name} pulse counting error: {e}")
            return (0, 0.0)
    
    def calculate_frequency_regression(self, pulse_count: int, duration: float = None) -> Optional[float]:
        """
        Calculate AC frequency using linear regression on all pulse timestamps.
        This method uses all timestamps to reduce the impact of individual timestamp jitter.
        
        Args:
            pulse_count: Number of pulses counted (used for validation)
            duration: Requested duration in seconds (used for logging)
            
        Returns:
            Calculated frequency in Hz, or None if invalid
        """
        if pulse_count < 2:
            return None
        
        try:
            # Retrieve full list of timestamps
            timestamps_ns = self.counter.get_timestamps(self.pin)
            
            if len(timestamps_ns) < 2:
                return None
            
            # Convert timestamps to relative time in seconds (starting from 0)
            t_first = timestamps_ns[0]
            times_sec = np.array([(ts - t_first) / 1e9 for ts in timestamps_ns])
            
            # Create pulse indices (0, 1, 2, ..., n-1)
            pulse_indices = np.arange(len(timestamps_ns))
            
            # Perform linear regression: time = slope * index + intercept
            # We want to find the slope (seconds per pulse interval)
            try:
                slope, intercept = np.polyfit(pulse_indices, times_sec, 1)
            except Exception as e:
                self.logger.warning(f"{self.name} regression polyfit failed: {e}")
                return None
            
            # Slope represents seconds per pulse interval
            # Frequency = 1 / (slope * pulses_per_cycle)
            if slope <= 0:
                self.logger.warning(f"{self.name} invalid regression slope: {slope}")
                return None
            
            frequency = 1.0 / (slope * self.pulses_per_cycle)
            
            # Sanity check (40-80Hz range) to prevent gross outliers
            if 40 <= frequency <= 80:
                self.logger.debug(f"{self.name} regression frequency: {frequency:.3f} Hz (from {len(timestamps_ns)} timestamps)")
                return frequency
            else:
                self.logger.warning(f"{self.name} regression frequency {frequency:.3f} Hz out of range")
                return None
                
        except Exception as e:
            self.logger.warning(f"{self.name} regression calculation failed: {e}")
            return None
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None, actual_duration: float = None) -> Optional[float]:
        """
        Calculate AC frequency from pulse count using correct libgpiod calculation.
        
        Args:
            pulse_count: Number of pulses counted
            duration: Requested duration in seconds (uses config default if None, used for logging)
            actual_duration: Actual measured duration in seconds (if None, uses duration parameter)
                           Use this for accurate frequency calculation based on actual elapsed time
            
        Returns:
            Calculated frequency in Hz, or None if invalid
        """
        if duration is None:
            duration = self.measurement_duration
        
        # Use actual_duration if provided, otherwise fall back to requested duration
        measurement_duration = actual_duration if actual_duration is not None else duration
        
        if pulse_count <= 0 or measurement_duration <= 0:
            return None
        
        # Calculate regression-based frequency if enabled for comparison
        freq_regression = None
        if ENABLE_REGRESSION_COMPARISON:
            freq_regression = self.calculate_frequency_regression(pulse_count, duration)
        
        # METHOD 1: Precise Timestamp Interval Analysis
        # This method eliminates synchronization errors between CPU sleep time and pulse arrival.
        # It calculates frequency based on the exact time elapsed between the first and last pulse.
        # Frequency = (Count - 1) / (Last_Timestamp - First_Timestamp)
        # This is the "raw" frequency of the observed pulse train without any median filtering.
        
        # Use the stats retrieved in count_optocoupler_pulses if available
        # (This assumes count_optocoupler_pulses was called just before this)
        freq_first_last = None
        try:
            stat_count, t_first, t_last = self.counter.get_frequency_info(self.pin)
            self.logger.debug(f"Timestamp debug: count={stat_count}, duration_ns={t_last - t_first if stat_count > 1 else 0}")
            
            if stat_count >= 2:
                # Calculate total duration of the observed pulses
                duration_ns = t_last - t_first
                duration_sec = duration_ns / 1e9
                
                # Calculate number of full intervals observed
                # If we have N pulses, we have N-1 intervals between them
                num_intervals = stat_count - 1
                
                if duration_ns > 0 and num_intervals > 0:
                    # Calculate frequency: Intervals / Duration
                    # Convert duration from ns to seconds (1e9)
                    # We use a divisor of 2 because:
                    # 1. H11AA1 generates 2 zero-crossing pulses per AC cycle (0 deg and 180 deg)
                    # 2. The pulses are very narrow (~33us).
                    # 3. Our 0.2ms debounce filters out the falling edge of each pulse.
                    # 4. Therefore, we count exactly 1 rising edge per zero-crossing.
                    # Total: 2 events per AC cycle.
                    freq_first_last = (num_intervals * 1e9) / (duration_ns * self.pulses_per_cycle)
                    
                    # Log detailed calculation breakdown
                    self.logger.debug(f"[FREQ_CALC_FIRST_LAST] {self.name} stat_count={stat_count} num_intervals={num_intervals} duration_ns={duration_ns} duration_sec={duration_sec:.6f} pulses_per_cycle={self.pulses_per_cycle} calculated={freq_first_last:.6f} Hz")
                    
                    # Sanity check (40-80Hz range) to prevent gross outliers from single glitches
                    if 40 <= freq_first_last <= 80:
                        self.logger.debug(f"{self.name} precision frequency: {freq_first_last:.3f} Hz (from {stat_count} pulses over {duration_sec:.3f}s)")
                    else:
                        self.logger.warning(f"{self.name} precision frequency {freq_first_last:.3f} Hz out of range, falling back to average")
                        freq_first_last = None
        except Exception as e:
            self.logger.warning(f"{self.name} timestamp analysis failed: {e}")
        
        # Log comparison if both methods succeeded and comparison is enabled
        if ENABLE_REGRESSION_COMPARISON and freq_first_last is not None and freq_regression is not None:
            diff = abs(freq_regression - freq_first_last)
            diff_pct = (diff / freq_first_last) * 100 if freq_first_last > 0 else 0
            self.logger.info(f"{self.name} frequency comparison: First/Last={freq_first_last:.6f} Hz, Regression={freq_regression:.6f} Hz, Diff={diff:.6f} Hz ({diff_pct:.3f}%)")
        
        # Use regression result if enabled and available, otherwise use first/last
        if USE_REGRESSION_FOR_RESULT and freq_regression is not None:
            return freq_regression
        elif freq_first_last is not None:
            return freq_first_last

        # METHOD 2: Average Frequency (Fallback)
        # Calculate frequency using correct libgpiod calculation for AC-into-DC-optocoupler
        # H11AA1 with AC input: optocoupler output is a square wave that transitions on each zero-crossing
        # libgpiod counts BOTH rising and falling edges (Edge.BOTH detection)
        # For 60 Hz AC: we get 4 edges per cycle (rising at +zero, falling at -zero, rising at +zero, falling at -zero)
        # Actual measurement confirms: 240 edges/second = 60 Hz * 4 edges/cycle
        # So we divide by 4 to convert edge count to frequency
        # UPDATE: With 0.2ms debounce, we filter the falling edge (pulse width ~33us).
        # So we count 2 edges per cycle.
        frequency = pulse_count / (measurement_duration * self.pulses_per_cycle)  # 2 edges per AC cycle (Debounced)
        
        # Log detailed calculation breakdown
        divisor = measurement_duration * self.pulses_per_cycle
        self.logger.debug(f"[FREQ_CALC_AVERAGE] {self.name} pulse_count={pulse_count} measurement_duration={measurement_duration:.6f} pulses_per_cycle={self.pulses_per_cycle} divisor={divisor:.6f} calculated={frequency:.6f} Hz")
        
        if actual_duration is not None and abs(actual_duration - duration) > 0.001:
            self.logger.debug(f"{self.name} calculated frequency: {frequency:.3f} Hz from {pulse_count} pulses in {actual_duration:.3f}s (requested: {duration:.3f}s)")
        else:
            self.logger.debug(f"{self.name} calculated frequency: {frequency:.3f} Hz from {pulse_count} pulses in {measurement_duration:.2f}s")
        return frequency
    
    def check_health(self) -> bool:
        """Check optocoupler health and attempt recovery if needed."""
        current_time = time.time()
        
        # Only check health periodically
        if current_time - self.last_health_check < self.health_check_interval:
            return True
        
        self.last_health_check = current_time
        
        try:
            # Perform a quick test read
            test_count = self.counter.get_count(self.pin)
            
            # Check if counter is responding
            if test_count >= 0:  # Valid count
                self.consecutive_errors = 0
                self.logger.debug(f"{self.name} health check passed: count={test_count}")
                return True
            else:
                self.consecutive_errors += 1
                self.logger.warning(f"{self.name} health check failed: invalid count={test_count}")
                
        except Exception as e:
            self.consecutive_errors += 1
            self.logger.warning(f"{self.name} health check failed: {e}")
        
        # Attempt recovery if too many consecutive errors
        if self.consecutive_errors >= self.max_consecutive_errors:
            return self._attempt_recovery()
        
        return True
    
    def _attempt_recovery(self) -> bool:
        """Attempt to recover from optocoupler failure."""
        if self.recovery_attempts >= self.max_recovery_attempts:
            self.logger.critical(f"{self.name} optocoupler recovery failed after {self.max_recovery_attempts} attempts")
            return False
        
        self.recovery_attempts += 1
        self.logger.warning(f"{self.name} attempting recovery (attempt {self.recovery_attempts}/{self.max_recovery_attempts})")
        
        try:
            # Reset counter
            self.counter.reset_count(self.pin)
            
            # Re-setup optocoupler
            self._setup_optocoupler()
            
            # Test with a short measurement
            try:
                test_pulses, test_elapsed = self.count_optocoupler_pulses(0.5)  # 0.5 second test

                if test_pulses >= 0:
                    self.consecutive_errors = 0
                    self.logger.info(f"{self.name} recovery successful: {test_pulses} pulses in {test_elapsed:.3f}s")
                    return True
                else:
                    self.logger.warning(f"{self.name} recovery test failed: {test_pulses} pulses")
                    return False
            except Exception as e:
                self.logger.error(f"{self.name} recovery test failed with exception: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"{self.name} recovery attempt failed: {e}")
            return False
    
    def is_healthy(self) -> bool:
        """Check if optocoupler is currently healthy."""
        return self.consecutive_errors < self.max_consecutive_errors and self.initialized
    
    def cleanup(self):
        """Cleanup optocoupler resources."""
        if self.gpio_available and self.initialized:
            try:
                # Cleanup libgpiod counter
                if self.counter:
                    self.counter.cleanup()
                self.logger.info(f"{self.name} optocoupler cleanup completed")
            except Exception as e:
                self.logger.error(f"{self.name} optocoupler cleanup error: {e}")


class OptocouplerManager:
    """Manages one or more optocouplers for frequency measurement with graceful degradation."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.gpio_available = GPIO_AVAILABLE
        
        # Get optocoupler configuration
        try:
            optocoupler_config = config['hardware']['optocoupler']
            self.optocoupler_enabled = optocoupler_config['enabled']
        except KeyError as e:
            raise KeyError(f"Missing required configuration key: {e}")
        
        
        # Initialize optocouplers
        self.optocouplers = {}
        self.optocoupler_initialized = False
        self.cpu_affinity_set = False
        
        # Thread priority optimization
        self._setup_thread_priority()
        
        if self.optocoupler_enabled:
            self._setup_optocouplers()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.cleanup()
        return False  # Don't suppress exceptions
    
    def _setup_optocouplers(self):
        """Setup optocouplers based on configuration."""
        if not self.optocoupler_enabled:
            self.logger.info("Optocoupler disabled, skipping setup")
            return
            
        try:
            optocoupler_config = self.config['hardware']['optocoupler']
            
            # Always setup primary optocoupler
            primary_config = optocoupler_config['primary']
            primary_pin = primary_config['gpio_pin']
            primary_pulses = primary_config['pulses_per_cycle']
            primary_duration = primary_config['measurement_duration']
            primary_name = primary_config['name']
        except KeyError as e:
            raise KeyError(f"Missing required configuration key: {e}")
        
        self.optocouplers['primary'] = SingleOptocoupler(
            self.config, self.logger, primary_name, primary_pin, 
            primary_pulses, primary_duration
        )
        self.logger.info(f"Optocoupler configured on pin {primary_pin}")
        
        # Check if optocoupler was initialized
        self.optocoupler_initialized = self.optocouplers['primary'].initialized
        self.logger.info(f"Optocoupler setup complete. Initialized: {self.optocoupler_initialized}")
        
        # Build inverter mapping for each optocoupler
        self._build_inverter_mapping()
    
    def _build_inverter_mapping(self):
        """Build mapping of optocouplers to their associated inverters."""
        self.inverter_mapping = {}
        
        try:
            optocoupler_config = self.config['hardware']['optocoupler']
            
            # Process primary optocoupler inverters
            primary_config = optocoupler_config['primary']
            primary_inverters = primary_config.get('inverters')
            
            # Handle backward compatibility - if old format exists, convert it
            if 'solark_inverter_id' in primary_config and primary_config['solark_inverter_id']:
                primary_inverters = [{
                    'id': primary_config['solark_inverter_id'],
                    'name': f"{primary_config['name']} Inverter",
                    'enabled': True
                }]
                self.logger.info("Converted legacy single inverter config to new multi-inverter format")
            
            self.inverter_mapping['primary'] = []
            if primary_inverters:
                for inverter in primary_inverters:
                    if inverter.get('id') and inverter.get('enabled', True):
                        self.inverter_mapping['primary'].append({
                            'id': inverter['id'],
                            'name': inverter.get('name', f"Inverter {inverter['id']}"),
                            'enabled': inverter.get('enabled', True)
                        })
                        self.logger.info(f"Optocoupler mapped to inverter: {inverter['id']} ({inverter.get('name', 'Unnamed')})")
                
        except KeyError as e:
            self.logger.warning(f"Missing inverter configuration: {e}")
            self.inverter_mapping = {'primary': []}
    
    def get_inverters_for_optocoupler(self, optocoupler_name: str) -> List[dict]:
        """
        Get list of inverters associated with a specific optocoupler.
        
        Args:
            optocoupler_name: 'primary' (only primary is supported)
            
        Returns:
            List of inverter dictionaries with 'id', 'name', and 'enabled' keys
        """
        if optocoupler_name != 'primary':
            self.logger.warning(f"Only 'primary' optocoupler is supported, got '{optocoupler_name}'")
            return []
        return self.inverter_mapping.get(optocoupler_name, [])
    
    def get_all_inverters(self) -> List[dict]:
        """
        Get all inverters from all optocouplers.
        
        Returns:
            List of all inverter dictionaries with optocoupler context
        """
        all_inverters = []
        
        for optocoupler_name, inverters in self.inverter_mapping.items():
            for inverter in inverters:
                inverter_with_context = inverter.copy()
                inverter_with_context['optocoupler'] = optocoupler_name
                all_inverters.append(inverter_with_context)
        
        return all_inverters
    
    def get_enabled_inverters(self) -> List[dict]:
        """
        Get all enabled inverters from all optocouplers.
        
        Returns:
            List of enabled inverter dictionaries with optocoupler context
        """
        return [inv for inv in self.get_all_inverters() if inv.get('enabled', True)]
    
    def _setup_thread_priority(self):
        """Setup high-priority threading and CPU affinity for optocoupler measurements."""
        try:
            # Set current process to high priority (safe for RPi 4)
            current_process = psutil.Process()
            
            # Set process priority to high (but not realtime to avoid system issues)
            if hasattr(psutil, 'HIGH_PRIORITY_CLASS'):
                current_process.nice(psutil.HIGH_PRIORITY_CLASS)
                self.logger.info("Set process priority to HIGH")
            else:
                # On Linux, use nice value (-10 to 19, lower = higher priority)
                # Use -5 for high priority (safe for RPi 4)
                os.nice(-5)
                self.logger.info("Set process nice value to -5 (high priority)")
            
            # Set CPU affinity to single core for consistent timing (RPi4 optimization)
            if not self.cpu_affinity_set:
                try:
                    # Pin to CPU core 3 (last core) to avoid interference with system processes
                    current_process.cpu_affinity([3])
                    self.cpu_affinity_set = True
                    self.logger.info("Set CPU affinity to core 3 for consistent timing")
                except (OSError, ValueError) as e:
                    self.logger.warning(f"Could not set CPU affinity: {e}")
                    # Try core 2 as fallback
                    try:
                        current_process.cpu_affinity([2])
                        self.cpu_affinity_set = True
                        self.logger.info("Set CPU affinity to core 2 for consistent timing")
                    except (OSError, ValueError):
                        self.logger.warning("Could not set CPU affinity, continuing with default")
                
        except (PermissionError, OSError) as e:
            self.logger.warning(f"Could not set high priority: {e}")
            self.logger.info("Continuing with normal priority")
        except Exception as e:
            self.logger.warning(f"Thread priority setup failed: {e}")
    
    def start_measurement(self, duration: float = None, optocoupler_name: str = 'primary') -> bool:
        """
        Start a non-blocking measurement window.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            optocoupler_name: Name of optocoupler to use ('primary' only)
            
        Returns:
            True if measurement started successfully, False otherwise
        """
        if not self.optocoupler_enabled:
            self.logger.debug("Optocoupler disabled, cannot start measurement")
            return False
            
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return False
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.start_measurement(duration)
    
    def check_measurement(self, optocoupler_name: str = 'primary') -> Tuple[bool, Optional[int], Optional[float]]:
        """
        Check if the current measurement window has elapsed.
        
        Args:
            optocoupler_name: Name of optocoupler to use ('primary' only)
            
        Returns:
            Tuple of (is_complete, pulse_count, actual_elapsed_time):
            - is_complete: True if measurement is complete, False if still in progress
            - pulse_count: Number of pulses counted (None if not complete)
            - actual_elapsed_time: Actual elapsed time in seconds (None if not complete)
        """
        if not self.optocoupler_enabled:
            self.logger.debug("Optocoupler disabled, measurement not available")
            return (False, None, None)
            
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return (False, None, None)
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.check_measurement()
    
    def count_optocoupler_pulses(self, duration: float = None, 
                                optocoupler_name: str = 'primary') -> Tuple[int, float]:
        """
        Count optocoupler pulses over specified duration using working libgpiod.
        BLOCKING VERSION - Use start_measurement()/check_measurement() for non-blocking operation.
        Uses interrupt-based counting for maximum accuracy.
        
        Args:
            duration: Duration in seconds to count pulses (uses config default if None)
            optocoupler_name: Name of optocoupler to use ('primary' only)
            
        Returns:
            Tuple of (pulse_count, actual_elapsed_time)
        """
        if not self.optocoupler_enabled:
            self.logger.debug("Optocoupler disabled, returning 0 pulses")
            return (0, 0.0)
            
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return (0, 0.0)
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.count_optocoupler_pulses(duration)
    
    def calculate_frequency_from_pulses(self, pulse_count: int, duration: float = None, 
                                       optocoupler_name: str = 'primary', actual_duration: float = None) -> Optional[float]:
        """
        Calculate AC frequency from pulse count using working libgpiod calculation.
        
        Args:
            pulse_count: Number of pulses counted
            duration: Requested duration in seconds (uses config default if None, used for logging)
            optocoupler_name: Name of optocoupler to use ('primary' only)
            actual_duration: Actual measured duration in seconds (if None, uses duration parameter)
                           Use this for accurate frequency calculation based on actual elapsed time
            
        Returns:
            Calculated frequency in Hz, or None if invalid
        """
        if not self.optocoupler_enabled:
            self.logger.debug("Optocoupler disabled, returning None frequency")
            return None
            
        if optocoupler_name not in self.optocouplers:
            self.logger.warning(f"Optocoupler '{optocoupler_name}' not found")
            return None
        
        optocoupler = self.optocouplers[optocoupler_name]
        return optocoupler.calculate_frequency_from_pulses(pulse_count, duration, actual_duration)
    
    def get_available_optocouplers(self) -> List[str]:
        """Get list of available optocoupler names."""
        if not self.optocoupler_enabled:
            return []
        return [name for name, opt in self.optocouplers.items() if opt.initialized]
    
    def check_all_health(self) -> Dict[str, bool]:
        """Check health of all optocouplers."""
        health_status = {}
        for name, optocoupler in self.optocouplers.items():
            health_status[name] = optocoupler.check_health()
        return health_status
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status of all optocouplers."""
        status = {}
        for name, optocoupler in self.optocouplers.items():
            status[name] = {
                'healthy': optocoupler.is_healthy(),
                'initialized': optocoupler.initialized,
                'consecutive_errors': optocoupler.consecutive_errors,
                'max_consecutive_errors': optocoupler.max_consecutive_errors,
                'recovery_attempts': optocoupler.recovery_attempts,
                'last_successful_count': optocoupler.last_successful_count
            }
        return status
    
    def cleanup(self):
        """Cleanup optocoupler resources."""
        for name, optocoupler in self.optocouplers.items():
            try:
                optocoupler.cleanup()
                self.logger.info(f"Cleaned up {name} optocoupler")
            except Exception as e:
                self.logger.error(f"Error cleaning up {name} optocoupler: {e}")