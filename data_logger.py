#!/usr/bin/env python3
"""
Data logging functionality for the frequency monitor.
Handles CSV logging of frequency data and system status.
"""

import csv
import logging
import time
import os
import fcntl
from typing import Optional, Dict, Any


class DataLogger:
    """Handles data logging operations."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.hourly_log_file = config.get('logging.hourly_log_file')
        
        # Detailed logging configuration
        self.detailed_logging_enabled = config.get('logging.detailed_logging_enabled')
        self.detailed_log_interval = config.get('logging.detailed_log_interval')  # seconds
        self.detailed_log_file = config.get('logging.detailed_log_file')
        self.last_detailed_log_time = 0
        
        # Initialize detailed log file header if enabled
        if self.detailed_logging_enabled:
            self._initialize_detailed_log_file()
    
    def _atomic_write_csv(self, filepath: str, data_rows: list, headers: list = None):
        """Write CSV data atomically with file locking."""
        temp_file = f"{filepath}.tmp"
        
        try:
            # Write to temporary file
            with open(temp_file, 'w', newline='') as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                
                writer = csv.writer(f)
                
                # Write headers if provided
                if headers:
                    writer.writerow(headers)
                
                # Write data rows
                for row in data_rows:
                    writer.writerow(row)
                
                # Flush and sync to disk
                f.flush()
                os.fsync(f.fileno())
            
            # Atomic rename
            os.rename(temp_file, filepath)
            self.logger.debug(f"Atomic write completed: {filepath}")
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_file):
                os.remove(temp_file)
            self.logger.error(f"Atomic write failed for {filepath}: {e}")
            raise
    
    def _initialize_detailed_log_file(self):
        """Initialize the detailed log file with headers."""
        try:
            with open(self.detailed_log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'datetime', 'unix_timestamp', 'elapsed_seconds',
                    'frequency_hz', 'allan_variance', 'std_deviation', 'kurtosis',
                    'power_source', 'confidence', 'sample_count', 'buffer_size'
                ])
            self.logger.info(f"Detailed logging enabled. Data will be written to: {self.detailed_log_file}")
        except Exception as e:
            self.logger.error(f"Failed to initialize detailed log file: {e}")
    
    def log_hourly_status(self, timestamp: str, freq: float, source: str,
                         std_freq: Optional[float], kurtosis: Optional[float],
                         sample_count: int, state_info: Optional[Dict[str, Any]] = None):
        """Log hourly status to CSV using atomic writes."""
        try:
            # Check if file exists to determine if we need headers
            file_exists = os.path.exists(self.hourly_log_file)
            
            # Prepare data row
            power_state = state_info.get('current_state', 'unknown') if state_info else 'unknown'
            state_duration = state_info.get('state_duration', 0) if state_info else 0
            
            data_row = [
                timestamp, f"{freq:.2f}", source,
                f"{std_freq:.4f}" if std_freq else "N/A",
                f"{kurtosis:.2f}" if kurtosis else "N/A",
                sample_count, power_state, f"{state_duration:.1f}"
            ]
            
            # Prepare headers if file doesn't exist
            headers = None
            if not file_exists:
                headers = ['timestamp', 'frequency_hz', 'source',
                          'std_dev_hz', 'kurtosis', 'samples_processed',
                          'power_state', 'state_duration_seconds']
            
            # Use atomic write
            self._atomic_write_csv(self.hourly_log_file, [data_row], headers)
            
            self.logger.info(f"Hourly status logged: {source} at {freq:.2f} Hz, state: {power_state}")
            
        except Exception as e:
            self.logger.error(f"Failed to log hourly status: {e}")
    
    def log_detailed_frequency_data(self, freq: float, analysis_results: Dict[str, Any], 
                                   source: str, sample_count: int, buffer_size: int,
                                   start_time: float):
        """Log detailed frequency data at configured intervals."""
        if not self.detailed_logging_enabled:
            return
        
        current_time = time.time()
        
        # Check if it's time to log (based on interval)
        if current_time - self.last_detailed_log_time < self.detailed_log_interval:
            return
        
        try:
            # Calculate confidence based on analysis results
            confidence = self._calculate_confidence(analysis_results, source)
            
            # Prepare data row
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            unix_timestamp = current_time
            elapsed_seconds = current_time - start_time
            
            data_row = [
                timestamp,
                time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],  # Include milliseconds
                f"{unix_timestamp:.3f}",
                f"{elapsed_seconds:.3f}",
                f"{freq:.6f}",
                f"{analysis_results.get('allan_variance', 0):.2e}" if analysis_results.get('allan_variance') is not None else "N/A",
                f"{analysis_results.get('std_deviation', 0):.6f}" if analysis_results.get('std_deviation') is not None else "N/A",
                f"{analysis_results.get('kurtosis', 0):.6f}" if analysis_results.get('kurtosis') is not None else "N/A",
                source,
                f"{confidence:.3f}",
                sample_count,
                buffer_size
            ]
            
            # Use atomic write
            self._atomic_write_csv(self.detailed_log_file, [data_row])
            
            self.last_detailed_log_time = current_time
            
        except Exception as e:
            self.logger.error(f"Failed to log detailed frequency data: {e}")
    
    def _calculate_confidence(self, analysis_results: Dict[str, Any], source: str) -> float:
        """Calculate confidence score for the classification."""
        try:
            # Get thresholds
            thresholds = self.config.get('analysis.generator_thresholds', {})
            avar_thresh = thresholds.get('allan_variance', 1e-9)
            std_thresh = thresholds.get('std_dev', 0.05)
            kurt_thresh = thresholds.get('kurtosis', 0.5)
            
            # Get analysis values
            avar = analysis_results.get('allan_variance', 0)
            std_dev = analysis_results.get('std_deviation', 0)
            kurtosis = analysis_results.get('kurtosis', 0)
            
            if avar is None or std_dev is None or kurtosis is None:
                return 0.5  # Unknown confidence
            
            # Calculate how far each metric is from threshold
            avar_ratio = avar / avar_thresh if avar_thresh > 0 else 0
            std_ratio = std_dev / std_thresh if std_thresh > 0 else 0
            kurt_ratio = kurtosis / kurt_thresh if kurt_thresh > 0 else 0
            
            # Calculate confidence based on how clearly the metrics indicate the classification
            if source == "Generac Generator":
                # Higher values should give higher confidence for generator
                confidence = min(1.0, (avar_ratio + std_ratio + kurt_ratio) / 3.0)
            else:
                # Lower values should give higher confidence for utility
                confidence = min(1.0, (1.0 / max(avar_ratio, 0.1) + 1.0 / max(std_ratio, 0.1) + 1.0 / max(kurt_ratio, 0.1)) / 3.0)
            
            return max(0.0, min(1.0, confidence))
            
        except Exception as e:
            self.logger.error(f"Error calculating confidence: {e}")
            return 0.5
    
    def enable_detailed_logging(self, log_file: str = None, interval: float = None):
        """Enable detailed logging with optional custom settings."""
        self.detailed_logging_enabled = True
        if log_file:
            self.detailed_log_file = log_file
        if interval:
            self.detailed_log_interval = interval
        
        self._initialize_detailed_log_file()
        self.logger.info(f"Detailed logging enabled: {self.detailed_log_file} (interval: {self.detailed_log_interval}s)")
    
    def disable_detailed_logging(self):
        """Disable detailed logging."""
        self.detailed_logging_enabled = False
        self.logger.info("Detailed logging disabled")
