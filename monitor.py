#!/usr/bin/env python3
"""
Raspberry Pi Frequency Monitor
Monitors AC line frequency to detect power source (Utility vs Generator)
"""

# Standard library imports
import argparse
import logging
import random
import signal
import sys
import time
from collections import deque
from typing import Optional, Tuple

# Third-party imports
import numpy as np
import allantools
from scipy import stats

# Local imports
from config import Config, Logger
from hardware import HardwareManager
from health import HealthMonitor, MemoryMonitor
from data_logger import DataLogger


class FrequencyAnalyzer:
    """Handles frequency analysis and classification."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.thresholds = config.get('analysis.generator_thresholds', {})
    
    def count_zero_crossings(self, duration: float = 0.5) -> Optional[float]:
        """Count zero-crossings over duration. Returns frequency (Hz)."""
        if not hasattr(self, 'hardware_manager'):
            return self._simulate_frequency()
        
        # Validate duration parameter
        if not isinstance(duration, (int, float)) or duration <= 0:
            self.logger.error(f"Invalid duration parameter: {duration}. Must be a positive number.")
            return None
        
        count = 0
        start_time = time.time()
        prev_state = self.hardware_manager.read_gpio()
        
        while time.time() - start_time < duration:
            state = self.hardware_manager.read_gpio()
            if state != prev_state and state == 1:  # Rising edge
                count += 1
            prev_state = state
            time.sleep(0.0001)  # Avoid CPU overload
        
        freq = count / (2 * duration)
        
        # Validate frequency is a number
        if not isinstance(freq, (int, float)) or np.isnan(freq) or np.isinf(freq):
            self.logger.error(f"Invalid frequency calculation result: {freq}")
            return None
        
        # Filter erratic readings
        min_freq = self.config.get('sampling.min_freq', 40.0)
        max_freq = self.config.get('sampling.max_freq', 80.0)
        
        if freq < min_freq or freq > max_freq:
            self.logger.warning(f"Invalid frequency reading: {freq:.2f} Hz (outside range {min_freq}-{max_freq} Hz)")
            return None
        
        return float(freq)  # Ensure we return a Python float
    
    def _simulate_frequency(self) -> float:
        """Simulate utility-like 60 Hz with noise."""
        base_freq = 60.0
        noise = random.gauss(0, 0.01)  # Utility-stable noise
        result = base_freq + noise
        
        return float(result)  # Ensure we return a Python float
    
    def analyze_stability(self, frac_freq: np.ndarray) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Compute Allan variance and statistical metrics."""
        # Check for None input first
        if frac_freq is None:
            self.logger.error("frac_freq is None. Cannot perform analysis.")
            return None, None, None
        
        if len(frac_freq) < 10:
            return None, None, None
        
        try:
            # Validate input data type - must be numeric
            if not isinstance(frac_freq, (np.ndarray, list, tuple)):
                self.logger.error(f"Invalid data type for frac_freq: {type(frac_freq)}. Expected numpy array, list, or tuple.")
                return None, None, None
            
            # Convert to numpy array and validate all elements are numeric
            try:
                frac_freq_array = np.array(frac_freq)
            except (ValueError, TypeError) as e:
                self.logger.error(f"Failed to convert frac_freq to numpy array: {e}. Data contains non-numeric values.")
                return None, None, None
            
            # Check if all elements are numeric (not strings, etc.)
            # First check if the dtype is numeric before using np.issubdtype
            if frac_freq_array.dtype.kind in ['U', 'S', 'O']:  # Unicode, byte string, or object
                self.logger.error(f"frac_freq contains non-numeric data. Dtype: {frac_freq_array.dtype}")
                return None, None, None
            
            # Now safe to use np.issubdtype
            if not np.issubdtype(frac_freq_array.dtype, np.number):
                self.logger.error(f"frac_freq contains non-numeric data. Dtype: {frac_freq_array.dtype}")
                return None, None, None
            
            # Check for NaN or infinite values
            if np.any(np.isnan(frac_freq_array)) or np.any(np.isinf(frac_freq_array)):
                self.logger.error("frac_freq contains NaN or infinite values")
                return None, None, None
            
            sample_rate = self.config.get('sampling.sample_rate', 2.0)
            # Use allantools.adev for Allan deviation calculation
            taus_out, adev, _, _ = allantools.adev(frac_freq_array, rate=sample_rate, data_type='freq')
            
            tau_target = self.config.get('analysis.allan_variance_tau', 10.0)
            if taus_out.size > 0 and adev.size > 0:
                avar_10s = float(adev[np.argmin(np.abs(taus_out - tau_target))])
            else:
                avar_10s = 0.0
            
            std_freq = float(np.std(frac_freq_array * 60.0))
            kurtosis = float(stats.kurtosis(frac_freq_array))
            
            return avar_10s, std_freq, kurtosis
        except Exception as e:
            self.logger.error(f"Error in stability analysis: {e}")
            return None, None, None
    
    def classify_power_source(self, avar_10s: Optional[float], std_freq: Optional[float], 
                            kurtosis: Optional[float]) -> str:
        """Classify as Generac generator or utility."""
        if any(x is None for x in [avar_10s, std_freq, kurtosis]):
            return "Unknown"
        
        # Get thresholds and ensure they are numeric
        avar_thresh = self.thresholds.get('allan_variance', 1e-9)
        std_thresh = self.thresholds.get('std_dev', 0.05)
        kurt_thresh = self.thresholds.get('kurtosis', 0.5)
        
        # Convert to float to ensure numeric comparison
        try:
            avar_thresh = float(avar_thresh)
            std_thresh = float(std_thresh)
            kurt_thresh = float(kurt_thresh)
        except (ValueError, TypeError) as e:
            self.logger.error(f"Invalid threshold values: avar={avar_thresh}, std={std_thresh}, kurt={kurt_thresh}. Error: {e}")
            return "Unknown"
        
        if avar_10s > avar_thresh or std_freq > std_thresh or kurtosis > kurt_thresh:
            return "Generac Generator"
        return "Utility Grid"


class FrequencyMonitor:
    """Main frequency monitoring class."""
    
    def __init__(self):
        self.config = Config("config.yaml")
        self.logger_setup = Logger(self.config)
        self.logger = logging.getLogger(__name__)
        
        self.hardware = HardwareManager(self.config, self.logger)
        self.analyzer = FrequencyAnalyzer(self.config, self.logger)
        self.health_monitor = HealthMonitor(self.config, self.logger)
        self.memory_monitor = MemoryMonitor(self.config, self.logger)
        self.data_logger = DataLogger(self.config, self.logger)
        
        # Connect analyzer to hardware
        self.analyzer.hardware_manager = self.hardware
        
        # Initialize data buffers
        sample_rate = self.config.get_float('sampling.sample_rate', 2.0)
        buffer_duration = self.config.get_float('sampling.buffer_duration', 300)
        buffer_size = int(buffer_duration * sample_rate)
        
        self.freq_buffer = deque(maxlen=buffer_size)
        self.time_buffer = deque(maxlen=buffer_size)
        
        # State variables
        self.running = True
        self.last_log_time = 0
        self.last_display_time = 0
        self.sample_count = 0
        self.start_time = time.time()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info("Frequency monitor initialized")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def run(self, simulator_mode: bool = None):
        """Main monitoring loop."""
        if simulator_mode is None:
            simulator_mode = self.config.get('app.simulator_mode', True)
        
        self.logger.info(f"Starting frequency monitor (simulator: {simulator_mode})")
        
        # Initialize display
        self.hardware.update_display("Starting...", "Please wait...")
        
        try:
            while self.running:
                current_time = time.time() - self.start_time
                
                # Get frequency reading
                if simulator_mode:
                    freq = self.analyzer._simulate_frequency()
                else:
                    freq = self.analyzer.count_zero_crossings(duration=1.0/self.config.get('sampling.sample_rate', 2.0))
                
                # Validate frequency reading
                if freq is None:
                    self.logger.warning("Skipping invalid frequency reading")
                    continue
                
                if not isinstance(freq, (int, float)):
                    self.logger.error(f"Invalid frequency data type: {type(freq)}. Expected number, got {freq}")
                    continue
                
                if np.isnan(freq) or np.isinf(freq):
                    self.logger.error(f"Invalid frequency value: {freq}")
                    continue
                
                # Update buffers
                self.freq_buffer.append(freq)
                self.time_buffer.append(current_time)
                self.sample_count += 1
                self.health_monitor.update_activity()
                
                # Analyze data
                frac_freq = (np.array(self.freq_buffer) - 60.0) / 60.0
                avar_10s, std_freq, kurtosis = self.analyzer.analyze_stability(frac_freq)
                source = self.analyzer.classify_power_source(avar_10s, std_freq, kurtosis)
                
                # Update display and LEDs once per second
                display_interval = self.config.get_float('app.display_update_interval', 1.0)
                
                if current_time - self.last_display_time >= display_interval:
                    self._update_display_and_leds(freq, source, std_freq)
                    self.last_display_time = current_time
                
                # Memory monitoring and cleanup
                memory_info = self.memory_monitor.get_memory_info()
                self.memory_monitor.check_memory_thresholds(memory_info)
                
                # Perform memory cleanup if needed
                self.memory_monitor.perform_cleanup()
                
                # Log hourly status
                if current_time - self.last_log_time >= 3600:  # 1 hour
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    self.data_logger.log_hourly_status(timestamp, freq, source, std_freq, kurtosis, self.sample_count)
                    
                    # Log memory information to CSV
                    memory_csv_file = self.config.get('logging.memory_log_file', 'memory_usage.csv')
                    self.memory_monitor.log_memory_to_csv(memory_csv_file)
                    
                    # Log memory summary
                    memory_summary = self.memory_monitor.get_memory_summary()
                    self.logger.info(f"Memory status: {memory_summary}")
                    
                    self.last_log_time = current_time
                
                # Maintain sample rate
                sample_rate = self.config.get_float('sampling.sample_rate', 2.0)
                
                sleep_time = max(0, 1.0/sample_rate - (time.time() - self.start_time - current_time))
                time.sleep(sleep_time)
                
        except Exception as e:
            self.logger.error(f"Error in main loop: {e}")
        finally:
            self.cleanup()
    
    def _update_display_and_leds(self, freq: float, source: str, std_freq: Optional[float]):
        """Update LCD display and LED indicators."""
        # Show time and frequency, updated once per second
        current_time = time.strftime("%H:%M:%S")
        line1 = f"Time: {current_time}"
        line2 = f"Freq: {freq:.2f} Hz"
        
        self.hardware.update_display(line1, line2)
        
        # Update LEDs
        is_utility = source == "Utility Grid"
        self.hardware.set_led('green', is_utility)
        self.hardware.set_led('red', not is_utility)
    
    def cleanup(self):
        """Cleanup resources."""
        self.logger.info("Cleaning up resources...")
        self.health_monitor.stop()
        
        if self.config.get('app.cleanup_on_exit', True):
            self.hardware.cleanup()
        
        self.logger.info("Cleanup completed")


def main():
    """Main entry point with command line argument parsing."""
    parser = argparse.ArgumentParser(description='Raspberry Pi Frequency Monitor')
    parser.add_argument('--simulator', '-s', action='store_true',
                       help='Run in simulator mode')
    parser.add_argument('--real', '-r', action='store_true',
                       help='Run with real hardware')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    parser.add_argument('--no-display-sim', action='store_true',
                       help='Disable LCD display simulation')
    
    args = parser.parse_args()
    
    # Determine simulator mode
    simulator_mode = args.simulator
    if args.real:
        simulator_mode = False
    
    try:
        monitor = FrequencyMonitor()
        
        # Override log level if verbose
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Override display simulation setting
        if args.no_display_sim:
            monitor.config.config['app']['simulate_display'] = False
        
        monitor.run(simulator_mode=simulator_mode)
        
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()