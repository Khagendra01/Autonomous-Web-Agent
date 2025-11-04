# Automated Deployment Guide

I've created automated deployment scripts that will handle everything for you!

## 🚀 Quick Deploy (Choose One Method)

### Option 1: Windows Batch Script (Easiest)

1. **Double-click** `deploy_from_windows.bat` OR
2. **Run in Command Prompt:**
   ```cmd
   deploy_from_windows.bat
   ```

That's it! The script will:
- ✅ Package all files
- ✅ Upload to your server
- ✅ Set up Python environment
- ✅ Install dependencies
- ✅ Configure systemd services
- ✅ Set up Nginx
- ✅ Configure firewall
- ✅ Start all services

### Option 2: PowerShell Script (More Detailed)

1. **Run PowerShell as Administrator:**
   ```powershell
   .\deploy_from_windows.ps1
   ```

This provides more detailed output and better error handling.

## 📋 What the Scripts Do

1. **Package Files**: Collects all necessary files
2. **Upload to Server**: Uses SCP to transfer files
3. **Run Setup**: Executes `setup_server.sh` on the server
4. **Configure Services**: Sets up systemd services
5. **Configure Nginx**: Sets up reverse proxy
6. **Configure Firewall**: Opens ports 80 and 22
7. **Start Services**: Starts both driver and web app

## ⚙️ After Deployment

### 1. Configure API Keys

SSH to your server and edit the `.env` file:

```bash
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184
nano /home/ubuntu/Autonomous-Web-Agent/.env
```

Add your `OPENAI_API_KEY`:
```
OPENAI_API_KEY=sk-your-actual-key-here
```

### 2. Restart Services

```bash
sudo systemctl restart web-agent-app
sudo systemctl restart web-agent-driver
```

### 3. Access Your Application

Open your browser and go to:
```
http://129.80.169.184
```

## 🔍 Verify Deployment

### Check Service Status

```bash
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184

# Check driver service
sudo systemctl status web-agent-driver

# Check web app service
sudo systemctl status web-agent-app

# Check nginx
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

## 🛠️ Troubleshooting

### If Upload Fails

1. Check SSH key path is correct in the script
2. Verify server is accessible: `ping 129.80.169.184`
3. Test SSH connection manually

### If Services Don't Start

1. Check logs: `sudo journalctl -u web-agent-app -n 50`
2. Verify `.env` file has API keys
3. Check Python environment: `source venv/bin/activate && python --version`

### If Web Interface Doesn't Load

1. Check nginx: `sudo systemctl status nginx`
2. Check firewall: `sudo ufw status`
3. Verify services are running: `sudo systemctl status web-agent-app`

## 🔄 Updating the Application

Just run the deployment script again - it will:
- Upload new files
- Restart services automatically

Or manually:

```bash
# On server
cd /home/ubuntu/Autonomous-Web-Agent
git pull  # if using git
# OR upload new files via SCP
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart web-agent-app
```

## 📝 Customization

### Change Server IP

Edit `deploy_from_windows.bat` or `deploy_from_windows.ps1`:
```batch
set SERVER_IP=your-new-ip-here
```

### Change SSH Key Path

Edit the scripts:
```batch
set SSH_KEY="your/path/to/key.key"
```

## 🎉 That's It!

The automated scripts handle everything. Just run one script and you're done!

