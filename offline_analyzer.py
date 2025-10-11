#!/usr/bin/env python3
"""
Offline data analysis for frequency monitoring data.
Handles analysis of detailed log files and generates comprehensive reports.
"""

import csv
import logging
import os
from typing import Dict, List, Any, Optional
import numpy as np


class OfflineAnalyzer:
    """Analyzes offline frequency monitoring data from detailed log files."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def analyze_offline_data(self, input_file: str, output_file: str):
        """Analyze offline data from detailed log file."""
        self.logger.info(f"Starting offline analysis of {input_file}")
        
        if not os.path.exists(input_file):
            self.logger.error(f"Input file not found: {input_file}")
            return
        
        try:
            # Read the detailed log data
            data = self._read_detailed_log_file(input_file)
            if not data:
                self.logger.error("No data found in input file")
                return
            
            self.logger.info(f"Loaded {len(data)} data points from {input_file}")
            
            # Perform analysis
            analysis_results = self._perform_offline_analysis(data)
            
            # Write results
            self._write_analysis_results(analysis_results, output_file)
            
            # Print summary
            self._print_analysis_summary(analysis_results)
            
        except Exception as e:
            self.logger.error(f"Error during offline analysis: {e}")
    
    def _read_detailed_log_file(self, filename: str) -> List[Dict[str, Any]]:
        """Read detailed log file and return structured data."""
        data = []
        
        try:
            with open(filename, 'r', newline='') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    # Parse and validate data
                    try:
                        data_point = {
                            'timestamp': row['timestamp'],
                            'datetime': row['datetime'],
                            'unix_timestamp': float(row['unix_timestamp']),
                            'elapsed_seconds': float(row['elapsed_seconds']),
                            'frequency_hz': float(row['frequency_hz']),
                            'allan_variance': float(row['allan_variance']) if row['allan_variance'] != 'N/A' else None,
                            'std_deviation': float(row['std_deviation']) if row['std_deviation'] != 'N/A' else None,
                            'kurtosis': float(row['kurtosis']) if row['kurtosis'] != 'N/A' else None,
                            'power_source': row['power_source'],
                            'confidence': float(row['confidence']),
                            'sample_count': int(row['sample_count']),
                            'buffer_size': int(row['buffer_size'])
                        }
                        data.append(data_point)
                    except (ValueError, KeyError) as e:
                        self.logger.warning(f"Skipping invalid row: {e}")
                        continue
                        
        except Exception as e:
            self.logger.error(f"Error reading log file: {e}")
            return []
        
        return data
    
    def _perform_offline_analysis(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform comprehensive offline analysis on the data."""
        if not data:
            return {}
        
        # Extract frequency data
        frequencies = np.array([d['frequency_hz'] for d in data])
        timestamps = np.array([d['unix_timestamp'] for d in data])
        
        # Basic statistics
        freq_stats = {
            'mean': float(np.mean(frequencies)),
            'std': float(np.std(frequencies)),
            'min': float(np.min(frequencies)),
            'max': float(np.max(frequencies)),
            'range': float(np.max(frequencies) - np.min(frequencies)),
            'count': len(frequencies)
        }
        
        # Time analysis
        duration = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0
        sample_rate = len(frequencies) / duration if duration > 0 else 0
        
        # Classification analysis
        classifications = [d['power_source'] for d in data]
        utility_count = classifications.count('Utility Grid')
        generator_count = classifications.count('Generac Generator')
        unknown_count = classifications.count('Unknown')
        
        classification_stats = {
            'utility_count': utility_count,
            'generator_count': generator_count,
            'unknown_count': unknown_count,
            'utility_percentage': (utility_count / len(classifications)) * 100,
            'generator_percentage': (generator_count / len(classifications)) * 100,
            'unknown_percentage': (unknown_count / len(classifications)) * 100
        }
        
        # Confidence analysis
        confidences = [d['confidence'] for d in data if d['confidence'] is not None]
        confidence_stats = {
            'mean_confidence': float(np.mean(confidences)) if confidences else 0,
            'std_confidence': float(np.std(confidences)) if confidences else 0,
            'min_confidence': float(np.min(confidences)) if confidences else 0,
            'max_confidence': float(np.max(confidences)) if confidences else 0
        }
        
        # Analysis metrics
        allan_variances = [d['allan_variance'] for d in data if d['allan_variance'] is not None]
        std_deviations = [d['std_deviation'] for d in data if d['std_deviation'] is not None]
        kurtoses = [d['kurtosis'] for d in data if d['kurtosis'] is not None]
        
        analysis_metrics = {
            'mean_allan_variance': float(np.mean(allan_variances)) if allan_variances else 0,
            'mean_std_deviation': float(np.mean(std_deviations)) if std_deviations else 0,
            'mean_kurtosis': float(np.mean(kurtoses)) if kurtoses else 0,
            'max_allan_variance': float(np.max(allan_variances)) if allan_variances else 0,
            'max_std_deviation': float(np.max(std_deviations)) if std_deviations else 0,
            'max_kurtosis': float(np.max(kurtoses)) if kurtoses else 0
        }
        
        # Threshold analysis
        thresholds = self.config.get('analysis.generator_thresholds', {})
        avar_thresh = thresholds.get('allan_variance', 1e-9)
        std_thresh = thresholds.get('std_dev', 0.05)
        kurt_thresh = thresholds.get('kurtosis', 0.5)
        
        # Count how many readings would be classified as generator based on each metric
        avar_above_thresh = sum(1 for av in allan_variances if av > avar_thresh)
        std_above_thresh = sum(1 for sd in std_deviations if sd > std_thresh)
        kurt_above_thresh = sum(1 for k in kurtoses if k > kurt_thresh)
        
        threshold_analysis = {
            'allan_variance_threshold': avar_thresh,
            'std_deviation_threshold': std_thresh,
            'kurtosis_threshold': kurt_thresh,
            'allan_variance_above_threshold': avar_above_thresh,
            'std_deviation_above_threshold': std_above_thresh,
            'kurtosis_above_threshold': kurt_above_thresh,
            'allan_variance_above_percentage': (avar_above_thresh / len(allan_variances)) * 100 if allan_variances else 0,
            'std_deviation_above_percentage': (std_above_thresh / len(std_deviations)) * 100 if std_deviations else 0,
            'kurtosis_above_percentage': (kurt_above_thresh / len(kurtoses)) * 100 if kurtoses else 0
        }
        
        # Recommended thresholds based on data
        if allan_variances:
            recommended_avar = np.percentile(allan_variances, 95)
        else:
            recommended_avar = avar_thresh
            
        if std_deviations:
            recommended_std = np.percentile(std_deviations, 95)
        else:
            recommended_std = std_thresh
            
        if kurtoses:
            recommended_kurt = np.percentile(kurtoses, 95)
        else:
            recommended_kurt = kurt_thresh
        
        recommended_thresholds = {
            'recommended_allan_variance': recommended_avar,
            'recommended_std_deviation': recommended_std,
            'recommended_kurtosis': recommended_kurt
        }
        
        return {
            'frequency_statistics': freq_stats,
            'time_analysis': {
                'duration_seconds': duration,
                'sample_rate_hz': sample_rate,
                'start_time': timestamps[0] if len(timestamps) > 0 else 0,
                'end_time': timestamps[-1] if len(timestamps) > 0 else 0
            },
            'classification_statistics': classification_stats,
            'confidence_statistics': confidence_stats,
            'analysis_metrics': analysis_metrics,
            'threshold_analysis': threshold_analysis,
            'recommended_thresholds': recommended_thresholds,
            'raw_data': data  # Include raw data for detailed analysis
        }
    
    def _write_analysis_results(self, results: Dict[str, Any], output_file: str):
        """Write analysis results to CSV file."""
        try:
            with open(output_file, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Write summary statistics
                writer.writerow(['Analysis Type', 'Metric', 'Value'])
                writer.writerow([])
                
                # Frequency statistics
                writer.writerow(['FREQUENCY STATISTICS', '', ''])
                for key, value in results['frequency_statistics'].items():
                    writer.writerow(['', key, value])
                writer.writerow([])
                
                # Time analysis
                writer.writerow(['TIME ANALYSIS', '', ''])
                for key, value in results['time_analysis'].items():
                    writer.writerow(['', key, value])
                writer.writerow([])
                
                # Classification statistics
                writer.writerow(['CLASSIFICATION STATISTICS', '', ''])
                for key, value in results['classification_statistics'].items():
                    writer.writerow(['', key, value])
                writer.writerow([])
                
                # Confidence statistics
                writer.writerow(['CONFIDENCE STATISTICS', '', ''])
                for key, value in results['confidence_statistics'].items():
                    writer.writerow(['', key, value])
                writer.writerow([])
                
                # Analysis metrics
                writer.writerow(['ANALYSIS METRICS', '', ''])
                for key, value in results['analysis_metrics'].items():
                    writer.writerow(['', key, value])
                writer.writerow([])
                
                # Threshold analysis
                writer.writerow(['THRESHOLD ANALYSIS', '', ''])
                for key, value in results['threshold_analysis'].items():
                    writer.writerow(['', key, value])
                writer.writerow([])
                
                # Recommended thresholds
                writer.writerow(['RECOMMENDED THRESHOLDS', '', ''])
                for key, value in results['recommended_thresholds'].items():
                    writer.writerow(['', key, value])
                writer.writerow([])
                
                # Raw data section
                writer.writerow(['RAW DATA', '', ''])
                if results.get('raw_data'):
                    # Write header for raw data
                    raw_data = results['raw_data']
                    if raw_data:
                        headers = list(raw_data[0].keys())
                        writer.writerow([''] + headers)
                        
                        # Write raw data rows
                        for row in raw_data:
                            writer.writerow([''] + [row.get(header, '') for header in headers])
            
            self.logger.info(f"Analysis results written to {output_file}")
            
        except Exception as e:
            self.logger.error(f"Error writing analysis results: {e}")
    
    def _print_analysis_summary(self, results: Dict[str, Any]):
        """Print a summary of the analysis results."""
        print("\n" + "="*60)
        print("OFFLINE ANALYSIS SUMMARY")
        print("="*60)
        
        # Frequency statistics
        freq_stats = results['frequency_statistics']
        print(f"\nFrequency Statistics:")
        print(f"  Mean: {freq_stats['mean']:.3f} Hz")
        print(f"  Std Dev: {freq_stats['std']:.3f} Hz")
        print(f"  Range: {freq_stats['min']:.3f} - {freq_stats['max']:.3f} Hz")
        print(f"  Total samples: {freq_stats['count']}")
        
        # Time analysis
        time_stats = results['time_analysis']
        print(f"\nTime Analysis:")
        print(f"  Duration: {time_stats['duration_seconds']:.1f} seconds ({time_stats['duration_seconds']/60:.1f} minutes)")
        print(f"  Sample rate: {time_stats['sample_rate_hz']:.2f} Hz")
        
        # Classification statistics
        class_stats = results['classification_statistics']
        print(f"\nClassification Statistics:")
        print(f"  Utility Grid: {class_stats['utility_count']} ({class_stats['utility_percentage']:.1f}%)")
        print(f"  Generator: {class_stats['generator_count']} ({class_stats['generator_percentage']:.1f}%)")
        print(f"  Unknown: {class_stats['unknown_count']} ({class_stats['unknown_percentage']:.1f}%)")
        
        # Confidence statistics
        conf_stats = results['confidence_statistics']
        print(f"\nConfidence Statistics:")
        print(f"  Mean confidence: {conf_stats['mean_confidence']:.3f}")
        print(f"  Confidence range: {conf_stats['min_confidence']:.3f} - {conf_stats['max_confidence']:.3f}")
        
        # Analysis metrics
        analysis_metrics = results['analysis_metrics']
        print(f"\nAnalysis Metrics:")
        print(f"  Mean Allan variance: {analysis_metrics['mean_allan_variance']:.2e}")
        print(f"  Mean std deviation: {analysis_metrics['mean_std_deviation']:.6f}")
        print(f"  Mean kurtosis: {analysis_metrics['mean_kurtosis']:.6f}")
        
        # Threshold analysis
        thresh_analysis = results['threshold_analysis']
        print(f"\nCurrent Threshold Analysis:")
        print(f"  Allan variance threshold: {thresh_analysis['allan_variance_threshold']:.2e}")
        print(f"  Std deviation threshold: {thresh_analysis['std_deviation_threshold']:.3f} Hz")
        print(f"  Kurtosis threshold: {thresh_analysis['kurtosis_threshold']:.3f}")
        
        # Recommended thresholds
        rec_thresh = results['recommended_thresholds']
        print(f"\nRecommended Thresholds (95th percentile):")
        print(f"  Allan variance: {rec_thresh['recommended_allan_variance']:.2e}")
        print(f"  Std deviation: {rec_thresh['recommended_std_deviation']:.6f} Hz")
        print(f"  Kurtosis: {rec_thresh['recommended_kurtosis']:.6f}")
        
        print("\n" + "="*60)
