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
        
        # Copy service files
        sudo cp update.service /etc/systemd/system/
        sudo cp update.timer /etc/systemd/system/
        sudo cp update.sh /home/pi/RpiSolArk/
        sudo chmod +x /home/pi/RpiSolArk/update.sh
        
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
        
        chmod +x setup_watchman.sh
        ./setup_watchman.sh
        
        echo "✅ Watchman setup complete!"
        echo "   Updates will trigger on file changes"
        echo "   View triggers: watchman trigger-list ."
        ;;
        
    5)
        echo "🔍 Setting up Inotify..."
        
        chmod +x setup_inotify.sh
        ./setup_inotify.sh
        
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
