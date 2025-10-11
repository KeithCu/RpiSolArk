#!/usr/bin/env python3
"""
Tests for HealthMonitor and MemoryMonitor classes.
"""

import pytest
import time
import psutil
import os
from collections import deque
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path so we can import monitor module
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from health import HealthMonitor, MemoryMonitor
from config import Config


@pytest.fixture
def config():
    """Create a config instance for testing."""
    return Config("config.yaml")


@pytest.fixture
def logger():
    """Create a logger for testing."""
    import logging
    logger = logging.getLogger('test_health_monitor')
    logger.setLevel(logging.WARNING)
    return logger


@pytest.fixture
def health_monitor(config, logger):
    """Create a HealthMonitor instance for testing."""
    return HealthMonitor(config, logger)


@pytest.fixture
def memory_monitor(config, logger):
    """Create a MemoryMonitor instance for testing."""
    return MemoryMonitor(config, logger)


def test_health_monitor_initialization(health_monitor):
    """Test HealthMonitor initializes correctly."""
    assert hasattr(health_monitor, 'config')
    assert hasattr(health_monitor, 'logger')
    assert hasattr(health_monitor, 'last_activity')
    assert hasattr(health_monitor, 'watchdog_timeout')

    # Should have recorded initial activity
    assert health_monitor.last_activity > 0
    assert health_monitor.running == True


def test_health_monitor_stop(health_monitor):
    """Test that stop method works without error."""
    # Should not raise any exceptions
    health_monitor.stop()
    assert health_monitor.running == False


# Memory Monitor Tests

def test_memory_monitor_initialization(memory_monitor):
    """Test MemoryMonitor initializes correctly."""
    assert hasattr(memory_monitor, 'config')
    assert hasattr(memory_monitor, 'logger')
    assert hasattr(memory_monitor, 'process')
    assert hasattr(memory_monitor, 'memory_history')
    assert hasattr(memory_monitor, 'last_cleanup_time')
    assert hasattr(memory_monitor, 'cleanup_interval')

    # Check memory history is a deque
    assert isinstance(memory_monitor.memory_history, deque)


def test_memory_monitor_get_memory_info(memory_monitor):
    """Test getting memory information."""
    info = memory_monitor.get_memory_info()

    # Should return a dictionary with memory info
    assert isinstance(info, dict)
    assert 'timestamp' in info
    assert 'process_memory_mb' in info
    assert 'system_memory_percent' in info
    assert 'gc_objects' in info

    # Values should be reasonable
    assert info['timestamp'] > 0
    assert info['process_memory_mb'] > 0
    assert 0 <= info['system_memory_percent'] <= 100


def test_memory_monitor_get_memory_summary(memory_monitor):
    """Test memory summary string generation."""
    summary = memory_monitor.get_memory_summary()

    assert isinstance(summary, str)
    assert "MB" in summary or "GB" in summary  # Should contain memory units


def test_memory_monitor_threshold_checking_warning(memory_monitor):
    """Test memory threshold checking logs warning."""
    # Mock logger to capture warning calls
    with patch.object(memory_monitor.logger, 'warning') as mock_warning:
        # Test with warning status
        memory_info = {
            'process_memory_mb': 600.0,  # Above warning threshold (500MB)
            'system_memory_percent': 50.0,
            'process_status': 'warning'
        }

        memory_monitor.check_memory_thresholds(memory_info)
        mock_warning.assert_called_once()


def test_memory_monitor_threshold_checking_critical(memory_monitor):
    """Test memory threshold checking logs critical."""
    # Mock logger to capture critical calls
    with patch.object(memory_monitor.logger, 'critical') as mock_critical:
        # Test with critical status
        memory_info = {
            'process_memory_mb': 1200.0,  # Above critical threshold (1000MB)
            'system_memory_percent': 50.0,
            'process_status': 'critical'
        }

        memory_monitor.check_memory_thresholds(memory_info)
        mock_critical.assert_called_once()


def test_memory_monitor_threshold_checking_normal(memory_monitor):
    """Test memory threshold checking with normal usage."""
    # Mock logger
    with patch.object(memory_monitor.logger, 'warning') as mock_warning:
        with patch.object(memory_monitor.logger, 'critical') as mock_critical:
            # Test with normal status
            memory_info = {
                'process_memory_mb': 100.0,  # Normal usage
                'system_memory_percent': 50.0,
                'process_status': 'normal'
            }

            memory_monitor.check_memory_thresholds(memory_info)

            # Should not log any warnings or critical messages
            mock_warning.assert_not_called()
            mock_critical.assert_not_called()


def test_memory_monitor_perform_cleanup(memory_monitor):
    """Test memory cleanup operations."""
    # Mock time to control cleanup timing
    with patch('time.time') as mock_time:
        # Set last cleanup to be old
        memory_monitor.last_cleanup_time = 0
        mock_time.return_value = 4000  # 4000 seconds later (past default 3600s interval)

        # Mock garbage collection
        with patch('gc.collect') as mock_gc:
            result = memory_monitor.perform_cleanup()

            # Should have called garbage collection and returned True
            mock_gc.assert_called_once()
            assert result == True

            # Should have updated last cleanup time
            assert memory_monitor.last_cleanup_time == 4000


def test_memory_monitor_cleanup_timing(memory_monitor):
    """Test that cleanup respects timing intervals."""
    with patch('time.time') as mock_time:
        # Set last cleanup to be recent
        memory_monitor.last_cleanup_time = 100
        mock_time.return_value = 150  # Only 50 seconds later

        # Mock garbage collection
        with patch('gc.collect') as mock_gc:
            memory_monitor.perform_cleanup()

            # Should NOT have called garbage collection (too recent)
            mock_gc.assert_not_called()


@patch('psutil.virtual_memory')
def test_memory_monitor_log_memory_to_csv(mock_vmem, memory_monitor, tmp_path):
    """Test logging memory info to CSV file."""
    # Mock memory info
    mock_memory = Mock()
    mock_memory.total = 8 * 1024**3  # 8 GB
    mock_memory.available = 4 * 1024**3  # 4 GB
    mock_memory.percent = 50.0
    mock_memory.used = 4 * 1024**3  # 4 GB
    mock_vmem.return_value = mock_memory

    # Create test CSV file path
    csv_file = tmp_path / "test_memory.csv"

    # Mock config to return our test file path
    with patch.object(memory_monitor.config, 'get') as mock_get:
        mock_get.return_value = str(csv_file)

        memory_monitor.log_memory_to_csv(str(csv_file))

        # Verify file was created
        assert csv_file.exists()

        # Read and verify content
        import csv
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            assert len(rows) == 1
            row = rows[0]

            # Check that key fields are present
            assert 'timestamp' in row
            assert 'process_memory_mb' in row
            assert 'system_memory_percent' in row
            assert 'process_status' in row

            # Check values are reasonable
            assert float(row['process_memory_mb']) > 0
            assert float(row['system_memory_percent']) >= 0


def test_memory_monitor_log_memory_csv_error(memory_monitor):
    """Test that CSV logging handles file errors gracefully."""
    # Try to log to an invalid path
    invalid_path = "/invalid/path/that/does/not/exist/memory.csv"

    # Should not raise an exception
    memory_monitor.log_memory_to_csv(invalid_path)


def test_health_monitor_combined_with_memory(memory_monitor, health_monitor):
    """Test that both monitors can work together."""
    # Get memory info
    mem_info = memory_monitor.get_memory_info()

    # Both should work without interfering
    assert isinstance(mem_info, dict)
    assert len(mem_info) > 0
    assert 'process_memory_mb' in mem_info
    assert 'system_memory_percent' in mem_info
