#!/usr/bin/env python3
"""
Health monitoring and memory management for the frequency monitor.
Handles system health checks, memory monitoring, and performance tracking.
"""

import gc
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Dict, Any

import psutil


class HealthMonitor:
    """Monitors system health and performance."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.watchdog_timeout = config.get('health.watchdog_timeout', 30.0)
        self.memory_threshold = config.get('health.memory_warning_threshold', 0.8)
        self.cpu_threshold = config.get('health.cpu_warning_threshold', 0.8)
        self.last_activity = time.time()
        self.running = True
        self._start_monitoring()
    
    def _start_monitoring(self):
        """Start health monitoring thread."""
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.logger.info("Health monitoring started")
    
    def _monitor_loop(self):
        """Main health monitoring loop."""
        while self.running:
            try:
                self._check_system_health()
                self._check_watchdog()
                time.sleep(10)  # Check every 10 seconds
            except Exception as e:
                self.logger.error(f"Health monitoring error: {e}")
    
    def _check_system_health(self):
        """Check system resource usage."""
        try:
            # Memory usage
            memory = psutil.virtual_memory()
            if memory.percent > self.memory_threshold * 100:
                self.logger.warning(f"High memory usage: {memory.percent:.1f}%")
            
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.cpu_threshold * 100:
                self.logger.warning(f"High CPU usage: {cpu_percent:.1f}%")
            
        except Exception as e:
            self.logger.error(f"System health check error: {e}")
    
    def _check_watchdog(self):
        """Check if system is responsive."""
        if time.time() - self.last_activity > self.watchdog_timeout:
            self.logger.error("Watchdog timeout - system appears unresponsive")
            # Could implement restart logic here
    
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = time.time()
    
    def stop(self):
        """Stop health monitoring."""
        self.running = False


class MemoryMonitor:
    """Monitors memory usage for the process and system."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.process = psutil.Process()
        
        # Memory thresholds
        self.process_memory_warning = config.get('memory.process_warning_mb', 500)  # MB
        self.process_memory_critical = config.get('memory.process_critical_mb', 1000)  # MB
        self.system_memory_warning = config.get('memory.system_warning_percent', 80)  # %
        self.system_memory_critical = config.get('memory.system_critical_percent', 90)  # %
        
        # Memory tracking
        self.memory_history = deque(maxlen=1000)  # Keep last 1000 measurements
        self.last_cleanup_time = time.time()
        self.cleanup_interval = config.get('memory.cleanup_interval', 3600)  # 1 hour
        
        self.logger.info("Memory monitor initialized")
    
    def get_memory_info(self) -> Dict[str, Any]:
        """Get current memory information."""
        try:
            # Process memory
            process_memory = self.process.memory_info()
            process_mb = process_memory.rss / 1024 / 1024  # Convert to MB
            
            # System memory
            system_memory = psutil.virtual_memory()
            system_percent = system_memory.percent
            system_available_gb = system_memory.available / 1024 / 1024 / 1024
            
            # Python garbage collection info
            gc_stats = gc.get_stats()
            gc_objects = len(gc.get_objects())
            
            memory_info = {
                'timestamp': time.time(),
                'process_memory_mb': round(process_mb, 2),
                'process_memory_percent': round((process_mb / (system_memory.total / 1024 / 1024)) * 100, 2),
                'system_memory_percent': round(system_percent, 2),
                'system_available_gb': round(system_available_gb, 2),
                'gc_objects': gc_objects,
                'gc_collections': sum(stat['collections'] for stat in gc_stats),
                'process_status': self._get_process_status(process_mb, system_percent)
            }
            
            # Add to history
            self.memory_history.append(memory_info)
            
            return memory_info
            
        except Exception as e:
            self.logger.error(f"Failed to get memory info: {e}")
            return {}
    
    def _get_process_status(self, process_mb: float, system_percent: float) -> str:
        """Determine process memory status."""
        if process_mb >= self.process_memory_critical or system_percent >= self.system_memory_critical:
            return 'critical'
        elif process_mb >= self.process_memory_warning or system_percent >= self.system_memory_warning:
            return 'warning'
        else:
            return 'normal'
    
    def check_memory_thresholds(self, memory_info: Dict[str, Any]) -> None:
        """Check memory thresholds and log warnings."""
        if not memory_info:
            return
        
        process_mb = memory_info['process_memory_mb']
        system_percent = memory_info['system_memory_percent']
        status = memory_info['process_status']
        
        if status == 'critical':
            self.logger.critical(
                f"CRITICAL memory usage - Process: {process_mb:.1f}MB, "
                f"System: {system_percent:.1f}%"
            )
        elif status == 'warning':
            self.logger.warning(
                f"High memory usage - Process: {process_mb:.1f}MB, "
                f"System: {system_percent:.1f}%"
            )
    
    def perform_cleanup(self) -> bool:
        """Perform memory cleanup if needed."""
        current_time = time.time()
        
        # Only cleanup if interval has passed
        if current_time - self.last_cleanup_time < self.cleanup_interval:
            return False
        
        try:
            # Force garbage collection
            collected = gc.collect()
            
            # Get memory after cleanup
            memory_after = self.get_memory_info()
            process_mb_after = memory_after.get('process_memory_mb', 0)
            
            self.logger.info(
                f"Memory cleanup performed - Collected {collected} objects, "
                f"Process memory: {process_mb_after:.1f}MB"
            )
            
            self.last_cleanup_time = current_time
            return True
            
        except Exception as e:
            self.logger.error(f"Memory cleanup failed: {e}")
            return False
    
    def get_memory_summary(self) -> str:
        """Get a summary string of current memory usage."""
        memory_info = self.get_memory_info()
        if not memory_info:
            return "Memory info unavailable"
        
        return (
            f"Process: {memory_info['process_memory_mb']:.1f}MB "
            f"({memory_info['process_memory_percent']:.1f}%), "
            f"System: {memory_info['system_memory_percent']:.1f}%, "
            f"Available: {memory_info['system_available_gb']:.1f}GB, "
            f"GC Objects: {memory_info['gc_objects']}"
        )
    
    def log_memory_to_csv(self, csv_file: str) -> None:
        """Log memory information to CSV file."""
        try:
            import csv
            
            memory_info = self.get_memory_info()
            if not memory_info:
                return
            
            # Check if file exists to determine if we need headers
            file_exists = Path(csv_file).exists()
            
            with open(csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                
                # Write headers if file is new
                if not file_exists:
                    writer.writerow([
                        'timestamp', 'datetime', 'process_memory_mb', 'process_memory_percent',
                        'system_memory_percent', 'system_available_gb', 'gc_objects',
                        'gc_collections', 'process_status'
                    ])
                
                # Write data
                writer.writerow([
                    memory_info['timestamp'],
                    time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(memory_info['timestamp'])),
                    memory_info['process_memory_mb'],
                    memory_info['process_memory_percent'],
                    memory_info['system_memory_percent'],
                    memory_info['system_available_gb'],
                    memory_info['gc_objects'],
                    memory_info['gc_collections'],
                    memory_info['process_status']
                ])
                
        except Exception as e:
            self.logger.error(f"Failed to log memory to CSV: {e}")
