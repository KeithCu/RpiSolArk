#!/bin/bash
# Simple auto-update script - NO CUSTOM CODE NEEDED!

set -e

cd /home/pi/RpiSolArk

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "Not a git repository - skipping update"
    exit 0
fi

# Fetch latest changes
git fetch origin

# Check if there are updates
if git diff --quiet HEAD origin/release; then
    echo "No updates available"
    exit 0
fi

echo "Updates available - applying..."

# Create backup
BACKUP_DIR="/tmp/backup_$(date +%Y%m%d_%H%M%S)"
cp -r . "$BACKUP_DIR"

# Pull updates
git pull origin release

# Install dependencies if requirements.txt changed
if git diff --name-only HEAD~1 HEAD | grep -q requirements.txt; then
    echo "Requirements changed - installing dependencies..."
    pip install -r requirements.txt
fi

# Restart service if it's running
if systemctl is-active --quiet frequency-monitor; then
    echo "Restarting frequency-monitor service..."
    systemctl restart frequency-monitor
fi

echo "Update completed successfully"
