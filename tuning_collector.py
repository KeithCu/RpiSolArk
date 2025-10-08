#!/usr/bin/env python3
"""
Tuning data collection module for frequency analysis optimization.
Collects detailed frequency data and analysis results for threshold tuning.
"""

import csv
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
import numpy as np


class TuningDataCollector:
    """Collects detailed frequency data for tuning analysis."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.tuning_config = config.get('tuning', {})
        
        # Tuning mode settings
        self.enabled = self.tuning_config.get('enabled', False)
        self.detailed_logging = self.tuning_config.get('detailed_logging', False)
        self.sample_interval = self.tuning_config.get('sample_interval', 0.1)
        self.analysis_interval = self.tuning_config.get('analysis_interval', 1.0)
        self.data_file = self.tuning_config.get('data_file', 'tuning_data.csv')
        self.analysis_file = self.tuning_config.get('analysis_file', 'tuning_analysis.csv')
        self.collection_duration = self.tuning_config.get('collection_duration', 3600)
        self.auto_stop = self.tuning_config.get('auto_stop', True)
        self.export_format = self.tuning_config.get('export_format', 'csv')
        
        # Data collection settings
        self.include_raw_data = self.tuning_config.get('include_raw_data', True)
        self.include_analysis = self.tuning_config.get('include_analysis', True)
        self.include_classification = self.tuning_config.get('include_classification', True)
        self.include_timestamps = self.tuning_config.get('include_timestamps', True)
        self.buffer_analysis = self.tuning_config.get('buffer_analysis', True)
        
        # Collection state
        self.start_time = None
        self.sample_count = 0
        self.analysis_count = 0
        self.last_analysis_time = 0
        self.data_buffer = []
        self.analysis_buffer = []
        
        # File handles
        self.data_file_handle = None
        self.analysis_file_handle = None
        self.data_writer = None
        self.analysis_writer = None
        
        if self.enabled:
            self._setup_data_collection()
            self.logger.info("Tuning data collection enabled")
    
    def _setup_data_collection(self):
        """Setup data collection files and headers."""
        try:
            # Setup data file
            if self.include_raw_data:
                self.data_file_handle = open(self.data_file, 'w', newline='')
                self.data_writer = csv.writer(self.data_file_handle)
                
                # Write headers
                headers = ['timestamp', 'datetime', 'frequency_hz']
                if self.include_timestamps:
                    headers.extend(['unix_timestamp', 'elapsed_seconds'])
                if self.include_analysis:
                    headers.extend(['allan_variance', 'std_deviation', 'kurtosis'])
                if self.include_classification:
                    headers.extend(['power_source', 'confidence'])
                
                self.data_writer.writerow(headers)
                self.logger.info(f"Data collection file: {self.data_file}")
            
            # Setup analysis file
            if self.include_analysis:
                self.analysis_file_handle = open(self.analysis_file, 'w', newline='')
                self.analysis_writer = csv.writer(self.analysis_file_handle)
                
                # Write analysis headers
                analysis_headers = [
                    'timestamp', 'datetime', 'sample_count', 'buffer_size',
                    'allan_variance', 'std_deviation', 'kurtosis',
                    'power_source', 'confidence', 'thresholds_used'
                ]
                self.analysis_writer.writerow(analysis_headers)
                self.logger.info(f"Analysis collection file: {self.analysis_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to setup data collection: {e}")
            self.enabled = False
    
    def start_collection(self):
        """Start data collection."""
        if not self.enabled:
            return
        
        self.start_time = time.time()
        self.sample_count = 0
        self.analysis_count = 0
        self.last_analysis_time = 0
        self.data_buffer = []
        self.analysis_buffer = []
        
        self.logger.info(f"Starting tuning data collection for {self.collection_duration} seconds")
        self.logger.info(f"Sample interval: {self.sample_interval}s, Analysis interval: {self.analysis_interval}s")
    
    def collect_frequency_sample(self, frequency: float, analysis_results: Optional[Dict] = None, 
                               classification: Optional[str] = None) -> bool:
        """Collect a frequency sample and analysis data."""
        if not self.enabled or not self.start_time:
            return False
        
        current_time = time.time()
        elapsed = current_time - self.start_time
        
        # Check if collection should stop
        if self.auto_stop and elapsed >= self.collection_duration:
            self.stop_collection()
            return False
        
        # Collect sample data
        sample_data = {
            'timestamp': current_time,
            'datetime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time)),
            'frequency_hz': frequency,
            'elapsed_seconds': elapsed
        }
        
        # Add analysis results if available
        if analysis_results and self.include_analysis:
            sample_data.update({
                'allan_variance': analysis_results.get('allan_variance'),
                'std_deviation': analysis_results.get('std_deviation'),
                'kurtosis': analysis_results.get('kurtosis')
            })
        
        # Add classification if available
        if classification and self.include_classification:
            sample_data.update({
                'power_source': classification,
                'confidence': self._calculate_confidence(analysis_results)
            })
        
        # Write to file immediately
        if self.data_writer and self.include_raw_data:
            try:
                row = [sample_data.get('timestamp', ''),
                       sample_data.get('datetime', ''),
                       sample_data.get('frequency_hz', '')]
                
                if self.include_timestamps:
                    row.extend([sample_data.get('timestamp', ''), sample_data.get('elapsed_seconds', '')])
                if self.include_analysis:
                    row.extend([
                        sample_data.get('allan_variance', ''),
                        sample_data.get('std_deviation', ''),
                        sample_data.get('kurtosis', '')
                    ])
                if self.include_classification:
                    row.extend([
                        sample_data.get('power_source', ''),
                        sample_data.get('confidence', '')
                    ])
                
                self.data_writer.writerow(row)
                self.data_file_handle.flush()  # Ensure data is written immediately
                
            except Exception as e:
                self.logger.error(f"Failed to write sample data: {e}")
        
        # Add to buffer for analysis
        self.data_buffer.append(sample_data)
        self.sample_count += 1
        
        # Detailed logging
        if self.detailed_logging:
            self.logger.debug(f"Sample {self.sample_count}: {frequency:.3f} Hz, "
                            f"Source: {classification}, Elapsed: {elapsed:.1f}s")
        
        return True
    
    def collect_analysis_results(self, analysis_results: Dict[str, Any], 
                               classification: str, buffer_size: int) -> bool:
        """Collect analysis results."""
        if not self.enabled or not self.start_time:
            return False
        
        current_time = time.time()
        elapsed = current_time - self.start_time
        
        # Check if collection should stop
        if self.auto_stop and elapsed >= self.collection_duration:
            self.stop_collection()
            return False
        
        # Only collect analysis at specified intervals
        if current_time - self.last_analysis_time < self.analysis_interval:
            return True
        
        self.last_analysis_time = current_time
        
        # Prepare analysis data
        analysis_data = {
            'timestamp': current_time,
            'datetime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time)),
            'sample_count': self.sample_count,
            'buffer_size': buffer_size,
            'allan_variance': analysis_results.get('allan_variance'),
            'std_deviation': analysis_results.get('std_deviation'),
            'kurtosis': analysis_results.get('kurtosis'),
            'power_source': classification,
            'confidence': self._calculate_confidence(analysis_results),
            'thresholds_used': self._get_current_thresholds()
        }
        
        # Write to analysis file
        if self.analysis_writer and self.include_analysis:
            try:
                row = [
                    analysis_data['timestamp'],
                    analysis_data['datetime'],
                    analysis_data['sample_count'],
                    analysis_data['buffer_size'],
                    analysis_data['allan_variance'],
                    analysis_data['std_deviation'],
                    analysis_data['kurtosis'],
                    analysis_data['power_source'],
                    analysis_data['confidence'],
                    analysis_data['thresholds_used']
                ]
                
                self.analysis_writer.writerow(row)
                self.analysis_file_handle.flush()
                
            except Exception as e:
                self.logger.error(f"Failed to write analysis data: {e}")
        
        # Add to buffer
        self.analysis_buffer.append(analysis_data)
        self.analysis_count += 1
        
        # Detailed logging
        if self.detailed_logging:
            self.logger.info(f"Analysis {self.analysis_count}: "
                           f"Allan={analysis_results.get('allan_variance', 0):.2e}, "
                           f"StdDev={analysis_results.get('std_deviation', 0):.3f}, "
                           f"Kurtosis={analysis_results.get('kurtosis', 0):.2f}, "
                           f"Source={classification}")
        
        return True
    
    def _calculate_confidence(self, analysis_results: Optional[Dict]) -> float:
        """Calculate confidence score for classification."""
        if not analysis_results:
            return 0.0
        
        # Simple confidence calculation based on how far values are from thresholds
        thresholds = self.config.get('analysis.generator_thresholds', {})
        avar_thresh = thresholds.get('allan_variance', 5e-10)
        std_thresh = thresholds.get('std_dev', 0.08)
        kurt_thresh = thresholds.get('kurtosis', 0.4)
        
        avar = analysis_results.get('allan_variance', 0)
        std_dev = analysis_results.get('std_deviation', 0)
        kurtosis = analysis_results.get('kurtosis', 0)
        
        # Calculate how far each metric is from threshold
        try:
            avar_ratio = avar / float(avar_thresh) if float(avar_thresh) > 0 else 0
            std_ratio = std_dev / float(std_thresh) if float(std_thresh) > 0 else 0
            kurt_ratio = kurtosis / float(kurt_thresh) if float(kurt_thresh) > 0 else 0
        except (ValueError, TypeError, ZeroDivisionError):
            return 0.0
        
        # Confidence is based on how clearly the values exceed thresholds
        max_ratio = max(avar_ratio, std_ratio, kurt_ratio)
        confidence = min(1.0, max_ratio)
        
        return round(confidence, 3)
    
    def _get_current_thresholds(self) -> str:
        """Get current threshold values as string."""
        thresholds = self.config.get('analysis.generator_thresholds', {})
        try:
            avar = float(thresholds.get('allan_variance', 0))
            std = float(thresholds.get('std_dev', 0))
            kurt = float(thresholds.get('kurtosis', 0))
            return f"avar={avar:.2e},std={std:.3f},kurt={kurt:.2f}"
        except (ValueError, TypeError):
            return "avar=0.00e+00,std=0.000,kurt=0.00"
    
    def stop_collection(self):
        """Stop data collection and generate summary."""
        if not self.enabled or not self.start_time:
            return
        
        collection_time = time.time() - self.start_time
        
        self.logger.info(f"Tuning data collection completed:")
        self.logger.info(f"  Duration: {collection_time:.1f} seconds")
        self.logger.info(f"  Samples collected: {self.sample_count}")
        self.logger.info(f"  Analysis points: {self.analysis_count}")
        self.logger.info(f"  Data file: {self.data_file}")
        self.logger.info(f"  Analysis file: {self.analysis_file}")
        
        # Generate summary report
        self._generate_summary_report()
        
        # Close files
        if self.data_file_handle:
            self.data_file_handle.close()
        if self.analysis_file_handle:
            self.analysis_file_handle.close()
        
        # Reset state
        self.start_time = None
        self.sample_count = 0
        self.analysis_count = 0
    
    def _generate_summary_report(self):
        """Generate a summary report of collected data."""
        if not self.data_buffer:
            return
        
        try:
            # Calculate statistics
            frequencies = [d['frequency_hz'] for d in self.data_buffer if 'frequency_hz' in d]
            
            if frequencies:
                freq_array = np.array(frequencies)
                summary = {
                    'collection_duration': time.time() - self.start_time,
                    'sample_count': len(frequencies),
                    'frequency_stats': {
                        'mean': float(np.mean(freq_array)),
                        'std': float(np.std(freq_array)),
                        'min': float(np.min(freq_array)),
                        'max': float(np.max(freq_array)),
                        'range': float(np.max(freq_array) - np.min(freq_array))
                    }
                }
                
                # Write summary to file
                summary_file = f"tuning_summary_{int(time.time())}.json"
                with open(summary_file, 'w') as f:
                    json.dump(summary, f, indent=2)
                
                self.logger.info(f"Summary report saved: {summary_file}")
                self.logger.info(f"Frequency range: {summary['frequency_stats']['min']:.2f} - {summary['frequency_stats']['max']:.2f} Hz")
                self.logger.info(f"Frequency std dev: {summary['frequency_stats']['std']:.3f} Hz")
                
        except Exception as e:
            self.logger.error(f"Failed to generate summary report: {e}")
    
    def is_collection_active(self) -> bool:
        """Check if data collection is currently active."""
        if not self.enabled or not self.start_time:
            return False
        
        if self.auto_stop:
            elapsed = time.time() - self.start_time
            return elapsed < self.collection_duration
        
        return True
    
    def get_collection_status(self) -> Dict[str, Any]:
        """Get current collection status."""
        if not self.enabled:
            return {'enabled': False}
        
        if not self.start_time:
            return {'enabled': True, 'status': 'not_started'}
        
        elapsed = time.time() - self.start_time
        remaining = max(0, self.collection_duration - elapsed) if self.auto_stop else None
        
        return {
            'enabled': True,
            'status': 'active' if self.is_collection_active() else 'completed',
            'elapsed_seconds': elapsed,
            'remaining_seconds': remaining,
            'sample_count': self.sample_count,
            'analysis_count': self.analysis_count,
            'data_file': self.data_file,
            'analysis_file': self.analysis_file
        }
