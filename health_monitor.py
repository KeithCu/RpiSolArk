#!/usr/bin/env python3
"""
Health monitoring and alerting system
"""

import time
import logging
import psutil
import smtplib
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime, timedelta

class HealthMonitor:
    """Monitor system health and send alerts."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.last_alert_time = {}
        self.alert_cooldown = 3600  # 1 hour between alerts
        
    def check_disk_space(self):
        """Check available disk space."""
        disk_usage = psutil.disk_usage('/')
        free_percent = (disk_usage.free / disk_usage.total) * 100
        
        if free_percent < 10:
            self.send_alert("CRITICAL", f"Disk space critically low: {free_percent:.1f}% free")
        elif free_percent < 20:
            self.send_alert("WARNING", f"Disk space low: {free_percent:.1f}% free")
            
    def check_memory_usage(self):
        """Check memory usage."""
        memory = psutil.virtual_memory()
        
        if memory.percent > 90:
            self.send_alert("CRITICAL", f"Memory usage critical: {memory.percent:.1f}%")
        elif memory.percent > 80:
            self.send_alert("WARNING", f"Memory usage high: {memory.percent:.1f}%")
            
    def check_cpu_temperature(self):
        """Check CPU temperature."""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp = int(f.read()) / 1000.0
                
            if temp > 80:
                self.send_alert("CRITICAL", f"CPU temperature critical: {temp:.1f}°C")
            elif temp > 70:
                self.send_alert("WARNING", f"CPU temperature high: {temp:.1f}°C")
        except Exception as e:
            self.logger.error(f"Failed to read CPU temperature: {e}")
            
    def check_log_file_size(self):
        """Check if log files are getting too large."""
        log_dir = Path("logs")
        if log_dir.exists():
            for log_file in log_dir.glob("*.log"):
                if log_file.stat().st_size > 100 * 1024 * 1024:  # 100MB
                    self.send_alert("WARNING", f"Log file {log_file.name} is large: {log_file.stat().st_size / 1024 / 1024:.1f}MB")
                    
    def check_process_health(self):
        """Check if the monitor process is running."""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'monitor.py' in ' '.join(proc.info['cmdline']):
                    # Process is running
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
        self.send_alert("CRITICAL", "Frequency monitor process not found!")
        return False
        
    def send_alert(self, level: str, message: str):
        """Send alert if not in cooldown period."""
        alert_key = f"{level}_{message}"
        current_time = time.time()
        
        if alert_key in self.last_alert_time:
            if current_time - self.last_alert_time[alert_key] < self.alert_cooldown:
                return  # Still in cooldown
                
        self.last_alert_time[alert_key] = current_time
        
        # Log the alert
        self.logger.warning(f"ALERT [{level}]: {message}")
        
        # Send email if configured
        self.send_email_alert(level, message)
        
    def send_email_alert(self, level: str, message: str):
        """Send email alert."""
        email_config = self.config.get('alerts.email', {})
        if not email_config.get('enabled', False):
            return
            
        try:
            msg = MIMEText(f"Frequency Monitor Alert\n\nLevel: {level}\nMessage: {message}\nTime: {datetime.now()}")
            msg['Subject'] = f"Frequency Monitor {level}: {message[:50]}"
            msg['From'] = email_config['from']
            msg['To'] = email_config['to']
            
            with smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port']) as server:
                server.starttls()
                server.login(email_config['username'], email_config['password'])
                server.send_message(msg)
                
            self.logger.info(f"Email alert sent: {level}")
        except Exception as e:
            self.logger.error(f"Failed to send email alert: {e}")
            
    def run_health_check(self):
        """Run all health checks."""
        self.check_disk_space()
        self.check_memory_usage()
        self.check_cpu_temperature()
        self.check_log_file_size()
        self.check_process_health()
