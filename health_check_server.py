#!/usr/bin/env python3
"""
Simple Flask server to receive and save health check reports.
This is a separate project file - deploy on another server.
"""

from flask import Flask, request, jsonify
import json
import os
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

# Configuration
DATA_DIR = "health_check_data"  # Directory to save health check data
os.makedirs(DATA_DIR, exist_ok=True)


@app.route('/api/health', methods=['GET'])
def receive_health_check():
    """
    Receive health check GET request and save to disk.
    
    Query parameters:
    - timestamp: Unix timestamp
    - uptime_seconds: System uptime
    - frequency: Current frequency (optional)
    - power_source: Power source classification (optional)
    - current_state: Current power state (optional)
    - memory_mb: Process memory in MB (optional)
    - memory_percent: Process memory percent (optional)
    - system_memory_percent: System memory percent (optional)
    - sample_count: Number of samples collected (optional)
    """
    try:
        # Get all query parameters
        data = dict(request.args)
        
        # Add server-side timestamp
        data['server_timestamp'] = datetime.now().isoformat()
        data['server_received_at'] = datetime.now().timestamp()
        
        # Create filename with timestamp
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"health_check_{timestamp_str}.json"
        filepath = os.path.join(DATA_DIR, filename)
        
        # Save to JSON file
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Also append to a daily log file for easier analysis
        date_str = datetime.now().strftime("%Y-%m-%d")
        daily_log_file = os.path.join(DATA_DIR, f"health_checks_{date_str}.jsonl")
        with open(daily_log_file, 'a') as f:
            f.write(json.dumps(data) + '\n')
        
        return jsonify({
            'status': 'success',
            'message': 'Health check received and saved',
            'file': filename
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/health/status', methods=['GET'])
def health_status():
    """Simple status endpoint to check if server is running."""
    return jsonify({
        'status': 'ok',
        'service': 'health_check_server',
        'data_dir': DATA_DIR
    }), 200


if __name__ == '__main__':
    # Run on all interfaces, port 5000
    # In production, use a proper WSGI server like gunicorn
    app.run(host='0.0.0.0', port=5000, debug=False)
