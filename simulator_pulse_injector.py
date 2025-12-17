#!/usr/bin/env python3
"""
Pulse injector for accurate simulator mode.
Injects GPIO pulses into mock gpiod based on simulator state, allowing
the full pulse counting and frequency calculation pipeline to be tested.
"""

import time
import threading
import logging
from typing import Optional, Dict
from tests.mock_gpiod import MockEdgeEvent
from tests.pulse_patterns import (
    generate_stable_60hz, generate_generator_hunting, generate_zero_voltage
)


class SimulatorPulseInjector:
    """Injects pulses into mock gpiod based on simulator state."""
    
    def __init__(self, mock_chip, pin: int, logger: logging.Logger, pulses_per_cycle: int = 2):
        self.mock_chip = mock_chip
        self.pin = pin
        self.logger = logger
        self.pulses_per_cycle = pulses_per_cycle
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._current_state = "grid"
        self._current_freq: Optional[float] = 60.0
        self._last_injection_time_ns = time.perf_counter_ns()
        self._next_pulse_time_ns = self._last_injection_time_ns
    
    def start(self):
        """Start the pulse injection thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._injection_loop, name="pulse-injector", daemon=True)
            self._thread.start()
            self.logger.info("Simulator pulse injector started")
    
    def stop(self):
        """Stop the pulse injection thread."""
        with self._lock:
            if not self._running:
                return
            self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self.logger.info("Simulator pulse injector stopped")
    
    def update_state(self, state: str, frequency: Optional[float]):
        """
        Update the current simulator state and frequency.
        
        Args:
            state: Current state ("grid", "generator", "off_grid")
            frequency: Current frequency in Hz (None for off-grid)
        """
        with self._lock:
            state_changed = self._current_state != state
            freq_changed = self._current_freq != frequency
            
            self._current_state = state
            self._current_freq = frequency
            
            if state_changed or freq_changed:
                # Reset timing when state/frequency changes
                self._last_injection_time_ns = time.perf_counter_ns()
                if frequency is not None and frequency > 0:
                    # Calculate next pulse time based on new frequency
                    pulse_freq = frequency * self.pulses_per_cycle
                    period_ns = int(1e9 / pulse_freq)
                    self._next_pulse_time_ns = self._last_injection_time_ns + period_ns
                else:
                    # Off-grid: no pulses
                    self._next_pulse_time_ns = float('inf')
    
    def _injection_loop(self):
        """Main injection loop running in background thread."""
        self.logger.debug("Pulse injection loop started")
        
        while self._running:
            try:
                with self._lock:
                    current_freq = self._current_freq
                    current_state = self._current_state
                    next_pulse_time = self._next_pulse_time_ns
                
                current_time_ns = time.perf_counter_ns()
                
                if current_freq is None or current_freq <= 0:
                    # Off-grid: no pulses
                    time.sleep(0.1)
                    continue
                
                # Check if it's time for the next pulse
                if current_time_ns >= next_pulse_time:
                    # Inject pulse with accurate timestamp
                    event = MockEdgeEvent(
                        line_offset=self.pin,
                        timestamp_ns=current_time_ns,
                        event_type="rising"
                    )
                    self.mock_chip.inject_event_to_all_requests(event)
                    
                    # Calculate next pulse time based on current frequency
                    # Re-read frequency in case it changed (for generator hunting)
                    with self._lock:
                        actual_freq = self._current_freq
                    
                    if actual_freq and actual_freq > 0:
                        pulse_freq = actual_freq * self.pulses_per_cycle
                        period_ns = int(1e9 / pulse_freq)
                        
                        with self._lock:
                            self._last_injection_time_ns = current_time_ns
                            self._next_pulse_time_ns = current_time_ns + period_ns
                    else:
                        # Frequency became invalid, wait
                        with self._lock:
                            self._next_pulse_time_ns = float('inf')
                
                # Sleep until next pulse (with some margin)
                sleep_time = max(0, (next_pulse_time - current_time_ns) / 1e9)
                if sleep_time > 0.001:  # Don't sleep less than 1ms
                    time.sleep(min(sleep_time, 0.01))  # Cap at 10ms
                else:
                    time.sleep(0.001)  # Minimum sleep
                    
            except Exception as e:
                self.logger.error(f"Error in pulse injection loop: {e}", exc_info=True)
                time.sleep(0.1)
        
        self.logger.debug("Pulse injection loop stopped")
    
    def inject_batch_for_measurement(self, duration: float, frequency: Optional[float]) -> int:
        """
        Inject a batch of pulses for a measurement window.
        Used for more accurate simulation during measurement periods.
        
        Args:
            duration: Measurement duration in seconds
            frequency: Frequency in Hz (None for off-grid)
        
        Returns:
            Number of pulses injected
        """
        if frequency is None or frequency <= 0:
            return 0
        
        start_time_ns = time.perf_counter_ns()
        timestamps = []
        
        pulse_freq = frequency * self.pulses_per_cycle
        period_ns = int(1e9 / pulse_freq)
        num_pulses = int(duration * pulse_freq)
        
        current_time = start_time_ns
        for _ in range(num_pulses):
            timestamps.append(current_time)
            current_time += period_ns
        
        # Inject all pulses
        for ts_ns in timestamps:
            event = MockEdgeEvent(
                line_offset=self.pin,
                timestamp_ns=ts_ns,
                event_type="rising"
            )
            self.mock_chip.inject_event_to_all_requests(event)
        
        return len(timestamps)
