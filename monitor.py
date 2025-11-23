#!/usr/bin/env python3
"""
Raspberry Pi Frequency Monitor
Monitors AC line frequency to detect power source (Utility vs Generator)
"""

# Standard library imports
import argparse
import csv
import json
import logging
import os
import random
import signal
import sys
import time
import socket
from collections import deque
from typing import Optional, Tuple, List, Dict, Any
from enum import Enum

# Third-party imports
import numpy as np
import allantools

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
    """State machine for power system management with persistent state storage."""

    def __init__(self, config, logger: logging.Logger, display_manager=None, solark_integration=None, optocoupler_name=None):
        self.config = config
        self.logger = logger
        self.display_manager = display_manager  # Reference to display manager for backlight control
        self.solark_integration = solark_integration  # Reference to Sol-Ark integration
        self.optocoupler_name = optocoupler_name  # Name of the optocoupler this state machine manages
        
        # Persistent state configuration
        self.state_file = f"/tmp/{config.get('state_machine.state_file')}"
        self.persistent_state_enabled = config.get('state_machine.persistent_state_enabled')

        # Ensure /tmp directory exists (it should, but be safe)
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        
        # Initialize state variables
        self.current_state = PowerState.TRANSITIONING  # Default start state
        self.previous_state = PowerState.TRANSITIONING
        self.state_entry_time = time.time()
        self.last_action_taken = None  # Track last action to prevent duplicates
        
        # Simple debouncing for state transitions
        self.pending_state = None
        self.pending_state_time = None
        self.debounce_seconds = 5.0  # Require state to be consistent for 5 seconds before transitioning
        
        # Load persistent state if enabled
        if self.persistent_state_enabled:
            self._load_persistent_state()
        
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

        self.logger.info(f"Power state machine initialized in {self.current_state.value} state (persistent: {self.persistent_state_enabled})")

    def update_state(self, frequency: Optional[float], power_source: str,
                    zero_voltage_duration: float) -> PowerState:
        """
        Update state based on current conditions with simple debouncing.

        Args:
            frequency: Current frequency reading (None if no signal)
            power_source: Classification from FrequencyAnalyzer ("Utility Grid", "Generac Generator", or "Unknown")
            zero_voltage_duration: How long voltage has been zero (seconds)
        """
        new_state = self._determine_state(frequency, power_source, zero_voltage_duration)

        # Simple debouncing: require state to be consistent for debounce_seconds before transitioning
        if new_state != self.current_state:
            current_time = time.time()
            
            # If this is a new pending state, start the timer
            if self.pending_state != new_state:
                self.pending_state = new_state
                self.pending_state_time = current_time
                self.logger.debug(f"State change pending: {self.current_state.value} -> {new_state.value} (debouncing for {self.debounce_seconds}s)")
            
            # If pending state has been consistent long enough, transition
            elif self.pending_state_time and (current_time - self.pending_state_time) >= self.debounce_seconds:
                # Get monitor reference from config if available (passed during initialization)
                monitor = getattr(self, '_monitor_ref', None)
                self._transition_to_state(new_state, monitor)
                self.pending_state = None
                self.pending_state_time = None
        else:
            # State is consistent, clear any pending state
            self.pending_state = None
            self.pending_state_time = None

        # Check for transition timeout
        if self.current_state == PowerState.TRANSITIONING:
            if time.time() - self.state_entry_time > self.transition_timeout:
                self.logger.warning(f"Transition timeout exceeded, forcing to OFF_GRID")
                monitor = getattr(self, '_monitor_ref', None)
                self._transition_to_state(PowerState.OFF_GRID, monitor)

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

    def _transition_to_state(self, new_state: PowerState, monitor=None):
        """Handle state transition."""
        old_state = self.current_state
        self.previous_state = old_state
        self.current_state = new_state
        self.state_entry_time = time.time()

        self.logger.info(f"Power state transition: {old_state.value} -> {new_state.value}")

        # Clear buffers when transitioning between major power states to avoid contamination
        # This ensures fresh analysis for the new state without old data from previous state
        major_states = [PowerState.GRID, PowerState.GENERATOR, PowerState.OFF_GRID]
        if (old_state != new_state and 
            (old_state == PowerState.TRANSITIONING or new_state in major_states or old_state in major_states)):
            if monitor:
                monitor._clear_buffers()
                self.logger.info(f"Buffers cleared on state transition: {old_state.value} -> {new_state.value}")

        # Save persistent state after transition
        if self.persistent_state_enabled:
            self._save_persistent_state()

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

    def _load_persistent_state(self):
        """Load persistent state from file with validation."""
        try:
            if not os.path.exists(self.state_file):
                self.logger.info(f"State file {self.state_file} does not exist, starting fresh")
                return
            
            with open(self.state_file, 'r') as f:
                state_data = json.load(f)
            
            # Validate state data
            if not self._validate_state_data(state_data):
                self.logger.warning(f"Invalid state data in {self.state_file}, starting fresh")
                return
            
            # Load state
            self.current_state = PowerState(state_data['current_state'])
            self.previous_state = PowerState(state_data['previous_state'])

            # Validate and convert state_entry_time to float
            try:
                self.state_entry_time = float(state_data['state_entry_time'])
            except (ValueError, TypeError) as e:
                self.logger.warning(f"Invalid state_entry_time value: {state_data['state_entry_time']}, starting fresh")
                return

            self.last_action_taken = state_data.get('last_action_taken')
            
            # Calculate state duration
            state_duration = time.time() - self.state_entry_time
            self.logger.info(f"Loaded persistent state: {self.current_state.value} (duration: {state_duration:.1f}s)")
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.warning(f"Failed to load persistent state: {e}, starting fresh")
        except Exception as e:
            self.logger.error(f"Unexpected error loading persistent state: {e}, starting fresh")
    
    def _save_persistent_state(self):
        """Save current state to file with atomic write."""
        try:
            state_data = {
                'current_state': self.current_state.value,
                'previous_state': self.previous_state.value,
                'state_entry_time': self.state_entry_time,
                'last_action_taken': self.last_action_taken,
                'timestamp': time.time(),
                'optocoupler_name': self.optocoupler_name
            }
            
            # Atomic write: write to temp file, then rename
            temp_file = f"{self.state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(state_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            
            # Atomic rename
            os.rename(temp_file, self.state_file)
            self.logger.debug(f"Persistent state saved to {self.state_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to save persistent state: {e}")
    
    def _validate_state_data(self, state_data: dict) -> bool:
        """Validate state data structure and values."""
        try:
            # Check required fields
            required_fields = ['current_state', 'previous_state', 'state_entry_time']
            for field in required_fields:
                if field not in state_data:
                    return False
            
            # Validate state values
            valid_states = [state.value for state in PowerState]
            if (state_data['current_state'] not in valid_states or 
                state_data['previous_state'] not in valid_states):
                return False
            
            # Validate timestamp (not too old, not in future)
            current_time = time.time()
            state_time = state_data['state_entry_time']
            if state_time > current_time or (current_time - state_time) > 86400 * 7:  # 7 days max
                return False
            
            return True
            
        except Exception:
            return False

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
        
        # Only perform actions if not already done or state actually changed
        if self.last_action_taken != 'off_grid_actions':
            # Prevent automatic system upgrades when off-grid
            self._create_upgrade_lock()
            # Turn on display backlight for power outage visibility
            if self.display_manager:
                self.display_manager.force_display_on()
                self.logger.info("Display backlight turned on for power outage")
            # Disable TOU when off-grid
            if self.solark_integration and self.optocoupler_name:
                self.solark_integration.on_power_source_change('off_grid', {}, self.optocoupler_name)
            
            self.last_action_taken = 'off_grid_actions'
            self.logger.info("OFF-GRID actions completed")
        else:
            self.logger.debug("OFF-GRID actions already performed, skipping")

    def _on_enter_grid(self):
        """Called when entering GRID state."""
        self.logger.info("GRID POWER: Stable utility power detected")
        
        # Only perform actions if not already done or state actually changed
        if self.last_action_taken != 'grid_actions':
            # Allow automatic system upgrades when on grid power
            self._remove_upgrade_lock()
            # Turn on display backlight for grid power confirmation
            if self.display_manager:
                self.display_manager.force_display_on()
                self.logger.info("Display backlight turned on for grid power")
            # Enable TOU when on grid power
            if self.solark_integration and self.optocoupler_name:
                self.solark_integration.on_power_source_change('grid', {}, self.optocoupler_name)
            
            self.last_action_taken = 'grid_actions'
            self.logger.info("GRID actions completed")
        else:
            self.logger.debug("GRID actions already performed, skipping")

    def _on_enter_generator(self):
        """Called when entering GENERATOR state."""
        self.logger.info("GENERATOR: Backup generator power detected")
        
        # Only perform actions if not already done or state actually changed
        if self.last_action_taken != 'generator_actions':
            # Prevent automatic system upgrades when on generator (unstable power)
            self._create_upgrade_lock()
            # Turn on display backlight for generator operation visibility
            if self.display_manager:
                self.display_manager.force_display_on()
                self.logger.info("Display backlight turned on for generator operation")
            # Disable TOU when on generator
            if self.solark_integration and self.optocoupler_name:
                self.solark_integration.on_power_source_change('generator', {}, self.optocoupler_name)
            
            self.last_action_taken = 'generator_actions'
            self.logger.info("GENERATOR actions completed")
        else:
            self.logger.debug("GENERATOR actions already performed, skipping")


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
        """Simulate power state cycling: grid (20s) -> off-grid (10s) -> generator (20s) -> grid (10s).
        
        With measurement_duration seconds per measurement, each state gets multiple measurements.
        Total cycle: 60 seconds.
        """
        current_time = time.time()

        # Initialize simulator start time
        if self.simulator_start_time is None:
            self.simulator_start_time = current_time

        # Calculate elapsed time and current phase (60 second cycle: longer grid periods for testing)
        elapsed = current_time - self.simulator_start_time
        cycle_time = elapsed % 60.0  # 60 second cycle: 20s grid + 10s off + 20s gen + 10s grid

        # Determine current state based on cycle time
        if cycle_time < 20.0:
            # Grid power (0-20s): very stable 60 Hz
            self.simulator_state = "grid"
            base_freq = 60.0
            noise = random.gauss(0, 0.005)  # Very small stable noise
            return float(base_freq + noise)

        elif cycle_time < 30.0:
            # Off-grid power (20-30s): no frequency (None)
            self.simulator_state = "off_grid"
            return None  # No signal

        elif cycle_time < 50.0:
            # Generator power (30-50s): variable frequency with hunting
            self.simulator_state = "generator"
            # Simulate generator hunting: alternating high/low
            phase_in_cycle = (cycle_time - 30.0) % 2.0
            if phase_in_cycle < 1.0:
                base_freq = 58.5 + random.uniform(-0.5, 1.0)  # Low range
            else:
                base_freq = 61.0 + random.uniform(-1.0, 0.5)  # High range
            noise = random.gauss(0, 0.3)  # Moderate generator noise
            return float(base_freq + noise)

        else:
            # Back to grid power (50-60s): stable 60 Hz
            self.simulator_state = "grid"
            base_freq = 60.0
            noise = random.gauss(0, 0.005)  # Very small stable noise
            return float(base_freq + noise)
    
    def analyze_stability(self, frac_freq: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
        """Compute Allan variance and standard deviation (simplified - kurtosis removed)."""
        # Check for None input first
        if frac_freq is None:
            self.logger.error("frac_freq is None. Cannot perform analysis.")
            return None, None
        
        # In simulator mode, allow analysis with fewer samples for faster state transitions
        min_samples = 3 if hasattr(self, 'simulator_mode') and getattr(self, 'simulator_mode', False) else 5
        if len(frac_freq) < min_samples:
            return None, None
        
        try:
            # Validate input data type - must be numeric
            if not isinstance(frac_freq, (np.ndarray, list, tuple)):
                self.logger.error(f"Invalid data type for frac_freq: {type(frac_freq)}. Expected numpy array, list, or tuple.")
                return None, None
            
            # Convert to numpy array and validate all elements are numeric
            try:
                frac_freq_array = np.array(frac_freq)
            except (ValueError, TypeError) as e:
                self.logger.error(f"Failed to convert frac_freq to numpy array: {e}. Data contains non-numeric values.")
                return None, None
            
            # Check if all elements are numeric (not strings, etc.)
            if frac_freq_array.dtype.kind in ['U', 'S', 'O']:  # Unicode, byte string, or object
                self.logger.error(f"frac_freq contains non-numeric data. Dtype: {frac_freq_array.dtype}")
                return None, None
            
            if not np.issubdtype(frac_freq_array.dtype, np.number):
                self.logger.error(f"frac_freq contains non-numeric data. Dtype: {frac_freq_array.dtype}")
                return None, None
            
            # Check for NaN or infinite values
            if np.any(np.isnan(frac_freq_array)) or np.any(np.isinf(frac_freq_array)):
                self.logger.error("frac_freq contains NaN or infinite values")
                return None, None
            
            try:
                # Calculate sample rate from measurement_duration (samples per second)
                measurement_duration = self.config.get_float('hardware.optocoupler.primary.measurement_duration')
                sample_rate = 1.0 / measurement_duration
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
            
            return avar_10s, std_freq
        except Exception as e:
            self.logger.error(f"Error in stability analysis: {e}")
            return None, None
    
    def analyze_signal_quality(self, freq_data: List[float]) -> Tuple[Optional[float], Optional[float]]:
        """Simplified signal analysis - returns Allan variance and standard deviation only."""
        # In simulator mode, allow analysis with fewer samples for faster state transitions
        min_samples = 3 if hasattr(self, 'simulator_mode') and getattr(self, 'simulator_mode', False) else 10
        if len(freq_data) < min_samples:
            return None, None
        
        freq_array = np.array(freq_data)
        frac_freq = (freq_array - 60.0) / 60.0
        avar_10s, std_freq = self.analyze_stability(frac_freq)
        
        return avar_10s, std_freq
    
    def classify_power_source(self, avar_10s: Optional[float], std_freq: Optional[float], sample_count: int = None) -> str:
        """Classify as Generac generator or utility using simplified OR logic (std_dev OR allan_variance).
        
        For small sample sizes (< 5), only use std_dev as Allan variance is too noisy.
        For medium sample sizes (5-9), use AND logic (both metrics must exceed thresholds) to prevent false positives.
        For larger sample sizes (>= 10), use OR logic for maximum detection sensitivity.
        """
        if std_freq is None:
            return "Unknown"
        
        # Get thresholds and ensure they are numeric
        try:
            avar_thresh = self.thresholds['allan_variance']
            std_thresh = self.thresholds['std_dev']
        except KeyError as e:
            raise KeyError(f"Missing required threshold configuration key: {e}")
        
        # Convert to float to ensure numeric comparison
        try:
            avar_thresh = float(avar_thresh)
            std_thresh = float(std_thresh)
        except (ValueError, TypeError) as e:
            self.logger.error(f"Invalid threshold values: avar={avar_thresh}, std={std_thresh}. Error: {e}")
            return "Unknown"
        
        # For small sample sizes (< 5), primarily use std_dev as Allan variance is too noisy
        # However, if Allan variance is VERY high (>10x threshold), that's a strong generator signal
        # This prevents false positives from unstable Allan variance while catching strong generator signals early
        if sample_count is not None and sample_count < 5:
            # Check for very high Allan variance first (strong generator signal)
            if avar_10s is not None and avar_10s > (avar_thresh * 10.0):
                return "Generac Generator"
            # Otherwise, use std_dev for small sample sizes
            if std_freq > std_thresh:
                return "Generac Generator"
            return "Utility Grid"
        
        # For medium sample sizes (5-9), use smart logic to prevent false positives while catching generators
        # If Allan variance is VERY high (>10x threshold), that's a strong generator signal regardless of std_dev
        # Otherwise, use AND logic to prevent false positives from noisy Allan variance
        if sample_count is not None and 5 <= sample_count < 10:
            if avar_10s is None:
                # Fallback to std_dev only if Allan variance not available
                if std_freq > std_thresh:
                    return "Generac Generator"
                return "Utility Grid"
            # If Allan variance is VERY high (>10x threshold), that's a strong generator signal
            # This catches generators even if std_dev is slightly below threshold
            if avar_10s > (avar_thresh * 10.0):
                return "Generac Generator"
            # Otherwise, use AND logic: both metrics must exceed thresholds
            # This prevents false positives from noisy Allan variance at small values
            if avar_10s > avar_thresh and std_freq > std_thresh:
                return "Generac Generator"
            return "Utility Grid"
        
        # For larger sample sizes (>= 10), use OR logic: if EITHER metric exceeds threshold → generator
        # Allan variance is more reliable with more samples, so we can use OR logic for maximum sensitivity
        if avar_10s is None:
            # Fallback to std_dev only if Allan variance not available
            if std_freq > std_thresh:
                return "Generac Generator"
            return "Utility Grid"
        
        if avar_10s > avar_thresh or std_freq > std_thresh:
            return "Generac Generator"
        return "Utility Grid"


class FrequencyMonitor:
    """Main frequency monitoring class."""
    
    def _sd_notify(self, state):
        """Notify systemd of status updates."""
        notify_socket = os.getenv('NOTIFY_SOCKET')
        if not notify_socket:
            return
            
        if notify_socket.startswith('@'):
            notify_socket = '\0' + notify_socket[1:]
            
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.connect(notify_socket)
            sock.sendall(state.encode('utf-8'))
            sock.close()
        except Exception as e:
            self.logger.debug(f"Failed to send systemd notification: {e}")

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
        # Set simulator mode on analyzer so it can use reduced sample requirements
        self.analyzer.simulator_mode = self.simulator_mode
        
        # Initialize Sol-Ark integration (with graceful handling if disabled)
        try:
            self.solark_integration = SolArkIntegration()
            self.logger.info("Sol-Ark integration initialized")
        except Exception as e:
            self.logger.warning(f"Sol-Ark integration disabled: {e}")
            self.solark_integration = None
        
        # Create separate state machines for each optocoupler
        self.state_machines = self._create_optocoupler_state_machines()
        self.health_monitor = HealthMonitor(self.config, self.logger)
        self.memory_monitor = MemoryMonitor(self.config, self.logger)
        self.data_logger = DataLogger(self.config, self.logger)
        self.tuning_collector = TuningDataCollector(self.config, self.logger)
        self.offline_analyzer = OfflineAnalyzer(self.config, self.logger)
        self.restart_manager = RestartManager(self.config, self.logger)
        
        # Connect analyzer to hardware (always available now)
        self.analyzer.hardware_manager = self.hardware
        
        # Initialize data buffers
        # Use measurement_duration as the primary timing parameter
        measurement_duration = self.config.get_float('hardware.optocoupler.primary.measurement_duration')
        
        # Buffer size: use analysis_window_seconds to determine both buffer size and analysis window
        # This ensures we only store what we actually use for analysis
        try:
            analysis_window_seconds = self.config.get_float('analysis.analysis_window_seconds')
        except (KeyError, ValueError):
            analysis_window_seconds = 30.0  # Default fallback
        
        # Calculate buffer size based on analysis window
        # Each measurement takes measurement_duration seconds
        buffer_size = int(analysis_window_seconds / measurement_duration)
        # Ensure buffer can hold at least a few samples
        buffer_size = max(buffer_size, 10)
        
        self.freq_buffer = deque(maxlen=buffer_size)
        self.time_buffer = deque(maxlen=buffer_size)
        
        # Clear buffers on startup to ensure fresh analysis
        self._clear_buffers()
        self.logger.info("Buffers cleared on startup for fresh analysis")
        
        # State variables
        self.running = True
        self.last_log_time = 0
        self.last_display_time = 0
        self.sample_count = 0
        self.start_time = time.time()
        self.zero_voltage_start_time = None  # Track when voltage went to zero (absolute time)
        self.zero_voltage_duration = 0.0    # How long voltage has been zero

        # Reset button state tracking
        self.reset_button_pressed = False
        self.last_reset_check = 0
        
        # Buffer validation tracking
        self.last_buffer_validation = 0
        self.buffer_validation_interval = 100  # Validate every 100 samples
        self.buffer_corruption_count = 0
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info("Frequency monitor initialized")
        
        # Notify systemd that we are ready
        self._sd_notify("READY=1")
        
        # Start tuning data collection if enabled
        if self.tuning_collector.enabled:
            self.tuning_collector.start_collection()
        
        # Start restart manager (auto-updates handled by system services)
        self.restart_manager.start_update_monitor()
    
    def _create_optocoupler_state_machines(self) -> Dict[str, PowerStateMachine]:
        """
        Create separate state machines for each configured optocoupler
        
        Returns:
            Dict mapping optocoupler name to PowerStateMachine instance
        """
        state_machines = {}
        
        try:
            optocoupler_config = self.config['hardware']['optocoupler']
            
            # Create state machine for primary optocoupler
            primary_config = optocoupler_config['primary']
            primary_name = primary_config['name']
            state_machine = PowerStateMachine(
                self.config, self.logger, self.hardware.display, 
                self.solark_integration, primary_name
            )
            # Store monitor reference for buffer clearing on state transitions
            state_machine._monitor_ref = self
            state_machines[primary_name] = state_machine
            self.logger.info(f"Created state machine for optocoupler: {primary_name}")
            
            self.logger.info(f"Created {len(state_machines)} optocoupler state machine")
            return state_machines
            
        except KeyError as e:
            raise KeyError(f"Missing required optocoupler configuration: {e}")
    
    def _analyze_frequency_for_optocoupler(self, freq: Optional[float], optocoupler_name: str) -> str:
        """
        Analyze frequency for a specific optocoupler (simplified - no confidence)
        
        Args:
            freq: Frequency reading
            optocoupler_name: Name of the optocoupler
            
        Returns:
            power_source classification string
        """
        if freq is None:
            return "Unknown"
        
        # Use the same analysis logic as the main loop: configurable analysis window
        measurement_duration = self.config.get_float('hardware.optocoupler.primary.measurement_duration')
        try:
            analysis_window_seconds = self.config.get_float('analysis.analysis_window_seconds')
        except (KeyError, ValueError):
            analysis_window_seconds = 30.0  # Default fallback
        samples_for_analysis = int(analysis_window_seconds / measurement_duration)
        samples_needed = 3  # Minimum: 3 samples required for analysis
        
        if len(self.freq_buffer) >= samples_needed:
            # Use 30-second analysis window (most recent samples)
            samples_to_use = min(samples_for_analysis, len(self.freq_buffer))
            recent_data = list(self.freq_buffer)[-samples_to_use:]
            avar_10s, std_freq = self.analyzer.analyze_signal_quality(recent_data)
            source = self.analyzer.classify_power_source(avar_10s, std_freq, len(recent_data))
        else:
            # Not enough data - stay in Unknown state
            source = "Unknown"
        
        return source
    
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

        # For simulator mode, set up auto-exit after 60 seconds (one full cycle)
        if simulator_mode:
            self.simulator_exit_time = time.time() + 60.0
            self.logger.info("Simulator mode: will auto-exit after 60 seconds (one full cycle: 20s grid -> 10s off-grid -> 20s generator -> 10s grid)")
        
        try:
            # Get measurement duration once at start
            measurement_duration = self.config.get_float('hardware.optocoupler.primary.measurement_duration')
            
            while self.running:
                current_time = time.time() - self.start_time
                
                # Get frequency reading - always measure for full measurement_duration
                if simulator_mode:
                    # In simulator, generate a reading but simulate the 5-second measurement time
                    freq = self.analyzer._simulate_frequency()
                    # Simulate the measurement duration by sleeping
                    time.sleep(measurement_duration)
                else:
                    # Real hardware: measure for full duration (blocks for measurement_duration seconds)
                    freq = self.analyzer.count_zero_crossings(duration=measurement_duration)

                # Track zero voltage duration
                self.logger.debug("Tracking zero voltage duration...")
                current_absolute_time = time.time()
                if freq is None or freq == 0:
                    # No frequency detected - voltage is zero
                    if self.zero_voltage_start_time is None:
                        self.zero_voltage_start_time = current_absolute_time
                    self.zero_voltage_duration = current_absolute_time - self.zero_voltage_start_time
                else:
                    # Frequency detected - reset zero voltage tracking
                    self.zero_voltage_start_time = None
                    self.zero_voltage_duration = 0.0

                # Validate frequency reading with enhanced accuracy checks
                self.logger.debug("Validating frequency reading...")
                if freq is None:
                    self.logger.info(f"No frequency reading (zero voltage duration: {self.zero_voltage_duration:.1f}s)")
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
                    validated_freq = self.analyzer.validate_frequency_reading(freq, pulse_count, measurement_duration)
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

                # Validate buffers periodically
                if self.sample_count - self.last_buffer_validation >= self.buffer_validation_interval:
                    self.validate_buffers()
                    self.last_buffer_validation = self.sample_count

                # Pet the systemd watchdog
                self._sd_notify("WATCHDOG=1")

                # Analyze data only if we have enough data
                # Use configurable analysis window for responsive detection while maintaining accuracy
                # This balances detection speed with statistical reliability
                self.logger.debug("Analyzing data...")
                confidence = 0.0
                
                # Get analysis window from config
                try:
                    analysis_window_seconds = self.config.get_float('analysis.analysis_window_seconds')
                except (KeyError, ValueError):
                    analysis_window_seconds = 30.0  # Default fallback
                
                # Calculate how many samples to use based on analysis window
                # Each measurement takes measurement_duration seconds
                samples_for_analysis = int(analysis_window_seconds / measurement_duration)
                samples_needed = 3  # Minimum: 3 samples required for analysis
                
                if freq is None:
                    # No frequency reading - classify as Unknown
                    self.logger.debug("No frequency reading - classifying as Unknown")
                    source = "Unknown"
                    avar_10s, std_freq, kurtosis, quality_score = None, None, None, None
                elif len(self.freq_buffer) >= samples_needed:
                    # We have enough data - use 30-second analysis window (most recent samples)
                    # Take the most recent samples up to the analysis window size
                    samples_to_use = min(samples_for_analysis, len(self.freq_buffer))
                    self.logger.debug(f"Analysis with {len(self.freq_buffer)} samples in buffer (using last {samples_to_use} samples = {samples_to_use * measurement_duration:.1f}s window)")
                    recent_data = list(self.freq_buffer)[-samples_to_use:]
                    
                    # Simplified signal analysis (std_dev + allan_variance only)
                    avar_10s, std_freq = self.analyzer.analyze_signal_quality(recent_data)
                    source = self.analyzer.classify_power_source(avar_10s, std_freq, len(recent_data))
                    
                    # Debug logging for classification
                    self.logger.debug(f"Analysis results: avar={avar_10s}, std={std_freq}, source={source}")
                    if len(recent_data) >= 2:
                        freq_range = max(recent_data) - min(recent_data)
                        self.logger.debug(f"Recent frequency range: {freq_range:.2f} Hz (min: {min(recent_data):.2f}, max: {max(recent_data):.2f})")
                else:
                    self.logger.debug(f"Not enough samples for analysis (have {len(self.freq_buffer)}, need {samples_needed} sample(s), each covering {measurement_duration}s)")
                    # Not enough data for analysis yet - stay in Unknown state
                    avar_10s, std_freq = None, None
                    source = "Unknown"

                # Update state machines for each optocoupler
                self.logger.debug("Updating state machines...")
                current_states = {}
                
                # Update optocoupler state machine (simplified - no confidence)
                primary_name = self.config.get('hardware.optocoupler.primary.name')
                if primary_name in self.state_machines:
                    current_states[primary_name] = self.state_machines[primary_name].update_state(
                        freq, source, self.zero_voltage_duration
                    )
                
                # Collect tuning data if enabled
                self.logger.debug("Collecting tuning data...")
                if self.tuning_collector.enabled:
                    analysis_results = {
                        'allan_variance': avar_10s,
                        'std_deviation': std_freq
                    }
                    self.tuning_collector.collect_frequency_sample(freq, analysis_results, source)
                    self.tuning_collector.collect_analysis_results(analysis_results, source, len(self.freq_buffer))
                
                # Log detailed frequency data if enabled
                self.logger.debug("Logging detailed frequency data...")
                analysis_results = {
                    'allan_variance': avar_10s,
                    'std_deviation': std_freq
                }
                self.data_logger.log_detailed_frequency_data(
                    freq, analysis_results, source, self.sample_count, 
                    len(self.freq_buffer), self.start_time
                )
                
                # Log accuracy metrics for debugging
                self.log_accuracy_metrics(freq, source, analysis_results)
                
                # Update display and LEDs once per second
                self.logger.debug("Checking display update...")
                display_interval = self.config.get_float('app.display_update_interval')
                
                if current_time - self.last_display_time >= display_interval:
                    self.logger.debug("Updating display and LEDs...")
                    ug_indicator = self._get_power_source_indicator(source)
                    primary_name = self.config.get('hardware.optocoupler.primary.name')
                    primary_state_machine = self.state_machines.get(primary_name)
                    
                    if primary_state_machine:
                        self.hardware.display.update_display_and_leds(
                            freq, ug_indicator, primary_state_machine, 
                            self.zero_voltage_duration
                        )
                    self.last_display_time = current_time
                
                # Memory monitoring and cleanup
                memory_info = self.memory_monitor.get_memory_info()
                self.memory_monitor.check_memory_thresholds(memory_info)
                
                # Perform memory cleanup if needed
                self.memory_monitor.perform_cleanup()
                
                # Check for simulator auto-exit
                if simulator_mode and time.time() >= self.simulator_exit_time:
                    elapsed = time.time() - self.start_time
                    self.logger.info(f"Simulator auto-exit time reached ({elapsed:.1f} seconds)")
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
                    # Log state info for all optocouplers
                    all_state_info = {}
                    for optocoupler_name, state_machine in self.state_machines.items():
                        all_state_info[optocoupler_name] = state_machine.get_state_info()
                    
                    self.data_logger.log_hourly_status(timestamp, freq, source, std_freq, None, self.sample_count,
                                                     state_info=all_state_info)

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

                # No sleep needed - measurement already took measurement_duration seconds
                # Loop will naturally run at rate: measurement_duration + processing time
                self.logger.debug("Main loop iteration complete")
                
        except Exception as e:
            self.logger.error(f"Error in main loop: {e}")
        finally:
            self.cleanup()
    
    def _get_power_source_indicator(self, source: str) -> str:
        """Convert power source classification to U/G indicator."""
        if source == "Utility Grid":
            return "Util"
        elif source == "Generac Generator":
            return "Gen"
        else:
            return "?"  # Unknown

    def _clear_buffers(self):
        """Clear frequency and time buffers to ensure fresh analysis."""
        self.freq_buffer.clear()
        self.time_buffer.clear()
        self.logger.debug("Frequency and time buffers cleared")

    def log_accuracy_metrics(self, freq: Optional[float], source: str, analysis_results: Dict[str, Any]):
        """Log detailed accuracy metrics for debugging (simplified - no confidence)."""
        if self.logger.isEnabledFor(logging.DEBUG):
            freq_str = f"{freq:.3f}Hz" if freq is not None else "N/A"
            self.logger.debug(f"Accuracy Metrics: freq={freq_str}, source={source}, "
                             f"avar={analysis_results.get('allan_variance', 'N/A')}, "
                             f"std={analysis_results.get('std_deviation', 'N/A')}")

    def validate_buffers(self) -> bool:
        """Validate buffer integrity and detect corruption."""
        try:
            corruption_detected = False
            
            # Check frequency buffer
            if len(self.freq_buffer) > 0:
                freq_list = list(self.freq_buffer)
                
                # Check for NaN or infinite values
                for i, freq in enumerate(freq_list):
                    if freq is not None and (np.isnan(freq) or np.isinf(freq)):
                        self.logger.error(f"Buffer corruption detected: NaN/inf value at index {i}: {freq}")
                        corruption_detected = True
                        break
                
                # Check for sudden jumps (more than 10Hz change)
                if len(freq_list) >= 2 and not corruption_detected:
                    for i in range(1, len(freq_list)):
                        if (freq_list[i] is not None and freq_list[i-1] is not None and 
                            abs(freq_list[i] - freq_list[i-1]) > 10.0):
                            self.logger.warning(f"Buffer anomaly: large frequency jump at index {i}: {freq_list[i-1]} -> {freq_list[i]}")
            
            # Check time buffer monotonicity
            if len(self.time_buffer) > 0:
                time_list = list(self.time_buffer)
                for i in range(1, len(time_list)):
                    if time_list[i] <= time_list[i-1]:
                        self.logger.error(f"Buffer corruption detected: non-monotonic time at index {i}: {time_list[i-1]} -> {time_list[i]}")
                        corruption_detected = True
                        break
            
            # Clear buffers if corruption detected
            if corruption_detected:
                self.buffer_corruption_count += 1
                self.logger.error(f"Buffer corruption detected (count: {self.buffer_corruption_count}), clearing buffers")
                
                # Clear all buffers
                self.freq_buffer.clear()
                self.time_buffer.clear()
                
                # Log corruption event
                self.logger.critical(f"Buffer corruption event #{self.buffer_corruption_count} - all buffers cleared")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Buffer validation error: {e}")
            return False

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
        self.logger.info("Exiting application to trigger systemd restart")
        sys.exit(1)

    def cleanup(self):
        """Cleanup resources with verification."""
        self.logger.info("Cleaning up resources...")
        
        # Stop health monitoring
        self.health_monitor.stop()
        
        # Stop tuning data collection
        if self.tuning_collector.enabled:
            self.tuning_collector.stop_collection()
        
        # Cleanup hardware components
        try:
            cleanup_on_exit = self.config['app']['cleanup_on_exit']
        except KeyError as e:
            raise KeyError(f"Missing required app configuration key: {e}")
        
        if cleanup_on_exit and self.hardware is not None:
            self.hardware.cleanup()
        
        # Verify cleanup was successful
        if hasattr(self.health_monitor, 'verify_cleanup'):
            cleanup_success = self.health_monitor.verify_cleanup()
            if not cleanup_success:
                self.logger.critical("Resource cleanup verification failed - potential resource leaks detected")
            else:
                self.logger.info("Resource cleanup verification passed")
        
        # Log final resource status
        if hasattr(self.health_monitor, 'get_resource_status'):
            resource_status = self.health_monitor.get_resource_status()
            self.logger.info(f"Final resource status: {resource_status}")
        
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
        import debugpy
        debugpy.listen(("0.0.0.0", args.debug_port))
        print(f"Remote debugging enabled on port {args.debug_port}")
        print("Waiting for debugger to attach...")
        debugpy.wait_for_client()
        print("Debugger attached!")
    
    # Determine simulator mode
    simulator_mode = args.simulator
    if args.real:
        simulator_mode = False
    
    try:
        monitor = FrequencyMonitor()
        
        # Override log level if verbose or debug logging
        if args.verbose or args.debug_logging:
            logging.getLogger().setLevel(logging.DEBUG)
        
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