#!/usr/bin/env python3
"""
Test the simulator to verify it cycles through power states correctly.
"""

import pytest
import time
import logging

# Add parent directory to path so we can import monitor module
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from monitor import FrequencyAnalyzer
from config import Config


@pytest.fixture
def config():
    """Create a config instance for testing."""
    return Config("config.yaml")


@pytest.fixture
def logger():
    """Create a logger for testing."""
    logger = logging.getLogger('test_simulator')
    logger.setLevel(logging.WARNING)  # Reduce log noise during tests
    return logger


@pytest.fixture
def analyzer(config, logger):
    """Create a FrequencyAnalyzer instance for testing."""
    return FrequencyAnalyzer(config, logger)


def test_simulator_state_cycling(analyzer):
    """Test that the simulator cycles through the expected states."""
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

    # Check frequency ranges
    grid_freqs = [freq for state, freq in states_observed if state == "grid" and freq is not None]
    generator_freqs = [freq for state, freq in states_observed if state == "generator" and freq is not None]
    off_grid_freqs = [freq for state, freq in states_observed if state == "off_grid" and freq is None]

    # Verify the cycling pattern
    # Should have grid > others since there are 2 grid periods in the 12s cycle
    # Grid: 6s total (0-3s, 9-12s), Off-grid: 3s, Generator: 3s
    expected_grid_ratio = grid_count / max(1, (grid_count + off_grid_count + generator_count))
    assert 0.5 <= expected_grid_ratio <= 0.8, "States are not cycling with correct proportions"

    # Grid should be stable
    if grid_freqs:
        assert all(59.9 <= f <= 60.1 for f in grid_freqs), "Grid frequencies not stable"

    # Generator should be variable (not all in stable range)
    if generator_freqs:
        assert any(f < 59.5 or f > 60.5 for f in generator_freqs), "Generator frequencies not variable enough"

    # Off-grid should have no frequency
    assert len(off_grid_freqs) == off_grid_count, "Off-grid has frequency readings"


def test_simulator_frequency_ranges(analyzer):
    """Test that simulator produces frequencies in expected ranges."""
    # Collect samples from different states
    grid_freqs = []
    generator_freqs = []
    off_grid_count = 0

    # Run for a longer period to get samples from all states
    start_time = time.time()
    while time.time() - start_time < 30:  # 30 seconds covers multiple cycles
        freq = analyzer._simulate_frequency()
        state = analyzer.simulator_state

        if state == "grid" and freq is not None:
            grid_freqs.append(freq)
        elif state == "generator" and freq is not None:
            generator_freqs.append(freq)
        elif state == "off_grid" and freq is None:
            off_grid_count += 1

        time.sleep(0.05)  # Faster sampling for more data

    # Verify frequency ranges (accounting for random noise)
    if grid_freqs:
        # Grid should be very stable around 60 Hz
        assert all(59.8 <= f <= 60.2 for f in grid_freqs), f"Grid frequencies out of range: {grid_freqs[:10]}..."

    if generator_freqs:
        # Generator can vary more widely due to hunting and noise
        # Base range: 58.0-61.5, with gauss(0, 0.3) noise can extend this
        assert all(57.5 <= f <= 62.5 for f in generator_freqs), f"Generator frequencies out of range: {generator_freqs[:10]}..."

    assert off_grid_count > 0, "No off-grid periods detected"
