#!/usr/bin/env python3
"""
Health monitoring and memory management for the frequency monitor.
Handles system health checks, memory monitoring, and performance tracking.
"""

import gc
import logging
import threading
import time
import psutil
import os
import csv
import fcntl
import glob
from collections import deque
from pathlib import Path
from typing import Dict, Any, Set, List


class HealthMonitor:
    """Monitors system health and performance with resource tracking."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.memory_threshold = config.get('health.memory_warning_threshold')
        self.cpu_threshold = config.get('health.cpu_warning_threshold')
        self.running = True

        # Resource tracking
        self.tracked_threads: Set[threading.Thread] = set()
        self.tracked_files: Set[str] = set()
        self.resource_lock = threading.Lock()
        self.startup_time = time.time()


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
    

    
    def _restart_application(self):
        """Restart the application by exiting with error code."""
        import sys
        self.logger.critical("Exiting application due to watchdog timeout (systemd will restart)")
        sys.exit(1)
    
    def _reboot_system(self):
        """Reboot the system."""
        import subprocess
        self.logger.critical("Rebooting system due to watchdog timeout")
        try:
            subprocess.run(['sudo', 'reboot'], check=True)
        except Exception as e:
            self.logger.critical(f"Failed to reboot system: {e}")
            self.logger.critical("Exiting process as last resort")
            os._exit(1)
    
    
    def stop(self):
        """Stop health monitoring."""
        self.running = False
    
    def track_thread(self, thread: threading.Thread, name: str = None):
        """Track a thread for resource monitoring."""
        with self.resource_lock:
            if name:
                thread.name = name
            self.tracked_threads.add(thread)
            self.logger.debug(f"Tracking thread: {thread.name}")
    
    def untrack_thread(self, thread: threading.Thread):
        """Stop tracking a thread."""
        with self.resource_lock:
            self.tracked_threads.discard(thread)
            self.logger.debug(f"Untracking thread: {thread.name}")
    
    def track_file(self, filepath: str):
        """Track a file for resource monitoring."""
        with self.resource_lock:
            self.tracked_files.add(filepath)
            self.logger.debug(f"Tracking file: {filepath}")
    
    def untrack_file(self, filepath: str):
        """Stop tracking a file."""
        with self.resource_lock:
            self.tracked_files.discard(filepath)
            self.logger.debug(f"Untracking file: {filepath}")
    
    def get_resource_status(self) -> Dict[str, Any]:
        """Get current resource status."""
        with self.resource_lock:
            # Check thread status
            active_threads = []
            for thread in self.tracked_threads:
                if thread.is_alive():
                    active_threads.append({
                        'name': thread.name,
                        'daemon': thread.daemon,
                        'ident': thread.ident
                    })
            
            # Check file status
            open_files = []
            for filepath in self.tracked_files:
                if os.path.exists(filepath):
                    try:
                        stat = os.stat(filepath)
                        open_files.append({
                            'path': filepath,
                            'size': stat.st_size,
                            'modified': stat.st_mtime
                        })
                    except OSError:
                        open_files.append({'path': filepath, 'status': 'error'})
            
            return {
                'tracked_threads': len(self.tracked_threads),
                'active_threads': len(active_threads),
                'active_thread_details': active_threads,
                'tracked_files': len(self.tracked_files),
                'open_files': open_files,
                'uptime_seconds': time.time() - self.startup_time
            }
    
    def verify_cleanup(self) -> bool:
        """Verify that cleanup was successful."""
        status = self.get_resource_status()
        
        # Check for leaked threads
        leaked_threads = []
        for thread in self.tracked_threads:
            if thread.is_alive():
                leaked_threads.append(thread.name)
        
        if leaked_threads:
            self.logger.critical(f"Resource leak detected: {len(leaked_threads)} threads still active: {leaked_threads}")
            return False
        
        # Check for leaked files (optional - files might be legitimately open)
        self.logger.info(f"Cleanup verification passed: {status['tracked_threads']} threads cleaned up")
        return True


class MemoryMonitor:
    """Monitors memory usage for the process and system."""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.process = psutil.Process()
        
        # Memory thresholds
        self.process_memory_warning = config.get('memory.process_warning_mb')  # MB
        self.process_memory_critical = config.get('memory.process_critical_mb')  # MB
        self.system_memory_warning = config.get('memory.system_warning_percent')  # %
        self.system_memory_critical = config.get('memory.system_critical_percent')  # %
        
        # CSV file size management
        self.memory_log_max_size = config.get('logging.memory_log_max_size')  # 1MB default
        self.csv_backup_count = config.get('logging.csv_backup_count')
        
        # Memory tracking
        self.memory_history = deque(maxlen=1000)  # Keep last 1000 measurements
        self.last_cleanup_time = time.time()
        self.cleanup_interval = config.get('memory.cleanup_interval')  # 1 hour
        
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
    
    def _atomic_write_csv(self, filepath: str, data_rows: list, headers: list = None):
        """Write CSV data atomically with file locking."""
        temp_file = f"{filepath}.tmp"
        
        try:
            # Write to temporary file
            with open(temp_file, 'w', newline='') as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                
                writer = csv.writer(f)
                
                # Write headers if provided
                if headers:
                    writer.writerow(headers)
                
                # Write data rows
                for row in data_rows:
                    writer.writerow(row)
                
                # Flush to disk (let OS handle sync for better SD card life)
                f.flush()
                # os.fsync(f.fileno()) - Removed to reduce SD card wear
            
            # Atomic rename
            os.rename(temp_file, filepath)
            self.logger.debug(f"Atomic write completed: {filepath}")
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_file):
                os.remove(temp_file)
            self.logger.error(f"Atomic write failed for {filepath}: {e}")
            raise
    
    def _rotate_csv_file_if_needed(self, filepath: str, max_size: int) -> None:
        """Rotate CSV file if it exceeds max_size, keeping backup_count files."""
        try:
            if not os.path.exists(filepath):
                return
            
            file_size = os.path.getsize(filepath)
            if file_size < max_size:
                return
            
            self.logger.info(f"CSV file {filepath} size ({file_size} bytes) exceeds limit ({max_size} bytes), rotating...")
            
            # Remove oldest backup files beyond backup_count
            base_name = filepath.replace('.csv', '')
            backup_pattern = f"{base_name}.csv.*"
            backup_files = sorted(glob.glob(backup_pattern), reverse=True)
            
            # Remove excess backup files
            for old_backup in backup_files[self.csv_backup_count - 1:]:
                try:
                    os.remove(old_backup)
                    self.logger.debug(f"Removed old backup file: {old_backup}")
                except OSError as e:
                    self.logger.warning(f"Failed to remove old backup file {old_backup}: {e}")
            
            # Shift existing backup files
            for i in range(min(len(backup_files), self.csv_backup_count - 1), 0, -1):
                old_name = f"{base_name}.csv.{i}"
                new_name = f"{base_name}.csv.{i + 1}"
                if os.path.exists(old_name):
                    try:
                        os.rename(old_name, new_name)
                    except OSError as e:
                        self.logger.warning(f"Failed to rename backup file {old_name} to {new_name}: {e}")
            
            # Move current file to .1
            backup_name = f"{base_name}.csv.1"
            try:
                os.rename(filepath, backup_name)
                self.logger.info(f"Rotated CSV file: {filepath} -> {backup_name}")
            except OSError as e:
                self.logger.error(f"Failed to rotate CSV file {filepath}: {e}")
                
        except Exception as e:
            self.logger.error(f"Error during CSV file rotation for {filepath}: {e}")
    
    def log_memory_to_csv(self, csv_file: str) -> None:
        """Log memory information to CSV file using atomic writes."""
        try:
            # Check if file rotation is needed before writing
            self._rotate_csv_file_if_needed(csv_file, self.memory_log_max_size)
            
            memory_info = self.get_memory_info()
            if not memory_info:
                return
            
            # Check if file exists to determine if we need headers
            file_exists = os.path.exists(csv_file)
            
            # Prepare data row
            data_row = [
                memory_info['timestamp'],
                time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(memory_info['timestamp'])),
                memory_info['process_memory_mb'],
                memory_info['process_memory_percent'],
                memory_info['system_memory_percent'],
                memory_info['system_available_gb'],
                memory_info['gc_objects'],
                memory_info['gc_collections'],
                memory_info['process_status']
            ]
            
            # Prepare headers if file doesn't exist
            headers = None
            if not file_exists:
                headers = [
                    'timestamp', 'datetime', 'process_memory_mb', 'process_memory_percent',
                    'system_memory_percent', 'system_available_gb', 'gc_objects',
                    'gc_collections', 'process_status'
                ]
            
            # Use atomic write
            self._atomic_write_csv(csv_file, [data_row], headers)
                
        except Exception as e:
            self.logger.error(f"Failed to log memory to CSV: {e}")
