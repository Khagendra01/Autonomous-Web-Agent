@echo off
REM Quick test script to verify deployment is working

set SERVER_IP=129.80.169.184
set SSH_KEY="C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key"
set SERVER_USER=ubuntu

echo ==========================================
echo 🧪 Testing Deployment
echo ==========================================
echo.

echo [Test 1/5] Checking services...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active web-agent-driver 2>&1 | grep -q 'active' && echo '✅ Driver: RUNNING' || echo '❌ Driver: NOT RUNNING'"
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active web-agent-app 2>&1 | grep -q 'active' && echo '✅ Web App: RUNNING' || echo '❌ Web App: NOT RUNNING'"
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active nginx 2>&1 | grep -q 'active' && echo '✅ Nginx: RUNNING' || echo '❌ Nginx: NOT RUNNING'"
echo.

echo [Test 2/5] Testing web interface connectivity...
powershell -Command "try { $response = Invoke-WebRequest -Uri 'http://%SERVER_IP%' -TimeoutSec 5 -UseBasicParsing; if ($response.StatusCode -eq 200) { Write-Host '✅ Web interface is ACCESSIBLE' -ForegroundColor Green } else { Write-Host '⚠️  Web interface returned status:' $response.StatusCode -ForegroundColor Yellow } } catch { Write-Host '❌ Web interface is NOT accessible' -ForegroundColor Red; Write-Host '   Error:' $_.Exception.Message -ForegroundColor Red }"
echo.

echo [Test 3/5] Checking if API key is set...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd /home/ubuntu/Autonomous-Web-Agent && if grep -q 'OPENAI_API_KEY=sk-' .env 2>/dev/null; then echo '✅ API key is configured'; else echo '⚠️  API key not found or not configured'; fi"
echo.

echo [Test 4/5] Testing driver connection...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd /home/ubuntu/Autonomous-Web-Agent && source venv/bin/activate && timeout 2 python -c 'from src.drivers.grpc_client import DriverClient; c = DriverClient(); print(\"✅ Driver connection: OK\")' 2>&1 | grep -E '(OK|Error|ModuleNotFound)' || echo '⚠️  Driver test completed'"
echo.

echo [Test 5/5] Checking recent logs for errors...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo journalctl -u web-agent-app --since '5 minutes ago' --no-pager | grep -i error | tail -3 || echo '✅ No recent errors in web app logs'"
echo.

echo ==========================================
echo 📋 Test Summary
echo ==========================================
echo.
echo ✅ If all tests pass, your deployment is working!
echo.
echo 🌐 Open in browser: http://%SERVER_IP%
echo.
echo 📝 To test a task:
echo    1. Open http://%SERVER_IP% in your browser
echo    2. Enter a task like: "Navigate to google.com"
echo    3. Click "Start Task"
echo    4. Watch for browser screenshots to appear
echo.
pause

