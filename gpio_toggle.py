#!/usr/bin/env python3
"""
Simple GPIO Toggle App for Raspberry Pi
Toggles GPIO pin 17 every second
"""

import RPi.GPIO as GPIO
import time
import signal
import sys

# GPIO pin to toggle
GPIO_PIN = 17

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print('\nShutting down GPIO toggle app...')
    GPIO.cleanup()
    sys.exit(0)

def main():
    """Main function to toggle GPIO pin"""
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Set up GPIO
    GPIO.setmode(GPIO.BCM)  # Use BCM pin numbering
    GPIO.setup(GPIO_PIN, GPIO.OUT)  # Set pin as output
    
    print(f"GPIO Toggle App Started")
    print(f"Toggling GPIO pin {GPIO_PIN} every second")
    print("Press Ctrl+C to stop")
    print("-" * 40)
    
    try:
        while True:
            # Toggle the pin
            GPIO.output(GPIO_PIN, GPIO.HIGH)
            print(f"GPIO {GPIO_PIN}: HIGH")
            time.sleep(1)
            
            GPIO.output(GPIO_PIN, GPIO.LOW)
            print(f"GPIO {GPIO_PIN}: LOW")
            time.sleep(1)
            
    except KeyboardInterrupt:
        pass
    finally:
        # Clean up GPIO on exit
        GPIO.cleanup()
        print("GPIO cleanup completed")

if __name__ == "__main__":
    main()
