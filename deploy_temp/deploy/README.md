# Deployment Guide for Oracle Cloud Ubuntu

This guide will help you deploy the Autonomous Web Agent to your Oracle Cloud Ubuntu server.

## Prerequisites

- Oracle Cloud Ubuntu server (Ubuntu 20.04 or 22.04)
- SSH access to the server
- Your SSH key file

## Step 1: Connect to Your Server

```bash
ssh -i "path/to/your/ssh-key.key" ubuntu@YOUR_SERVER_IP
```

## Step 2: Clone or Upload Your Project

If you have the project in a git repository:
```bash
git clone YOUR_REPO_URL
cd Autonomous-Web-Agent
```

Or use SCP to upload your project:
```bash
# From your local machine
scp -i "path/to/your/ssh-key.key" -r /path/to/Autonomous-Web-Agent ubuntu@YOUR_SERVER_IP:~/
```

## Step 3: Set Up Python Environment

```bash
cd ~/Autonomous-Web-Agent
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Step 4: Install Playwright Browsers

```bash
source venv/bin/activate
playwright install chromium
playwright install-deps chromium
```

## Step 5: Configure Environment Variables

Create a `.env` file in the project root:
```bash
nano .env
```

Add your API keys:
```
OPENAI_API_KEY=your_openai_api_key
# Add any other environment variables you need
```

## Step 6: Set Up Systemd Services

```bash
# Copy service files
sudo cp deploy/web-agent-driver.service /etc/systemd/system/
sudo cp deploy/web-agent-app.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable web-agent-driver
sudo systemctl enable web-agent-app
```

**Important**: Update the service files with the correct path to your project:
- Replace `/home/ubuntu/Autonomous-Web-Agent` with your actual project path

## Step 7: Configure Nginx

```bash
# Copy nginx configuration
sudo cp deploy/nginx.conf /etc/nginx/sites-available/web-agent

# Create symbolic link
sudo ln -s /etc/nginx/sites-available/web-agent /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm /etc/nginx/sites-enabled/default

# Test nginx configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

## Step 8: Configure Firewall

Allow HTTP traffic:
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp  # If you plan to use HTTPS
sudo ufw status
```

## Step 9: Start Services

```bash
# Make scripts executable
chmod +x deploy/*.sh

# Start services
./deploy/start_services.sh
```

Or start manually:
```bash
sudo systemctl start web-agent-driver
sudo systemctl start web-agent-app
sudo systemctl reload nginx
```

## Step 10: Verify Deployment

1. Check service status:
```bash
sudo systemctl status web-agent-driver
sudo systemctl status web-agent-app
```

2. Check logs:
```bash
sudo journalctl -u web-agent-driver -f
sudo journalctl -u web-agent-app -f
```

3. Access the web interface:
   - Open your browser and go to: `http://YOUR_SERVER_IP`

## Troubleshooting

### Service won't start
- Check logs: `sudo journalctl -u web-agent-app -n 50`
- Verify paths in service files are correct
- Ensure virtual environment is activated and dependencies are installed

### Browser not working
- Ensure Playwright browsers are installed: `playwright install chromium`
- Check if display is available (for headless mode, this should be fine)

### Can't access web interface
- Check firewall: `sudo ufw status`
- Verify nginx is running: `sudo systemctl status nginx`
- Check nginx logs: `sudo tail -f /var/log/nginx/web-agent-error.log`

### Permission issues
- Ensure files are owned by ubuntu user: `sudo chown -R ubuntu:ubuntu ~/Autonomous-Web-Agent`

## Updating the Application

1. Pull latest changes or upload new files
2. Activate virtual environment and update dependencies:
```bash
source venv/bin/activate
pip install -r requirements.txt
```
3. Restart services:
```bash
sudo systemctl restart web-agent-app
sudo systemctl restart web-agent-driver
```

## Security Considerations

1. **Set up HTTPS**: Use Let's Encrypt with Certbot for SSL certificates
2. **Change default secrets**: Update `SECRET_KEY` in `.env` file
3. **Firewall**: Only open necessary ports
4. **Authentication**: Consider adding authentication to the web interface

## Setting Up HTTPS (Optional but Recommended)

```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Certbot will automatically configure nginx and renew certificates.

## Monitoring

- View logs: `sudo journalctl -u web-agent-app -f`
- Check nginx access logs: `sudo tail -f /var/log/nginx/web-agent-access.log`
- Monitor system resources: `htop` or `top`

## Stopping Services

```bash
./deploy/stop_services.sh
```

Or manually:
```bash
sudo systemctl stop web-agent-app
sudo systemctl stop web-agent-driver
```

