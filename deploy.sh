#!/bin/bash
# Production deployment script for frequency monitor

set -e  # Exit on any error

echo "🚀 Deploying Frequency Monitor to Production..."

# Update system
echo "📦 Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install required packages
echo "📦 Installing required packages..."
sudo apt install -y python3-pip python3-venv watchdog

# Create virtual environment
echo "🐍 Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Setup hardware watchdog
echo "🐕 Setting up hardware watchdog..."
sudo modprobe bcm2835_wdt
sudo systemctl enable watchdog
sudo systemctl start watchdog

# Create systemd service
echo "⚙️ Creating systemd service..."
sudo tee /etc/systemd/system/frequency-monitor.service > /dev/null <<EOF
[Unit]
Description=Raspberry Pi Frequency Monitor
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python $(pwd)/production_monitor.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create log directory
echo "📁 Creating log directory..."
mkdir -p logs

# Set permissions
echo "🔐 Setting permissions..."
chmod +x production_monitor.py
chmod +x monitor.py
chmod 644 config.yaml

# Create reboot scheduler service
echo "⏰ Creating reboot scheduler service..."
sudo tee /etc/systemd/system/frequency-reboot.service > /dev/null <<EOF
[Unit]
Description=Frequency Monitor Reboot Scheduler
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python $(pwd)/scheduled_reboot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create health monitor service
echo "🏥 Creating health monitor service..."
sudo tee /etc/systemd/system/frequency-health.service > /dev/null <<EOF
[Unit]
Description=Frequency Monitor Health Monitor
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python $(pwd)/system_health.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable and start services
echo "🚀 Starting services..."
sudo systemctl daemon-reload
sudo systemctl enable frequency-monitor
sudo systemctl enable frequency-reboot
sudo systemctl enable frequency-health
sudo systemctl start frequency-monitor
sudo systemctl start frequency-reboot
sudo systemctl start frequency-health

# Check status
echo "✅ Checking service status..."
sudo systemctl status frequency-monitor --no-pager
sudo systemctl status frequency-reboot --no-pager
sudo systemctl status frequency-health --no-pager

echo "🎉 Deployment complete!"
echo "📊 Monitor logs: sudo journalctl -u frequency-monitor -f"
echo "⏰ Reboot logs: sudo journalctl -u frequency-reboot -f"
echo "🏥 Health logs: sudo journalctl -u frequency-health -f"
echo "🔄 Restart service: sudo systemctl restart frequency-monitor"
echo "⏹️ Stop service: sudo systemctl stop frequency-monitor"
