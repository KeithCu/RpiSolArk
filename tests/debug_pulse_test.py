#!/usr/bin/env python3
"""
Debug script to analyze pulse detection and frequency calculation issues.
Runs for short duration (1-2 seconds) to collect timing data with enhanced logging.
"""

import sys
import time
import logging
from gpio_event_counter import create_counter

def main():
    # Setup logging with DEBUG level to see all detailed logs
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    logger = logging.getLogger(__name__)

    # Create counter
    counter = create_counter(logger)

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

    # Capture for specified duration
    start_time = time.perf_counter()
    time.sleep(duration)
    end_time = time.perf_counter()

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