#!/usr/bin/env python3
"""
Measure actual AC frequency to determine the correct pulses_per_cycle setting.
"""

import sys
import os
import time
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from optocoupler import OptocouplerManager

def measure_ac_frequency():
    """Measure actual AC frequency to determine correct configuration."""
    
    # Setup logging
    logger = logging.getLogger('frequency_measure')
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Test different pulses_per_cycle settings
    test_configs = [
        {'pulses_per_cycle': 1, 'description': '1 pulse per cycle'},
        {'pulses_per_cycle': 2, 'description': '2 pulses per cycle'},
    ]
    
    for config in test_configs:
        print(f"\n{'='*60}")
        print(f"Testing: {config['description']}")
        print(f"{'='*60}")
        
        # Create config
        full_config = {
            'hardware': {
                'optocoupler': {
                    'enabled': True,
                    'gpio_pin': 26,
                    'pulses_per_cycle': config['pulses_per_cycle'],
                    'measurement_duration': 1.0
                }
            }
        }
        
        # Create optocoupler manager
        optocoupler = OptocouplerManager(full_config, logger)
        
        if not optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            continue
            
        # Measure for 10 seconds
        duration = 10.0
        print(f"Measuring for {duration} seconds...")
        
        pulse_count = optocoupler.count_optocoupler_pulses(duration)
        frequency = optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
        
        print(f"Pulse count: {pulse_count}")
        print(f"Duration: {duration:.2f}s")
        print(f"Calculated frequency: {frequency:.2f} Hz")
        
        # Check if this looks like 60 Hz
        if frequency and 55 <= frequency <= 65:
            print("✅ This looks like 60 Hz AC!")
        elif frequency and 45 <= frequency <= 55:
            print("✅ This looks like 50 Hz AC!")
        else:
            print(f"⚠️  Frequency {frequency:.2f} Hz doesn't match typical AC frequencies")
        
        # Cleanup
        optocoupler.cleanup()
        time.sleep(1)  # Brief pause between tests

if __name__ == "__main__":
    measure_ac_frequency()
