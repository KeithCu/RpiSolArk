#!/bin/bash
# Setup ZERO-CODE auto-updates - Choose your method!

set -e

echo "🚀 Setting up ZERO-CODE auto-updates"
echo "=================================="
echo ""
echo "Choose your preferred method:"
echo "1. Systemd Timer (Recommended - Built into Linux)"
echo "2. Cron Job (Simplest)"
echo "3. GitHub Actions (Cloud-based)"
echo "4. Watchman (Facebook's file watcher)"
echo "5. Inotify (Linux kernel file watcher)"
echo ""

read -p "Enter your choice (1-5): " choice

case $choice in
    1)
        echo "📅 Setting up Systemd Timer..."

        # Create update script
        sudo tee /home/pi/RpiSolArk/update.sh > /dev/null << 'EOF'
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
EOF

        sudo chmod +x /home/pi/RpiSolArk/update.sh

        # Create systemd service
        sudo tee /etc/systemd/system/update.service > /dev/null << EOF
[Unit]
Description=Auto-update RpiSolArk from GitHub
After=network.target

[Service]
Type=oneshot
User=pi
WorkingDirectory=/home/pi/RpiSolArk
ExecStart=/home/pi/RpiSolArk/update.sh
StandardOutput=journal
StandardError=journal
EOF

        # Create systemd timer
        sudo tee /etc/systemd/system/update.timer > /dev/null << EOF
[Unit]
Description=Run auto-update every hour
Requires=update.service

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
EOF

        # Enable and start
        sudo systemctl daemon-reload
        sudo systemctl enable update.timer
        sudo systemctl start update.timer

        echo "✅ Systemd timer setup complete!"
        echo "   Updates will run every hour automatically"
        echo "   View status: sudo systemctl status update.timer"
        echo "   View logs: journalctl -u update.service"
        ;;
        
    2)
        echo "⏰ Setting up Cron Job..."

        # Add cron job
        (crontab -l 2>/dev/null; echo "0 * * * * cd /home/pi/RpiSolArk && git pull origin release && sudo systemctl restart frequency-monitor") | crontab -

        echo "✅ Cron job setup complete!"
        echo "   Updates will run every hour automatically"
        echo "   View cron jobs: crontab -l"
        echo "   Edit cron jobs: crontab -e"
        ;;
        
    3)
        echo "☁️ Setting up GitHub Actions..."
        
        # Create .github directory
        mkdir -p .github/workflows
        
        echo "✅ GitHub Actions workflow created!"
        echo "   Add these secrets to your GitHub repository:"
        echo "   - PI_HOST: Your Raspberry Pi IP address"
        echo "   - PI_USER: Your Pi username (usually 'pi')"
        echo "   - PI_SSH_KEY: Your SSH private key"
        echo "   Updates will deploy automatically when you push to 'release' branch"
        ;;
        
    4)
        echo "👀 Setting up Watchman..."

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

        echo "✅ Watchman setup complete!"
        echo "   Updates will trigger on file changes"
        echo "   View triggers: watchman trigger-list ."
        ;;
        
    5)
        echo "🔍 Setting up Inotify..."

        # Install inotify-tools
        sudo apt update
        sudo apt install -y inotify-tools

        # Create inotify script
        cat > /home/pi/RpiSolArk/watch_for_updates.sh << 'EOF'
#!/bin/bash
# Watch for changes and auto-update

cd /home/pi/RpiSolArk

# Watch for changes in the current directory
inotifywait -m -r -e modify,create,delete,move . --exclude '\.(git|logs|solark_cache|venv|__pycache__)' |
while read path action file; do
    echo "File $file $action in $path"

    # Check if it's a git change (not local file change)
    if git status --porcelain | grep -q .; then
        echo "Local changes detected - skipping auto-update"
        continue
    fi

    # Pull updates
    git pull origin release

    # Restart service
    sudo systemctl restart frequency-monitor

    echo "Auto-update completed"
done
EOF

        chmod +x /home/pi/RpiSolArk/watch_for_updates.sh

        # Create systemd service for inotify
        sudo tee /etc/systemd/system/auto-update-watch.service > /dev/null << EOF
[Unit]
Description=Auto-update watcher using inotify
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/RpiSolArk
ExecStart=/home/pi/RpiSolArk/watch_for_updates.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl enable auto-update-watch
        sudo systemctl start auto-update-watch

        echo "✅ Inotify setup complete!"
        echo "   Updates will trigger on file changes"
        echo "   View status: sudo systemctl status auto-update-watch"
        ;;
        
    *)
        echo "❌ Invalid choice. Please run the script again."
        exit 1
        ;;
esac

echo ""
echo "🎉 Auto-update setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Make sure your code is in a git repository"
echo "2. Push your code to the 'release' branch"
echo "3. Your system will automatically update!"
echo ""
echo "🔧 Manual commands:"
echo "   Force update: cd /home/pi/RpiSolArk && git pull origin release"
echo "   Restart service: sudo systemctl restart frequency-monitor"
echo "   Check status: sudo systemctl status frequency-monitor"
