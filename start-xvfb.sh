#!/bin/bash
# Wrapper script to start Xvfb in the background for systemd

# Check if Xvfb is already running on display :99
if pgrep -f "Xvfb :99" > /dev/null; then
    echo "Xvfb is already running on display :99"
    exit 0
fi

# Start Xvfb in the background
/usr/bin/Xvfb :99 -screen 0 1366x768x24 -ac +extension GLX +render -noreset > /dev/null 2>&1 &

# Wait a moment to ensure it started
sleep 1

# Verify it's running
if pgrep -f "Xvfb :99" > /dev/null; then
    echo "Xvfb started successfully on display :99"
    exit 0
else
    echo "Failed to start Xvfb" >&2
    exit 1
fi
