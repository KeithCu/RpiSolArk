#!/usr/bin/env python3
"""
Simple web dashboard for monitoring status
"""

from flask import Flask, render_template, jsonify
import json
import psutil
import time
from pathlib import Path
from datetime import datetime

app = Flask(__name__)

def get_system_status():
    """Get current system status."""
    return {
        'timestamp': datetime.now().isoformat(),
        'cpu_percent': psutil.cpu_percent(),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_percent': psutil.disk_usage('/').percent,
        'uptime': time.time() - psutil.boot_time(),
        'temperature': get_cpu_temperature()
    }

def get_cpu_temperature():
    """Get CPU temperature."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return int(f.read()) / 1000.0
    except:
        return None

def get_monitor_status():
    """Get monitor process status."""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        try:
            if 'monitor.py' in ' '.join(proc.info['cmdline']):
                return {
                    'running': True,
                    'pid': proc.info['pid'],
                    'uptime': time.time() - proc.info['create_time']
                }
        except:
            continue
    return {'running': False}

def get_latest_logs():
    """Get latest log entries."""
    log_file = Path("logs/monitor.log")
    if not log_file.exists():
        return []
    
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
            return lines[-20:]  # Last 20 lines
    except:
        return []

@app.route('/')
def dashboard():
    """Main dashboard page."""
    return render_template('dashboard.html')

@app.route('/api/status')
def api_status():
    """API endpoint for system status."""
    return jsonify({
        'system': get_system_status(),
        'monitor': get_monitor_status(),
        'logs': get_latest_logs()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
