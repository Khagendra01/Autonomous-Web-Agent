# 🧪 How to Test Your Deployment

## Quick Test (30 seconds)

### Option 1: Run the Test Script
**Double-click:** `test_deployment.bat`

This will automatically test:
- ✅ Service status
- ✅ Web interface accessibility
- ✅ API key configuration
- ✅ Driver connection
- ✅ Error logs

### Option 2: Manual Browser Test

1. **Open your browser**
2. **Go to:** http://129.80.169.184
3. **You should see:** The Autonomous Web Agent interface

✅ **If you see the interface, it's working!**

## Detailed Testing Steps

### Step 1: Check Service Status

**On your server:**
```bash
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184

# Check all services
sudo systemctl status web-agent-driver
sudo systemctl status web-agent-app
sudo systemctl status nginx
```

**Expected:** All should show "active (running)" in green

### Step 2: Test Web Interface

**In your browser:**
1. Navigate to: **http://129.80.169.184**
2. You should see:
   - Task input form
   - Browser view panel
   - Status indicators

✅ **If you see the interface, the web app is working!**

### Step 3: Test a Simple Task

**In the web interface:**
1. Enter a task: `"Navigate to google.com"`
2. Click **"Start Task"**
3. Watch for:
   - ✅ Status updates appearing
   - ✅ Browser view showing screenshots
   - ✅ Screenshot count increasing

**Expected behavior:**
- Status changes from "starting" → "running"
- Browser view shows screenshots updating every second
- Screenshot count increases

### Step 4: Verify API Key

**Check if API key is configured:**
```bash
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184
cat /home/ubuntu/Autonomous-Web-Agent/.env | grep OPENAI_API_KEY
```

**Expected:** Should show `OPENAI_API_KEY=sk-...` (not `your_openai_api_key_here`)

**If not configured:**
```bash
nano /home/ubuntu/Autonomous-Web-Agent/.env
# Add: OPENAI_API_KEY=sk-your-actual-key-here
sudo systemctl restart web-agent-app
```

### Step 5: Check Logs

**View real-time logs:**
```bash
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184

# Web app logs
sudo journalctl -u web-agent-app -f

# Driver logs
sudo journalctl -u web-agent-driver -f
```

**Expected:** No error messages, just normal operation logs

## Common Test Scenarios

### Test 1: Simple Navigation
**Task:** `"Navigate to google.com"`

**Expected:**
- Browser opens Google
- Screenshots show Google homepage
- Status shows "completed"

### Test 2: Search Task
**Task:** `"Search for 'autonomous agents' on google.com"`

**Expected:**
- Browser navigates to Google
- Search box is filled
- Search results appear

### Test 3: Form Interaction
**Task:** `"Fill out a contact form on example.com"`

**Expected:**
- Browser navigates to site
- Form fields are filled
- Form is submitted

## Troubleshooting Tests

### If Web Interface Doesn't Load

**Check:**
```bash
# Check if services are running
sudo systemctl status web-agent-app
sudo systemctl status nginx

# Check nginx logs
sudo tail -f /var/log/nginx/web-agent-error.log

# Check firewall
sudo ufw status
```

**Fix:**
```bash
sudo systemctl restart web-agent-app
sudo systemctl restart nginx
```

### If Tasks Fail Immediately

**Check:**
```bash
# Check API key
cat /home/ubuntu/Autonomous-Web-Agent/.env | grep OPENAI_API_KEY

# Check logs
sudo journalctl -u web-agent-app -n 50 | grep -i error
```

**Fix:**
- Add API key if missing
- Check logs for specific errors

### If No Screenshots Appear

**Check:**
```bash
# Check driver service
sudo systemctl status web-agent-driver

# Test driver connection
cd /home/ubuntu/Autonomous-Web-Agent
source venv/bin/activate
python -c "from src.drivers.grpc_client import DriverClient; c = DriverClient(); print('Driver OK')"
```

**Fix:**
```bash
sudo systemctl restart web-agent-driver
```

## Quick Verification Checklist

- [ ] Services are running (driver, web app, nginx)
- [ ] Web interface loads in browser
- [ ] Can submit tasks
- [ ] Browser view shows screenshots
- [ ] Status updates appear
- [ ] API key is configured
- [ ] No errors in logs

## Success Indicators

✅ **Everything is working if:**
- Web interface loads
- Can submit tasks
- Browser view shows screenshots (updates every second)
- Status shows "running" or "completed"
- Screenshot count increases
- No error messages

❌ **Not working if:**
- Web interface doesn't load (404 or connection refused)
- Tasks fail immediately
- No browser view/screenshots
- Error messages in status panel
- Services show "failed" status

## Automated Test Scripts

**Run from Windows:**
- `test_deployment.bat` - Quick automated test
- `check_status.bat` - Detailed status check
- `diagnose_and_fix.bat` - Diagnostic tool

All scripts will test your deployment and show you exactly what's working and what needs attention!

