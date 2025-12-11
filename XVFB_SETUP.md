# Xvfb Setup for RpiSolArk

## Problem

The Sol-Ark website doesn't work in headless mode, so we need to use non-headless mode with Xvfb (virtual framebuffer) for systemd services.

## Solution: Separate Xvfb Service (Recommended)

This is the cleanest approach - Xvfb runs as a separate service that the main service depends on.

### Setup Steps

1. **Install Xvfb:**
   ```bash
   sudo apt-get install xvfb
   ```

2. **Install the Xvfb service:**
   ```bash
   sudo cp xvfb.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable xvfb
   sudo systemctl start xvfb
   ```

3. **Verify Xvfb is running:**
   ```bash
   sudo systemctl status xvfb
   ps aux | grep Xvfb
   ```

4. **Update the main service:**
   ```bash
   sudo cp rpisolark-monitor.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

5. **Start the main service:**
   ```bash
   sudo systemctl start rpisolark-monitor
   ```

## Alternative: Wrapper Script

If you prefer not to use a separate service, the wrapper script approach is also available:

1. The `start-xvfb.sh` script backgrounds Xvfb properly
2. The service file uses `ExecStartPre` to call the wrapper script
3. This works but is less clean than a separate service

## Troubleshooting

### Service hangs on start

- Check if Xvfb is already running: `ps aux | grep Xvfb`
- Check service logs: `sudo journalctl -u rpisolark-monitor -f`
- Verify DISPLAY is set: The service sets `DISPLAY=:99`

### Xvfb not starting

- Check Xvfb service: `sudo systemctl status xvfb`
- Check logs: `sudo journalctl -u xvfb -f`
- Verify Xvfb is installed: `which Xvfb`

### Browser still can't connect

- Verify DISPLAY environment: `echo $DISPLAY` (should be `:99`)
- Test manually: `DISPLAY=:99 xterm` (should open a terminal)
- Check Xvfb is listening: `netstat -an | grep :99` (if using TCP)

## Configuration

Make sure `config.yaml` has:
```yaml
solark_cloud:
  headless: false  # Must be false for Xvfb to work
```
