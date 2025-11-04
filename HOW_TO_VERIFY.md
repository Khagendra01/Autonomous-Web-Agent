# 🔍 How to Know if It's Working

## Quick Check (30 seconds)

### Option 1: Run Status Check Script
**Double-click:** `check_status.bat`

Or run:
```cmd
check_status.bat
```

This will automatically check:
- ✅ Server connectivity
- ✅ SSH access
- ✅ Driver service status
- ✅ Web app service status
- ✅ Nginx status
- ✅ Web interface accessibility

### Option 2: Open in Browser
Simply open: **http://129.80.169.184**

If you see the web interface, it's working! 🎉

## Manual Verification Steps

### 1. Check if Web Interface is Accessible

Open your browser and go to:
```
http://129.80.169.184
```

**✅ Working:** You see the Autonomous Web Agent interface with:
- Task input form
- Browser view panel
- Status indicators

**❌ Not Working:** Page doesn't load or shows error

### 2. Check Service Status

SSH to your server:
```cmd
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184
```

Then check services:
```bash
# Check driver service
sudo systemctl status web-agent-driver

# Check web app service
sudo systemctl status web-agent-app

# Check nginx
sudo systemctl status nginx
```

**✅ Working:** All show "active (running)" in green

**❌ Not Working:** Shows "inactive" or "failed" in red

### 3. Test a Task

If the web interface loads:

1. Enter a task like: "Navigate to google.com"
2. Click "Start Task"
3. Watch for:
   - ✅ Status updates appearing
   - ✅ Browser view showing screenshots
   - ✅ Screenshot count increasing

**✅ Working:** You see real-time browser updates

**❌ Not Working:** Status shows error or no browser view

## Common Issues & Solutions

### Issue: "Web interface not loading"

**Check:**
```bash
# On server
sudo systemctl status nginx
sudo systemctl status web-agent-app
```

**Fix:**
```bash
sudo systemctl restart web-agent-app
sudo systemctl restart nginx
```

### Issue: "Driver server not available"

**Check:**
```bash
sudo systemctl status web-agent-driver
```

**Fix:**
```bash
sudo systemctl restart web-agent-driver
```

### Issue: "No screenshots showing"

**Check logs:**
```bash
sudo journalctl -u web-agent-app -f
```

**Common causes:**
- API key not set in `.env`
- Driver not running
- Playwright browsers not installed

**Fix:**
```bash
# Check API key
cat .env | grep OPENAI_API_KEY

# Reinstall browsers
source venv/bin/activate
playwright install chromium
```

### Issue: "Task fails immediately"

**Check logs:**
```bash
sudo journalctl -u web-agent-app -n 50
```

**Common causes:**
- Missing API key
- Driver not initialized
- Network issues

**Fix:**
```bash
# Verify API key is set
nano .env
# Add: OPENAI_API_KEY=sk-your-key-here

# Restart services
sudo systemctl restart web-agent-driver
sudo systemctl restart web-agent-app
```

## Quick Health Check Commands

Run these on the server to verify everything:

```bash
# All services should be active
sudo systemctl is-active web-agent-driver
sudo systemctl is-active web-agent-app
sudo systemctl is-active nginx

# Check if ports are listening
sudo netstat -tlnp | grep -E '5000|50051|80'

# Check recent logs for errors
sudo journalctl -u web-agent-app --since "5 minutes ago" | grep -i error
```

## Visual Indicators It's Working

### ✅ Working Correctly:
- Web interface loads in browser
- Can submit tasks
- Browser view shows screenshots (updates every second)
- Status shows "running" or "completed"
- Screenshot count increases
- No error messages

### ❌ Not Working:
- Web interface doesn't load (404 or connection refused)
- Tasks fail immediately
- No browser view/screenshots
- Error messages in status
- Services show "failed" status

## Automated Test

Run this quick test on the server:

```bash
# Test all components
curl -s http://localhost:5000 > /dev/null && echo "✅ Web app responding" || echo "❌ Web app not responding"
sudo systemctl is-active web-agent-driver > /dev/null && echo "✅ Driver running" || echo "❌ Driver not running"
sudo systemctl is-active web-agent-app > /dev/null && echo "✅ App running" || echo "❌ App not running"
sudo systemctl is-active nginx > /dev/null && echo "✅ Nginx running" || echo "❌ Nginx not running"
```

All should show ✅ for a working deployment.

## Need More Help?

1. **View detailed logs:**
   ```bash
   sudo journalctl -u web-agent-app -f
   ```

2. **Check service files:**
   ```bash
   cat /etc/systemd/system/web-agent-app.service
   ```

3. **Test manually:**
   ```bash
   cd /home/ubuntu/Autonomous-Web-Agent
   source venv/bin/activate
   python web_app.py
   ```

If it works manually but not as a service, check the service file paths.

