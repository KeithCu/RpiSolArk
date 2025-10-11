#!/bin/bash
# Setup cron job for auto-updates - ZERO CUSTOM CODE!

# Add cron job to check for updates every hour
(crontab -l 2>/dev/null; echo "0 * * * * cd /home/pi/RpiSolArk && git pull origin release && systemctl restart frequency-monitor") | crontab -

echo "Cron job added for hourly auto-updates"
echo "To view: crontab -l"
echo "To remove: crontab -e (then delete the line)"
