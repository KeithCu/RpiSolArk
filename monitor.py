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
from offline_analyzer import OfflineAnalyzer
from restart_manager import RestartManager
from solark_integration import SolArkIntegration


class PowerState(Enum):
    """Power system states."""
    OFF_GRID = "off_grid"
    GRID = "grid"
    GENERATOR = "generator"
    TRANSITIONING = "transitioning"


class PowerStateMachine:
    """State machine for power system management."""

    def __init__(self, config, logger: logging.Logger, display_manager=None, solark_integration=None):
        self.config = config
        self.logger = logger
        self.display_manager = display_manager  # Reference to display manager for backlight control
        self.solark_integration = solark_integration  # Reference to Sol-Ark integration
        self.current_state = PowerState.TRANSITIONING  # Start in transitioning to allow detection
        self.previous_state = PowerState.TRANSITIONING
        self.state_entry_time = time.time()
        try:
            self.transition_timeout = config['state_machine']['transition_timeout']  # seconds
            self.zero_voltage_threshold = config['state_machine']['zero_voltage_threshold']  # seconds of no cycles
            self.unsteady_voltage_threshold = config['state_machine']['unsteady_voltage_threshold']  # Hz variation
        except KeyError as e:
            raise KeyError(f"Missing required state machine configuration key: {e}")
        
        # Upgrade lock file path
        self.upgrade_lock_path = "/var/run/unattended-upgrades.lock"

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
    
    def update_state_with_confidence(self, frequency: Optional[float], power_source: str, 
                                   confidence: float, zero_voltage_duration: float) -> PowerState:
        """Update state with confidence-based logic for maximum accuracy."""
        
        # Add confidence tracking to state machine
        if not hasattr(self, 'confidence_history'):
            self.confidence_history = deque(maxlen=10)
        
        self.confidence_history.append(confidence)
        avg_confidence = sum(self.confidence_history) / len(self.confidence_history)
        
        # Only transition if confidence is high enough
        if avg_confidence < 0.6:
            self.logger.debug(f"Low confidence ({avg_confidence:.2f}), maintaining current state")
            return self.current_state
        
        # Enhanced state determination with confidence
        if zero_voltage_duration >= self.zero_voltage_threshold:
            new_state = PowerState.OFF_GRID
        elif frequency is None:
            new_state = PowerState.TRANSITIONING
        elif power_source == "Utility Grid" and avg_confidence > 0.8:
            new_state = PowerState.GRID
        elif power_source == "Generac Generator" and avg_confidence > 0.8:
            new_state = PowerState.GENERATOR
        else:
            new_state = PowerState.TRANSITIONING
        
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

    def _create_upgrade_lock(self):
        """Create lock file to prevent automatic system upgrades."""
        try:
            with open(self.upgrade_lock_path, 'w') as f:
                f.write(f"# Lock file created by RpiSolArk monitor\n")
                f.write(f"# Created at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Reason: System is off-grid\n")
            self.logger.info(f"Created upgrade lock file: {self.upgrade_lock_path}")
            return True
        except PermissionError:
            self.logger.error("Permission denied: Cannot create upgrade lock file. Run with sudo privileges.")
            return False
        except Exception as e:
            self.logger.error(f"Error creating upgrade lock file: {e}")
            return False

    def _remove_upgrade_lock(self):
        """Remove lock file to allow automatic system upgrades."""
        try:
            if os.path.exists(self.upgrade_lock_path):
                os.remove(self.upgrade_lock_path)
                self.logger.info(f"Removed upgrade lock file: {self.upgrade_lock_path}")
            return True
        except PermissionError:
            self.logger.error("Permission denied: Cannot remove upgrade lock file. Run with sudo privileges.")
            return False
        except Exception as e:
            self.logger.error(f"Error removing upgrade lock file: {e}")
            return False

    # Template action functions - to be implemented with real work
    def _on_enter_off_grid(self):
        """Called when entering OFF_GRID state."""
        self.logger.info("POWER OUTAGE: System is now OFF-GRID")
        # Prevent automatic system upgrades when off-grid
        self._create_upgrade_lock()
        # Turn on display backlight for power outage visibility
        if self.display_manager:
            self.display_manager.force_display_on()
            self.logger.info("Display backlight turned on for power outage")
        # Disable TOU when off-grid
        if self.solark_integration:
            self.solark_integration.on_power_source_change('off_grid', {})

    def _on_enter_grid(self):
        """Called when entering GRID state."""
        self.logger.info("GRID POWER: Stable utility power detected")
        # Allow automatic system upgrades when on grid power
        self._remove_upgrade_lock()
        # Turn on display backlight for grid power confirmation
        if self.display_manager:
            self.display_manager.force_display_on()
            self.logger.info("Display backlight turned on for grid power")
        # Enable TOU when on grid power
        if self.solark_integration:
            self.solark_integration.on_power_source_change('grid', {})

    def _on_enter_generator(self):
        """Called when entering GENERATOR state."""
        self.logger.info("GENERATOR: Backup generator power detected")
        # Prevent automatic system upgrades when on generator (unstable power)
        self._create_upgrade_lock()
        # Turn on display backlight for generator operation visibility
        if self.display_manager:
            self.display_manager.force_display_on()
            self.logger.info("Display backlight turned on for generator operation")
        # Disable TOU when on generator
        if self.solark_integration:
            self.solark_integration.on_power_source_change('generator', {})


class FrequencyAnalyzer:
    """Handles frequency analysis and classification."""

    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        try:
            self.thresholds = config['analysis']['generator_thresholds']
        except KeyError as e:
            raise KeyError(f"Missing required analysis configuration key: {e}")

        # Simulator state
        self.simulator_start_time = None
        self.simulator_state = "grid"  # grid -> off_grid -> generator -> grid
    
    def count_zero_crossings(self, duration: float = 0.5) -> Optional[float]:
        """Count zero-crossings over duration. Returns frequency (Hz)."""
        if not hasattr(self, 'hardware_manager'):
            return self._simulate_frequency()
        
        # Check if optocoupler is available and enabled
        if (hasattr(self.hardware_manager, 'optocoupler_initialized') and 
            self.hardware_manager.optocoupler_initialized):
            return self._count_optocoupler_frequency(duration)
        
        # Fall back to original zero-crossing method
        return self._count_zero_crossings_original(duration)
    
    def validate_signal_quality(self, freq: Optional[float], pulse_count: int, duration: float) -> bool:
        """Comprehensive signal quality validation for maximum accuracy."""
        if freq is None:
            return False
        
        # Check 1: Frequency range validation
        try:
            min_freq = self.config['sampling']['min_freq']
            max_freq = self.config['sampling']['max_freq']
        except KeyError as e:
            raise KeyError(f"Missing required sampling configuration key: {e}")
        if not (min_freq <= freq <= max_freq):
            self.logger.warning(f"Frequency {freq:.2f}Hz outside valid range {min_freq}-{max_freq}Hz")
            return False
        
        # Check 2: Pulse count reasonableness (skip in simulator mode)
        if pulse_count > 0:  # Only validate pulse count if we have actual pulses (not simulator mode)
            expected_min = int(duration * 50 * 2)  # 50Hz * 2 pulses/cycle
            expected_max = int(duration * 70 * 2)  # 70Hz * 2 pulses/cycle
            if not (expected_min <= pulse_count <= expected_max):
                self.logger.warning(f"Pulse count {pulse_count} unreasonable for {duration:.1f}s (expected {expected_min}-{expected_max})")
                return False
        
        # Check 3: Signal stability (if we have recent history)
        if hasattr(self, 'freq_buffer') and len(self.freq_buffer) >= 3:
            recent_freqs = list(self.freq_buffer)[-3:]
            freq_std = np.std(recent_freqs)
            if freq_std > 2.0:  # >2Hz standard deviation indicates noise
                self.logger.warning(f"High frequency variation detected: {freq_std:.2f}Hz std dev")
                return False
        
        return True
    
    def validate_frequency_reading(self, freq: Optional[float], pulse_count: int, duration: float) -> Optional[float]:
        """Comprehensive frequency reading validation with multi-layer checks."""
        # Multi-layer validation
        if not self.validate_signal_quality(freq, pulse_count, duration):
            return None
        
        # Additional checks for sudden jumps
        if freq and hasattr(self, 'freq_buffer') and len(self.freq_buffer) >= 5:
            recent_freqs = list(self.freq_buffer)[-5:]
            if abs(freq - np.mean(recent_freqs)) > 5.0:  # >5Hz jump
                self.logger.warning(f"Sudden frequency jump detected: {freq:.2f}Hz")
                return None
        
        return freq
    
    def get_dual_frequencies(self, duration: float = 2.0) -> Tuple[Optional[float], Optional[float]]:
        """
        Get frequency readings from both optocouplers simultaneously.
        Returns tuple of (primary_frequency, secondary_frequency).
        """
        if not hasattr(self, 'hardware_manager'):
            # In simulator mode, return simulated frequencies
            primary_freq = self._simulate_frequency()
            secondary_freq = self._simulate_frequency()
            return primary_freq, secondary_freq
        
        # Check if dual optocoupler mode is enabled
        if (hasattr(self.hardware_manager, 'is_dual_optocoupler_mode') and 
            self.hardware_manager.is_dual_optocoupler_mode()):
            return self._count_dual_optocoupler_frequencies(duration)
        
        # Fall back to single optocoupler mode
        primary_freq = self._count_optocoupler_frequency(duration)
        return primary_freq, None
    
    def _count_optocoupler_frequency(self, duration: float = 2.0) -> Optional[float]:
        """
        Optimized 2-second optocoupler frequency measurement.
        NO AVERAGING - measures actual frequency changes.
        """
        try:
            # Use optimized 2-second measurement with no debouncing for clean signals
            pulse_count = self.hardware_manager.count_optocoupler_pulses(duration, debounce_time=0.0)
            
            if pulse_count <= 0:
                self.logger.debug(f"No pulses detected in {duration:.2f} seconds")
                return None
            
            # Calculate frequency from pulse count
            frequency = self.hardware_manager.calculate_frequency_from_pulses(pulse_count, duration)
            
            if frequency is None:
                self.logger.warning(f"Failed to calculate frequency from {pulse_count} pulses")
                return None
            
            # Validate frequency range
            try:
                min_freq = self.config['sampling']['min_freq']
                max_freq = self.config['sampling']['max_freq']
            except KeyError as e:
                raise KeyError(f"Missing required sampling configuration key: {e}")
            
            if frequency < min_freq or frequency > max_freq:
                self.logger.warning(f"Invalid frequency reading: {frequency:.2f} Hz (outside range {min_freq}-{max_freq} Hz)")
                return None
            
            self.logger.debug(f"Optocoupler frequency: {frequency:.2f} Hz from {pulse_count} pulses in {duration:.2f}s")
            return float(frequency)
            
        except Exception as e:
            self.logger.error(f"Error in optocoupler frequency measurement: {e}")
            return None
    
    def _count_dual_optocoupler_frequencies(self, duration: float = 2.0) -> Tuple[Optional[float], Optional[float]]:
        """
        Get frequency readings from both optocouplers simultaneously.
        Returns tuple of (primary_frequency, secondary_frequency).
        """
        try:
            # Use hardware manager's dual frequency method
            primary_freq, secondary_freq = self.hardware_manager.get_dual_frequencies(duration, debounce_time=0.0)
            
            # Validate frequency ranges for both readings
            try:
                min_freq = self.config['sampling']['min_freq']
                max_freq = self.config['sampling']['max_freq']
            except KeyError as e:
                raise KeyError(f"Missing required sampling configuration key: {e}")
            
            if primary_freq is not None and (primary_freq < min_freq or primary_freq > max_freq):
                self.logger.warning(f"Invalid primary frequency reading: {primary_freq:.2f} Hz (outside range {min_freq}-{max_freq} Hz)")
                primary_freq = None
            
            if secondary_freq is not None and (secondary_freq < min_freq or secondary_freq > max_freq):
                self.logger.warning(f"Invalid secondary frequency reading: {secondary_freq:.2f} Hz (outside range {min_freq}-{max_freq} Hz)")
                secondary_freq = None
            
            self.logger.debug(f"Dual optocoupler frequencies: Primary={primary_freq:.2f} Hz, Secondary={secondary_freq:.2f} Hz")
            return primary_freq, secondary_freq
            
        except Exception as e:
            self.logger.error(f"Error in dual optocoupler frequency measurement: {e}")
            return None, None
    
    def _count_zero_crossings_original(self, duration: float = 0.5) -> Optional[float]:
        """Original zero-crossing counting method (fallback)."""
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
            time.sleep(0.00005)  # 50μs sleep for faster polling while avoiding CPU overload
        
        freq = count / (2 * duration)
        
        # Validate frequency is a number
        if not isinstance(freq, (int, float)) or np.isnan(freq) or np.isinf(freq):
            self.logger.error(f"Invalid frequency calculation result: {freq}")
            return None
        
        # Filter erratic readings
        try:
            min_freq = self.config['sampling']['min_freq']
            max_freq = self.config['sampling']['max_freq']
        except KeyError as e:
            raise KeyError(f"Missing required sampling configuration key: {e}")
        
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
            
            try:
                sample_rate = self.config['sampling']['sample_rate']
                tau_target = self.config['analysis']['allan_variance_tau']
            except KeyError as e:
                raise KeyError(f"Missing required configuration key: {e}")
            # Use allantools.adev for Allan deviation calculation
            taus_out, adev, _, _ = allantools.adev(frac_freq_array, rate=sample_rate, data_type='freq')
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
    
    def analyze_signal_quality(self, freq_data: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Enhanced signal quality analysis for maximum accuracy."""
        if len(freq_data) < 10:
            return None, None, None, None
        
        freq_array = np.array(freq_data)
        
        # Standard metrics
        frac_freq = (freq_array - 60.0) / 60.0
        avar_10s, std_freq, kurtosis = self.analyze_stability(frac_freq)
        
        # Additional accuracy metrics
        freq_range = np.max(freq_array) - np.min(freq_array)
        freq_trend = np.polyfit(range(len(freq_array)), freq_array, 1)[0]  # Linear trend
        
        # Signal quality score (0-1, higher is better)
        quality_score = self._calculate_signal_quality(freq_array, std_freq, freq_range)
        
        return avar_10s, std_freq, kurtosis, quality_score
    
    def _calculate_signal_quality(self, freq_array: np.ndarray, std_freq: float, freq_range: float) -> float:
        """Calculate signal quality score for accuracy assessment."""
        # Utility grid should have low std dev and small range
        if std_freq < 0.1 and freq_range < 0.5:
            return 1.0  # Excellent signal quality
        elif std_freq < 0.5 and freq_range < 2.0:
            return 0.8  # Good signal quality
        elif std_freq < 1.0 and freq_range < 5.0:
            return 0.6  # Fair signal quality
        else:
            return 0.3  # Poor signal quality
    
    def classify_power_source(self, avar_10s: Optional[float], std_freq: Optional[float], 
                            kurtosis: Optional[float]) -> str:
        """Classify as Generac generator or utility."""
        if any(x is None for x in [avar_10s, std_freq, kurtosis]):
            return "Unknown"
        
        # Get thresholds and ensure they are numeric
        try:
            avar_thresh = self.thresholds['allan_variance']
            std_thresh = self.thresholds['std_dev']
            kurt_thresh = self.thresholds['kurtosis']
        except KeyError as e:
            raise KeyError(f"Missing required threshold configuration key: {e}")
        
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
    
    def classify_power_source_with_confidence(self, avar_10s: Optional[float], std_freq: Optional[float], 
                                            kurtosis: Optional[float], quality_score: Optional[float]) -> Tuple[str, float]:
        """Classify power source with confidence scoring for maximum accuracy."""
        if any(x is None for x in [avar_10s, std_freq, kurtosis]):
            return "Unknown", 0.0
        
        # Get thresholds
        try:
            avar_thresh = self.thresholds['allan_variance']
            std_thresh = self.thresholds['std_dev']
            kurt_thresh = self.thresholds['kurtosis']
        except KeyError as e:
            raise KeyError(f"Missing required threshold configuration key: {e}")
        
        # Calculate confidence based on how far values are from thresholds
        avar_confidence = min(1.0, avar_10s / avar_thresh) if avar_10s > avar_thresh else 0.0
        std_confidence = min(1.0, std_freq / std_thresh) if std_freq > std_thresh else 0.0
        kurt_confidence = min(1.0, kurtosis / kurt_thresh) if kurtosis > kurt_thresh else 0.0
        
        # Weight by signal quality
        quality_weight = quality_score if quality_score else 0.5
        
        # Generator indicators
        generator_indicators = [avar_confidence, std_confidence, kurt_confidence]
        max_confidence = max(generator_indicators)
        
        # Apply quality weighting
        final_confidence = max_confidence * quality_weight
        
        if final_confidence > 0.7:
            return "Generac Generator", final_confidence
        elif final_confidence < 0.3:
            return "Utility Grid", 1.0 - final_confidence
        else:
            return "Unknown", 0.5


class FrequencyMonitor:
    """Main frequency monitoring class."""
    
    def __init__(self):
        self.config = Config("config.yaml")
        self.logger_setup = Logger(self.config)
        self.logger = logging.getLogger(__name__)
        
        # Check if we're in simulator mode
        try:
            self.simulator_mode = self.config['app']['simulator_mode']
        except KeyError as e:
            raise KeyError(f"Missing required app configuration key: {e}")
        
        # Always initialize hardware manager (it handles graceful degradation internally)
        # Simulator mode only affects frequency data source, not hardware availability
        self.hardware = HardwareManager(self.config, self.logger)
        if self.simulator_mode:
            self.logger.info("Simulator mode: Using simulated frequency data, but hardware manager initialized")
        else:
            self.logger.info("Real mode: Using real hardware for frequency data")
        
        self.analyzer = FrequencyAnalyzer(self.config, self.logger)
        
        # Initialize Sol-Ark integration (with graceful handling if disabled)
        try:
            self.solark_integration = SolArkIntegration()
            self.logger.info("Sol-Ark integration initialized")
        except Exception as e:
            self.logger.warning(f"Sol-Ark integration disabled: {e}")
            self.solark_integration = None
        
        self.state_machine = PowerStateMachine(self.config, self.logger, self.hardware.display, self.solark_integration)
        self.health_monitor = HealthMonitor(self.config, self.logger)
        self.memory_monitor = MemoryMonitor(self.config, self.logger)
        self.data_logger = DataLogger(self.config, self.logger)
        self.tuning_collector = TuningDataCollector(self.config, self.logger)
        self.offline_analyzer = OfflineAnalyzer(self.config, self.logger)
        self.restart_manager = RestartManager(self.config, self.logger)
        
        # Connect analyzer to hardware (always available now)
        self.analyzer.hardware_manager = self.hardware
        
        # Initialize data buffers
        sample_rate = self.config.get_float('sampling.sample_rate', 2.0)
        buffer_duration = self.config.get_float('sampling.buffer_duration', 300)
        buffer_size = int(buffer_duration * sample_rate)
        
        self.freq_buffer = deque(maxlen=buffer_size)
        self.time_buffer = deque(maxlen=buffer_size)
        
        # Initialize dual optocoupler buffers if dual mode is enabled
        self.dual_mode = (hasattr(self.hardware, 'is_dual_optocoupler_mode') and 
                         self.hardware.is_dual_optocoupler_mode())
        if self.dual_mode:
            self.secondary_freq_buffer = deque(maxlen=buffer_size)
            self.logger.info("Dual optocoupler mode enabled - tracking both primary and secondary frequencies")
        
        # Initialize power source classification buffer for U/G indicator
        classification_window = self.config.get_float('display.classification_window', 300)  # 5 minutes default
        
        # Use smaller window in simulator mode for better testing
        if self.simulator_mode:
            classification_window = min(classification_window, 10)  # Max 10 seconds in simulator
        
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
        
        # Start restart manager (auto-updates handled by system services)
        self.restart_manager.start_update_monitor()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        # Force cleanup and exit
        try:
            self.cleanup()
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        # Force exit the program
        import sys
        sys.exit(0)
    
    def run(self, simulator_mode: bool = None):
        """Main monitoring loop."""
        if simulator_mode is None:
            try:
                simulator_mode = self.config['app']['simulator_mode']
            except KeyError as e:
                raise KeyError(f"Missing required app configuration key: {e}")
        
        self.logger.info(f"Starting frequency monitor (simulator: {simulator_mode})")

        # Initialize display
        if self.hardware is not None:
            self.hardware.update_display("Starting...", "Please wait...")

        # For simulator mode, set up auto-exit after 20 seconds
        if simulator_mode:
            self.simulator_exit_time = time.time() + 20.0
            self.logger.info("Simulator mode: will auto-exit after 20 seconds (28s power cycle)")
        
        try:
            while self.running:
                current_time = time.time() - self.start_time
                
                # Get frequency reading(s)
                if simulator_mode:
                    freq = self.analyzer._simulate_frequency()
                    secondary_freq = None  # No secondary in simulator mode
                else:
                    # Check if dual optocoupler mode is enabled
                    if (hasattr(self.hardware, 'is_dual_optocoupler_mode') and 
                        self.hardware.is_dual_optocoupler_mode()):
                        # Get dual frequency readings
                        freq, secondary_freq = self.analyzer.get_dual_frequencies(duration=2.0)
                        self.logger.debug(f"Dual optocoupler readings: Primary={freq:.2f} Hz, Secondary={secondary_freq:.2f} Hz")
                    else:
                        # Single optocoupler mode
                        # Use measurement duration from config
                        measurement_duration = self.config.get_float('hardware.optocoupler.primary.measurement_duration', 2.0)
                        freq = self.analyzer.count_zero_crossings(duration=measurement_duration)
                        secondary_freq = None

                # Track zero voltage duration
                self.logger.debug("Tracking zero voltage duration...")
                if freq is None or freq == 0:
                    # No frequency detected - voltage is zero
                    if self.zero_voltage_start_time is None:
                        self.zero_voltage_start_time = current_time
                    self.zero_voltage_duration = current_time - self.zero_voltage_start_time
                else:
                    # Frequency detected - reset zero voltage tracking
                    self.zero_voltage_start_time = None
                    self.zero_voltage_duration = 0.0

                # Validate frequency reading with enhanced accuracy checks
                self.logger.debug("Validating frequency reading...")
                if freq is None:
                    self.logger.warning(f"No frequency reading (zero voltage duration: {self.zero_voltage_duration:.1f}s)")
                    # Continue processing even with no frequency for state machine updates
                elif not isinstance(freq, (int, float)):
                    self.logger.error(f"Invalid frequency data type: {type(freq)}. Expected number, got {freq}")
                    continue
                elif np.isnan(freq) or np.isinf(freq):
                    self.logger.error(f"Invalid frequency value: {freq}")
                    continue
                else:
                    # Enhanced validation for accuracy
                    pulse_count = getattr(self, 'last_pulse_count', 0)  # Get from optocoupler if available
                    validated_freq = self.analyzer.validate_frequency_reading(freq, pulse_count, 2.0)
                    if validated_freq is None:
                        self.logger.warning(f"Frequency reading failed validation: {freq:.2f}Hz")
                        continue
                    
                    freq = validated_freq
                
                # Update buffers only with valid frequency readings
                self.logger.debug("Updating buffers...")
                if freq is not None:
                    self.freq_buffer.append(freq)
                    self.time_buffer.append(current_time)
                    self.sample_count += 1
                    
                    # Update secondary frequency buffer if in dual mode
                    if self.dual_mode and secondary_freq is not None:
                        self.secondary_freq_buffer.append(secondary_freq)
                        self.logger.debug(f"Updated dual frequency buffers: Primary={freq:.2f} Hz, Secondary={secondary_freq:.2f} Hz")

                self.logger.debug("Updating health monitor...")
                self.health_monitor.update_activity()

                # Analyze data only if we have enough samples
                self.logger.debug("Analyzing data...")
                confidence = 0.0
                if freq is None:
                    # No frequency reading - classify as Unknown
                    self.logger.debug("No frequency reading - classifying as Unknown")
                    source = "Unknown"
                    avar_10s, std_freq, kurtosis, quality_score = None, None, None, None
                    
                    # Clear classification buffer when signal is lost to show "?" immediately
                    if len(self.classification_buffer) > 0:
                        self.logger.debug("Clearing classification buffer due to signal loss")
                        self.classification_buffer.clear()
                elif len(self.freq_buffer) >= 10:
                    self.logger.debug("Full analysis with 10+ samples")
                    # Use enhanced signal quality analysis
                    avar_10s, std_freq, kurtosis, quality_score = self.analyzer.analyze_signal_quality(list(self.freq_buffer))
                    source, confidence = self.analyzer.classify_power_source_with_confidence(avar_10s, std_freq, kurtosis, quality_score)
                    
                    # Debug logging for classification with confidence
                    self.logger.debug(f"Analysis results: avar={avar_10s}, std={std_freq}, kurtosis={kurtosis}, quality={quality_score}, source={source}, confidence={confidence:.2f}")
                    if len(self.freq_buffer) >= 5:
                        recent_freqs = list(self.freq_buffer)[-5:]
                        freq_range = max(recent_freqs) - min(recent_freqs)
                        self.logger.debug(f"Recent frequency range: {freq_range:.2f} Hz (min: {min(recent_freqs):.2f}, max: {max(recent_freqs):.2f})")
                elif len(self.freq_buffer) >= 3:
                    self.logger.debug("Quick analysis with 3+ samples")
                    # Quick detection with fewer samples for better UX
                    recent_freqs = list(self.freq_buffer)[-3:]  # Last 3 readings
                    avg_freq = sum(recent_freqs) / len(recent_freqs)
                    variation = max(recent_freqs) - min(recent_freqs)

                    if variation < 0.1 and 59.9 <= avg_freq <= 60.1:
                        source = "Utility Grid"  # Quick stable detection
                        confidence = 0.9
                    elif variation > 2.0:  # Increased threshold for utility power (was 0.5)
                        source = "Generac Generator"  # Quick unstable detection
                        confidence = 0.8
                    else:
                        source = "Unknown"  # Default to Unknown for moderate variation
                        confidence = 0.3
                    avar_10s, std_freq, kurtosis, quality_score = None, None, None, None
                else:
                    self.logger.debug("Not enough samples for analysis")
                    # Not enough data for analysis yet
                    avar_10s, std_freq, kurtosis, quality_score = None, None, None, None
                    source = "Unknown"
                    confidence = 0.0

                # Update classification buffer immediately after analysis
                self.classification_buffer.append(source)
                
                # Update state machine with current conditions using confidence-based logic
                self.logger.debug("Updating state machine...")
                current_state = self.state_machine.update_state_with_confidence(freq, source, confidence, self.zero_voltage_duration)
                
                # Collect tuning data if enabled
                self.logger.debug("Collecting tuning data...")
                if self.tuning_collector.enabled:
                    analysis_results = {
                        'allan_variance': avar_10s,
                        'std_deviation': std_freq,
                        'kurtosis': kurtosis
                    }
                    self.tuning_collector.collect_frequency_sample(freq, analysis_results, source)
                    self.tuning_collector.collect_analysis_results(analysis_results, source, len(self.freq_buffer))
                
                # Log detailed frequency data if enabled
                self.logger.debug("Logging detailed frequency data...")
                analysis_results = {
                    'allan_variance': avar_10s,
                    'std_deviation': std_freq,
                    'kurtosis': kurtosis,
                    'quality_score': quality_score,
                    'confidence': confidence
                }
                self.data_logger.log_detailed_frequency_data(
                    freq, analysis_results, source, self.sample_count, 
                    len(self.freq_buffer), self.start_time
                )
                
                # Log accuracy metrics for debugging
                self.log_accuracy_metrics(freq, source, confidence, analysis_results)
                
                # Update display and LEDs once per second
                self.logger.debug("Checking display update...")
                display_interval = self.config.get_float('app.display_update_interval', 1.0)
                
                if current_time - self.last_display_time >= display_interval:
                    self.logger.debug("Updating display and LEDs...")
                    ug_indicator = self._get_current_power_source_indicator()
                    # Pass secondary frequency if in dual mode
                    secondary_freq = secondary_freq if self.dual_mode else None
                    self.hardware.display.update_display_and_leds(freq, ug_indicator, self.state_machine, self.zero_voltage_duration, secondary_freq)
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
                    if self.hardware is not None and self.hardware.check_reset_button():
                        if not self.reset_button_pressed:
                            self.reset_button_pressed = True
                            self.logger.info("Reset button pressed - initiating restart")
                            if self.restart_manager.handle_restart_button():
                                # Restart was initiated successfully
                                break  # Exit main loop
                            else:
                                # Restart was blocked by safety checks
                                self.reset_button_pressed = False
                    else:
                        self.reset_button_pressed = False

                # Log hourly status
                if current_time - self.last_log_time >= 3600:  # 1 hour
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    state_info = self.state_machine.get_state_info()
                    self.data_logger.log_hourly_status(timestamp, freq, source, std_freq, kurtosis, self.sample_count,
                                                     state_info=state_info)

                    # Log memory information to CSV
                    try:
                        memory_csv_file = self.config['logging']['memory_log_file']
                    except KeyError as e:
                        raise KeyError(f"Missing required logging configuration key: {e}")
                    self.memory_monitor.log_memory_to_csv(memory_csv_file)

                    # Log memory summary
                    memory_summary = self.memory_monitor.get_memory_summary()
                    self.logger.info(f"Memory status: {memory_summary}")

                    self.last_log_time = current_time

                # Maintain sample rate
                self.logger.debug("Maintaining sample rate...")
                sample_rate = self.config.get_float('sampling.sample_rate', 2.0)

                # Simple sleep to maintain sample rate
                sleep_time = 1.0 / sample_rate
                self.logger.debug(f"Sleeping for {sleep_time:.3f} seconds")
                time.sleep(sleep_time)
                self.logger.debug("Main loop iteration complete")
                
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
            indicator = "Util"  # Utility
        elif generator_count > utility_count:
            indicator = "Gen"   # Generator
        else:
            indicator = ""    # Unknown/Equal
        
        # Log classification details for debugging (only occasionally to avoid spam)
        if total_count % 5 == 0:  # Log every 5th update for more frequent debugging
            self.logger.debug(f"Power Source Indicator: {indicator} (U:{utility_count}, G:{generator_count}, Total:{total_count})")
            # Show recent classifications for debugging
            recent_classifications = list(self.classification_buffer)[-10:] if len(self.classification_buffer) >= 10 else list(self.classification_buffer)
            self.logger.debug(f"Recent classifications: {recent_classifications}")
        
        return indicator

    def log_accuracy_metrics(self, freq: Optional[float], source: str, confidence: float, analysis_results: Dict[str, Any]):
        """Log detailed accuracy metrics for debugging."""
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"Accuracy Metrics: freq={freq:.3f}Hz, source={source}, "
                             f"confidence={confidence:.2f}, avar={analysis_results.get('allan_variance', 'N/A')}, "
                             f"std={analysis_results.get('std_deviation', 'N/A')}, "
                             f"quality={analysis_results.get('quality_score', 'N/A')}")
            
            # Log confidence history if available
            if hasattr(self.state_machine, 'confidence_history') and len(self.state_machine.confidence_history) > 0:
                avg_confidence = sum(self.state_machine.confidence_history) / len(self.state_machine.confidence_history)
                self.logger.debug(f"Confidence History: avg={avg_confidence:.2f}, recent={list(self.state_machine.confidence_history)[-3:]}")

    def _handle_reset(self):
        """Handle reset button press - restart the application."""
        self.logger.info("Initiating application restart...")

        # Show reset message on LCD
        if self.hardware is not None:
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
        
        try:
            cleanup_on_exit = self.config['app']['cleanup_on_exit']
        except KeyError as e:
            raise KeyError(f"Missing required app configuration key: {e}")
        if cleanup_on_exit and self.hardware is not None:
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
    parser.add_argument('--debug', action='store_true',
                       help='Enable remote debugging on port 5678')
    parser.add_argument('--debug-port', type=int, default=5678,
                       help='Remote debugging port (default: 5678)')
    parser.add_argument('--debug-logging', action='store_true',
                       help='Enable debug-level logging')
    
    args = parser.parse_args()
    
    # Enable remote debugging if requested
    if args.debug:
        try:
            import debugpy
            debugpy.listen(("0.0.0.0", args.debug_port))
            print(f"Remote debugging enabled on port {args.debug_port}")
            print("Waiting for debugger to attach...")
            debugpy.wait_for_client()
            print("Debugger attached!")
        except ImportError:
            print("debugpy not installed. Install with: pip install debugpy")
            sys.exit(1)
    
    # Determine simulator mode
    simulator_mode = args.simulator
    if args.real:
        simulator_mode = False
    
    try:
        monitor = FrequencyMonitor()
        
        # Override log level if verbose or debug logging
        if args.verbose or args.debug_logging:
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
            monitor.offline_analyzer.analyze_offline_data(args.input_file, args.output_file)
            return
        
        monitor.run(simulator_mode=simulator_mode)
        
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()