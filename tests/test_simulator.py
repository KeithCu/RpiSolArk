#!/usr/bin/env python3
"""
Test the simulator to verify it cycles through power states correctly.
"""

import sys
import os
import time
import logging

# Add parent directory to path so we can import monitor module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from monitor import FrequencyAnalyzer
from config import Config


def test_simulator_states():
    """Test that the simulator cycles through the expected states."""
    print("Testing Simulator State Cycling")
    print("=" * 40)

    # Setup
    config = Config("config.yaml")
    analyzer = FrequencyAnalyzer(config, logging.getLogger(__name__))

    # Test the 12-second cycle
    states_observed = []
    start_time = time.time()

    # Run for about 13 seconds to see a full cycle
    while time.time() - start_time < 13:
        freq = analyzer._simulate_frequency()
        states_observed.append((analyzer.simulator_state, freq))
        time.sleep(0.1)  # Small delay to not overwhelm

    # Analyze the observed states
    grid_count = sum(1 for state, _ in states_observed if state == "grid")
    off_grid_count = sum(1 for state, _ in states_observed if state == "off_grid")
    generator_count = sum(1 for state, _ in states_observed if state == "generator")

    print(f"Grid readings: {grid_count}")
    print(f"Off-grid readings: {off_grid_count}")
    print(f"Generator readings: {generator_count}")

    # Check frequency ranges
    grid_freqs = [freq for state, freq in states_observed if state == "grid" and freq is not None]
    generator_freqs = [freq for state, freq in states_observed if state == "generator" and freq is not None]
    off_grid_freqs = [freq for state, freq in states_observed if state == "off_grid" and freq is None]

    print(f"\nGrid frequencies: {len(grid_freqs)} readings")
    if grid_freqs:
        print(f"Min: {min(grid_freqs):.2f} Hz, Max: {max(grid_freqs):.2f} Hz")
        print(f"  All stable (59.9-60.1 Hz): {all(59.9 <= f <= 60.1 for f in grid_freqs)}")

    print(f"\nGenerator frequencies: {len(generator_freqs)} readings")
    if generator_freqs:
        print(f"Min: {min(generator_freqs):.2f} Hz, Max: {max(generator_freqs):.2f} Hz")
        print(f"  All variable (58.5-62.0 Hz): {all(58.5 <= f <= 62.0 for f in generator_freqs)}")

    print(f"\nOff-grid readings: {len(off_grid_freqs)} readings (should be None)")

    # Verify the cycling pattern
    success = True

    # Should have grid > others since there are 2 grid periods in the 12s cycle
    # Grid: 6s total (0-3s, 9-12s), Off-grid: 3s, Generator: 3s
    expected_grid_ratio = grid_count / max(1, (grid_count + off_grid_count + generator_count))
    if not (0.5 <= expected_grid_ratio <= 0.8):  # Grid should be ~50-67% of readings
        print("FAIL: Uneven state distribution")
        success = False
    else:
        print("PASS: States are cycling with correct proportions")

    # Grid should be stable
    if grid_freqs and not all(59.9 <= f <= 60.1 for f in grid_freqs):
        print("FAIL: Grid frequencies not stable")
        success = False
    else:
        print("PASS: Grid frequencies are stable")

    # Generator should be variable (not all in stable range)
    if generator_freqs and not any(f < 59.5 or f > 60.5 for f in generator_freqs):
        print("FAIL: Generator frequencies not variable enough")
        success = False
    else:
        print("PASS: Generator frequencies are variable")

    # Off-grid should have no frequency
    if len(off_grid_freqs) != off_grid_count:
        print("FAIL: Off-grid has frequency readings")
        success = False
    else:
        print("PASS: Off-grid has no frequency readings")

    print(f"\n{'SUCCESS' if success else 'FAILURE'}: Simulator test {'PASSED' if success else 'FAILED'}")
    return success


if __name__ == "__main__":
    success = test_simulator_states()
    sys.exit(0 if success else 1)
