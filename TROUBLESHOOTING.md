# 🔧 Troubleshooting Guide

## Current Issue: "Exception calling application"

The error shows that the driver's `Observe()` method is being called, but the browser hasn't been initialized yet (`_page is None`).

## What's Happening

1. ✅ Task is submitted
2. ✅ Bootstrap node runs (tries to infer URL from instruction)
3. ⚠️ Bootstrap calls `Init()` to initialize browser
4. ❌ Then `Observe()` is called but browser isn't ready

## Quick Fix: Test Directly

**Test if driver initialization works:**
```bash
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184
cd /home/ubuntu/Autonomous-Web-Agent
source venv/bin/activate
python3 -c "from src.drivers.grpc_client import DriverClient; c = DriverClient(); r = c.init('YouTube', 'https://youtube.com'); print('Init:', r.ok)"
```

## Expected Behavior When Working

### ✅ Working Correctly:

1. **Status Updates:**
   - "STARTING" → "RUNNING" (within 5-10 seconds)
   - Status messages appear

2. **Browser View:**
   - First screenshot appears within 10 seconds
   - Screenshots update every second
   - You see the browser navigating

3. **Screenshot Count:**
   - Increases from 0 → 1 → 2 → 3...

4. **Task Completion:**
   - Status shows "COMPLETED"
   - Browser view shows final state

### ❌ Not Working:

- Status stuck on "STARTING" for 30+ seconds
- No screenshots appear
- Screenshot count stays at 0
- Error messages in status

## How to Know It's Working

**Watch for these signs:**

1. **Within 5 seconds:**
   - Status changes from "STARTING" to "RUNNING"
   - First status message appears

2. **Within 10 seconds:**
   - First screenshot appears in browser view
   - Screenshot count changes from 0 to 1

3. **Every second after:**
   - New screenshot appears
   - Screenshot count increases
   - You see the browser navigating to YouTube

4. **When task completes:**
   - Status shows "COMPLETED"
   - Screenshot count stops increasing
   - Browser view shows final page

## Check Current Status

**In your browser, watch for:**
- Status panel updates
- Browser view panel shows images
- Screenshot count increases

**If stuck on "STARTING":**
- Wait 30 seconds
- If still stuck, check logs (see below)

## View Real-Time Status

**SSH to server and watch logs:**
```bash
ssh -i "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key" ubuntu@129.80.169.184
sudo journalctl -u web-agent-app -f
```

**Watch for:**
- Bootstrap messages
- "Driver initialized" message
- "OBSERVE" messages
- Any error messages

## Quick Test

**Try a simpler task first:**
- Task: `"Navigate to google.com"`
- This is simpler and should work faster

**Watch for browser view to update within 10 seconds!**

