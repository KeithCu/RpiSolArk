#!/usr/bin/env python3
"""
Test script to analyze frequency data from CSV files and validate detection code.
"""

import os
import sys
import csv
import logging
import numpy as np
import allantools
from scipy import stats
from typing import List, Dict, Tuple, Optional
import pandas as pd

# Add parent directory to path to import project modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from monitor import FrequencyAnalyzer

class FrequencyDataTester:
    """Test frequency analysis against real-world data patterns."""
    
    def __init__(self):
        self.config = Config()
        self.logger = self._setup_logger()
        self.analyzer = FrequencyAnalyzer(self.config, self.logger)
        
        # Expected classifications based on data descriptions
        self.expected_classifications = {
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
    
    def _setup_logger(self) -> logging.Logger:
        """Setup logging for the test."""
        logger = logging.getLogger('FrequencyDataTester')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def load_csv_data(self, filepath: str) -> Tuple[List[float], List[str]]:
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
            self.logger.error(f"Error loading {filepath}: {e}")
            return [], []
        
        return frequencies, timestamps
    
    def analyze_frequency_data(self, frequencies: List[float]) -> Dict[str, float]:
        """Analyze frequency data and return metrics."""
        if not frequencies:
            return {}
        
        freq_array = np.array(frequencies)
        
        # Convert to fractional frequency
        frac_freq = (freq_array - 60.0) / 60.0
        
        # Calculate Allan variance
        try:
            avar_10s, _, _ = self.analyzer.analyze_stability(frac_freq)
        except Exception as e:
            self.logger.warning(f"Allan variance calculation failed: {e}")
            avar_10s = None
        
        # Calculate standard deviation
        std_freq = np.std(freq_array)
        
        # Calculate kurtosis
        try:
            kurtosis = stats.kurtosis(frac_freq)
        except Exception as e:
            self.logger.warning(f"Kurtosis calculation failed: {e}")
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
    
    def classify_data(self, metrics: Dict[str, float]) -> str:
        """Classify the data using the analyzer."""
        avar = metrics.get('allan_variance')
        std_dev = metrics.get('std_deviation')
        kurtosis = metrics.get('kurtosis')
        
        return self.analyzer.classify_power_source(avar, std_dev, kurtosis)
    
    def test_single_file(self, filename: str) -> Dict[str, any]:
        """Test analysis on a single CSV file."""
        filepath = os.path.join(os.path.dirname(__file__), filename)
        
        if not os.path.exists(filepath):
            return {'error': f'File not found: {filepath}'}
        
        self.logger.info(f"Testing {filename}...")
        
        # Load data
        frequencies, timestamps = self.load_csv_data(filepath)
        
        if not frequencies:
            return {'error': f'No frequency data found in {filename}'}
        
        # Analyze data
        metrics = self.analyze_frequency_data(frequencies)
        
        # Classify
        classification = self.classify_data(metrics)
        
        # Get expected classification
        expected = self.expected_classifications.get(filename, 'Unknown')
        
        # Determine if classification is correct
        correct = classification == expected
        
        return {
            'filename': filename,
            'sample_count': len(frequencies),
            'metrics': metrics,
            'classification': classification,
            'expected': expected,
            'correct': correct,
            'timestamps': timestamps[:5] if timestamps else []  # First 5 timestamps
        }
    
    def run_all_tests(self) -> Dict[str, any]:
        """Run tests on all CSV files in the tests directory."""
        test_dir = os.path.dirname(__file__)
        csv_files = [f for f in os.listdir(test_dir) if f.endswith('.csv') and not f.startswith('test_')]
        
        results = {}
        correct_count = 0
        total_count = 0
        
        self.logger.info(f"Found {len(csv_files)} CSV files to test")
        
        for filename in csv_files:
            result = self.test_single_file(filename)
            results[filename] = result
            
            if 'error' not in result:
                total_count += 1
                if result['correct']:
                    correct_count += 1
        
        # Summary
        results['summary'] = {
            'total_files': len(csv_files),
            'successful_tests': total_count,
            'correct_classifications': correct_count,
            'accuracy': correct_count / total_count if total_count > 0 else 0
        }
        
        return results
    
    def print_results(self, results: Dict[str, any]):
        """Print test results in a formatted way."""
        print("\n" + "="*80)
        print("FREQUENCY ANALYSIS TEST RESULTS")
        print("="*80)
        
        # Individual file results
        for filename, result in results.items():
            if filename == 'summary':
                continue
                
            print(f"\nFILE: {filename}")
            print("-" * 50)
            
            if 'error' in result:
                print(f"ERROR: {result['error']}")
                continue
            
            metrics = result['metrics']
            print(f"Sample Count: {result['sample_count']}")
            print(f"Mean Frequency: {metrics['mean_frequency']:.3f} Hz")
            print(f"Std Deviation: {metrics['std_deviation']:.3f} Hz")
            print(f"Frequency Range: {metrics['frequency_range']:.3f} Hz")
            print(f"Allan Variance: {metrics['allan_variance']:.2e}" if metrics['allan_variance'] else "Allan Variance: N/A")
            print(f"Kurtosis: {metrics['kurtosis']:.3f}" if metrics['kurtosis'] else "Kurtosis: N/A")
            print(f"Classification: {result['classification']}")
            print(f"Expected: {result['expected']}")
            print(f"Result: {'CORRECT' if result['correct'] else 'INCORRECT'}")
        
        # Summary
        if 'summary' in results:
            summary = results['summary']
            print(f"\nSUMMARY")
            print("-" * 50)
            print(f"Total Files: {summary['total_files']}")
            print(f"Successful Tests: {summary['successful_tests']}")
            print(f"Correct Classifications: {summary['correct_classifications']}")
            print(f"Accuracy: {summary['accuracy']:.1%}")
            
            if summary['accuracy'] >= 0.8:
                print("EXCELLENT: Detection algorithm is working well!")
            elif summary['accuracy'] >= 0.6:
                print("GOOD: Detection algorithm is mostly working")
            else:
                print("NEEDS IMPROVEMENT: Detection algorithm needs tuning")

def main():
    """Main function to run the tests."""
    tester = FrequencyDataTester()
    results = tester.run_all_tests()
    tester.print_results(results)
    
    # Return exit code based on accuracy
    if 'summary' in results:
        accuracy = results['summary']['accuracy']
        if accuracy >= 0.8:
            return 0  # Success
        elif accuracy >= 0.6:
            return 1  # Partial success
        else:
            return 2  # Needs improvement
    
    return 3  # Error

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
