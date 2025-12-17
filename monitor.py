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
from health_check_reporter import HealthCheckReporter

# Simulator imports (only used in simulator mode)
_simulator_imports_available = False
try:
    from tests.test_utils_gpio import is_raspberry_pi, setup_mock_gpiod
    from simulator_pulse_injector import SimulatorPulseInjector
    _simulator_imports_available = True
except ImportError:
    pass

# Internal simulator mode setting: True = use pulse injection (new), False = direct frequency simulation (old)
# This is an internal implementation detail, not user-configurable
USE_PULSE_INJECTION_IN_SIMULATOR = True

# Module-specific log level override (empty string or None to use default from config.yaml)
MODULE_LOG_LEVEL = None  # Use default log level from config.yaml


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
        module_dir = os.path.dirname(os.path.abspath(__file__))
        raw_state_file = config.get('state_machine.state_file')
        if not raw_state_file:
            raise ValueError("state_machine.state_file must be configured")

        # Keep it simple: if absolute, use it; otherwise place alongside this module.
        if os.path.isabs(raw_state_file):
            self.state_file = raw_state_file
        else:
            self.state_file = os.path.join(module_dir, os.path.basename(raw_state_file))

        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
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
        self.buffers_cleared_for_pending_transition = False  # Track if buffers were cleared for current pending transition
        
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
                self.buffers_cleared_for_pending_transition = False  # Reset flag for new pending transition
                self.logger.debug(f"State change pending: {self.current_state.value} -> {new_state.value} (debouncing for {self.debounce_seconds}s)")
                
                # Clear buffers immediately when transitioning between GENERATOR and GRID
                # This prevents contamination of new state analysis with old state data
                major_states = [PowerState.GRID, PowerState.GENERATOR]
                if (self.current_state in major_states and new_state in major_states):
                    monitor = getattr(self, '_monitor_ref', None)
                    if monitor is not None:
                        monitor._clear_buffers()
                        self.buffers_cleared_for_pending_transition = True
                        self.logger.info(f"Buffers cleared immediately on pending transition: {self.current_state.value} -> {new_state.value} (to prevent data contamination)")
            
            # If pending state has been consistent long enough, transition
            elif self.pending_state_time and (current_time - self.pending_state_time) >= self.debounce_seconds:
                # Get monitor reference from config if available (passed during initialization)
                monitor = getattr(self, '_monitor_ref', None)
                if monitor is not None:
                    self._transition_to_state(new_state, monitor)
                else:
                    # Fallback: transition without monitor (won't clear buffers)
                    self._transition_to_state(new_state, None)
                self.pending_state = None
                self.pending_state_time = None
                self.buffers_cleared_for_pending_transition = False
        else:
            # State is consistent, clear any pending state
            self.pending_state = None
            self.pending_state_time = None
            self.buffers_cleared_for_pending_transition = False

        # Check for transition timeout
        if self.current_state == PowerState.TRANSITIONING:
            if time.time() - self.state_entry_time > self.transition_timeout:
                self.logger.warning(f"Transition timeout exceeded, forcing to OFF_GRID")
                monitor = getattr(self, '_monitor_ref', None)
                if monitor is not None:
                    self._transition_to_state(PowerState.OFF_GRID, monitor)
                else:
                    # Fallback: transition without monitor (won't clear buffers)
                    self._transition_to_state(PowerState.OFF_GRID, None)

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
            # If we have a pending transition and buffers were cleared, don't reset to TRANSITIONING
            # This allows time for samples to accumulate after buffer clear
            if (self.pending_state is not None and 
                self.buffers_cleared_for_pending_transition and 
                frequency is not None):
                # Keep the pending state instead of resetting to TRANSITIONING
                return self.pending_state
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
        
        # Use optocoupler with libgpiod (required - no fallback)
        if (hasattr(self.hardware_manager, 'optocoupler_initialized') and 
            self.hardware_manager.optocoupler_initialized):
            return self._count_optocoupler_frequency(duration)
        
        # Optocoupler not initialized - this should not happen if libgpiod is working
        self.logger.error("Optocoupler not initialized - libgpiod setup failed")
        return None
    
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
        Uses actual elapsed time for maximum accuracy.
        """
        try:
            # Use optimized 2-second measurement (debounce configured at startup)
            pulse_count, actual_elapsed = self.hardware_manager.count_optocoupler_pulses(duration)
            
            if pulse_count <= 0:
                self.logger.debug(f"No pulses detected in {actual_elapsed:.3f} seconds (requested: {duration:.2f}s)")
                return None
            
            # Calculate frequency from pulse count using actual elapsed time for accuracy
            frequency = self.hardware_manager.calculate_frequency_from_pulses(
                pulse_count, duration, actual_duration=actual_elapsed
            )
            
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
            
            # Log timing difference if significant
            time_diff_ms = (actual_elapsed - duration) * 1000
            if abs(time_diff_ms) > 0.5:
                self.logger.debug(f"Optocoupler frequency: {frequency:.2f} Hz from {pulse_count} pulses in {actual_elapsed:.3f}s (requested: {duration:.2f}s, diff: {time_diff_ms:+.1f}ms)")
            else:
                self.logger.debug(f"Optocoupler frequency: {frequency:.2f} Hz from {pulse_count} pulses in {actual_elapsed:.3f}s")
            return float(frequency)
            
        except Exception as e:
            self.logger.error(f"Error in optocoupler frequency measurement: {e}")
            return None
    
    def _simulate_frequency(self) -> Optional[float]:
        """Simulate power state cycling: grid (20s) -> off-grid (10s) -> generator (20s) -> grid (40s).
        
        With measurement_duration seconds per measurement, each state gets multiple measurements.
        Total cycle: 90 seconds. Extended Grid Period 2 allows buffer to clear (30s) and verify convergence.
        """
        current_time = time.time()

        # Initialize simulator start time
        if self.simulator_start_time is None:
            self.simulator_start_time = current_time

        # Calculate elapsed time and current phase (90 second cycle: extended Grid Period 2 for convergence testing)
        elapsed = current_time - self.simulator_start_time
        cycle_time = elapsed % 90.0  # 90 second cycle: 20s grid + 10s off + 20s gen + 40s grid

        # Determine current state based on cycle time and generate frequency
        expected_state = None
        expected_freq_desc = None
        actual_freq = None

        if cycle_time < 20.0:
            # Grid power (0-20s): very stable 60 Hz
            self.simulator_state = "grid"
            expected_state = "grid"
            expected_freq_desc = "~60.0 Hz ± 0.005 (stable)"
            base_freq = 60.0
            noise = random.gauss(0, 0.005)  # Very small stable noise
            actual_freq = float(base_freq + noise)

        elif cycle_time < 30.0:
            # Off-grid power (20-30s): no frequency (None)
            self.simulator_state = "off_grid"
            expected_state = "off_grid"
            expected_freq_desc = "None (no signal)"
            actual_freq = None  # No signal

        elif cycle_time < 50.0:
            # Generator power (30-50s): variable frequency with hunting
            self.simulator_state = "generator"
            expected_state = "generator"
            # Simulate generator hunting: alternating high/low
            phase_in_cycle = (cycle_time - 30.0) % 2.0
            if phase_in_cycle < 1.0:
                base_freq = 58.5 + random.uniform(-0.5, 1.0)  # Low range: 58.0-59.5 Hz
                expected_freq_desc = "58.0-59.5 Hz (low phase, hunting pattern)"
            else:
                base_freq = 61.0 + random.uniform(-1.0, 0.5)  # High range: 60.0-61.5 Hz
                expected_freq_desc = "60.0-61.5 Hz (high phase, hunting pattern)"
            noise = random.gauss(0, 0.3)  # Moderate generator noise
            actual_freq = float(base_freq + noise)

        else:
            # Back to grid power (50-90s): stable 60 Hz (extended to allow buffer convergence)
            self.simulator_state = "grid"
            expected_state = "grid"
            expected_freq_desc = "~60.0 Hz ± 0.005 (stable)"
            base_freq = 60.0
            noise = random.gauss(0, 0.005)  # Very small stable noise
            actual_freq = float(base_freq + noise)

        # Log expected vs actual for debugging
        if actual_freq is not None:
            self.logger.debug(f"SIMULATOR: Cycle time {cycle_time:.1f}s | Expected: {expected_state} ({expected_freq_desc}) | Actual: {actual_freq:.3f} Hz")
        else:
            self.logger.debug(f"SIMULATOR: Cycle time {cycle_time:.1f}s | Expected: {expected_state} ({expected_freq_desc}) | Actual: None")

        return actual_freq
    
    def analyze_stability(self, frac_freq: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
        """Compute Allan variance and standard deviation (simplified - kurtosis removed).
        
        Allan variance requires at least 6 samples for reliability. With fewer samples,
        only standard deviation is calculated (which works with any sample size).
        """
        # Check for None input first
        if frac_freq is None:
            self.logger.error("frac_freq is None. Cannot perform analysis.")
            return None, None
        
        # Minimum samples for any analysis (std_dev works with 3+ samples)
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
            
            # Calculate standard deviation (works with any sample size >= 3)
            std_freq = float(np.std(frac_freq_array * 60.0))
            
            # Allan variance requires at least 6 samples for reliability
            # Skip calculation if insufficient samples (saves computation and avoids unreliable values)
            min_samples_for_allan = 6
            if len(frac_freq_array) < min_samples_for_allan:
                return None, std_freq  # Return None for Allan variance, but keep std_dev
            
            # Calculate Allan variance only when we have enough samples
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
                avar_10s = None
            
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
        """Classify power source with stabilized thresholds and simpler rules.
        
        - Require a few samples before classifying.
        - Use std-dev until Allan variance has enough samples to settle.
        - Then use simple OR logic (either metric beyond threshold => generator).
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
        
        # Normalize sample count
        sample_count = sample_count or 0
        min_samples_for_any = 3
        min_samples_for_avar = 10  # allow Allan variance to stabilize (matches analyze_signal_quality requirement)
        min_samples_for_or_logic = 13  # switch to OR logic after more samples (extra protection against startup transients)
        
        # Not enough data yet
        if sample_count < min_samples_for_any:
            return "Unknown"
        
        # Until Allan variance has enough samples (or is missing), rely on std-dev only
        # This prevents false positives from Allan variance with insufficient data (e.g., startup transients)
        if sample_count < min_samples_for_avar or avar_10s is None:
            return "Generac Generator" if std_freq > std_thresh else "Utility Grid"
        
        # For 10-12 samples: Use AND logic (both metrics must exceed threshold) for extra protection
        # This prevents false positives from startup transients that might still be in the window
        if sample_count < min_samples_for_or_logic:
            if avar_10s > avar_thresh and std_freq > std_thresh:
                return "Generac Generator"
            return "Utility Grid"
        
        # For 13+ samples: Use OR logic (either metric beyond threshold => generator)
        # With enough samples, Allan variance is fully reliable and startup transients are out of window
        # std_dev catches wide swings, Allan variance catches hunting patterns - either indicates generator
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
        
        # Cache socket connection to avoid creating new socket every iteration
        # This significantly reduces CPU overhead from socket creation/teardown
        if not hasattr(self, '_sd_notify_sock') or self._sd_notify_sock is None:
            try:
                if notify_socket.startswith('@'):
                    notify_socket = '\0' + notify_socket[1:]
                self._sd_notify_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                self._sd_notify_sock.connect(notify_socket)
            except Exception as e:
                self.logger.debug(f"Failed to create systemd notification socket: {e}")
                self._sd_notify_sock = None
                return
        
        try:
            self._sd_notify_sock.sendall(state.encode('utf-8'))
        except Exception as e:
            # Socket may have been closed, reset and try again next time
            self.logger.debug(f"Failed to send systemd notification: {e}")
            try:
                self._sd_notify_sock.close()
            except:
                pass
            self._sd_notify_sock = None

    def __init__(self):
        self.config = Config("config.yaml")
        self.logger_setup = Logger(self.config)
        self.logger = logging.getLogger(__name__)
        
        # Apply module-specific log level if set
        if MODULE_LOG_LEVEL and MODULE_LOG_LEVEL.strip():
            try:
                log_level = getattr(logging, MODULE_LOG_LEVEL.strip().upper())
                self.logger.setLevel(log_level)
            except AttributeError:
                self.logger.warning(f"Invalid MODULE_LOG_LEVEL '{MODULE_LOG_LEVEL}', using default")
        
        # Check if we're in simulator mode
        try:
            self.simulator_mode = self.config['app']['simulator_mode']
        except KeyError as e:
            raise KeyError(f"Missing required app configuration key: {e}")
        
        # Setup mock gpiod if in simulator mode and not on RPi
        self.pulse_injector = None
        self.mock_chip = None
        
        if self.simulator_mode and _simulator_imports_available:
            if not is_raspberry_pi():
                self.logger.info("Simulator mode: Setting up mock gpiod for accurate pulse simulation")
                setup_mock_gpiod()
                # Get mock chip after hardware is initialized
                # We'll set it up in _initialize_components
            else:
                self.logger.info("Simulator mode: Running on RPi, using real hardware with simulated frequency")
        
        # Initialize components
        self._initialize_components()
        
        # Initialize state variables
        self._initialize_state()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info("Frequency monitor initialized")
        
        # Notify systemd that we are ready
        self._sd_notify("READY=1")
        
        # Start background services
        self._start_background_services()
    
    def _initialize_components(self):
        """Initialize all system components."""
        # Create analyzer first (needed for pulse injector initialization)
        self.analyzer = FrequencyAnalyzer(self.config, self.logger)
        # Set simulator mode on analyzer so it can use reduced sample requirements
        self.analyzer.simulator_mode = self.simulator_mode
        
        # Always initialize hardware manager (it handles graceful degradation internally)
        # Simulator mode only affects frequency data source, not hardware availability
        self.hardware = HardwareManager(self.config, self.logger)
        
        # Setup pulse injector if in simulator mode with mock gpiod
        # Only setup if pulse injection is enabled (controlled by global variable)
        if self.simulator_mode and USE_PULSE_INJECTION_IN_SIMULATOR and _simulator_imports_available and not is_raspberry_pi():
            try:
                from tests.mock_gpiod import mock_gpiod
                # Get the mock chip from the optocoupler's counter
                # The counter creates a request when a pin is registered
                if (hasattr(self.hardware, 'optocoupler') and 
                    hasattr(self.hardware.optocoupler, 'optocouplers')):
                    primary_optocoupler = self.hardware.optocoupler.optocouplers.get('primary')
                    if primary_optocoupler and hasattr(primary_optocoupler, 'counter'):
                        counter = primary_optocoupler.counter
                        pin = primary_optocoupler.pin
                        pulses_per_cycle = primary_optocoupler.pulses_per_cycle
                        
                        # Ensure optocoupler is initialized
                        if not primary_optocoupler.initialized:
                            self.logger.warning("Primary optocoupler not initialized yet, cannot setup pulse injector")
                            self.pulse_injector = None
                            return
                        
                        # Get the mock chip - must use the same chip instance the counter is using
                        # Check counter's _chip first (set during _start_request in register_pin)
                        mock_chip = None
                        if hasattr(counter, '_chip') and counter._chip is not None:
                            mock_chip = counter._chip
                            self.logger.debug(f"Found mock chip from counter._chip")
                        elif hasattr(counter, '_request') and counter._request is not None:
                            if hasattr(counter._request, 'chip') and counter._request.chip is not None:
                                mock_chip = counter._request.chip
                                self.logger.debug(f"Found mock chip from counter._request.chip")
                        
                        if mock_chip is None:
                            self.logger.warning("Could not access mock chip from counter. Counter may not be fully initialized. Using direct frequency simulation.")
                            self.pulse_injector = None
                            return
                        
                        # Verify it's a mock chip (has inject_event_to_all_requests method)
                        if not hasattr(mock_chip, 'inject_event_to_all_requests'):
                            self.logger.warning(f"Chip does not have inject_event_to_all_requests method. Using direct frequency simulation.")
                            self.pulse_injector = None
                            return
                        
                        self.mock_chip = mock_chip
                        self.pulse_injector = SimulatorPulseInjector(
                            self.mock_chip, pin, self.logger, pulses_per_cycle
                        )
                        # Initialize with current simulator state and frequency
                        # IMPORTANT: Call _simulate_frequency() to set simulator_start_time first
                        initial_freq = self.analyzer._simulate_frequency()
                        initial_state = getattr(self.analyzer, 'simulator_state', 'grid')
                        # Update state BEFORE starting to ensure correct initial frequency
                        self.pulse_injector.update_state(initial_state, initial_freq)
                        self.pulse_injector.start()
                        self.logger.info(f"Simulator pulse injector initialized for pin {pin} (pulses_per_cycle={pulses_per_cycle}) with initial state={initial_state}, freq={initial_freq:.3f} Hz")
                    else:
                        self.logger.warning("Primary optocoupler or counter not found, cannot setup pulse injector")
                        self.pulse_injector = None
                else:
                    self.logger.warning("Hardware optocoupler not available, cannot setup pulse injector")
                    self.pulse_injector = None
            except Exception as e:
                self.logger.warning(f"Failed to setup pulse injector: {e}. Using direct frequency simulation.", exc_info=True)
                self.pulse_injector = None
        
        if self.simulator_mode:
            if self.pulse_injector:
                self.logger.info("Simulator mode: Using mock gpiod with pulse injection for accurate simulation")
            elif not USE_PULSE_INJECTION_IN_SIMULATOR:
                self.logger.info("Simulator mode: Pulse injection disabled, using direct frequency simulation")
            else:
                self.logger.info("Simulator mode: Pulse injection unavailable, using direct frequency simulation")
        else:
            self.logger.info("Real mode: Using real hardware for frequency data")
        
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
            analysis_window_seconds = 20.0  # Default fallback
        
        # Calculate buffer size based on analysis window
        # Each measurement takes measurement_duration seconds
        buffer_size = int(analysis_window_seconds / measurement_duration)
        # Ensure buffer can hold at least enough samples for analysis (minimum 10 for Allan variance)
        buffer_size = max(buffer_size, 10)
        
        self.freq_buffer = deque(maxlen=buffer_size)
        self.time_buffer = deque(maxlen=buffer_size)
        
        # Clear buffers on startup to ensure fresh analysis
        self._clear_buffers()
        self.logger.info("Buffers cleared on startup for fresh analysis")
    
    def _initialize_state(self):
        """Initialize state variables."""
        # State variables
        self.running = True
        self.last_log_time = 0
        self.last_display_time = 0
        self.sample_count = 0
        self.start_time = time.time()
        self.zero_voltage_start_time = None  # Track when voltage went to zero (absolute time)
        self.zero_voltage_duration = 0.0    # How long voltage has been zero
        
        # Non-blocking measurement state
        self.measurement_in_progress = False
        self.has_new_reading = False  # Track if we have a new reading to process
        
        # Store current values for health check reporter callback
        self.last_freq = None
        self.last_source = "Unknown"

        # Reset button state tracking
        self.reset_button_pressed = False
        self.last_reset_check = 0
        
        # Buffer validation tracking
        self.last_buffer_validation = 0
        self.buffer_validation_interval = 100  # Validate every 100 samples
        self.buffer_corruption_count = 0
        
        # Memory monitoring tracking (run every 100 iterations = ~5 seconds with 50ms sleep)
        self.loop_iteration_count = 0
        self.memory_monitoring_interval = 100  # Run memory monitoring every 100 loop iterations (reduced frequency for CPU optimization)
    
    def _start_background_services(self):
        """Start background services and health check reporter."""
        # Start tuning data collection if enabled
        if self.tuning_collector.enabled:
            self.tuning_collector.start_collection()
        
        # Start restart manager (auto-updates handled by system services)
        self.restart_manager.start_update_monitor()
        
        # Initialize health check reporter (if enabled)
        self.health_check_reporter = None
        try:
            if self.config.get('health_check.enabled', False):
                # Create callback function to get current state
                def get_current_state():
                    """Callback to get current system state for health check."""
                    state_info = {}
                    
                    # Get memory info
                    try:
                        memory_info = self.memory_monitor.get_memory_info()
                        if memory_info:
                            state_info['memory_mb'] = memory_info.get('process_memory_mb', 0)
                            state_info['memory_percent'] = memory_info.get('process_memory_percent', 0)
                            state_info['system_memory_percent'] = memory_info.get('system_memory_percent', 0)
                    except Exception as e:
                        self.logger.debug(f"Error getting memory info for health check: {e}")
                    
                    # Get current frequency and power source (from most recent values)
                    # These are set in the main loop, so we access them safely
                    try:
                        if hasattr(self, 'last_freq') and self.last_freq is not None:
                            state_info['frequency'] = self.last_freq
                        if hasattr(self, 'last_source') and self.last_source:
                            state_info['power_source'] = self.last_source
                        if hasattr(self, 'sample_count'):
                            state_info['sample_count'] = self.sample_count
                    except Exception as e:
                        self.logger.debug(f"Error getting frequency info for health check: {e}")
                    
                    # Get current state from state machines
                    try:
                        primary_name = self.config.get('hardware.optocoupler.primary.name')
                        if primary_name in self.state_machines:
                            state_info_dict = self.state_machines[primary_name].get_state_info()
                            state_info['current_state'] = state_info_dict.get('current_state', 'unknown')
                    except Exception as e:
                        self.logger.debug(f"Error getting state machine info for health check: {e}")
                    
                    return state_info
                
                self.health_check_reporter = HealthCheckReporter(
                    self.config, self.logger, get_current_state
                )
        except Exception as e:
            self.logger.warning(f"Failed to initialize health check reporter: {e}")
    
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
            analysis_window_seconds = 20.0  # Default fallback
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
        # Exit with code 1 to indicate shutdown (systemd will handle restart if configured)
        import sys
        sys.exit(1)
    
    def _get_simulated_frequency(self, measurement_duration: float) -> Optional[float]:
        """Get simulated frequency reading with validation logging."""
        try:
            # In simulator, generate a reading but simulate the measurement time
            freq = self.analyzer._simulate_frequency()
            # Mark that we have a new reading to process
            self.has_new_reading = True
            # Log expected vs actual comparison for simulator debugging
            expected_state = getattr(self.analyzer, 'simulator_state', 'unknown')
            if freq is not None:
                # Validate frequency matches expected state
                if expected_state == "grid":
                    # Grid should be ~60.0 Hz ± 0.01 (allowing some margin)
                    matches = 59.99 <= freq <= 60.01
                    self.logger.debug(f"SIMULATOR COMPARISON: Expected state={expected_state}, freq={freq:.3f} Hz | {'✓ MATCHES' if matches else '✗ OUT OF RANGE (expected ~60.0 Hz)'}")
                elif expected_state == "generator":
                    # Generator should be 58.0-61.5 Hz range
                    matches = 58.0 <= freq <= 61.5
                    self.logger.debug(f"SIMULATOR COMPARISON: Expected state={expected_state}, freq={freq:.3f} Hz | {'✓ MATCHES' if matches else '✗ OUT OF RANGE (expected 58.0-61.5 Hz)'}")
                else:
                    self.logger.debug(f"SIMULATOR COMPARISON: Expected state={expected_state}, freq={freq:.3f} Hz")
            else:
                # None frequency should match off_grid state
                matches = expected_state == "off_grid"
                self.logger.debug(f"SIMULATOR COMPARISON: Expected state={expected_state}, freq=None | {'✓ MATCHES' if matches else '✗ MISMATCH (expected off_grid for None)'}")
            # Simulate the measurement duration by sleeping
            time.sleep(measurement_duration)
            return freq
        except Exception as e:
            self.logger.error(f"Error getting simulated frequency: {e}", exc_info=True)
            return None
    
    def _get_hardware_frequency(self, measurement_duration: float) -> Optional[float]:
        """Get hardware frequency reading (non-blocking)."""
        try:
            # Real hardware: check if measurement is complete (non-blocking)
            is_complete, pulse_count, actual_elapsed = self.hardware.check_measurement()
            
            if is_complete:
                # Measurement complete - process result
                freq = None
                if pulse_count is not None and actual_elapsed is not None:
                    # Calculate frequency from pulse count
                    freq = self.hardware.calculate_frequency_from_pulses(
                        pulse_count, measurement_duration, actual_duration=actual_elapsed
                    )
                    
                    # Validate frequency range
                    if freq is not None:
                        try:
                            min_freq = self.config['sampling']['min_freq']
                            max_freq = self.config['sampling']['max_freq']
                        except KeyError as e:
                            raise KeyError(f"Missing required sampling configuration key: {e}")
                        
                        if freq < min_freq or freq > max_freq:
                            self.logger.warning(f"Invalid frequency reading: {freq:.2f} Hz (outside range {min_freq}-{max_freq} Hz)")
                            freq = None
                
                # Mark that we have a new reading to process
                self.has_new_reading = True
                self.measurement_in_progress = False
                
                # Start next measurement immediately (non-blocking)
                if self.hardware.start_measurement(duration=measurement_duration):
                    self.measurement_in_progress = True
                else:
                    self.logger.warning("Failed to start next measurement")
                    self.measurement_in_progress = False
                
                return freq
            else:
                # Measurement still in progress - skip frequency processing this iteration
                # Main loop continues with other tasks (display updates, button checks, etc.)
                self.has_new_reading = False
                return None
        except Exception as e:
            self.logger.error(f"Error getting hardware frequency: {e}", exc_info=True)
            self.measurement_in_progress = False
            self.has_new_reading = False
            return None
    
    def _acquire_frequency_reading(self, simulator_mode: bool, measurement_duration: float) -> Optional[float]:
        """
        Acquire a frequency reading (non-blocking for real hardware).
        Returns frequency or None if no reading available yet.
        """
        if simulator_mode:
            # If we have pulse injector, use hardware path with mock pulses
            # Otherwise, use direct frequency simulation (old logic)
            if self.pulse_injector:
                # Use hardware path (which will read from mock pulses)
                # Pulse injector state is updated in main loop before this call
                return self._get_hardware_frequency(measurement_duration)
            else:
                return self._get_simulated_frequency(measurement_duration)
        else:
            return self._get_hardware_frequency(measurement_duration)
    
    def _update_zero_voltage_tracking(self, freq: Optional[float]):
        """Update zero voltage duration tracking."""
        try:
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
        except Exception as e:
            self.logger.error(f"Error updating zero voltage tracking: {e}", exc_info=True)
    
    def _validate_frequency(self, freq: Optional[float], measurement_duration: float) -> Optional[float]:
        """Validate frequency reading with enhanced accuracy checks."""
        try:
            if freq is None:
                self.logger.info(f"No frequency reading (zero voltage duration: {self.zero_voltage_duration:.1f}s)")
                return None
            
            if not isinstance(freq, (int, float)):
                self.logger.error(f"Invalid frequency data type: {type(freq)}. Expected number, got {freq}")
                return None
            
            if np.isnan(freq) or np.isinf(freq):
                self.logger.error(f"Invalid frequency value: {freq}")
                return None
            
            # Enhanced validation for accuracy
            pulse_count = getattr(self, 'last_pulse_count', 0)  # Get from optocoupler if available
            validated_freq = self.analyzer.validate_frequency_reading(freq, pulse_count, measurement_duration)
            if validated_freq is None:
                self.logger.warning(f"Frequency reading failed validation: {freq:.2f}Hz")
                return None
            
            return validated_freq
        except Exception as e:
            self.logger.error(f"Error validating frequency: {e}", exc_info=True)
            return None
    
    def _update_buffers(self, freq: float):
        """Update frequency and time buffers."""
        try:
            elapsed_time = time.time() - self.start_time
            self.freq_buffer.append(freq)
            self.time_buffer.append(elapsed_time)
            self.sample_count += 1
        except Exception as e:
            self.logger.error(f"Error updating buffers: {e}", exc_info=True)
    
    def _process_frequency_reading(self, freq: Optional[float], measurement_duration: float) -> Optional[float]:
        """
        Process and validate a frequency reading.
        Updates buffers and zero-voltage tracking.
        Returns validated frequency or None.
        """
        # Track zero voltage
        self._update_zero_voltage_tracking(freq)
        
        # Validate frequency
        validated_freq = self._validate_frequency(freq, measurement_duration)
        if validated_freq is None:
            return None
        
        # Update buffers
        self._update_buffers(validated_freq)
        return validated_freq
    
    def _analyze_and_classify(self, freq: Optional[float]) -> Tuple[str, Dict[str, Any]]:
        """
        Analyze frequency data and classify power source.
        Returns (power_source, analysis_results).
        """
        try:
            if freq is None:
                return "Unknown", {}
            
            # Get analysis window
            try:
                analysis_window_seconds = self.config.get_float('analysis.analysis_window_seconds')
            except (KeyError, ValueError):
                analysis_window_seconds = 20.0  # Default fallback
            
            measurement_duration = self.config.get_float('hardware.optocoupler.primary.measurement_duration')
            samples_for_analysis = int(analysis_window_seconds / measurement_duration)
            samples_needed = 3  # Minimum: 3 samples required for analysis
            
            if len(self.freq_buffer) < samples_needed:
                self.logger.debug(f"Not enough samples for analysis (have {len(self.freq_buffer)}, need {samples_needed} sample(s), each covering {measurement_duration}s)")
                return "Unknown", {}
            
            # Use analysis window (most recent samples)
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
            
            return source, {
                'allan_variance': avar_10s,
                'std_deviation': std_freq
            }
        except Exception as e:
            self.logger.error(f"Error in analysis and classification: {e}", exc_info=True)
            return "Unknown", {}
    
    def _update_state_machines(self, freq: Optional[float], source: str) -> Dict[str, PowerState]:
        """
        Update all state machines with current frequency and classification.
        Returns dict mapping optocoupler names to current states.
        """
        try:
            current_states = {}
            primary_name = self.config.get('hardware.optocoupler.primary.name')
            
            if primary_name in self.state_machines:
                state_machine = self.state_machines[primary_name]
                current_state = state_machine.update_state(
                    freq, source, self.zero_voltage_duration
                )
                current_states[primary_name] = current_state
            
            return current_states
        except Exception as e:
            self.logger.error(f"Error updating state machines: {e}", exc_info=True)
            return {}
    
    def _update_display(self, freq: Optional[float], source: str):
        """Update display and LEDs."""
        try:
            # Use last known frequency if measurement in progress
            display_freq = self.last_freq if self.measurement_in_progress else freq
            ug_indicator = self._get_power_source_indicator(source)
            primary_name = self.config.get('hardware.optocoupler.primary.name')
            primary_state_machine = self.state_machines.get(primary_name)
            
            if primary_state_machine:
                self.hardware.display.update_display_and_leds(
                    display_freq, ug_indicator, primary_state_machine, 
                    self.zero_voltage_duration
                )
        except Exception as e:
            self.logger.error(f"Error updating display: {e}", exc_info=True)
    
    def _log_hourly_status(self, current_time: float, freq: Optional[float], source: str, analysis_results: Dict[str, Any]):
        """Log hourly status and memory information."""
        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            # Log state info for all optocouplers
            all_state_info = {}
            for optocoupler_name, state_machine in self.state_machines.items():
                all_state_info[optocoupler_name] = state_machine.get_state_info()
            
            std_freq = analysis_results.get('std_deviation')
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
        except Exception as e:
            self.logger.error(f"Error logging hourly status: {e}", exc_info=True)
    
    def _log_and_collect_data(self, freq: Optional[float], source: str, analysis_results: Dict[str, Any]):
        """Log data and collect tuning data."""
        try:
            # Collect tuning data if enabled
            if self.tuning_collector.enabled:
                self.tuning_collector.collect_frequency_sample(freq, analysis_results, source)
                self.tuning_collector.collect_analysis_results(analysis_results, source, len(self.freq_buffer))
            
            # Log detailed frequency data if enabled
            self.data_logger.log_detailed_frequency_data(
                freq, analysis_results, source, self.sample_count, 
                len(self.freq_buffer), self.start_time
            )
            
            # Log accuracy metrics for debugging
            self.log_accuracy_metrics(freq, source, analysis_results)
        except Exception as e:
            self.logger.error(f"Error logging and collecting data: {e}", exc_info=True)
    
    def _handle_periodic_tasks(self, current_time: float, freq: Optional[float], source: str, analysis_results: Dict[str, Any]):
        """
        Handle periodic tasks: display updates, buffer validation, hourly logging.
        """
        try:
            # Buffer validation
            if self.sample_count - self.last_buffer_validation >= self.buffer_validation_interval:
                self.validate_buffers()
                self.last_buffer_validation = self.sample_count
            
            # Display updates
            display_interval = self.config.get_float('app.display_update_interval')
            if current_time - self.last_display_time >= display_interval:
                self._update_display(freq, source)
                self.last_display_time = current_time
            
            # Hourly logging
            if current_time - self.last_log_time >= 3600:
                self._log_hourly_status(current_time, freq, source, analysis_results)
                self.last_log_time = current_time
        except Exception as e:
            self.logger.error(f"Error handling periodic tasks: {e}", exc_info=True)
    
    def _should_exit(self, simulator_mode: bool) -> bool:
        """Check if we should exit the main loop."""
        try:
            # Check for simulator auto-exit
            if simulator_mode and hasattr(self, 'simulator_exit_time'):
                if time.time() >= self.simulator_exit_time:
                    elapsed = time.time() - self.start_time
                    self.logger.info(f"Simulator auto-exit time reached ({elapsed:.1f} seconds)")
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Error checking exit conditions: {e}", exc_info=True)
            return False
    
    def _loop_sleep(self):
        """Sleep to prevent busy-waiting in main loop."""
        try:
            loop_sleep_interval = self.config.get_float('app.loop_sleep_interval')  # Default 50ms
            if self.measurement_in_progress:
                # Sleep during measurement to avoid busy-waiting
                # Still responsive enough for button checks and other tasks
                time.sleep(loop_sleep_interval)
            else:
                # When measurement completes, still sleep a small amount to prevent tight looping
                # Use a shorter sleep (10ms) for better responsiveness after measurement completes
                time.sleep(0.01)  # 10ms minimum sleep to prevent CPU spinning
        except Exception as e:
            self.logger.error(f"Error in loop sleep: {e}", exc_info=True)
    
    def run(self, simulator_mode: bool = None):
        """Main monitoring loop - simplified and focused."""
        if simulator_mode is None:
            try:
                simulator_mode = self.config['app']['simulator_mode']
            except KeyError as e:
                raise KeyError(f"Missing required app configuration key: {e}")
        
        # Update self.simulator_mode if it was overridden by command line
        if simulator_mode != self.simulator_mode:
            self.simulator_mode = simulator_mode
            # Re-initialize pulse injector if needed (wasn't set up in __init__)
            if self.simulator_mode and _simulator_imports_available and not is_raspberry_pi():
                if self.pulse_injector is None:
                    # Try to set up pulse injector now
                    try:
                        from tests.mock_gpiod import mock_gpiod
                        if (hasattr(self.hardware, 'optocoupler') and 
                            hasattr(self.hardware.optocoupler, 'optocouplers')):
                            primary_optocoupler = self.hardware.optocoupler.optocouplers.get('primary')
                            if primary_optocoupler and hasattr(primary_optocoupler, 'counter'):
                                counter = primary_optocoupler.counter
                                pin = primary_optocoupler.pin
                                pulses_per_cycle = primary_optocoupler.pulses_per_cycle
                                
                                if primary_optocoupler.initialized:
                                    mock_chip = None
                                    if hasattr(counter, '_chip') and counter._chip is not None:
                                        mock_chip = counter._chip
                                    elif hasattr(counter, '_request') and counter._request is not None:
                                        if hasattr(counter._request, 'chip') and counter._request.chip is not None:
                                            mock_chip = counter._request.chip
                                    
                                    if mock_chip is not None and hasattr(mock_chip, 'inject_event_to_all_requests'):
                                        self.mock_chip = mock_chip
                                        self.pulse_injector = SimulatorPulseInjector(
                                            self.mock_chip, pin, self.logger, pulses_per_cycle
                                        )
                                        # Initialize with current simulator state and frequency
                                        initial_freq = self.analyzer._simulate_frequency()
                                        initial_state = getattr(self.analyzer, 'simulator_state', 'grid')
                                        self.pulse_injector.update_state(initial_state, initial_freq)
                                        self.pulse_injector.start()
                                        self.logger.info(f"Simulator pulse injector initialized for pin {pin} (pulses_per_cycle={pulses_per_cycle}) with initial state={initial_state}, freq={initial_freq}")
                    except Exception as e:
                        self.logger.warning(f"Failed to setup pulse injector in run(): {e}. Using direct frequency simulation.", exc_info=True)
        
        self.logger.info(f"Starting frequency monitor (simulator: {simulator_mode})")

        # Initialize display
        if self.hardware is not None:
            self.hardware.update_display("Starting...", "Please wait...")
            time.sleep(1)  # Display startup message for 1 second

        # For simulator mode, set up auto-exit after 90 seconds (one full cycle)
        if simulator_mode:
            self.simulator_exit_time = time.time() + 90.0
            self.logger.info("Simulator mode: will auto-exit after 90 seconds (one full cycle: 20s grid -> 10s off-grid -> 20s generator -> 40s grid)")
        
        try:
            # Get measurement duration once at start
            measurement_duration = self.config.get_float('hardware.optocoupler.primary.measurement_duration')
            
            # Initialize pulse injector state before starting measurements
            if simulator_mode and USE_PULSE_INJECTION_IN_SIMULATOR and self.pulse_injector:
                # Get current simulator state to initialize injector
                initial_freq = self.analyzer._simulate_frequency()
                initial_state = getattr(self.analyzer, 'simulator_state', 'grid')
                self.pulse_injector.update_state(initial_state, initial_freq)
                self.logger.debug(f"Pulse injector initialized with state={initial_state}, freq={initial_freq}")
            
            # Start first measurement immediately (non-blocking)
            # In simulator mode with pulse injector, we still use hardware measurement
            if not simulator_mode or (USE_PULSE_INJECTION_IN_SIMULATOR and self.pulse_injector):
                self.hardware.start_measurement(duration=measurement_duration)
                self.measurement_in_progress = True
            
            while self.running:
                current_time = time.time()
                
                # 1. Update pulse injector state if using mock (before acquiring reading)
                if simulator_mode and USE_PULSE_INJECTION_IN_SIMULATOR and self.pulse_injector:
                    # Get current simulator state to update injector
                    current_freq = self.analyzer._simulate_frequency()
                    current_state = getattr(self.analyzer, 'simulator_state', 'grid')
                    self.pulse_injector.update_state(current_state, current_freq)
                
                # 2. Acquire frequency reading (non-blocking)
                freq = self._acquire_frequency_reading(simulator_mode, measurement_duration)
                
                # 3. Process reading if available
                if self.has_new_reading:
                    validated_freq = self._process_frequency_reading(freq, measurement_duration)
                    
                    # 3. Analyze and classify
                    source, analysis_results = self._analyze_and_classify(validated_freq)
                    
                    # 4. Update state machines
                    current_states = self._update_state_machines(validated_freq, source)
                    
                    # 5. Logging and data collection
                    self._log_and_collect_data(validated_freq, source, analysis_results)
                    
                    # Store for health checks
                    self.last_freq = validated_freq
                    self.last_source = source
                else:
                    # Measurement in progress - use last known values
                    source = self.last_source
                    analysis_results = {}
                
                # 6. Periodic tasks (always run)
                self._handle_periodic_tasks(current_time, self.last_freq, self.last_source, analysis_results)
                
                # 7. Systemd watchdog
                self._sd_notify("WATCHDOG=1")
                
                # 8. Memory monitoring and cleanup (run every N iterations to reduce CPU)
                if self.loop_iteration_count % self.memory_monitoring_interval == 0:
                    try:
                        memory_info = self.memory_monitor.get_memory_info()
                        self.memory_monitor.check_memory_thresholds(memory_info)
                        self.memory_monitor.perform_cleanup()
                    except Exception as e:
                        self.logger.error(f"Error in memory monitoring: {e}", exc_info=True)
                
                # 9. Check reset button (debounced, check every 0.5 seconds)
                try:
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
                except Exception as e:
                    self.logger.error(f"Error checking reset button: {e}", exc_info=True)
                
                # 10. Check for exit conditions
                if self._should_exit(simulator_mode):
                    break
                
                # 11. Sleep if needed
                self._loop_sleep()
                
        except Exception as e:
            self.logger.error(f"Error in main loop: {e}", exc_info=True)
        finally:
            # Stop pulse injector if running
            if self.pulse_injector:
                self.pulse_injector.stop()
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
        
        # Close systemd notification socket
        if hasattr(self, '_sd_notify_sock') and self._sd_notify_sock is not None:
            try:
                self._sd_notify_sock.close()
            except:
                pass
            self._sd_notify_sock = None
        
        # Stop health check reporter
        if self.health_check_reporter is not None:
            self.health_check_reporter.stop()
        
        # Stop health monitoring
        self.health_monitor.stop()
        
        # Stop tuning data collection
        if self.tuning_collector.enabled:
            self.tuning_collector.stop_collection()
        
        # Cleanup Sol-Ark integration (stops threads and browser)
        if self.solark_integration is not None:
            try:
                self.solark_integration.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up Sol-Ark integration: {e}")
        
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