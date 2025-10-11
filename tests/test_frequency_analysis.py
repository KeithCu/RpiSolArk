#!/usr/bin/env python3
"""
Test script to analyze frequency data from CSV files and validate detection code.
"""

import pytest
import os
import csv
import logging
import numpy as np
from typing import List, Dict, Tuple, Optional

# Add parent directory to path to import project modules
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from monitor import FrequencyAnalyzer


@pytest.fixture
def config():
    """Create a config instance for testing."""
    return Config()


@pytest.fixture
def logger():
    """Create a logger for testing."""
    logger = logging.getLogger('test_frequency_analysis')
    logger.setLevel(logging.WARNING)  # Reduce log noise during tests
    return logger


@pytest.fixture
def analyzer(config, logger):
    """Create a FrequencyAnalyzer instance for testing."""
    return FrequencyAnalyzer(config, logger)


# Expected classifications based on data descriptions
EXPECTED_CLASSIFICATIONS = {
    '8kw_pro_spikes.csv': 'Generac Generator',  # AVR hunting spikes
    '20kw_guardian_fluctuation.csv': 'Generac Generator',  # Governor hunting
    '16kw_guardian_startup.csv': 'Generac Generator',  # Cold start surging
    '16kw_vtwin_load.csv': 'Generac Generator',  # Load-dependent hunting
    'xg7000e_portable_hunting.csv': 'Generac Generator',  # Extreme hunting
    '12kw_ng_conversion.csv': 'Generac Generator',  # Extreme swings
    '22kw_startup_harmonics.csv': 'Generac Generator',  # Harmonic distortion
    'aircooled_55load.csv': 'Generac Generator',  # Load-dependent
    '7.5kw_powerpact_meter.csv': 'Generac Generator',  # Meter errors
    '22kw_ng_startup.csv': 'Generac Generator',  # Harmonic issues
    '20kw_ac_cycles.csv': 'Generac Generator',  # UPS cycling
    'diesel_gen_fluctuation_example.csv': 'Generac Generator',  # Diesel hunting
}
def load_csv_data(filepath: str) -> Tuple[List[float], List[str]]:
    """Load frequency data from CSV file."""
    frequencies = []
    timestamps = []

    try:
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'frequency_hz' in row:
                    freq = float(row['frequency_hz'])
                    frequencies.append(freq)
                    timestamps.append(row.get('timestamp', ''))
                elif 'frequency' in row:
                    freq = float(row['frequency'])
                    frequencies.append(freq)
                    timestamps.append(row.get('timestamp', ''))
    except Exception as e:
        pytest.fail(f"Error loading {filepath}: {e}")

    return frequencies, timestamps
def analyze_frequency_data(analyzer, frequencies: List[float]) -> Dict[str, float]:
    """Analyze frequency data and return metrics."""
    if not frequencies:
        return {}

    freq_array = np.array(frequencies)

    # Convert to fractional frequency
    frac_freq = (freq_array - 60.0) / 60.0

    # Calculate Allan variance
    try:
        avar_10s, _, _ = analyzer.analyze_stability(frac_freq)
    except Exception as e:
        avar_10s = None

    # Calculate standard deviation
    std_freq = np.std(freq_array)

    # Calculate kurtosis
    try:
        from scipy import stats
        kurtosis = stats.kurtosis(frac_freq)
    except Exception as e:
        kurtosis = None

    # Basic statistics
    mean_freq = np.mean(freq_array)
    min_freq = np.min(freq_array)
    max_freq = np.max(freq_array)
    freq_range = max_freq - min_freq

    return {
        'mean_frequency': mean_freq,
        'std_deviation': std_freq,
        'min_frequency': min_freq,
        'max_frequency': max_freq,
        'frequency_range': freq_range,
        'allan_variance': avar_10s,
        'kurtosis': kurtosis,
        'sample_count': len(frequencies)
    }
def classify_data(analyzer, metrics: Dict[str, float]) -> str:
    """Classify the data using the analyzer."""
    avar = metrics.get('allan_variance')
    std_dev = metrics.get('std_deviation')
    kurtosis = metrics.get('kurtosis')

    return analyzer.classify_power_source(avar, std_dev, kurtosis)
@pytest.mark.parametrize("filename", [
    '8kw_pro_spikes.csv',
    '20kw_guardian_fluctuation.csv',
    '16kw_guardian_startup.csv',
    '16kw_vtwin_load.csv',
    'xg7000e_portable_hunting.csv',
    '12kw_ng_conversion.csv',
    '22kw_startup_harmonics.csv',
    'aircooled_55load.csv',
    '7.5kw_powerpact_meter.csv',
    '22kw_ng_startup.csv',
    '20kw_ac_cycles.csv',
    'diesel_gen_fluctuation_example.csv',
])
def test_frequency_analysis_csv_files(analyzer, filename):
    """Test frequency analysis on real CSV data files."""
    filepath = os.path.join(os.path.dirname(__file__), filename)

    # Skip if file doesn't exist
    if not os.path.exists(filepath):
        pytest.skip(f"Test file {filename} not found")

    # Load data
    frequencies, _ = load_csv_data(filepath)

    assert len(frequencies) > 0, f"No frequency data found in {filename}"

    # Analyze data
    metrics = analyze_frequency_data(analyzer, frequencies)

    # Classify
    classification = classify_data(analyzer, metrics)

    # Get expected classification
    expected = EXPECTED_CLASSIFICATIONS.get(filename, 'Unknown')

    # Verify classification is correct
    assert classification == expected, (
        f"Classification failed for {filename}: got '{classification}', expected '{expected}'"
    )

    # Verify we have valid metrics
    assert 'sample_count' in metrics
    assert metrics['sample_count'] == len(frequencies)
    assert 'mean_frequency' in metrics
    assert 'std_deviation' in metrics
    
def test_frequency_analyzer_stability_analysis(analyzer):
    """Test the analyze_stability method with sample data."""
    # Create sample frequency data with some variation
    freq_data = np.array([59.9, 60.0, 60.1, 59.95, 60.05, 60.02, 59.98, 60.03, 60.01, 59.97])

    # Convert to fractional frequency
    frac_freq = (freq_data - 60.0) / 60.0

    # Test stability analysis
    avar, std_freq, kurtosis = analyzer.analyze_stability(frac_freq)

    # Verify results are reasonable
    assert avar is not None, "Allan variance should be calculated"
    assert std_freq is not None, "Standard deviation should be calculated"
    assert kurtosis is not None, "Kurtosis should be calculated"

    # Basic sanity checks
    assert avar >= 0, "Allan variance should be non-negative"
    assert std_freq >= 0, "Standard deviation should be non-negative"


def test_frequency_analyzer_classification(analyzer):
    """Test power source classification with various metrics."""
    test_cases = [
        # (avar, std_dev, kurtosis, expected)
        (1e-10, 0.01, 0.1, "Utility Grid"),  # Very stable
        (1e-8, 0.1, 0.8, "Generac Generator"),  # Unstable
        (None, 0.05, 0.5, "Unknown"),  # Missing avar
        (1e-9, None, 0.5, "Unknown"),  # Missing std_dev
        (1e-9, 0.05, None, "Unknown"),  # Missing kurtosis
    ]

    for avar, std_dev, kurtosis, expected in test_cases:
        result = analyzer.classify_power_source(avar, std_dev, kurtosis)
        assert result == expected, f"Classification failed: got {result}, expected {expected}"
