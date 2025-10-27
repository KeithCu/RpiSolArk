#!/usr/bin/env python3
"""
Smart scheduled reboot system for frequency monitor
"""

import time
import logging
import subprocess
import signal
import os
from datetime import datetime, timedelta
from pathlib import Path

class ScheduledReboot:
    """Handle scheduled reboots with smart timing."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.reboot_interval_days = config.get('reboot.interval_days')
        self.reboot_hour = config.get('reboot.hour')  # 3 AM
        self.reboot_minute = config.get('reboot.minute')
        self.last_reboot_file = Path("last_reboot.txt")
        self.graceful_shutdown_timeout = 30  # seconds
        
    def should_reboot(self) -> bool:
        """Check if it's time for a scheduled reboot."""
        if not self.last_reboot_file.exists():
            # First run - record current time
            self.record_reboot_time()
            return False
            
        try:
            with open(self.last_reboot_file, 'r') as f:
                last_reboot_str = f.read().strip()
                last_reboot = datetime.fromisoformat(last_reboot_str)
                
            days_since_reboot = (datetime.now() - last_reboot).days
            return days_since_reboot >= self.reboot_interval_days
            
        except Exception as e:
            self.logger.error(f"Error checking reboot schedule: {e}")
            return False
            
    def is_reboot_time(self) -> bool:
        """Check if current time matches reboot schedule."""
        now = datetime.now()
        return (now.hour == self.reboot_hour and 
                now.minute == self.reboot_minute and
                now.second < 10)  # 10-second window
            
    def record_reboot_time(self):
        """Record the current time as last reboot."""
        try:
            with open(self.last_reboot_file, 'w') as f:
                f.write(datetime.now().isoformat())
            self.logger.info("Recorded reboot time")
        except Exception as e:
            self.logger.error(f"Failed to record reboot time: {e}")
            
    def graceful_shutdown_monitor(self):
        """Gracefully shutdown the frequency monitor."""
        self.logger.info("Initiating graceful shutdown of frequency monitor...")
        
        try:
            # Find monitor process
            for proc in self.get_monitor_processes():
                self.logger.info(f"Sending SIGTERM to monitor process {proc.pid}")
                proc.send_signal(signal.SIGTERM)
                
            # Wait for graceful shutdown
            time.sleep(self.graceful_shutdown_timeout)
            
            # Force kill if still running
            for proc in self.get_monitor_processes():
                self.logger.warning(f"Force killing monitor process {proc.pid}")
                proc.kill()
                
        except Exception as e:
            self.logger.error(f"Error during graceful shutdown: {e}")
            
    def get_monitor_processes(self):
        """Get all frequency monitor processes."""
        import psutil
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'monitor.py' in ' '.join(proc.info['cmdline']):
                    processes.append(proc)
            except:
                continue
        return processes
        
    def perform_reboot(self):
        """Perform the actual reboot."""
        self.logger.info("Performing scheduled reboot...")
        
        # Graceful shutdown
        self.graceful_shutdown_monitor()
        
        # Record reboot time
        self.record_reboot_time()
        
        # Log reboot reason
        self.logger.info(f"Scheduled reboot after {self.reboot_interval_days} days")
        
        # Reboot system
        try:
            subprocess.run(['sudo', 'reboot'], check=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to reboot system: {e}")
            
    def run_reboot_scheduler(self):
        """Main reboot scheduler loop."""
        self.logger.info(f"Reboot scheduler started - interval: {self.reboot_interval_days} days at {self.reboot_hour:02d}:{self.reboot_minute:02d}")
        
        while True:
            try:
                if self.should_reboot() and self.is_reboot_time():
                    self.perform_reboot()
                    
                time.sleep(10)  # Check every 10 seconds
                
            except KeyboardInterrupt:
                self.logger.info("Reboot scheduler stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Error in reboot scheduler: {e}")
                time.sleep(60)  # Wait longer on error

if __name__ == "__main__":
    from monitor import Config
    config = Config()
    scheduler = ScheduledReboot(config)
    scheduler.run_reboot_scheduler()
