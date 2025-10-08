#!/usr/bin/env python3
"""
Advanced system health monitoring with automatic recovery
"""

import time
import logging
import subprocess
import psutil
from datetime import datetime, timedelta
from pathlib import Path

class SystemHealthMonitor:
    """Monitor system health and trigger reboots when needed."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.health_log = Path("logs/health.log")
        self.health_log.parent.mkdir(exist_ok=True)
        
        # Health thresholds
        self.memory_threshold = config.get('health.memory_critical', 95)
        self.disk_threshold = config.get('health.disk_critical', 5)
        self.temp_threshold = config.get('health.temp_critical', 85)
        self.uptime_max_days = config.get('health.max_uptime_days', 45)
        
        # Recovery actions
        self.auto_reboot_on_critical = config.get('health.auto_reboot', True)
        self.cleanup_before_reboot = config.get('health.cleanup_before_reboot', True)
        
    def log_health_status(self, status):
        """Log health status to file."""
        timestamp = datetime.now().isoformat()
        with open(self.health_log, 'a') as f:
            f.write(f"{timestamp} - {status}\n")
            
    def check_memory_health(self):
        """Check memory usage and fragmentation."""
        memory = psutil.virtual_memory()
        
        if memory.percent > self.memory_threshold:
            self.log_health_status(f"CRITICAL: Memory usage {memory.percent:.1f}%")
            return False
            
        # Check for memory fragmentation (Linux specific)
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
                # Look for high fragmentation indicators
                if 'MemAvailable' in meminfo:
                    # Parse available memory
                    for line in meminfo.split('\n'):
                        if line.startswith('MemAvailable:'):
                            available_kb = int(line.split()[1])
                            available_gb = available_kb / 1024 / 1024
                            if available_gb < 0.5:  # Less than 500MB available
                                self.log_health_status(f"WARNING: Low available memory {available_gb:.1f}GB")
                                return False
        except:
            pass
            
        return True
        
    def check_disk_health(self):
        """Check disk usage and health."""
        disk = psutil.disk_usage('/')
        free_percent = (disk.free / disk.total) * 100
        
        if free_percent < self.disk_threshold:
            self.log_health_status(f"CRITICAL: Disk space {free_percent:.1f}% free")
            return False
            
        # Check for disk errors (if accessible)
        try:
            result = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=5)
            if 'I/O error' in result.stdout or 'disk error' in result.stdout.lower():
                self.log_health_status("WARNING: Disk I/O errors detected")
                return False
        except:
            pass
            
        return True
        
    def check_temperature_health(self):
        """Check CPU and system temperature."""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp = int(f.read()) / 1000.0
                
            if temp > self.temp_threshold:
                self.log_health_status(f"CRITICAL: CPU temperature {temp:.1f}°C")
                return False
                
            # Check for thermal throttling
            with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq', 'r') as f:
                current_freq = int(f.read())
            with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq', 'r') as f:
                max_freq = int(f.read())
                
            if current_freq < max_freq * 0.8:  # Running at less than 80% max frequency
                self.log_health_status(f"WARNING: CPU throttling detected - {current_freq/1000:.0f}MHz vs {max_freq/1000:.0f}MHz max")
                
        except Exception as e:
            self.logger.error(f"Error checking temperature: {e}")
            
        return True
        
    def check_uptime_health(self):
        """Check system uptime."""
        uptime_seconds = time.time() - psutil.boot_time()
        uptime_days = uptime_seconds / (24 * 3600)
        
        if uptime_days > self.uptime_max_days:
            self.log_health_status(f"INFO: System uptime {uptime_days:.1f} days - scheduled for reboot")
            return False
            
        return True
        
    def check_process_health(self):
        """Check for zombie processes and memory leaks."""
        zombie_count = 0
        total_processes = 0
        
        for proc in psutil.process_iter(['status']):
            total_processes += 1
            try:
                if proc.info['status'] == psutil.STATUS_ZOMBIE:
                    zombie_count += 1
            except:
                continue
                
        if zombie_count > 10:  # More than 10 zombie processes
            self.log_health_status(f"WARNING: {zombie_count} zombie processes detected")
            return False
            
        return True
        
    def cleanup_system(self):
        """Perform system cleanup before reboot."""
        self.logger.info("Performing system cleanup...")
        
        try:
            # Clear temporary files
            subprocess.run(['sudo', 'apt', 'autoclean'], timeout=30)
            subprocess.run(['sudo', 'apt', 'autoremove', '-y'], timeout=60)
            
            # Clear log files older than 30 days
            subprocess.run(['sudo', 'find', '/var/log', '-name', '*.log', '-mtime', '+30', '-delete'], timeout=30)
            
            # Clear systemd journal
            subprocess.run(['sudo', 'journalctl', '--vacuum-time=30d'], timeout=30)
            
            # Sync filesystem
            subprocess.run(['sync'], timeout=10)
            
            self.log_health_status("System cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            
    def trigger_health_reboot(self, reason):
        """Trigger reboot due to health issues."""
        self.log_health_status(f"HEALTH REBOOT: {reason}")
        
        if self.cleanup_before_reboot:
            self.cleanup_system()
            
        if self.auto_reboot_on_critical:
            self.logger.critical(f"Triggering health reboot: {reason}")
            subprocess.run(['sudo', 'reboot'], check=True)
        else:
            self.logger.critical(f"Health reboot needed but auto-reboot disabled: {reason}")
            
    def run_health_monitor(self):
        """Main health monitoring loop."""
        self.logger.info("System health monitor started")
        
        while True:
            try:
                health_checks = [
                    ("Memory", self.check_memory_health),
                    ("Disk", self.check_disk_health),
                    ("Temperature", self.check_temperature_health),
                    ("Uptime", self.check_uptime_health),
                    ("Processes", self.check_process_health)
                ]
                
                for check_name, check_func in health_checks:
                    if not check_func():
                        self.trigger_health_reboot(f"{check_name} health check failed")
                        return
                        
                time.sleep(300)  # Check every 5 minutes
                
            except KeyboardInterrupt:
                self.logger.info("Health monitor stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Error in health monitor: {e}")
                time.sleep(60)

if __name__ == "__main__":
    from monitor import Config
    config = Config()
    health_monitor = SystemHealthMonitor(config)
    health_monitor.run_health_monitor()
