@echo off
REM Quick fix script for the service issues

set SERVER_IP=129.80.169.184
set SSH_KEY="C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key"
set SERVER_USER=ubuntu
set REMOTE_PATH=/home/ubuntu/Autonomous-Web-Agent

echo ==========================================
echo 🔧 Fixing Service Issues
echo ==========================================
echo.
echo The issue: Services are not using the virtual environment correctly
echo.

echo [1/4] Installing missing dependencies...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt"
echo.

echo [2/4] Verifying dependencies are installed...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && source venv/bin/activate && pip list | grep -E 'grpc|flask|playwright'"
echo.

echo [3/4] Testing if services can start manually...
echo Testing driver...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && source venv/bin/activate && timeout 2 python -m src.drivers.grpc_playwright_server 2>&1 | head -5 || echo 'Timeout expected - service is working'"
echo.

echo [4/4] Restarting services...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl daemon-reload && sudo systemctl restart web-agent-driver && sleep 3 && sudo systemctl restart web-agent-app"
echo.

echo Waiting for services to initialize...
timeout /t 5 /nobreak >nul
echo.

echo ==========================================
echo ✅ Checking Final Status
echo ==========================================
echo.

ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active web-agent-driver && echo '✅ Driver: RUNNING' || echo '❌ Driver: FAILED - check logs with: sudo journalctl -u web-agent-driver -n 30'"
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active web-agent-app && echo '✅ Web App: RUNNING' || echo '❌ Web App: FAILED - check logs with: sudo journalctl -u web-agent-app -n 30'"
echo.

echo If services are still failing, run:
echo   diagnose_and_fix.bat
echo.
pause

