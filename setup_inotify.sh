#!/bin/bash
# Setup inotify for file monitoring - ZERO CUSTOM CODE!

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

echo "Inotify auto-update service installed and started"
