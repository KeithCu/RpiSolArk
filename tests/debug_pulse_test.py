#!/usr/bin/env python3
"""
Debug script to analyze pulse detection and frequency calculation issues.
Runs for short duration (1-2 seconds) to collect timing data with enhanced logging.
Auto-detects non-RPi hardware and uses mock libgpiod with synthetic pulses.
"""

import sys
import os
import time
import logging
import threading

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gpio_event_counter import create_counter
from tests.test_utils_gpio import is_raspberry_pi, setup_mock_gpiod, inject_pulses, create_test_counter
from tests.pulse_patterns import generate_stable_60hz

def main():
    # Setup logging with DEBUG level to see all detailed logs
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    logger = logging.getLogger(__name__)

    # Check if running on RPi
    on_rpi = is_raspberry_pi()
    use_mock = not on_rpi
    
    if use_mock:
        logger.info("Not running on Raspberry Pi - using mock libgpiod with synthetic pulses")
        # Setup mock gpiod
        setup_mock_gpiod()
        counter, mock_chip = create_test_counter(logger, use_mock=True)
    else:
        logger.info("Running on Raspberry Pi - using real hardware")
        counter = create_counter(logger)
        mock_chip = None

    # Register pin 26 (same as config)
    pin = 26
    if not counter.register_pin(pin, debounce_ns=200000):  # 0.2ms debounce
        logger.error(f"Failed to register pin {pin}")
        return

    # Use short timeout (2 seconds) as requested
    duration = 2.0
    logger.info(f"Starting {duration}-second pulse capture with enhanced logging...")

    # Reset counters
    counter.reset_count(pin)

    # If using mock, inject synthetic pulses in background thread
    if use_mock and mock_chip:
        logger.info("Injecting synthetic 60Hz pulses...")
        start_time_ns = time.perf_counter_ns()
        timestamps = generate_stable_60hz(duration, pulses_per_cycle=2, start_time_ns=start_time_ns)
        
        def inject_pulses_thread():
            # Wait a bit for counter to be ready
            time.sleep(0.1)
            # Inject pulses gradually to simulate real-time behavior
            current_time_ns = time.perf_counter_ns()
            for ts_ns in timestamps:
                # Wait until it's time for this pulse
                if ts_ns > current_time_ns:
                    sleep_time = (ts_ns - current_time_ns) / 1e9
                    if sleep_time > 0 and sleep_time < 1.0:  # Don't sleep too long
                        time.sleep(sleep_time)
                
                # Inject the pulse
                inject_pulses(mock_chip, pin, [ts_ns])
                current_time_ns = time.perf_counter_ns()
        
        inject_thread = threading.Thread(target=inject_pulses_thread, daemon=True)
        inject_thread.start()

    # Capture for specified duration
    start_time = time.perf_counter()
    time.sleep(duration)
    end_time = time.perf_counter()
    
    # Wait for injection thread to finish if using mock
    if use_mock and mock_chip:
        inject_thread.join(timeout=0.5)

    actual_duration = end_time - start_time
    pulse_count = counter.get_count(pin)
    timestamps = counter.get_timestamps(pin)
    
    # Get event statistics
    event_stats = counter.get_event_statistics(pin)

    logger.info("=" * 80)
    logger.info("CAPTURE SUMMARY")
    logger.info("=" * 80)
    logger.info(f"  Duration: {actual_duration:.3f} seconds (requested: {duration:.3f}s)")
    logger.info(f"  Pulse count: {pulse_count}")
    logger.info(f"  Pulse rate: {pulse_count / actual_duration:.3f} pulses/second")
    logger.info(f"  Expected rate: 120.0 pulses/second (for 60Hz AC)")
    logger.info(f"  Timestamps collected: {len(timestamps)}")
    
    if event_stats:
        logger.info("=" * 80)
        logger.info("EVENT STATISTICS")
        logger.info("=" * 80)
        logger.info(f"  Events received from hardware: {event_stats['received']}")
        logger.info(f"  Events debounced/rejected: {event_stats['debounced']}")
        logger.info(f"  Events accepted: {event_stats['accepted']}")
        logger.info(f"  Final count: {event_stats['count']}")
        logger.info(f"  Timestamp count: {event_stats['timestamp_count']}")
        
        if event_stats.get('intervals'):
            intervals = event_stats['intervals']
            logger.info("=" * 80)
            logger.info("INTERVAL STATISTICS")
            logger.info("=" * 80)
            logger.info(f"  Interval count: {intervals['count']}")
            logger.info(f"  Min interval: {intervals['min_us']:.1f} μs ({intervals['min_ms']:.3f} ms)")
            logger.info(f"  Max interval: {intervals['max_us']:.1f} μs ({intervals['max_ms']:.3f} ms)")
            logger.info(f"  Mean interval: {intervals['mean_us']:.1f} μs ({intervals['mean_ms']:.3f} ms)")
            logger.info(f"  Median interval: {intervals['median_us']:.1f} μs ({intervals['median_ms']:.3f} ms)")
            logger.info(f"  Std deviation: {intervals['std_dev_us']:.1f} μs ({intervals['std_dev_ms']:.3f} ms)")
            
            # Expected interval for 60Hz AC (120 pulses/second)
            expected_interval_us = 1_000_000 / 120  # 8333.33 μs
            logger.info(f"  Expected interval (60Hz AC): {expected_interval_us:.2f} μs")
            interval_error_pct = abs(intervals['mean_us'] - expected_interval_us) / expected_interval_us * 100
            logger.info(f"  Interval error: {interval_error_pct:.2f}%")

    # Analyze timestamps
    if len(timestamps) > 1:
        # Calculate intervals between consecutive timestamps
        intervals_ns = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
        intervals_us = [ns / 1000 for ns in intervals_ns]

        logger.info("=" * 80)
        logger.info("FREQUENCY CALCULATION ANALYSIS")
        logger.info("=" * 80)
        
        # Test current calculation methods
        pulses_per_cycle = 2  # From config
        freq_current = pulse_count / (actual_duration * pulses_per_cycle)
        logger.info(f"  Current calculation (count/(duration*{pulses_per_cycle})): {freq_current:.3f} Hz")
        
        # Alternative calculation
        freq_alt = pulse_count / actual_duration
        logger.info(f"  Alternative calculation (count/duration): {freq_alt:.3f} Hz")
        
        # Calculate from interval statistics
        if event_stats and event_stats.get('intervals'):
            avg_interval_sec = event_stats['intervals']['mean_us'] / 1_000_000
            pulse_freq = 1.0 / avg_interval_sec
            ac_freq_from_intervals = pulse_freq / pulses_per_cycle
            logger.info(f"  Frequency from interval mean: {ac_freq_from_intervals:.3f} Hz")
        
        # Pulse loss analysis
        expected_pulses = int(actual_duration * 60 * pulses_per_cycle)  # 120 pulses/second * duration
        pulse_loss = expected_pulses - pulse_count
        pulse_loss_pct = (pulse_loss / expected_pulses) * 100 if expected_pulses > 0 else 0
        logger.info(f"  Expected pulses: {expected_pulses}")
        logger.info(f"  Actual pulses: {pulse_count}")
        logger.info(f"  Pulse loss: {pulse_loss} ({pulse_loss_pct:.1f}%)")
        
        logger.info("=" * 80)
        logger.info("FIRST 10 INTERVALS (for pattern analysis)")
        logger.info("=" * 80)
        logger.info(f"  {intervals_us[:10]} μs")

    # Cleanup
    counter.cleanup()
    logger.info("=" * 80)
    logger.info("Test complete")
    logger.info("=" * 80)

if __name__ == "__main__":
    main()