#!/usr/bin/env python3
"""
Raspberry Pi Frequency Monitor
Monitors AC line frequency to detect power source (Utility vs Generator)
"""

# Standard library imports
import argparse
import csv
import logging
import os
import random
import signal
import sys
import time
from collections import deque
from typing import Optional, Tuple, List, Dict, Any
from enum import Enum

# Third-party imports
import numpy as np
import allantools
from scipy import stats

# Local imports
from config import Config, Logger
from hardware import HardwareManager
from health import HealthMonitor, MemoryMonitor
from data_logger import DataLogger
from tuning_collector import TuningDataCollector


class PowerState(Enum):
    """Power system states."""
    OFF_GRID = "off_grid"
    GRID = "grid"
    GENERATOR = "generator"
    TRANSITIONING = "transitioning"


class PowerStateMachine:
    """State machine for power system management."""

    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.current_state = PowerState.TRANSITIONING  # Start in transitioning to allow detection
        self.previous_state = PowerState.TRANSITIONING
        self.state_entry_time = time.time()
        self.transition_timeout = config.get('state_machine.transition_timeout', 30)  # seconds
        self.zero_voltage_threshold = config.get('state_machine.zero_voltage_threshold', 5)  # seconds of no cycles
        self.unsteady_voltage_threshold = config.get('state_machine.unsteady_voltage_threshold', 0.1)  # Hz variation

        # State change callbacks - only for main power states
        self.on_state_change_callbacks = {
            PowerState.OFF_GRID: self._on_enter_off_grid,
            PowerState.GRID: self._on_enter_grid,
            PowerState.GENERATOR: self._on_enter_generator
        }

        self.logger.info(f"Power state machine initialized in {self.current_state.value} state")

    def update_state(self, frequency: Optional[float], power_source: str,
                    zero_voltage_duration: float) -> PowerState:
        """
        Update state based on current conditions using existing frequency analysis.

        Args:
            frequency: Current frequency reading (None if no signal)
            power_source: Classification from FrequencyAnalyzer ("Utility Grid", "Generac Generator", or "Unknown")
            zero_voltage_duration: How long voltage has been zero (seconds)
        """
        new_state = self._determine_state(frequency, power_source, zero_voltage_duration)

        # Check if state changed
        if new_state != self.current_state:
            self._transition_to_state(new_state)

        # Check for transition timeout
        elif self.current_state == PowerState.TRANSITIONING:
            if time.time() - self.state_entry_time > self.transition_timeout:
                self.logger.warning(f"Transition timeout exceeded, forcing to OFF_GRID")
                self._transition_to_state(PowerState.OFF_GRID)

        return self.current_state

    def _determine_state(self, frequency: Optional[float], power_source: str,
                        zero_voltage_duration: float) -> PowerState:
        """Determine the appropriate state based on existing frequency analysis."""

        # No voltage detected for extended period = OFF_GRID
        if zero_voltage_duration >= self.zero_voltage_threshold:
            return PowerState.OFF_GRID

        # No frequency reading available = TRANSITIONING
        if frequency is None:
            return PowerState.TRANSITIONING

        # Use existing frequency analysis classification
        if power_source == "Utility Grid":
            return PowerState.GRID
        elif power_source == "Generac Generator":
            return PowerState.GENERATOR
        else:  # "Unknown" or any other classification
            return PowerState.TRANSITIONING

    def _transition_to_state(self, new_state: PowerState):
        """Handle state transition."""
        old_state = self.current_state
        self.previous_state = old_state
        self.current_state = new_state
        self.state_entry_time = time.time()

        self.logger.info(f"Power state transition: {old_state.value} -> {new_state.value}")

        # Execute state change callback
        if new_state in self.on_state_change_callbacks:
            try:
                self.on_state_change_callbacks[new_state]()
            except Exception as e:
                self.logger.error(f"Error in state change callback for {new_state.value}: {e}")

    def get_state_info(self) -> Dict[str, Any]:
        """Get current state information."""
        return {
            'current_state': self.current_state.value,
            'previous_state': self.previous_state.value,
            'state_duration': time.time() - self.state_entry_time,
            'transition_timeout': self.transition_timeout
        }

    # Template action functions - to be implemented with real work
    def _on_enter_off_grid(self):
        """Called when entering OFF_GRID state."""
        self.logger.info("POWER OUTAGE: System is now OFF-GRID")
        # TODO: Implement power outage response actions
        pass

    def _on_enter_grid(self):
        """Called when entering GRID state."""
        self.logger.info("GRID POWER: Stable utility power detected")
        # TODO: Implement grid power restoration actions
        pass

    def _on_enter_generator(self):
        """Called when entering GENERATOR state."""
        self.logger.info("GENERATOR: Backup generator power detected")
        # TODO: Implement generator power response actions
        pass


class FrequencyAnalyzer:
    """Handles frequency analysis and classification."""

    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.thresholds = config.get('analysis.generator_thresholds', {})

        # Simulator state
        self.simulator_start_time = None
        self.simulator_state = "grid"  # grid -> off_grid -> generator -> grid
    
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
    
    def _simulate_frequency(self) -> Optional[float]:
        """Simulate power state cycling: grid (8s) -> off-grid (6s) -> generator (8s) -> grid (6s)."""
        current_time = time.time()

        # Initialize simulator start time
        if self.simulator_start_time is None:
            self.simulator_start_time = current_time

        # Calculate elapsed time and current phase (0-28 seconds cycle)
        elapsed = current_time - self.simulator_start_time
        cycle_time = elapsed % 28.0  # 28 second cycle: 8s grid + 6s off + 8s gen + 6s grid

        # Determine current state based on cycle time
        if cycle_time < 8.0:
            # Grid power (0-8s): very stable 60 Hz - gives time for detection
            self.simulator_state = "grid"
            base_freq = 60.0
            noise = random.gauss(0, 0.005)  # Very small stable noise
            return float(base_freq + noise)

        elif cycle_time < 14.0:
            # Off-grid power (8-14s): no frequency (None) - longer than 5s threshold
            self.simulator_state = "off_grid"
            return None  # No signal

        elif cycle_time < 22.0:
            # Generator power (14-22s): variable frequency with hunting - gives time for detection
            self.simulator_state = "generator"
            # Simulate generator hunting: alternating high/low every 2 seconds
            phase_in_cycle = (cycle_time - 14.0) % 4.0
            if phase_in_cycle < 2.0:
                base_freq = 58.5 + random.uniform(-0.5, 1.0)  # Low range
            else:
                base_freq = 61.0 + random.uniform(-1.0, 0.5)  # High range
            noise = random.gauss(0, 0.3)  # Moderate generator noise
            return float(base_freq + noise)

        else:
            # Back to grid power (22-28s): stable 60 Hz - final grid period
            self.simulator_state = "grid"
            base_freq = 60.0
            noise = random.gauss(0, 0.005)  # Very small stable noise
            return float(base_freq + noise)
    
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
        self.state_machine = PowerStateMachine(self.config, self.logger)
        self.health_monitor = HealthMonitor(self.config, self.logger)
        self.memory_monitor = MemoryMonitor(self.config, self.logger)
        self.data_logger = DataLogger(self.config, self.logger)
        self.tuning_collector = TuningDataCollector(self.config, self.logger)
        
        # Connect analyzer to hardware
        self.analyzer.hardware_manager = self.hardware
        
        # Initialize data buffers
        sample_rate = self.config.get_float('sampling.sample_rate', 2.0)
        buffer_duration = self.config.get_float('sampling.buffer_duration', 300)
        buffer_size = int(buffer_duration * sample_rate)
        
        self.freq_buffer = deque(maxlen=buffer_size)
        self.time_buffer = deque(maxlen=buffer_size)
        
        # Initialize power source classification buffer for U/G indicator
        classification_window = self.config.get_float('display.classification_window', 300)  # 5 minutes default
        classification_buffer_size = int(classification_window * sample_rate)
        self.classification_buffer = deque(maxlen=classification_buffer_size)
        
        # State variables
        self.running = True
        self.last_log_time = 0
        self.last_display_time = 0
        self.sample_count = 0
        self.start_time = time.time()
        self.zero_voltage_start_time = None  # Track when voltage went to zero
        self.zero_voltage_duration = 0.0    # How long voltage has been zero

        # Reset button state tracking
        self.reset_button_pressed = False
        self.last_reset_check = 0
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info("Frequency monitor initialized")
        
        # Start tuning data collection if enabled
        if self.tuning_collector.enabled:
            self.tuning_collector.start_collection()
    
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

        # For simulator mode, set up auto-exit after 20 seconds
        if simulator_mode:
            self.simulator_exit_time = time.time() + 20.0
            self.logger.info("Simulator mode: will auto-exit after 20 seconds (28s power cycle)")
        
        try:
            while self.running:
                current_time = time.time() - self.start_time
                
                # Get frequency reading
                if simulator_mode:
                    freq = self.analyzer._simulate_frequency()
                else:
                    freq = self.analyzer.count_zero_crossings(duration=1.0/self.config.get('sampling.sample_rate', 2.0))

                # Track zero voltage duration
                if freq is None or freq == 0:
                    # No frequency detected - voltage is zero
                    if self.zero_voltage_start_time is None:
                        self.zero_voltage_start_time = current_time
                    self.zero_voltage_duration = current_time - self.zero_voltage_start_time
                else:
                    # Frequency detected - reset zero voltage tracking
                    self.zero_voltage_start_time = None
                    self.zero_voltage_duration = 0.0

                # Validate frequency reading
                if freq is None:
                    self.logger.warning(f"No frequency reading (zero voltage duration: {self.zero_voltage_duration:.1f}s)")
                    # Continue processing even with no frequency for state machine updates
                elif not isinstance(freq, (int, float)):
                    self.logger.error(f"Invalid frequency data type: {type(freq)}. Expected number, got {freq}")
                    continue
                elif np.isnan(freq) or np.isinf(freq):
                    self.logger.error(f"Invalid frequency value: {freq}")
                    continue
                
                # Update buffers only with valid frequency readings
                if freq is not None:
                    self.freq_buffer.append(freq)
                    self.time_buffer.append(current_time)
                    self.sample_count += 1

                self.health_monitor.update_activity()

                # Analyze data only if we have enough samples
                if len(self.freq_buffer) >= 10:
                    frac_freq = (np.array(self.freq_buffer) - 60.0) / 60.0
                    avar_10s, std_freq, kurtosis = self.analyzer.analyze_stability(frac_freq)
                    source = self.analyzer.classify_power_source(avar_10s, std_freq, kurtosis)
                elif len(self.freq_buffer) >= 3:
                    # Quick detection with fewer samples for better UX
                    recent_freqs = list(self.freq_buffer)[-3:]  # Last 3 readings
                    avg_freq = sum(recent_freqs) / len(recent_freqs)
                    variation = max(recent_freqs) - min(recent_freqs)

                    if variation < 0.1 and 59.9 <= avg_freq <= 60.1:
                        source = "Utility Grid"  # Quick stable detection
                    elif variation > 0.5:
                        source = "Generac Generator"  # Quick unstable detection
                    else:
                        source = "Unknown"
                    avar_10s, std_freq, kurtosis = None, None, None
                else:
                    # Not enough data for analysis yet
                    avar_10s, std_freq, kurtosis = None, None, None
                    source = "Unknown"

                # Update state machine with current conditions
                current_state = self.state_machine.update_state(freq, source, self.zero_voltage_duration)
                
                # Collect tuning data if enabled
                if self.tuning_collector.enabled:
                    analysis_results = {
                        'allan_variance': avar_10s,
                        'std_deviation': std_freq,
                        'kurtosis': kurtosis
                    }
                    self.tuning_collector.collect_frequency_sample(freq, analysis_results, source)
                    self.tuning_collector.collect_analysis_results(analysis_results, source, len(self.freq_buffer))
                
                # Log detailed frequency data if enabled
                analysis_results = {
                    'allan_variance': avar_10s,
                    'std_deviation': std_freq,
                    'kurtosis': kurtosis
                }
                self.data_logger.log_detailed_frequency_data(
                    freq, analysis_results, source, self.sample_count, 
                    len(self.freq_buffer), self.start_time
                )
                
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
                
                # Check for simulator auto-exit
                if simulator_mode and time.time() >= self.simulator_exit_time:
                    self.logger.info("Simulator auto-exit time reached (20 seconds)")
                    break

                # Check reset button (debounced, check every 0.5 seconds)
                current_time = time.time()
                if current_time - self.last_reset_check >= 0.5:
                    self.last_reset_check = current_time
                    if self.hardware.check_reset_button():
                        if not self.reset_button_pressed:
                            self.reset_button_pressed = True
                            self.logger.info("Reset button pressed - restarting application")
                            self._handle_reset()
                    else:
                        self.reset_button_pressed = False

                # Log hourly status
                if current_time - self.last_log_time >= 3600:  # 1 hour
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    state_info = self.state_machine.get_state_info()
                    self.data_logger.log_hourly_status(timestamp, freq, source, std_freq, kurtosis, self.sample_count,
                                                     state_info=state_info)

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
    
    def _get_current_power_source_indicator(self) -> str:
        """Get U/G indicator based on recent power source classifications."""
        if not self.classification_buffer:
            return "?"
        
        # Count recent classifications
        utility_count = sum(1 for source in self.classification_buffer if source == "Utility Grid")
        generator_count = sum(1 for source in self.classification_buffer if source == "Generac Generator")
        total_count = len(self.classification_buffer)
        
        # Determine majority classification
        if utility_count > generator_count:
            indicator = "U"  # Utility
        elif generator_count > utility_count:
            indicator = "G"  # Generator
        else:
            indicator = "?"  # Unknown/Equal
        
        # Log classification details for debugging (only occasionally to avoid spam)
        if total_count % 10 == 0:  # Log every 10th update
            self.logger.debug(f"U/G Indicator: {indicator} (U:{utility_count}, G:{generator_count}, Total:{total_count})")
        
        return indicator
    
    def _update_display_and_leds(self, freq: float, source: str, std_freq: Optional[float]):
        """Update LCD display and LED indicators."""
        # Add current classification to buffer
        self.classification_buffer.append(source)

        # Get state machine status
        state_info = self.state_machine.get_state_info()
        current_state = state_info['current_state']

        # Get U/G indicator based on recent data
        ug_indicator = self._get_current_power_source_indicator()

        # Show time and frequency with state indicator, updated once per second
        current_time = time.strftime("%H:%M:%S")
        state_display = self._get_state_display_code(current_state)
        line1 = f"Time: {current_time} [{state_display}]"

        if freq is not None:
            line2 = f"Freq: {freq:.2f} Hz"
        else:
            line2 = f"No Signal ({self.zero_voltage_duration:.0f}s)"

        self.hardware.update_display(line1, line2)

        # Update LEDs based on state machine state
        self._update_leds_for_state(current_state)

    def _get_state_display_code(self, state: str) -> str:
        """Get display code for power state."""
        state_codes = {
            'off_grid': 'OFF-GRID',
            'grid': 'UTILITY',
            'generator': 'GENERATOR',
            'transitioning': 'DETECTING'
        }
        return state_codes.get(state, 'UNKNOWN')

    def _update_leds_for_state(self, state: str):
        """Update LED indicators based on power state."""
        # Turn off all LEDs first
        self.hardware.set_led('green', False)
        self.hardware.set_led('red', False)

        # Set LEDs based on state
        if state == 'grid':
            self.hardware.set_led('green', True)  # Green for grid power
        elif state == 'generator':
            self.hardware.set_led('red', True)    # Red for generator power
        elif state == 'off_grid':
            # Both LEDs off for off-grid (power outage)
            pass
        elif state == 'transitioning':
            # Both LEDs on for transitioning (flashing/unclear state)
            self.hardware.set_led('green', True)
            self.hardware.set_led('red', True)

    def _handle_reset(self):
        """Handle reset button press - restart the application."""
        self.logger.info("Initiating application restart...")

        # Show reset message on LCD
        self.hardware.update_display("RESET", "Restarting...")

        # Cleanup resources
        self.cleanup()

        # Brief delay to show the message
        time.sleep(1)

        # Restart the application
        import sys
        import os
        self.logger.info("Restarting application now")
        os.execv(sys.executable, ['python'] + sys.argv)

    def cleanup(self):
        """Cleanup resources."""
        self.logger.info("Cleaning up resources...")
        self.health_monitor.stop()
        
        # Stop tuning data collection
        if self.tuning_collector.enabled:
            self.tuning_collector.stop_collection()
        
        if self.config.get('app.cleanup_on_exit', True):
            self.hardware.cleanup()
        
        self.logger.info("Cleanup completed")
    
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
                    writer.writerow(['Frequency', key, value])
                writer.writerow([])
                
                # Time analysis
                writer.writerow(['TIME ANALYSIS', '', ''])
                for key, value in results['time_analysis'].items():
                    writer.writerow(['Time', key, value])
                writer.writerow([])
                
                # Classification statistics
                writer.writerow(['CLASSIFICATION STATISTICS', '', ''])
                for key, value in results['classification_statistics'].items():
                    writer.writerow(['Classification', key, value])
                writer.writerow([])
                
                # Confidence statistics
                writer.writerow(['CONFIDENCE STATISTICS', '', ''])
                for key, value in results['confidence_statistics'].items():
                    writer.writerow(['Confidence', key, value])
                writer.writerow([])
                
                # Analysis metrics
                writer.writerow(['ANALYSIS METRICS', '', ''])
                for key, value in results['analysis_metrics'].items():
                    writer.writerow(['Analysis', key, value])
                writer.writerow([])
                
                # Threshold analysis
                writer.writerow(['THRESHOLD ANALYSIS', '', ''])
                for key, value in results['threshold_analysis'].items():
                    writer.writerow(['Threshold', key, value])
                writer.writerow([])
                
                # Recommended thresholds
                writer.writerow(['RECOMMENDED THRESHOLDS', '', ''])
                for key, value in results['recommended_thresholds'].items():
                    writer.writerow(['Recommended', key, value])
                writer.writerow([])
                
                # Raw data
                writer.writerow(['RAW DATA', '', ''])
                raw_data = results['raw_data']
                if raw_data:
                    # Write header
                    writer.writerow(list(raw_data[0].keys()))
                    # Write data
                    for row in raw_data:
                        writer.writerow(list(row.values()))
            
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
        print(f"  Mean std deviation: {analysis_metrics['mean_std_deviation']:.6f} Hz")
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
    parser.add_argument('--tuning', '-t', action='store_true',
                       help='Enable tuning data collection mode')
    parser.add_argument('--tuning-duration', type=int, default=3600,
                       help='Tuning data collection duration in seconds (default: 3600)')
    parser.add_argument('--detailed-logging', '-d', action='store_true',
                       help='Enable detailed frequency logging mode')
    parser.add_argument('--log-interval', type=float, default=1.0,
                       help='Detailed logging interval in seconds (default: 1.0)')
    parser.add_argument('--log-file', type=str, default='detailed_frequency_data.csv',
                       help='Detailed log file name (default: detailed_frequency_data.csv)')
    parser.add_argument('--analyze-offline', action='store_true',
                       help='Analyze offline data from detailed log file')
    parser.add_argument('--input-file', type=str, default='detailed_frequency_data.csv',
                       help='Input file for offline analysis (default: detailed_frequency_data.csv)')
    parser.add_argument('--output-file', type=str, default='offline_analysis_results.csv',
                       help='Output file for offline analysis results (default: offline_analysis_results.csv)')
    
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
        
        # Override tuning settings
        if args.tuning:
            monitor.config.config['tuning']['enabled'] = True
            monitor.config.config['tuning']['detailed_logging'] = True
            monitor.config.config['tuning']['collection_duration'] = args.tuning_duration
            monitor.logger.info(f"Tuning mode enabled for {args.tuning_duration} seconds")
        
        # Override detailed logging settings
        if args.detailed_logging:
            monitor.data_logger.enable_detailed_logging(
                log_file=args.log_file,
                interval=args.log_interval
            )
            monitor.logger.info(f"Detailed logging enabled: {args.log_file} (interval: {args.log_interval}s)")
        
        # Handle offline analysis mode
        if args.analyze_offline:
            monitor.analyze_offline_data(args.input_file, args.output_file)
            return
        
        monitor.run(simulator_mode=simulator_mode)
        
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()