#!/usr/bin/env python3
"""
Tests for FrequencyMonitor class - the main monitoring orchestrator.
"""

import pytest
import time
import logging
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from collections import deque

# Add parent directory to path so we can import monitor module
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor import FrequencyMonitor, PowerState
from config import Config


@pytest.fixture
def config():
    """Create a config instance for testing."""
    return Config("config.yaml")


@pytest.fixture
def logger():
    """Create a logger for testing."""
    logger = logging.getLogger('test_frequency_monitor')
    logger.setLevel(logging.WARNING)  # Reduce log noise during tests
    return logger


@pytest.fixture
def mock_hardware():
    """Create a mock hardware manager."""
    hardware = Mock()
    hardware.update_display = Mock()
    hardware.display = Mock()
    hardware.display.update_display_and_leds = Mock()
    hardware.check_reset_button = Mock(return_value=False)
    return hardware


@pytest.fixture
def mock_components(config, logger):
    """Create mock components for FrequencyMonitor."""
    return {
        'state_machine': Mock(),
        'health_monitor': Mock(),
        'memory_monitor': Mock(),
        'data_logger': Mock(),
        'tuning_collector': Mock(),
        'restart_manager': Mock(),
        'offline_analyzer': Mock(),
    }


@patch('monitor.HardwareManager')
@patch('monitor.PowerStateMachine')
@patch('monitor.HealthMonitor')
@patch('monitor.MemoryMonitor')
@patch('monitor.DataLogger')
@patch('monitor.TuningDataCollector')
@patch('monitor.RestartManager')
@patch('monitor.OfflineAnalyzer')
def test_frequency_monitor_initialization(mock_offline, mock_restart, mock_tuning,
                                        mock_data_logger, mock_memory, mock_health,
                                        mock_state_machine, mock_hardware,
                                        config, logger):
    """Test FrequencyMonitor initializes all components correctly."""
    # Setup mocks
    mock_hardware.return_value = Mock()
    mock_state_machine.return_value = Mock()
    mock_health.return_value = Mock()
    mock_memory.return_value = Mock()
    mock_data_logger.return_value = Mock()
    mock_tuning.return_value = Mock()
    mock_restart.return_value = Mock()
    mock_offline.return_value = Mock()

    # Create monitor
    monitor = FrequencyMonitor()

    # Verify all components were created
    assert hasattr(monitor, 'hardware')
    assert hasattr(monitor, 'analyzer')
    assert hasattr(monitor, 'state_machine')
    assert hasattr(monitor, 'health_monitor')
    assert hasattr(monitor, 'memory_monitor')
    assert hasattr(monitor, 'data_logger')
    assert hasattr(monitor, 'tuning_collector')
    assert hasattr(monitor, 'restart_manager')

    # Verify data buffers were initialized
    assert hasattr(monitor, 'freq_buffer')
    assert hasattr(monitor, 'time_buffer')
    assert isinstance(monitor.freq_buffer, deque)
    assert isinstance(monitor.time_buffer, deque)

    # Verify state variables
    assert monitor.running == True
    assert monitor.sample_count == 0
    assert monitor.zero_voltage_duration == 0.0
    assert monitor.reset_button_pressed == False


@patch('monitor.HardwareManager')
@patch('monitor.PowerStateMachine')
@patch('monitor.HealthMonitor')
@patch('monitor.MemoryMonitor')
@patch('monitor.DataLogger')
@patch('monitor.TuningDataCollector')
@patch('monitor.RestartManager')
@patch('monitor.OfflineAnalyzer')
def test_frequency_monitor_buffer_sizes(mock_offline, mock_restart, mock_tuning,
                                       mock_data_logger, mock_memory, mock_health,
                                       mock_state_machine, mock_hardware, config):
    """Test that data buffers are created with correct sizes."""
    mock_hardware.return_value = Mock()
    mock_state_machine.return_value = Mock()
    mock_health.return_value = Mock()
    mock_memory.return_value = Mock()
    mock_data_logger.return_value = Mock()
    mock_tuning.return_value = Mock()
    mock_restart.return_value = Mock()
    mock_offline.return_value = Mock()

    monitor = FrequencyMonitor()

    # Check buffer sizes based on config
    sample_rate = config.get_float('sampling.sample_rate', 2.0)
    buffer_duration = config.get_float('sampling.buffer_duration', 300)
    expected_freq_buffer_size = int(buffer_duration * sample_rate)

    assert len(monitor.freq_buffer) == 0  # Should start empty
    assert monitor.freq_buffer.maxlen == expected_freq_buffer_size
    assert monitor.time_buffer.maxlen == expected_freq_buffer_size


@patch('monitor.HardwareManager')
@patch('monitor.PowerStateMachine')
@patch('monitor.HealthMonitor')
@patch('monitor.MemoryMonitor')
@patch('monitor.DataLogger')
@patch('monitor.TuningDataCollector')
@patch('monitor.RestartManager')
@patch('monitor.OfflineAnalyzer')
def test_frequency_monitor_simulator_mode(mock_offline, mock_restart, mock_tuning,
                                         mock_data_logger, mock_memory, mock_health,
                                         mock_state_machine, mock_hardware, config):
    """Test FrequencyMonitor behaves differently in simulator mode."""
    mock_hardware.return_value = Mock()
    mock_state_machine.return_value = Mock()
    mock_health.return_value = Mock()
    mock_memory.return_value = Mock()
    mock_data_logger.return_value = Mock()
    mock_tuning.return_value = Mock()
    mock_restart.return_value = Mock()
    mock_offline.return_value = Mock()

    # Test simulator mode enabled
    config.config['app'] = {'simulator_mode': True}
    monitor_sim = FrequencyMonitor()

    # Classification buffer removed - display uses current classification directly


@patch('monitor.HardwareManager')
@patch('monitor.PowerStateMachine')
@patch('monitor.HealthMonitor')
@patch('monitor.MemoryMonitor')
@patch('monitor.DataLogger')
@patch('monitor.TuningDataCollector')
@patch('monitor.RestartManager')
@patch('monitor.OfflineAnalyzer')
@patch('signal.signal')  # Mock signal handlers
def test_frequency_monitor_signal_handlers(mock_signal, mock_offline, mock_restart, mock_tuning,
                                         mock_data_logger, mock_memory, mock_health,
                                         mock_state_machine, mock_hardware):
    """Test that signal handlers are set up correctly."""
    mock_hardware.return_value = Mock()
    mock_state_machine.return_value = Mock()
    mock_health.return_value = Mock()
    mock_memory.return_value = Mock()
    mock_data_logger.return_value = Mock()
    mock_tuning.return_value = Mock()
    mock_restart.return_value = Mock()
    mock_offline.return_value = Mock()

    monitor = FrequencyMonitor()

    # Verify signal handlers were set up (signal.signal should have been called twice)
    assert mock_signal.call_count == 2


@patch('monitor.HardwareManager')
@patch('monitor.PowerStateMachine')
@patch('monitor.HealthMonitor')
@patch('monitor.MemoryMonitor')
@patch('monitor.DataLogger')
@patch('monitor.TuningDataCollector')
@patch('monitor.RestartManager')
@patch('monitor.OfflineAnalyzer')
def test_frequency_monitor_tuning_collection_enabled(mock_offline, mock_restart, mock_tuning,
                                                   mock_data_logger, mock_memory, mock_health,
                                                   mock_state_machine, mock_hardware, config):
    """Test that tuning collector is started when enabled."""
    mock_hardware.return_value = Mock()
    mock_state_machine.return_value = Mock()
    mock_health.return_value = Mock()
    mock_memory.return_value = Mock()
    mock_data_logger.return_value = Mock()

    mock_tuning_instance = Mock()
    mock_tuning_instance.enabled = True
    mock_tuning.return_value = mock_tuning_instance

    mock_restart.return_value = Mock()
    mock_offline.return_value = Mock()

    monitor = FrequencyMonitor()

    # Verify tuning collector was started
    mock_tuning_instance.start_collection.assert_called_once()


@patch('monitor.HardwareManager')
@patch('monitor.PowerStateMachine')
@patch('monitor.HealthMonitor')
@patch('monitor.MemoryMonitor')
@patch('monitor.DataLogger')
@patch('monitor.TuningDataCollector')
@patch('monitor.RestartManager')
@patch('monitor.OfflineAnalyzer')
def test_frequency_monitor_tuning_collection_disabled(mock_offline, mock_restart, mock_tuning,
                                                    mock_data_logger, mock_memory, mock_health,
                                                    mock_state_machine, mock_hardware, config):
    """Test that tuning collector is not started when disabled."""
    mock_hardware.return_value = Mock()
    mock_state_machine.return_value = Mock()
    mock_health.return_value = Mock()
    mock_memory.return_value = Mock()
    mock_data_logger.return_value = Mock()

    mock_tuning_instance = Mock()
    mock_tuning_instance.enabled = False
    mock_tuning.return_value = mock_tuning_instance

    mock_restart.return_value = Mock()
    mock_offline.return_value = Mock()

    monitor = FrequencyMonitor()

    # Verify tuning collector was not started
    mock_tuning_instance.start_collection.assert_not_called()


@patch('monitor.HardwareManager')
@patch('monitor.PowerStateMachine')
@patch('monitor.HealthMonitor')
@patch('monitor.MemoryMonitor')
@patch('monitor.DataLogger')
@patch('monitor.TuningDataCollector')
@patch('monitor.RestartManager')
@patch('monitor.OfflineAnalyzer')
def test_frequency_monitor_restart_manager_started(mock_offline, mock_restart, mock_tuning,
                                                 mock_data_logger, mock_memory, mock_health,
                                                 mock_state_machine, mock_hardware):
    """Test that restart manager update monitor is started."""
    mock_hardware.return_value = Mock()
    mock_state_machine.return_value = Mock()
    mock_health.return_value = Mock()
    mock_memory.return_value = Mock()
    mock_data_logger.return_value = Mock()
    mock_tuning.return_value = Mock()

    mock_restart_instance = Mock()
    mock_restart.return_value = mock_restart_instance
    mock_offline.return_value = Mock()

    monitor = FrequencyMonitor()

    # Verify restart manager update monitor was started
    mock_restart_instance.start_update_monitor.assert_called_once()


@patch('monitor.HardwareManager')
@patch('monitor.PowerStateMachine')
@patch('monitor.HealthMonitor')
@patch('monitor.MemoryMonitor')
@patch('monitor.DataLogger')
@patch('monitor.TuningDataCollector')
@patch('monitor.RestartManager')
@patch('monitor.OfflineAnalyzer')
@patch('time.sleep')
def test_frequency_monitor_cleanup(mock_sleep, mock_offline, mock_restart, mock_tuning,
                                 mock_data_logger, mock_memory, mock_health,
                                 mock_state_machine, mock_hardware):
    """Test that cleanup properly shuts down all components."""
    mock_hardware_instance = Mock()
    mock_hardware.return_value = mock_hardware_instance

    mock_health_instance = Mock()
    mock_health.return_value = mock_health_instance

    mock_tuning_instance = Mock()
    mock_tuning_instance.enabled = True
    mock_tuning.return_value = mock_tuning_instance

    # Other mocks
    mock_state_machine.return_value = Mock()
    mock_memory.return_value = Mock()
    mock_data_logger.return_value = Mock()
    mock_restart.return_value = Mock()
    mock_offline.return_value = Mock()

    monitor = FrequencyMonitor()

    # Call cleanup
    monitor.cleanup()

    # Verify all components were cleaned up
    mock_health_instance.stop.assert_called_once()
    mock_tuning_instance.stop_collection.assert_called_once()
    mock_hardware_instance.cleanup.assert_called_once()
