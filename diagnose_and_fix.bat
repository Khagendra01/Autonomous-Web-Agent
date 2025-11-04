@echo off
REM Diagnostic and fix script for deployment issues

set SERVER_IP=129.80.169.184
set SSH_KEY="C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key"
set SERVER_USER=ubuntu
set REMOTE_PATH=/home/ubuntu/Autonomous-Web-Agent

echo ==========================================
echo 🔍 Diagnosing Issues
echo ==========================================
echo.

echo [1] Checking service logs...
echo.
echo === Driver Service Logs (last 30 lines) ===
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo journalctl -u web-agent-driver -n 30 --no-pager"
echo.
echo === Web App Service Logs (last 30 lines) ===
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo journalctl -u web-agent-app -n 30 --no-pager"
echo.

echo [2] Checking Python environment...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && source venv/bin/activate && python --version && which python"
echo.

echo [3] Checking if dependencies are installed...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && source venv/bin/activate && pip list | findstr -i 'flask socketio playwright'"
echo.

echo [4] Checking file paths...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && ls -la web_app.py && ls -la src/drivers/grpc_playwright_server.py"
echo.

echo [5] Checking .env file...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && if [ -f .env ]; then echo '.env exists'; cat .env | grep -v 'API_KEY' | head -5; else echo '.env NOT FOUND'; fi"
echo.

echo [6] Testing manual execution...
echo Testing driver server...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && source venv/bin/activate && timeout 3 python -m src.drivers.grpc_playwright_server 2>&1 | head -20 || echo 'Driver test completed'"
echo.

echo ==========================================
echo 🔧 Attempting Fixes
echo ==========================================
echo.

echo [Fix 1] Reinstalling dependencies...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt --quiet"
echo.

echo [Fix 2] Installing Playwright browsers...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && source venv/bin/activate && playwright install chromium --quiet"
echo.

echo [Fix 3] Checking service file paths...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo cat /etc/systemd/system/web-agent-driver.service | grep -E 'WorkingDirectory|ExecStart'"
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo cat /etc/systemd/system/web-agent-app.service | grep -E 'WorkingDirectory|ExecStart'"
echo.

echo [Fix 4] Fixing permissions...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && sudo chown -R ubuntu:ubuntu . && chmod +x deploy/*.sh 2>/dev/null"
echo.

echo [Fix 5] Reloading systemd and restarting services...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl daemon-reload && sudo systemctl restart web-agent-driver && sleep 2 && sudo systemctl restart web-agent-app"
echo.

echo [Fix 6] Waiting for services to start...
timeout /t 5 /nobreak >nul
echo.

echo ==========================================
echo ✅ Final Status Check
echo ==========================================
echo.

ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active web-agent-driver && echo '✅ Driver: RUNNING' || echo '❌ Driver: NOT RUNNING'"
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active web-agent-app && echo '✅ Web App: RUNNING' || echo '❌ Web App: NOT RUNNING'"
echo.

echo If services are still not running, check the detailed logs above.
echo.
pause

