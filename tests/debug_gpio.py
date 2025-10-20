#!/usr/bin/env python3
"""
Debug script to check GPIO state and pulse detection.
"""

import sys
import os
import time
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from optocoupler import OptocouplerManager

# Hardware imports
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

def debug_gpio_state():
    """Debug GPIO state and pulse detection."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    pin = 26
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    print(f"🔍 Debugging GPIO pin {pin}")
    print("=" * 50)
    
    # Check initial state
    initial_state = GPIO.input(pin)
    print(f"Initial state: {initial_state}")
    
    # Monitor for 2 seconds - count only falling edges
    print("Monitoring GPIO state for 2 seconds (falling edges only)...")
    start_time = time.time()
    falling_edges = 0
    rising_edges = 0
    last_state = initial_state
    
    while time.time() - start_time < 2.0:
        current_state = GPIO.input(pin)
        if current_state != last_state:
            elapsed = time.time() - start_time
            if last_state == 1 and current_state == 0:
                falling_edges += 1
                if falling_edges <= 10:  # Show first 10 falling edges
                    print(f"[{elapsed:.3f}s] FALLING edge: {last_state} -> {current_state}")
            elif last_state == 0 and current_state == 1:
                rising_edges += 1
            last_state = current_state
        time.sleep(0.001)  # 1ms polling
    
    elapsed = time.time() - start_time
    print(f"\nFalling edges: {falling_edges} in {elapsed:.2f}s")
    print(f"Rising edges: {rising_edges} in {elapsed:.2f}s")
    print(f"Estimated frequency: {falling_edges / (elapsed * 2):.2f} Hz (assuming 2 pulses per cycle)")
    print(f"Expected for 60Hz: {60 * 2 * elapsed:.0f} falling edges")

if __name__ == "__main__":
    debug_gpio_state()
