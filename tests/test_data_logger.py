#!/usr/bin/env python3
"""
Tests for DataLogger class - handles CSV logging functionality.
"""

import pytest
import csv
import os
import tempfile
import time
from unittest.mock import Mock, patch

# Add parent directory to path so we can import monitor module
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_logger import DataLogger
from config import Config


@pytest.fixture
def config():
    """Create a config instance for testing."""
    return Config("config.yaml")


@pytest.fixture
def logger():
    """Create a logger for testing."""
    import logging
    logger = logging.getLogger('test_data_logger')
    logger.setLevel(logging.WARNING)
    return logger


@pytest.fixture
def data_logger(config, logger):
    """Create a DataLogger instance for testing."""
    return DataLogger(config, logger)


@pytest.fixture
def temp_csv_file():
    """Create a temporary CSV file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        yield f.name
    # Cleanup
    try:
        os.unlink(f.name)
    except:
        pass


def test_data_logger_initialization(data_logger, config):
    """Test DataLogger initializes with correct configuration."""
    assert hasattr(data_logger, 'config')
    assert hasattr(data_logger, 'logger')
    assert hasattr(data_logger, 'detailed_logging_enabled')
    assert hasattr(data_logger, 'detailed_log_file')
    assert hasattr(data_logger, 'detailed_log_interval')


def test_enable_detailed_logging(data_logger):
    """Test enabling detailed logging with custom parameters."""
    log_file = "test_detailed.csv"
    interval = 5.0

    data_logger.enable_detailed_logging(log_file=log_file, interval=interval)

    assert data_logger.detailed_logging_enabled == True
    assert data_logger.detailed_log_file == log_file
    assert data_logger.detailed_log_interval == interval


def test_log_detailed_frequency_data_disabled(data_logger):
    """Test that detailed logging does nothing when disabled."""
    # Ensure detailed logging is disabled
    data_logger.detailed_logging_enabled = False

    # This should not raise an error and should not create any files
    data_logger.log_detailed_frequency_data(
        freq=60.0,
        analysis_results={'allan_variance': 1e-9, 'std_deviation': 0.1, 'kurtosis': 0.5},
        source="Utility Grid",
        sample_count=100,
        buffer_size=50,
        start_time=1000.0
    )


def test_enable_detailed_logging_functionality(data_logger):
    """Test that enable_detailed_logging configures the logger correctly."""
    log_file = "test_detailed.csv"
    interval = 5.0

    data_logger.enable_detailed_logging(log_file=log_file, interval=interval)

    assert data_logger.detailed_logging_enabled == True
    assert data_logger.detailed_log_file == log_file
    assert data_logger.detailed_log_interval == interval


def test_log_hourly_status(data_logger, config):
    """Test hourly status logging to CSV."""
    with tempfile.TemporaryDirectory() as temp_dir:
        hourly_log_file = os.path.join(temp_dir, "test_hourly.csv")

        # Set the hourly log file directly
        data_logger.hourly_log_file = hourly_log_file

        timestamp = "2024-01-01 12:00:00"
        state_info = {
            'current_state': 'grid',
            'previous_state': 'off_grid',
            'state_duration': 3600.0,
            'transition_timeout': 30.0
        }

        data_logger.log_hourly_status(
            timestamp=timestamp,
            freq=60.0,
            source="Utility Grid",
            std_freq=0.05,
            kurtosis=0.2,
            sample_count=7200,
            state_info=state_info
        )

        # Verify file was created and has correct content
        assert os.path.exists(hourly_log_file)

        with open(hourly_log_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            assert len(rows) == 1
            row = rows[0]
            assert row['timestamp'] == timestamp
            assert row['frequency_hz'] == '60.00'
            assert row['source'] == 'Utility Grid'
            assert row['std_dev_hz'] == '0.0500'
            assert row['kurtosis'] == '0.20'
            assert row['samples_processed'] == '7200'
            assert row['power_state'] == 'grid'
            assert row['state_duration_seconds'] == '3600.0'


def test_log_hourly_status_no_state_info(data_logger):
    """Test hourly status logging without state info."""
    with tempfile.TemporaryDirectory() as temp_dir:
        hourly_log_file = os.path.join(temp_dir, "test_hourly.csv")

        # Set the hourly log file directly
        data_logger.hourly_log_file = hourly_log_file

        timestamp = "2024-01-01 12:00:00"

        data_logger.log_hourly_status(
            timestamp=timestamp,
            freq=60.0,
            source="Utility Grid",
            std_freq=0.05,
            kurtosis=0.2,
            sample_count=7200
        )

        # Verify file was created
        assert os.path.exists(hourly_log_file)

        with open(hourly_log_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            assert len(rows) == 1
            row = rows[0]
            assert row['timestamp'] == timestamp
            # State info columns should be empty or have defaults
            assert row.get('current_state', '') == ''
            assert row.get('previous_state', '') == ''
            assert row.get('state_duration', '') == ''


def test_log_hourly_status_file_error(data_logger):
    """Test hourly status logging handles file errors gracefully."""
    # Set invalid path directly
    data_logger.hourly_log_file = "/invalid/path/that/does/not/exist/hourly.csv"

    # This should not raise an exception
    data_logger.log_hourly_status(
        timestamp="2024-01-01 12:00:00",
        freq=60.0,
        source="Utility Grid",
        std_freq=0.05,
        kurtosis=0.2,
        sample_count=7200
    )


def test_detailed_logging_configuration(data_logger):
    """Test detailed logging configuration."""
    # Test default state
    assert data_logger.detailed_logging_enabled == False

    # Test enabling with custom settings
    data_logger.enable_detailed_logging(log_file="custom.csv", interval=2.5)
    assert data_logger.detailed_logging_enabled == True
    assert data_logger.detailed_log_file == "custom.csv"
    assert data_logger.detailed_log_interval == 2.5
