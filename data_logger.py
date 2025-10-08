#!/usr/bin/env python3
"""
Data logging functionality for the frequency monitor.
Handles CSV logging of frequency data and system status.
"""

import csv
import logging
from typing import Optional


class DataLogger:
    """Handles data logging operations."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.hourly_log_file = config.get('logging.hourly_log_file', 'hourly_status.csv')
    
    def log_hourly_status(self, timestamp: str, freq: float, source: str, 
                         std_freq: Optional[float], kurtosis: Optional[float], 
                         sample_count: int):
        """Log hourly status to CSV."""
        try:
            with open(self.hourly_log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                if f.tell() == 0:
                    writer.writerow(['timestamp', 'frequency_hz', 'source', 
                                   'std_dev_hz', 'kurtosis', 'samples_processed'])
                writer.writerow([
                    timestamp, f"{freq:.2f}", source,
                    f"{std_freq:.4f}" if std_freq else "N/A",
                    f"{kurtosis:.2f}" if kurtosis else "N/A",
                    sample_count
                ])
            self.logger.info(f"Hourly status logged: {source} at {freq:.2f} Hz")
        except Exception as e:
            self.logger.error(f"Failed to log hourly status: {e}")
