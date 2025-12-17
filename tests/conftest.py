#!/usr/bin/env python3
"""
Pytest configuration and fixtures for GPIO event counter tests.
Provides mock gpiod fixtures for testing without hardware.
"""

import pytest
import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.test_utils_gpio import is_raspberry_pi, setup_mock_gpiod, create_test_counter
from tests.mock_gpiod import mock_gpiod


@pytest.fixture(scope="session", autouse=True)
def auto_setup_mock_gpiod():
    """
    Automatically setup mock gpiod if not running on Raspberry Pi.
    This fixture runs once per test session and patches gpiod globally.
    """
    if not is_raspberry_pi():
        # Setup mock for non-RPi systems
        setup_mock_gpiod()
        yield
    else:
        # On RPi, use real hardware
        yield


@pytest.fixture
def mock_gpiod_module(monkeypatch):
    """
    Provide mock gpiod module for individual tests.
    Use this fixture if you need explicit control over mock setup.
    """
    return setup_mock_gpiod(monkeypatch)


@pytest.fixture
def test_logger():
    """Create a test logger."""
    logger = logging.getLogger('test')
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Add console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


@pytest.fixture
def counter_with_mock(test_logger, mock_gpiod_module):
    """
    Create GPIOEventCounter with mock gpiod.
    Returns tuple of (counter, mock_chip).
    """
    counter, mock_chip = create_test_counter(test_logger, use_mock=True, monkeypatch=None)
    yield counter, mock_chip
    counter.cleanup()


@pytest.fixture
def use_real_hardware():
    """
    Fixture to check if tests should use real hardware.
    Returns True only on Raspberry Pi.
    """
    return is_raspberry_pi()


# Pytest markers for test organization
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "hardware: marks tests that require real hardware"
    )
    config.addinivalue_line(
        "markers", "mock: marks tests that use mock hardware"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
