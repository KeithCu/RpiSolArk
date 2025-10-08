#!/usr/bin/env python3
"""
Hardware watchdog setup for Raspberry Pi
"""

import subprocess
import time
import logging

def setup_hardware_watchdog():
    """Setup hardware watchdog timer."""
    try:
        # Enable hardware watchdog
        subprocess.run(['sudo', 'modprobe', 'bcm2835_wdt'], check=True)
        subprocess.run(['sudo', 'systemctl', 'enable', 'watchdog'], check=True)
        subprocess.run(['sudo', 'systemctl', 'start', 'watchdog'], check=True)
        
        logging.info("Hardware watchdog enabled")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to setup hardware watchdog: {e}")
        return False

def feed_watchdog():
    """Feed the hardware watchdog."""
    try:
        with open('/dev/watchdog', 'w') as f:
            f.write('1')
    except Exception as e:
        logging.error(f"Failed to feed watchdog: {e}")

if __name__ == "__main__":
    setup_hardware_watchdog()
