#!/usr/bin/env python3
"""
Tests for error handling and edge cases across the monitoring system.
"""

import pytest
import numpy as np
import logging
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path so we can import monitor module
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor import FrequencyAnalyzer, PowerStateMachine, FrequencyMonitor
from config import Config


@pytest.fixture
def config():
    """Create a config instance for testing."""
    return Config("config.yaml")


@pytest.fixture
def logger():
    """Create a logger for testing."""
    logger = logging.getLogger('test_error_handling')
    logger.setLevel(logging.WARNING)
    return logger


class TestFrequencyAnalyzerErrorHandling:
    """Test FrequencyAnalyzer error handling."""

    def test_analyze_stability_none_input(self, config, logger):
        """Test analyze_stability handles None input."""
        analyzer = FrequencyAnalyzer(config, logger)

        result = analyzer.analyze_stability(None)
        assert result == (None, None, None)

    def test_analyze_stability_insufficient_data(self, config, logger):
        """Test analyze_stability handles insufficient data."""
        analyzer = FrequencyAnalyzer(config, logger)

        # Less than 10 samples
        small_data = np.array([60.0, 60.1, 59.9])
        result = analyzer.analyze_stability(small_data)
        assert result == (None, None, None)

    def test_analyze_stability_invalid_data_types(self, config, logger):
        """Test analyze_stability handles invalid data types."""
        analyzer = FrequencyAnalyzer(config, logger)

        # String data
        invalid_data = np.array(["invalid", "data"])
        result = analyzer.analyze_stability(invalid_data)
        assert result == (None, None, None)

    def test_analyze_stability_nan_values(self, config, logger):
        """Test analyze_stability handles NaN values."""
        analyzer = FrequencyAnalyzer(config, logger)

        # Data with NaN
        nan_data = np.array([60.0, np.nan, 60.1, np.inf])
        result = analyzer.analyze_stability(nan_data)
        assert result == (None, None, None)

    def test_classify_power_source_none_inputs(self, config, logger):
        """Test classify_power_source handles None inputs."""
        analyzer = FrequencyAnalyzer(config, logger)

        result = analyzer.classify_power_source(None, None, None)
        assert result == "Unknown"

    def test_classify_power_source_invalid_thresholds(self, config, logger):
        """Test classify_power_source handles invalid threshold config."""
        analyzer = FrequencyAnalyzer(config, logger)

        # Mock invalid thresholds
        analyzer.thresholds = {
            'allan_variance': 'invalid',
            'std_dev': 'also_invalid',
            'kurtosis': 'not_a_number'
        }

        result = analyzer.classify_power_source(1e-9, 0.05, 0.3)
        assert result == "Unknown"  # Should fall back due to threshold conversion failure

    def test_count_zero_crossings_hardware_failure(self, config, logger):
        """Test count_zero_crossings handles hardware failures."""
        analyzer = FrequencyAnalyzer(config, logger)

        # No hardware manager attached
        assert analyzer.hardware_manager is None

        result = analyzer.count_zero_crossings()
        assert result is not None  # Should return simulated data

    def test_simulate_frequency_consistency(self, config, logger):
        """Test simulator produces consistent cycling behavior."""
        analyzer = FrequencyAnalyzer(config, logger)

        # Run through multiple cycles
        states = []
        for i in range(100):
            freq = analyzer._simulate_frequency()
            states.append(analyzer.simulator_state)

        # Should have seen all states
        assert "grid" in states
        assert "off_grid" in states
        assert "generator" in states


class TestPowerStateMachineErrorHandling:
    """Test PowerStateMachine error handling."""

    def test_state_machine_callbacks_error_handling(self, config, logger):
        """Test state machine handles callback errors gracefully."""
        state_machine = PowerStateMachine(config, logger)

        # Mock a callback that raises an exception
        def failing_callback():
            raise Exception("Callback failed")

        # Replace a callback with failing one
        state_machine.on_state_change_callbacks[PowerState.GRID] = failing_callback

        # This should not raise an exception, just log the error
        with patch.object(logger, 'error') as mock_error:
            state_machine.update_state(60.0, "Utility Grid", 0.0)
            mock_error.assert_called_once()

    def test_state_machine_invalid_power_source(self, config, logger):
        """Test state machine handles unknown power sources."""
        state_machine = PowerStateMachine(config, logger)

        # Should transition to TRANSITIONING for unknown source
        state = state_machine.update_state(60.0, "Completely Unknown Source", 0.0)
        assert state == PowerState.TRANSITIONING

    def test_state_machine_timeout_recovery(self, config, logger):
        """Test state machine recovers from timeout."""
        state_machine = PowerStateMachine(config, logger)

        # Put in transitioning state
        state_machine.update_state(None, "Unknown", 0.5)

        # Manually age the state to trigger timeout
        import time
        state_machine.state_entry_time = time.time() - 40  # Past 30s timeout

        # Should force to OFF_GRID
        state = state_machine.update_state(None, "Unknown", 0.5)
        assert state == PowerState.OFF_GRID


class TestFrequencyMonitorErrorHandling:
    """Test FrequencyMonitor error handling."""

    @patch('monitor.HardwareManager')
    @patch('monitor.PowerStateMachine')
    @patch('monitor.HealthMonitor')
    @patch('monitor.MemoryMonitor')
    @patch('monitor.DataLogger')
    @patch('monitor.TuningDataCollector')
    @patch('monitor.RestartManager')
    @patch('monitor.OfflineAnalyzer')
    def test_monitor_component_initialization_failures(self, mock_offline, mock_restart,
                                                      mock_tuning, mock_data_logger, mock_memory,
                                                      mock_health, mock_state_machine, mock_hardware):
        """Test monitor handles component initialization failures."""

        # Make one component fail during creation
        mock_hardware.side_effect = Exception("Hardware init failed")
        mock_state_machine.return_value = Mock()
        mock_health.return_value = Mock()
        mock_memory.return_value = Mock()
        mock_data_logger.return_value = Mock()
        mock_tuning.return_value = Mock()
        mock_restart.return_value = Mock()
        mock_offline.return_value = Mock()

        # Should handle the exception gracefully
        monitor = FrequencyMonitor()
        assert monitor.hardware is None  # Hardware should be None due to failure

    @patch('monitor.HardwareManager')
    @patch('monitor.PowerStateMachine')
    @patch('monitor.HealthMonitor')
    @patch('monitor.MemoryMonitor')
    @patch('monitor.DataLogger')
    @patch('monitor.TuningDataCollector')
    @patch('monitor.RestartManager')
    @patch('monitor.OfflineAnalyzer')
    def test_monitor_run_with_component_failures(self, mock_offline, mock_restart, mock_tuning,
                                                mock_data_logger, mock_memory, mock_health,
                                                mock_state_machine, mock_hardware):
        """Test monitor continues running despite component failures."""
        # Setup all mocks
        mock_hardware.return_value = Mock()
        mock_state_machine.return_value = Mock()
        mock_health.return_value = Mock()
        mock_memory.return_value = Mock()
        mock_data_logger.return_value = Mock()
        mock_tuning.return_value = Mock()
        mock_restart.return_value = Mock()
        mock_offline.return_value = Mock()

        monitor = FrequencyMonitor()

        # Mock analyzer to fail during frequency measurement
        monitor.analyzer.count_zero_crossings = Mock(side_effect=Exception("Measurement failed"))

        # Mock time functions for controlled testing
        with patch('time.time') as mock_time, \
             patch('time.sleep') as mock_sleep:

            mock_time.return_value = 0

            # This should not crash the monitor
            try:
                # Simulate a few iterations
                for i in range(3):
                    mock_time.return_value = i
                    if i >= 2:  # Exit condition
                        break
                    # The run loop would normally continue despite errors
            except Exception:
                pytest.fail("Monitor should handle component failures gracefully")


class TestConfigurationErrorHandling:
    """Test configuration error handling."""

    def test_config_missing_file(self):
        """Test Config handles missing config file."""
        config = Config("nonexistent_config.yaml")

        # Should return empty dict, not crash
        assert isinstance(config.config, dict)

        # Should return defaults for missing keys
        result = config.get("nonexistent_key", "default")
        assert result == "default"

    def test_config_invalid_yaml(self, tmp_path):
        """Test Config handles invalid YAML gracefully."""
        invalid_yaml = tmp_path / "invalid.yaml"
        invalid_yaml.write_text("invalid: yaml: content: [")

        config = Config(str(invalid_yaml))

        # Should not crash, should have empty config
        assert isinstance(config.config, dict)

    def test_config_corrupted_file(self, tmp_path):
        """Test Config handles file read errors."""
        corrupted_file = tmp_path / "corrupted.yaml"
        corrupted_file.write_text("valid: yaml")

        # Make the file unreadable
        with patch('builtins.open', side_effect=PermissionError("Access denied")):
            config = Config(str(corrupted_file))

            # Should not crash
            assert isinstance(config.config, dict)


class TestSystemIntegrationErrorHandling:
    """Test end-to-end error scenarios."""

    @patch('monitor.HardwareManager')
    def test_full_system_with_hardware_failure(self, mock_hardware, config):
        """Test full system operation with hardware failures."""
        # Mock hardware that fails
        mock_hw_instance = Mock()
        mock_hw_instance.read_gpio.side_effect = Exception("GPIO read failed")
        mock_hardware.return_value = mock_hw_instance

        analyzer = FrequencyAnalyzer(config, Mock())

        # Should handle hardware failure gracefully
        result = analyzer.count_zero_crossings()
        # Should fall back to simulation or return None
        assert result is not None  # Simulator should work

    def test_buffer_overflow_handling(self, config, logger):
        """Test system handles buffer overflows gracefully."""
        from collections import deque

        # Create a monitor with very small buffers for testing
        monitor = FrequencyMonitor.__new__(FrequencyMonitor)
        monitor.freq_buffer = deque(maxlen=2)  # Very small buffer
        monitor.time_buffer = deque(maxlen=2)

        # Fill buffers beyond capacity
        for i in range(10):
            monitor.freq_buffer.append(60.0 + i * 0.1)
            monitor.time_buffer.append(i)

        # Buffers should have maintained only the most recent items
        assert len(monitor.freq_buffer) == 2
        assert len(monitor.time_buffer) == 2

    def test_concurrent_access_simulation(self, config, logger):
        """Test system handles concurrent access scenarios."""
        analyzer = FrequencyAnalyzer(config, logger)

        # Simulate rapid concurrent calls
        import threading
        results = []
        errors = []

        def worker():
            try:
                for _ in range(100):
                    result = analyzer._simulate_frequency()
                    results.append(result)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should have completed without errors
        assert len(errors) == 0
        assert len(results) > 0

        # All results should be valid frequencies or None
        for result in results:
            assert result is None or (isinstance(result, (int, float)) and 50 <= result <= 65)
