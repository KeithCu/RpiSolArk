#!/usr/bin/env python3
"""
Simple Restart Manager - handles restart button functionality only.
Auto-updates are handled by system-level services (see setup_zero_code_updates.sh).
"""

import os
import sys
import time
import logging
import subprocess
from pathlib import Path


class RestartManager:
    """
    Simple restart manager for hardware button functionality.
    Auto-updates are handled by system-level services.
    """
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Restart safety settings
        self.restart_cooldown = config.get('restart.cooldown_seconds')  # seconds
        self.max_restarts_per_hour = config.get('restart.max_per_hour')
        self.restart_count_current_hour = 0
        self.last_restart_timestamp = 0
        self.hourly_reset_timestamp = time.time()
        
        self.logger.info("RestartManager initialized (restart button only)")
    
    def _reset_hourly_count(self):
        """Resets the hourly restart count if an hour has passed."""
        if time.time() - self.hourly_reset_timestamp > 3600:  # 1 hour
            self.restart_count_current_hour = 0
            self.hourly_reset_timestamp = time.time()
    
    def _can_restart(self) -> bool:
        """Checks if a restart is allowed based on cooldown and hourly limits."""
        self._reset_hourly_count()
        
        if time.time() - self.last_restart_timestamp < self.restart_cooldown:
            self.logger.warning(f"Restart cooldown active. Next restart allowed in {self.restart_cooldown - (time.time() - self.last_restart_timestamp):.1f}s")
            return False
        
        if self.restart_count_current_hour >= self.max_restarts_per_hour:
            self.logger.critical(f"Exceeded maximum restarts ({self.max_restarts_per_hour}) in the last hour. Manual intervention required.")
            return False
        
        return True
    
    def handle_restart_button(self) -> bool:
        """
        Handle restart button press with safety checks.
        Returns True if restart was initiated, False if blocked.
        """
        if not self._can_restart():
            self.logger.warning("Restart blocked by safety checks")
            return False
        
        self.logger.info("Initiating application restart...")
        self.restart_count_current_hour += 1
        self.last_restart_timestamp = time.time()
        
        # Attempt to gracefully restart the application
        try:
            self.logger.info(f"Restarting process: {sys.executable} {' '.join(sys.argv)}")
            os.execv(sys.executable, ['python'] + sys.argv)
        except Exception as e:
            self.logger.critical(f"Failed to restart application using os.execv: {e}")
            # Fallback: if execv fails, try a system reboot (more drastic)
            try:
                self.logger.critical("Attempting system reboot as fallback for application restart.")
                subprocess.run(['sudo', 'reboot'], check=True)
            except Exception as reboot_e:
                self.logger.critical(f"Failed to trigger system reboot: {reboot_e}. System may be in an unrecoverable state.")
                sys.exit(1)  # Exit if even reboot fails
        
        return True
    
    def start_update_monitor(self):
        """
        Placeholder method for compatibility.
        Auto-updates are handled by system-level services.
        """
        self.logger.info("Auto-updates are handled by system-level services (systemd, cron, etc.)")
        self.logger.info("See setup_zero_code_updates.sh for auto-update setup")
    
    def get_status(self) -> dict:
        """Get current restart status."""
        return {
            'restart_count_current_hour': self.restart_count_current_hour,
            'max_restarts_per_hour': self.max_restarts_per_hour,
            'last_restart_timestamp': self.last_restart_timestamp,
            'restart_cooldown': self.restart_cooldown,
            'can_restart': self._can_restart()
        }
