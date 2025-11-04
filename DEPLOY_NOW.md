# 🚀 Deploy Now - One Click Deployment

I've created automated deployment scripts! Just run one of these:

## ⚡ Quick Start

### Option 1: Windows Batch (Easiest)
**Double-click this file:** `deploy_from_windows.bat`

OR run in Command Prompt:
```cmd
deploy_from_windows.bat
```

### Option 2: PowerShell (Better Output)
Run in PowerShell:
```powershell
.\deploy_from_windows.ps1
```

## 📋 What Happens Automatically

The script will:
1. ✅ Package all your files
2. ✅ Upload everything to `129.80.169.184`
3. ✅ Set up Python environment
4. ✅ Install all dependencies
5. ✅ Configure systemd services
6. ✅ Set up Nginx reverse proxy
7. ✅ Configure firewall
8. ✅ Start all services

## ⚠️ After Deployment - You Need To:

### 1. Add Your API Key

SSH to server:
```cmd
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184
```

Edit the `.env` file:
```bash
nano /home/ubuntu/Autonomous-Web-Agent/.env
```

Add your OpenAI API key:
```
OPENAI_API_KEY=sk-your-actual-key-here
```

Save and exit (Ctrl+X, then Y, then Enter)

### 2. Restart Services
```bash
sudo systemctl restart web-agent-app
sudo systemctl restart web-agent-driver
```

### 3. Open Your Browser
Go to: **http://129.80.169.184**

## 🎉 Done!

Your web agent is now live and accessible!

## 🔍 If Something Goes Wrong

Check the logs:
```bash
# Web app logs
sudo journalctl -u web-agent-app -f

# Driver logs  
sudo journalctl -u web-agent-driver -f
```

## 📞 Need Help?

See `AUTOMATED_DEPLOY.md` for detailed troubleshooting.

