#!/usr/bin/env python3
"""
State Machine Tests for RpiSolark Frequency Monitor
Tests the power state machine transitions and functionality.
"""

import pytest
import logging
from pathlib import Path
from unittest.mock import patch

# Add parent directory to path so we can import monitor module
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from monitor import PowerState, PowerStateMachine
from config import Config


@pytest.fixture
def config():
    """Create a config instance for testing."""
    return Config("config.yaml")


@pytest.fixture
def logger():
    """Create a logger for testing."""
    logger = logging.getLogger('test_state_machine')
    logger.setLevel(logging.WARNING)  # Reduce log noise during tests
    return logger


@pytest.fixture
def state_machine(config, logger):
    """Create a PowerStateMachine instance for testing."""
    return PowerStateMachine(config, logger)


@pytest.mark.parametrize("frequency,power_source,zero_voltage_duration,expected_state,description", [
    (None, "Unknown", 6.0, PowerState.OFF_GRID, "No signal for 6 seconds"),
    (None, "Unknown", 2.0, PowerState.TRANSITIONING, "No signal for 2 seconds"),
    (59.8, "Utility Grid", 0.0, PowerState.GRID, "Stable utility power"),
    (60.2, "Utility Grid", 0.0, PowerState.GRID, "Stable utility power"),
    (58.5, "Generac Generator", 0.0, PowerState.GENERATOR, "Generator power detected"),
    (61.5, "Generac Generator", 0.0, PowerState.GENERATOR, "Generator power detected"),
    (60.0, "Unknown", 0.0, PowerState.TRANSITIONING, "Uncertain classification"),
    (None, "Unknown", 8.0, PowerState.OFF_GRID, "Extended no signal"),
])
def test_state_machine_transitions(state_machine, frequency, power_source, zero_voltage_duration, expected_state, description):
    """Test state machine transitions with various inputs."""
    state = state_machine.update_state(frequency, power_source, zero_voltage_duration)
    assert state == expected_state, f"Failed: {description}"


def test_state_transition_sequences(state_machine):
    """Test specific state transition sequences."""
    # Test: Off-grid -> Grid (power restoration)
    state_machine.update_state(None, "Unknown", 6.0)  # OFF_GRID
    assert state_machine.current_state == PowerState.OFF_GRID

    state_machine.update_state(60.0, "Utility Grid", 0.0)  # GRID
    assert state_machine.current_state == PowerState.GRID

    # Test: Grid -> Generator (generator starts)
    state_machine.update_state(58.5, "Generac Generator", 0.0)  # GENERATOR
    assert state_machine.current_state == PowerState.GENERATOR

    # Test: Generator -> Off-grid (power failure)
    state_machine.update_state(None, "Unknown", 6.0)  # OFF_GRID
    assert state_machine.current_state == PowerState.OFF_GRID


def test_state_timeout(state_machine):
    """Test transition timeout functionality."""
    import time

    # Put in transitioning state
    state_machine.update_state(None, "Unknown", 2.0)  # TRANSITIONING
    assert state_machine.current_state == PowerState.TRANSITIONING

    # Simulate timeout by manually setting state_entry_time
    state_machine.state_entry_time = time.time() - 35  # 35 seconds ago (past timeout)

    # This should trigger timeout and force OFF_GRID
    state_machine.update_state(None, "Unknown", 2.0)  # Should timeout
    assert state_machine.current_state == PowerState.OFF_GRID


def test_reset_button_config(config):
    """Test reset button configuration."""
    reset_pin = config['hardware']['reset_button']
    assert reset_pin == 22, f"Reset button pin should be 22, got {reset_pin}"
