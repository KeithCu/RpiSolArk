# Reverse Tunnel Setup for Remote SSH Access

This guide explains how to set up remote SSH access to your Raspberry Pi (RPi) by having it establish a reverse tunnel to your server at keithcu.com. This creates an outbound connection from the RPi to the server, allowing you to SSH into the RPi via the server without needing port forwarding on your home router.

This setup is secure for low-usage scenarios like monitoring your 120VAC frequency measurement project and works well if keithcu.com is publicly accessible (e.g., a VPS).

## Prerequisites

- SSH is enabled on the RPi (run `sudo raspi-config` > Interface Options > SSH)
- You have SSH access to keithcu.com (e.g., as user `youruser`)
- RPi username is `pi` (default; adjust as needed)
- Check for firewalls on keithcu.com (e.g., ufw/iptables) allowing inbound SSH

## Step 1: Set Up Key-Based Authentication (Passwordless Login from RPi to Server)

This ensures the tunnel can run without prompting for passwords and auto-reconnects easily.

### On the RPi:

```bash
ssh-keygen -t ed25519  # Press Enter for defaults; no passphrase for automation

ssh-copy-id youruser@keithcu.com  # Enter server password when prompted
```

### Test the connection:
```bash
ssh youruser@keithcu.com
```

This should log in without requiring a password.

## Step 2: Install Autossh on RPi for Persistent Tunneling

Autossh keeps the tunnel alive even if connections drop (better than plain ssh).

### On RPi:
```bash
sudo apt update && sudo apt install autossh
```

## Step 3: Create the Reverse Tunnel on the RPi

### Manual tunnel creation:
Run this command on the RPi (replace `youruser` and port 2222 if needed; choose an unused port on the server):

```bash
autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -f -N -R 2222:localhost:22 youruser@keithcu.com
```

- `-R 2222:localhost:22`: Forwards port 2222 on the server to port 22 (SSH) on the RPi
- `-f -N`: Runs in background without executing remote commands
- This binds the tunnel to localhost on the server by default (secure)

### Make it auto-start on boot:

Create a systemd service:
```bash
sudo nano /etc/systemd/system/autossh-tunnel.service
```

Add the following content:
```ini
[Unit]
Description=AutoSSH tunnel to keithcu.com
After=network.target

[Service]
User=pi
ExecStart=/usr/bin/autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -N -R 2222:localhost:22 youruser@keithcu.com
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable autossh-tunnel.service
sudo systemctl start autossh-tunnel.service
```

Check status:
```bash
sudo systemctl status autossh-tunnel.service
```

## Step 4: Access the RPi Remotely

### From your remote machine (e.g., laptop):

1. SSH into keithcu.com:
```bash
ssh youruser@keithcu.com
```

2. From the server's shell, connect to the RPi via the tunnel:
```bash
ssh pi@localhost -p 2222
```

## Optional: Direct Access Without Hopping Through Server Shell

If you want direct access without hopping through the server's shell (e.g., `ssh pi@keithcu.com -p 2222` from anywhere):

### On keithcu.com:
Edit `/etc/ssh/sshd_config` (with sudo):
```
GatewayPorts yes
```

Restart SSH:
```bash
sudo systemctl restart sshd
```

### On RPi:
Change the tunnel to expose the port publicly (restart the service):
```bash
# In the systemd service file, change:
# ExecStart=/usr/bin/autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -N -R 2222:localhost:22 youruser@keithcu.com
# To:
ExecStart=/usr/bin/autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -N -R *:2222:localhost:22 youruser@keithcu.com
```

**Warning**: This exposes the port publicly on the server—secure it with key auth and Fail2Ban.

## Tips for Your Frequency Project

- Once connected, you can tail logs (e.g., `tail -f /var/log/frequency.log`) or edit scripts remotely
- Monitor tunnel: On RPi, `ps aux | grep autossh`; on server, `netstat -tuln | grep 2222`
- If using IPv6 (from past setups), add `-6` to ssh/autossh commands if preferred
- Test locally first: Run the tunnel manually, connect from server

## Troubleshooting

If you hit issues (e.g., port conflicts or connection drops), share error messages or server OS details for tweaks.
