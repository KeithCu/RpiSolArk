#!/usr/bin/env bash
# Wrapper to run RpiSolarkMonitor as a systemd service.
# Requirements:
# - This script lives in the same directory as monitor.py and the .venv (if used).
# - Systemd unit should ExecStart this script.
#
# Behavior:
# - Detects its own directory (supports different install vs dev paths).
# - Uses ./.venv if present; otherwise falls back to system python3.
# - Runs: python monitor.py --real
# - Exits non-zero on failure so systemd can restart it.

set -euo pipefail

# Resolve directory of this script (handles symlinks)
SCRIPT_PATH="$(readlink -f "$0")"
APP_DIR="$(dirname "$SCRIPT_PATH")"
cd "$APP_DIR"

# Prefer local virtualenv if it exists
PYTHON_BIN=""
if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$APP_DIR/.venv/bin/python"
else
    # Fallback to system python3
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    else
        echo "ERROR: No python3 found and no .venv present in $APP_DIR" >&2
        exit 1
    fi
fi

# Ensure monitor.py exists in this directory
if [[ ! -f "$APP_DIR/monitor.py" ]]; then
    echo "ERROR: monitor.py not found in $APP_DIR" >&2
    exit 1
fi

# Optional: log where we are running from for debugging
echo "RpiSolarkMonitor starting from: $APP_DIR"
echo "Using Python: $PYTHON_BIN"
echo "Command: $PYTHON_BIN monitor.py --real"

exec "$PYTHON_BIN" "$APP_DIR/monitor.py" --real