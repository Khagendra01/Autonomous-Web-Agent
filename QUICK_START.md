# Quick Start Guide

## 🚀 Local Development

1. **Set up the environment:**
   ```bash
   chmod +x setup_server.sh
   ./setup_server.sh
   ```

2. **Configure your API keys:**
   ```bash
   nano .env
   # Add your OPENAI_API_KEY
   ```

3. **Start the gRPC driver server** (in Terminal 1):
   ```bash
   source venv/bin/activate
   python -m src.drivers.grpc_playwright_server
   ```

4. **Start the web application** (in Terminal 2):
   ```bash
   source venv/bin/activate
   python web_app.py
   ```

5. **Open your browser:**
   - Go to: `http://localhost:5000`
   - Enter a task like: "Create a new project called Softlight in Linear"
   - Watch the browser in real-time!

## 🌐 Deployment to Oracle Cloud

### Step 1: Connect to Your Server

```bash
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184
```

### Step 2: Upload Your Project

**Option A: Using Git (if you have a repo):**
```bash
git clone YOUR_REPO_URL
cd Autonomous-Web-Agent
```

**Option B: Using SCP (from your local machine):**
```bash
# From your Windows machine
scp -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" -r . ubuntu@129.80.169.184:~/Autonomous-Web-Agent
```

### Step 3: Set Up on Server

```bash
cd ~/Autonomous-Web-Agent
chmod +x setup_server.sh
./setup_server.sh
```

### Step 4: Configure Environment

```bash
nano .env
# Add your OPENAI_API_KEY and other required variables
```

### Step 5: Set Up Systemd Services

```bash
# Copy service files (update paths if needed)
sudo cp deploy/web-agent-driver.service /etc/systemd/system/
sudo cp deploy/web-agent-app.service /etc/systemd/system/

# Edit paths in service files if your project is not in /home/ubuntu/Autonomous-Web-Agent
sudo nano /etc/systemd/system/web-agent-driver.service
sudo nano /etc/systemd/system/web-agent-app.service

# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable web-agent-driver
sudo systemctl enable web-agent-app
```

### Step 6: Configure Nginx

```bash
# Copy nginx configuration
sudo cp deploy/nginx.conf /etc/nginx/sites-available/web-agent

# Create symbolic link
sudo ln -s /etc/nginx/sites-available/web-agent /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### Step 7: Configure Firewall

```bash
sudo ufw allow 80/tcp
sudo ufw allow 22/tcp  # SSH
sudo ufw enable
```

### Step 8: Start Services

```bash
chmod +x deploy/*.sh
./deploy/start_services.sh
```

### Step 9: Access Your Application

Open your browser and go to:
```
http://129.80.169.184
```

## 🔧 Troubleshooting

### Check Service Status

```bash
sudo systemctl status web-agent-driver
sudo systemctl status web-agent-app
sudo systemctl status nginx
```

### View Logs

```bash
# Driver logs
sudo journalctl -u web-agent-driver -f

# Web app logs
sudo journalctl -u web-agent-app -f

# Nginx logs
sudo tail -f /var/log/nginx/web-agent-error.log
```

### Restart Services

```bash
sudo systemctl restart web-agent-driver
sudo systemctl restart web-agent-app
sudo systemctl reload nginx
```

### Common Issues

1. **"Driver server not available"**
   - Make sure `web-agent-driver` service is running
   - Check: `sudo systemctl status web-agent-driver`

2. **"Cannot connect to gRPC server"**
   - Verify the driver is listening on port 50051
   - Check firewall rules

3. **"No screenshots showing"**
   - Ensure Playwright browsers are installed: `playwright install chromium`
   - Check driver logs for errors

4. **"Web interface not loading"**
   - Check nginx is running: `sudo systemctl status nginx`
   - Verify firewall allows port 80
   - Check nginx error logs

## 📝 Notes

- The web interface streams screenshots every 1 second while a task is running
- Tasks run in the background and can be monitored via the web interface
- All screenshots and captures are saved in the `captures/` directory
- The gRPC driver must be running before starting tasks

## 🔒 Security Recommendations

1. **Set up HTTPS** (recommended for production):
   ```bash
   sudo apt-get install certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   ```

2. **Change the SECRET_KEY** in `.env`:
   ```bash
   openssl rand -hex 32
   # Add this to .env as SECRET_KEY=...
   ```

3. **Add authentication** to the web interface (consider Flask-Login)

4. **Restrict firewall** to only necessary ports

## 📚 Additional Resources

- See `deploy/README.md` for detailed deployment instructions
- Check logs regularly for errors
- Monitor system resources: `htop`

