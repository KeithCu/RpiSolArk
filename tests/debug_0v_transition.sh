#!/usr/bin/env bash
# Debug script to capture 0V to Generator misclassification issue
# Runs monitor.py with full debug logging for 30 seconds
# Captures all output to a timestamped log file

set -euo pipefail

# Resolve directory of this script
SCRIPT_PATH="$(readlink -f "$0")"
APP_DIR="$(dirname "$SCRIPT_PATH")"
cd "$APP_DIR"

# Generate timestamped log file name
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="debug_0v_transition_${TIMESTAMP}.log"

echo "========================================="
echo "Debug 0V Transition Test"
echo "========================================="
echo "Log file: $LOG_FILE"
echo "Duration: 90 seconds"
echo "Test sequence:"
echo "  - 10 seconds: Grid power (baseline)"
echo "  - 5 seconds: Unplug (0V state)"
echo "  - Remainder: Plug back in (should detect utility)"
echo "Starting in 3 seconds..."
echo "========================================="
sleep 3

# Prefer local virtualenv if it exists
PYTHON_BIN=""
if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$APP_DIR/.venv/bin/python"
    echo "Using Python from .venv: $PYTHON_BIN"
else
    # Fallback to system python3
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
        echo "Using system Python: $PYTHON_BIN"
    else
        echo "ERROR: No python3 found and no .venv present in $APP_DIR" >&2
        exit 1
    fi
fi

# Ensure monitor.py exists
if [[ ! -f "$APP_DIR/monitor.py" ]]; then
    echo "ERROR: monitor.py not found in $APP_DIR" >&2
    exit 1
fi

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "========================================="
    echo "Stopping monitor (sending SIGTERM)..."
    echo "========================================="
    if [[ -n "${MONITOR_PID:-}" ]]; then
        kill -TERM "$MONITOR_PID" 2>/dev/null || true
        # Wait up to 5 seconds for graceful shutdown
        for i in {1..50}; do
            if ! kill -0 "$MONITOR_PID" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done
        # Force kill if still running
        if kill -0 "$MONITOR_PID" 2>/dev/null; then
            echo "Force killing monitor process..."
            kill -KILL "$MONITOR_PID" 2>/dev/null || true
        fi
    fi
    echo "Debug test completed. Log saved to: $LOG_FILE"
}

# Set up trap to cleanup on script exit
trap cleanup EXIT INT TERM

# Start monitor in background with all output redirected to log file
echo "Starting monitor with full debug logging..."
echo "Command: $PYTHON_BIN monitor.py --real --debug-logging --verbose --detailed-logging"
echo ""

# Run monitor and capture all output (stdout + stderr) directly to log file only
# Redirect to file only (no stdout) to avoid filling context
"$PYTHON_BIN" "$APP_DIR/monitor.py" --real --debug-logging --verbose --detailed-logging > "$LOG_FILE" 2>&1 &
MONITOR_PID=$!

# Wait for 90 seconds (plenty of time for the test sequence)
echo "Monitor started (PID: $MONITOR_PID)"
echo "Running for 90 seconds..."
echo "All output being saved to: $LOG_FILE"
sleep 90

# Cleanup will be handled by trap
exit 0

