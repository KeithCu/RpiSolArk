#!/bin/bash
# Setup Watchman for file monitoring - ZERO CUSTOM CODE!

# Install watchman
sudo apt update
sudo apt install -y watchman

# Create watchman configuration
cat > .watchmanconfig << EOF
{
  "ignore_dirs": [".git", "logs", "solark_cache", "venv", "__pycache__"]
}
EOF

# Create watchman trigger
watchman watch .
watchman trigger set . auto-update \
  -- '["anyof", ["match", "*.py", "wholename"], ["match", "*.yaml", "wholename"], ["match", "*.sh", "wholename"]]' \
  -- bash -c 'cd /home/pi/RpiSolArk && git pull origin release && systemctl restart frequency-monitor'

echo "Watchman configured for auto-updates"
echo "To view triggers: watchman trigger-list ."
echo "To remove: watchman trigger-del . auto-update"
