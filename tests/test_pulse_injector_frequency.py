#!/usr/bin/env python3
"""
Test script to verify pulse injector generates the same frequencies as the old simulator logic.
"""

import time
import sys
sys.path.insert(0, '/home/keithcu/Desktop/RpiSolArk')

from tests.test_utils_gpio import setup_mock_gpiod, is_raspberry_pi
from tests.mock_gpiod import mock_gpiod
from simulator_pulse_injector import SimulatorPulseInjector
from monitor import FrequencyAnalyzer
from config import Config
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('test')

# Setup mock gpiod
if not is_raspberry_pi():
    setup_mock_gpiod()

# Create analyzer
config = Config('config.yaml')
analyzer = FrequencyAnalyzer(config, logger)

# Create mock chip and pulse injector
mock_chip = mock_gpiod.Chip("/dev/gpiochip0")
pin = 26
pulses_per_cycle = 2

pulse_injector = SimulatorPulseInjector(mock_chip, pin, logger, pulses_per_cycle)

# Create a mock request to receive events
from tests.mock_gpiod import MockLineSettings
line_settings = {pin: MockLineSettings()}
request = mock_chip.request_lines("test", line_settings)

# Start pulse injector
pulse_injector.start()

# Test frequencies at different cycle times
test_cases = [
    (0.0, "grid", 60.0),      # Start of cycle - grid
    (10.0, "grid", 60.0),     # Middle of grid period
    (25.0, "off_grid", None), # Off-grid period
    (35.0, "generator", None), # Generator period (will have variable freq)
    (55.0, "grid", 60.0),     # Back to grid
]

print("\n=== Testing Pulse Injector Frequency Generation ===\n")

# Manually set simulator start time to control cycle
analyzer.simulator_start_time = time.time() - 0.0  # Start at cycle time 0

for cycle_offset, expected_state, expected_freq_base in test_cases:
    # Set analyzer to specific cycle time
    analyzer.simulator_start_time = time.time() - cycle_offset
    
    # Get frequency from analyzer (old logic)
    analyzer_freq = analyzer._simulate_frequency()
    analyzer_state = analyzer.simulator_state
    
    # Update pulse injector
    pulse_injector.update_state(analyzer_state, analyzer_freq)
    
    print(f"Cycle time: {cycle_offset:.1f}s")
    print(f"  Analyzer state: {analyzer_state}, freq: {analyzer_freq}")
    print(f"  Expected state: {expected_state}, base freq: {expected_freq_base}")
    
    if analyzer_freq is not None:
        # Wait a bit for pulses to accumulate
        time.sleep(0.5)
        
        # Read events from request
        events = request.read_edge_events()
        if events:
            # Calculate frequency from pulses
            if len(events) >= 2:
                duration_ns = events[-1].timestamp_ns - events[0].timestamp_ns
                duration_sec = duration_ns / 1e9
                num_intervals = len(events) - 1
                if duration_ns > 0:
                    calculated_freq = (num_intervals * 1e9) / (duration_ns * pulses_per_cycle)
                    print(f"  Calculated from pulses: {calculated_freq:.3f} Hz ({len(events)} pulses in {duration_sec:.3f}s)")
                    print(f"  Error: {abs(calculated_freq - analyzer_freq):.3f} Hz")
                else:
                    print(f"  No duration (all events at same time)")
            else:
                print(f"  Not enough events ({len(events)})")
        else:
            print(f"  No events received")
    else:
        print(f"  Off-grid: no pulses expected")
    
    print()

# Cleanup
pulse_injector.stop()
request.release()
mock_chip.close()

print("=== Test Complete ===")
