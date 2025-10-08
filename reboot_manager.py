#!/usr/bin/env python3
"""
Manual reboot management and monitoring
"""

import argparse
import subprocess
import time
import logging
from datetime import datetime
from pathlib import Path

def check_service_status():
    """Check status of all frequency monitor services."""
    services = ['frequency-monitor', 'frequency-reboot', 'frequency-health']
    
    print("🔍 Service Status:")
    print("-" * 50)
    
    for service in services:
        try:
            result = subprocess.run(['systemctl', 'is-active', service], 
                                  capture_output=True, text=True)
            status = result.stdout.strip()
            print(f"{service:20} : {status}")
        except Exception as e:
            print(f"{service:20} : ERROR - {e}")
            
def check_system_health():
    """Check current system health."""
    import psutil
    
    print("\n🏥 System Health:")
    print("-" * 50)
    
    # Memory
    memory = psutil.virtual_memory()
    print(f"Memory Usage    : {memory.percent:.1f}%")
    
    # Disk
    disk = psutil.disk_usage('/')
    free_percent = (disk.free / disk.total) * 100
    print(f"Disk Free       : {free_percent:.1f}%")
    
    # CPU Temperature
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp = int(f.read()) / 1000.0
        print(f"CPU Temperature : {temp:.1f}°C")
    except:
        print("CPU Temperature : N/A")
    
    # Uptime
    uptime_seconds = time.time() - psutil.boot_time()
    uptime_days = uptime_seconds / (24 * 3600)
    print(f"System Uptime   : {uptime_days:.1f} days")
    
def schedule_reboot(hours=1):
    """Schedule a reboot in specified hours."""
    reboot_time = datetime.now().timestamp() + (hours * 3600)
    reboot_datetime = datetime.fromtimestamp(reboot_time)
    
    print(f"⏰ Scheduling reboot for {reboot_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Create a simple reboot script
    reboot_script = f"""#!/bin/bash
sleep {hours * 3600}
sudo reboot
"""
    
    with open('/tmp/scheduled_reboot.sh', 'w') as f:
        f.write(reboot_script)
    
    subprocess.run(['chmod', '+x', '/tmp/scheduled_reboot.sh'])
    subprocess.Popen(['nohup', '/tmp/scheduled_reboot.sh'], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL)
    
    print("✅ Reboot scheduled successfully")

def immediate_reboot():
    """Perform immediate reboot."""
    print("🚨 Performing immediate reboot in 10 seconds...")
    print("Press Ctrl+C to cancel")
    
    for i in range(10, 0, -1):
        print(f"Rebooting in {i} seconds...", end='\r')
        time.sleep(1)
    
    print("\n🔄 Rebooting now...")
    subprocess.run(['sudo', 'reboot'])

def cancel_scheduled_reboot():
    """Cancel any scheduled reboot."""
    print("❌ Cancelling scheduled reboot...")
    
    # Kill any scheduled reboot processes
    try:
        subprocess.run(['pkill', '-f', 'scheduled_reboot.sh'], check=False)
        subprocess.run(['rm', '-f', '/tmp/scheduled_reboot.sh'], check=False)
        print("✅ Scheduled reboot cancelled")
    except Exception as e:
        print(f"❌ Error cancelling reboot: {e}")

def show_logs(service='frequency-monitor', lines=50):
    """Show recent logs for a service."""
    print(f"📋 Recent logs for {service}:")
    print("-" * 50)
    
    try:
        subprocess.run(['journalctl', '-u', service, '-n', str(lines), '--no-pager'])
    except Exception as e:
        print(f"Error showing logs: {e}")

def main():
    parser = argparse.ArgumentParser(description='Frequency Monitor Reboot Manager')
    parser.add_argument('action', choices=['status', 'health', 'reboot', 'schedule', 'cancel', 'logs'],
                       help='Action to perform')
    parser.add_argument('--hours', type=int, default=1,
                       help='Hours until reboot (for schedule action)')
    parser.add_argument('--service', default='frequency-monitor',
                       help='Service name for logs action')
    parser.add_argument('--lines', type=int, default=50,
                       help='Number of log lines to show')
    
    args = parser.parse_args()
    
    if args.action == 'status':
        check_service_status()
    elif args.action == 'health':
        check_system_health()
    elif args.action == 'reboot':
        immediate_reboot()
    elif args.action == 'schedule':
        schedule_reboot(args.hours)
    elif args.action == 'cancel':
        cancel_scheduled_reboot()
    elif args.action == 'logs':
        show_logs(args.service, args.lines)

if __name__ == "__main__":
    main()
