# Reverse Tunnel Setup for Remote SSH Access

This guide explains how to set up remote SSH access to your Raspberry Pi (RPi) by having it establish a reverse tunnel to your server at keithcu.com. This creates an outbound connection from the RPi to the server, allowing you to SSH into the RPi via the server without needing port forwarding on your home router.

This setup is secure for low-usage scenarios like monitoring your 120VAC frequency measurement project and works well if keithcu.com is publicly accessible (e.g., a VPS).

**Note**: This guide assumes the RPi doesn't have direct SSH access to keithcu.com, but you have access to keithcu.com from another machine. We'll set up the `rpisolark` user and keys through that intermediate access.

## How It Works (Quick Overview)

The reverse tunnel works like this:

1. **RPi → keithcu.com**: The RPi establishes an SSH connection to keithcu.com on port 2227 and creates a reverse tunnel
2. **Tunnel**: Port 2222 on keithcu.com forwards to port 22 (SSH) on the RPi
3. **You → RPi**: You SSH to keithcu.com first, then connect to `localhost:2222` to reach the RPi

**Connection Flow:**
```
Your Machine → keithcu.com:2227 → (on keithcu.com) → localhost:2222 → RPi:22
```

**Port Summary:**
- **Port 2227**: SSH port on keithcu.com (used by RPi to connect to server, and by you to connect to server)
- **Port 2222**: Reverse tunnel port on keithcu.com (forwards to RPi's SSH on port 22)
- **Port 22**: Standard SSH port on the RPi

## Prerequisites

- SSH is enabled on the RPi (run `sudo raspi-config` > Interface Options > SSH)
- You have SSH access to keithcu.com from another machine (e.g., your current workstation)
- RPi username is `pi` (default; adjust as needed)
- keithcu.com uses port 2227 for SSH
- Check for firewalls on keithcu.com (e.g., ufw/iptables) allowing inbound SSH on port 2227

## Step 1: Create the rpisolark User on keithcu.com

From your machine that has SSH access to keithcu.com:

```bash
ssh youruser@keithcu.com -p 2227
```

Once connected to keithcu.com, create the rpisolark user:

```bash
sudo useradd -m -s /bin/bash rpisolark
sudo passwd rpisolark  # Set a temporary password (you can disable it later)
```

## Step 2: Set Up Key-Based Authentication (Passwordless Login from RPi to Server)

Since the RPi doesn't have direct SSH access to keithcu.com, we'll generate the keys on the RPi and then copy the public key to keithcu.com via your intermediate machine.

### On the RPi:

```bash
ssh-keygen -t ed25519  # Press Enter for defaults; no passphrase for automation
```

This creates `~/.ssh/id_ed25519` (private key) and `~/.ssh/id_ed25519.pub` (public key).

### Copy the public key to your intermediate machine:

On the RPi, display the public key:
```bash
cat ~/.ssh/id_ed25519.pub
```

Copy this entire output (it's one line starting with `ssh-ed25519`).

### On your intermediate machine (that has access to keithcu.com):

SSH to keithcu.com:
```bash
ssh youruser@keithcu.com -p 2227
```

Once on keithcu.com, add the RPi's public key to the rpisolark user:
```bash
sudo mkdir -p /home/rpisolark/.ssh
sudo chmod 700 /home/rpisolark/.ssh
sudo nano /home/rpisolark/.ssh/authorized_keys
```

Paste the public key you copied from the RPi (one line), save and exit.

Set proper permissions:
```bash
sudo chmod 600 /home/rpisolark/.ssh/authorized_keys
sudo chown -R rpisolark:rpisolark /home/rpisolark/.ssh
```

### Test the connection from RPi:

On the RPi, test the connection:
```bash
ssh rpisolark@keithcu.com -p 2227
```

This should log in without requiring a password. If it works, you can optionally disable password authentication for the rpisolark user on keithcu.com for better security.

## Step 3: Install Autossh on RPi for Persistent Tunneling

Autossh keeps the tunnel alive even if connections drop (better than plain ssh).

### On RPi:
```bash
sudo apt update && sudo apt install autossh
```

## Step 4: Create the Reverse Tunnel on the RPi

### Manual tunnel creation:
Run this command on the RPi (replace port 2222 if needed; choose an unused port on the server):

```bash
autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -f -N -R 2222:localhost:22 -p 2227 rpisolark@keithcu.com
```

**Port explanation:**
- `-R 2222:localhost:22`: Creates a reverse tunnel where port **2222 on the server** (keithcu.com) forwards to port 22 (SSH) on the RPi. Port 2222 is the port you'll use on the server to access the RPi's SSH service.
- `-p 2227`: Uses port 2227 to establish the SSH connection **to** keithcu.com (keithcu.com only listens on port 2227 for SSH, not the default port 22)
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
ExecStart=/usr/bin/autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -N -R 2222:localhost:22 -p 2227 rpisolark@keithcu.com
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

## Step 5: Access the RPi Remotely

### From your remote machine (e.g., laptop):

**Step 1:** SSH into keithcu.com using your regular user account:
```bash
ssh youruser@keithcu.com -p 2227
```

**Step 2:** Once you're on keithcu.com, connect to the RPi via the reverse tunnel:
```bash
ssh pi@localhost -p 2222
```

**Login Details:**
- **Username**: `pi` (the RPi username, not `rpisolark`)
- **Host**: `localhost` (because you're already on keithcu.com)
- **Port**: `2222` (the reverse tunnel port)
- **Authentication**: Use your RPi's SSH credentials (password or SSH key, depending on how your RPi is configured)

**Note:** The tunnel binds to `localhost` on the server, so you must connect from within the keithcu.com shell. You cannot directly connect to `keithcu.com:2222` from your local machine unless you enable `GatewayPorts` (see Optional section below).

### Quick Test

To verify the tunnel is working, after connecting to keithcu.com, you can check if port 2222 is listening:
```bash
netstat -tuln | grep 2222
# or
ss -tuln | grep 2222
```

You should see something like `127.0.0.1:2222` (localhost binding).

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
# ExecStart=/usr/bin/autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -N -R 2222:localhost:22 -p 2227 rpisolark@keithcu.com
# To:
ExecStart=/usr/bin/autossh -M 0 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" -N -R *:2222:localhost:22 -p 2227 rpisolark@keithcu.com
```

**Warning**: This exposes the port publicly on the server—secure it with key auth and Fail2Ban.

## Quick Reference: Connecting to Your RPi

Once everything is set up, here's the two-step process to connect:

```bash
# Step 1: Connect to keithcu.com
ssh youruser@keithcu.com -p 2227

# Step 2: From keithcu.com, connect to RPi via tunnel
ssh pi@localhost -p 2222
```

## Tips for Your Frequency Project

- Once connected, you can tail logs (e.g., `tail -f /var/log/frequency.log`) or edit scripts remotely
- Monitor tunnel: 
  - On RPi: `ps aux | grep autossh` or `sudo systemctl status autossh-tunnel.service`
  - On server: `netstat -tuln | grep 2222` or `ss -tuln | grep 2222`
- If using IPv6 (from past setups), add `-6` to ssh/autossh commands if preferred
- Test locally first: Run the tunnel manually, connect from server
- To exit: Type `exit` twice (once to leave RPi, once to leave keithcu.com)

## Troubleshooting

If you hit issues (e.g., port conflicts or connection drops), share error messages or server OS details for tweaks.
