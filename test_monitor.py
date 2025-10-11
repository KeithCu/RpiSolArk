#!/usr/bin/env python3
"""
Unit tests for the frequency monitor
"""

import unittest
import numpy as np
import tempfile
import yaml
from unittest.mock import Mock, patch
import sys
import os

# Add the current directory to the path so we can import monitor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monitor import Config, FrequencyAnalyzer, DataLogger


class TestConfig(unittest.TestCase):
    """Test configuration management."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_config = {
            'hardware': {'gpio_pin': 17, 'led_green': 18},
            'sampling': {'sample_rate': 2.0, 'min_freq': 40.0},
            'analysis': {
                'generator_thresholds': {
                    'allan_variance': 1e-9,
                    'std_dev': 0.05,
                    'kurtosis': 0.5
                }
            }
        }
    
    def test_config_loading(self):
        """Test configuration loading from file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(self.test_config, f)
            temp_file = f.name
        
        try:
            config = Config(temp_file)
            self.assertEqual(config.get('hardware.gpio_pin'), 17)
            self.assertEqual(config.get('sampling.sample_rate'), 2.0)
            self.assertEqual(config.get('analysis.generator_thresholds.allan_variance'), 1e-9)
        finally:
            os.unlink(temp_file)
    
    def test_config_defaults(self):
        """Test default configuration values."""
        # Test with actual config file
        config = Config('config.yaml')
        self.assertIsNotNone(config.get('hardware.gpio_pin'))
        self.assertIsNotNone(config.get('sampling.sample_rate'))

        # Test defaults for missing keys
        self.assertEqual(config.get('nonexistent.key', 'default'), 'default')
        self.assertEqual(config.get('missing.nested.key', 42), 42)
    
    def test_config_get_with_default(self):
        """Test getting configuration values with defaults."""
        # Test with empty config (nonexistent file)
        config = Config('nonexistent.yaml')
        self.assertEqual(config.get('nonexistent.key', 'default'), 'default')

        # Test with actual config file
        config = Config('config.yaml')
        self.assertEqual(config.get('hardware.gpio_pin', 999), 17)  # Should get actual value
        self.assertEqual(config.get('nonexistent.key', 'fallback'), 'fallback')  # Should get default


class TestFrequencyAnalyzer(unittest.TestCase):
    """Test frequency analysis functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = Mock()
        self.config.get.side_effect = lambda key, default=None: {
            'sampling.min_freq': 40.0,
            'sampling.max_freq': 80.0,
            'sampling.sample_rate': 2.0,
            'analysis.allan_variance_tau': 10.0,
            'analysis.generator_thresholds': {
                'allan_variance': 1e-9,
                'std_dev': 0.05,
                'kurtosis': 0.5
            }
        }.get(key, default)
        
        self.logger = Mock()
        self.analyzer = FrequencyAnalyzer(self.config, self.logger)
    
    def test_simulate_frequency(self):
        """Test frequency simulation."""
        freq = self.analyzer._simulate_frequency()
        self.assertIsInstance(freq, float)
        self.assertGreater(freq, 59.0)
        self.assertLess(freq, 61.0)
    
    def test_classify_power_source_utility(self):
        """Test power source classification for utility."""
        # Utility should have low Allan variance, std dev, and kurtosis
        avar = 1e-10  # Low Allan variance
        std_dev = 0.01  # Low standard deviation
        kurtosis = 0.1  # Low kurtosis
        
        source = self.analyzer.classify_power_source(avar, std_dev, kurtosis)
        self.assertEqual(source, "Utility Grid")
    
    def test_classify_power_source_generator(self):
        """Test power source classification for generator."""
        # Generator should have high Allan variance, std dev, or kurtosis
        avar = 1e-8  # High Allan variance
        std_dev = 0.01  # Low standard deviation
        kurtosis = 0.1  # Low kurtosis
        
        source = self.analyzer.classify_power_source(avar, std_dev, kurtosis)
        self.assertEqual(source, "Generac Generator")
    
    def test_classify_power_source_unknown(self):
        """Test power source classification with None values."""
        source = self.analyzer.classify_power_source(None, 0.01, 0.1)
        self.assertEqual(source, "Unknown")
    
    def test_analyze_stability_insufficient_data(self):
        """Test stability analysis with insufficient data."""
        frac_freq = np.array([0.001, 0.002])  # Only 2 samples
        result = self.analyzer.analyze_stability(frac_freq)
        self.assertEqual(result, (None, None, None))
    
    @patch('allantools.adev')
    def test_analyze_stability_success(self, mock_adev):
        """Test successful stability analysis."""
        # Mock Allan deviation calculation
        mock_adev.return_value = (
            np.array([1, 10, 100]),  # taus
            np.array([1e-10, 1e-9, 1e-8]),  # adev values
            None,  # errors
            None   # ns
        )
        
        # Create test data
        frac_freq = np.random.normal(0, 0.001, 100)  # 100 samples
        
        avar, std_freq, kurtosis = self.analyzer.analyze_stability(frac_freq)
        
        self.assertIsNotNone(avar)
        self.assertIsNotNone(std_freq)
        self.assertIsNotNone(kurtosis)
        self.assertIsInstance(std_freq, float)
        self.assertIsInstance(kurtosis, float)


class TestDataLogger(unittest.TestCase):
    """Test data logging functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = Mock()
        self.config.get.return_value = 'test_hourly_log.csv'
        self.logger = Mock()
        self.data_logger = DataLogger(self.config, self.logger)
    
    def test_log_hourly_status(self):
        """Test hourly status logging."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            temp_file = f.name
        
        try:
            # Create a new DataLogger with the temp file
            config = Mock()
            config.get.return_value = temp_file
            logger = Mock()
            data_logger = DataLogger(config, logger)
            
            # Test logging
            data_logger.log_hourly_status(
                "2024-01-01 12:00:00", 60.0, "Utility Grid", 0.01, 0.1, 7200
            )
            
            # Verify file was created and contains expected data
            with open(temp_file, 'r') as f:
                content = f.read()
                self.assertIn("2024-01-01 12:00:00", content)
                self.assertIn("60.00", content)
                self.assertIn("Utility Grid", content)
                self.assertIn("7200", content)
                
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestIntegration(unittest.TestCase):
    """Integration tests."""
    
    def test_config_and_analyzer_integration(self):
        """Test that Config and FrequencyAnalyzer work together."""
        config = Config('config.yaml')  # Use actual config
        logger = Mock()
        analyzer = FrequencyAnalyzer(config, logger)

        # Test that analyzer can access config values
        self.assertIsNotNone(analyzer.thresholds)
        self.assertIn('allan_variance', analyzer.thresholds)

        # Test with empty config (should still work with defaults)
        empty_config = Config('nonexistent.yaml')
        analyzer_empty = FrequencyAnalyzer(empty_config, logger)
        self.assertIsNotNone(analyzer_empty.thresholds)  # Should be empty dict but not None


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
