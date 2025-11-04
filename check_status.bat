@echo off
REM Quick status check script for deployed application

set SERVER_IP=129.80.169.184
set SSH_KEY="C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key"
set SERVER_USER=ubuntu

echo ==========================================
echo 🔍 Checking Deployment Status
echo ==========================================
echo.

echo [1/6] Testing server connectivity...
ping -n 1 %SERVER_IP% >nul 2>&1
if errorlevel 1 (
    echo ❌ Server is not reachable!
    echo    Check if server is running and accessible
) else (
    echo ✅ Server is reachable
)
echo.

echo [2/6] Checking SSH connection...
ssh -i %SSH_KEY% -o ConnectTimeout=5 %SERVER_USER%@%SERVER_IP% "echo 'SSH connection successful'" >nul 2>&1
if errorlevel 1 (
    echo ❌ Cannot connect via SSH!
    echo    Check SSH key path and server accessibility
) else (
    echo ✅ SSH connection successful
)
echo.

echo [3/6] Checking gRPC Driver Service...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active web-agent-driver" >temp_status.txt 2>&1
findstr /C:"active" temp_status.txt >nul
if errorlevel 1 (
    echo ❌ Driver service is NOT running
    echo    Status:
    type temp_status.txt
) else (
    echo ✅ Driver service is RUNNING
)
del temp_status.txt 2>nul
echo.

echo [4/6] Checking Web App Service...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active web-agent-app" >temp_status.txt 2>&1
findstr /C:"active" temp_status.txt >nul
if errorlevel 1 (
    echo ❌ Web app service is NOT running
    echo    Status:
    type temp_status.txt
) else (
    echo ✅ Web app service is RUNNING
)
del temp_status.txt 2>nul
echo.

echo [5/6] Checking Nginx...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl is-active nginx" >temp_status.txt 2>&1
findstr /C:"active" temp_status.txt >nul
if errorlevel 1 (
    echo ❌ Nginx is NOT running
) else (
    echo ✅ Nginx is RUNNING
)
del temp_status.txt 2>nul
echo.

echo [6/6] Testing Web Interface...
curl -s -o nul -w "HTTP Status: %%{http_code}\n" --connect-timeout 5 http://%SERVER_IP%/ >temp_http.txt 2>&1
findstr /C:"200" temp_http.txt >nul
if errorlevel 1 (
    echo ❌ Web interface is NOT accessible
    echo    Response:
    type temp_http.txt
    echo.
    echo    Try opening: http://%SERVER_IP% in your browser
) else (
    echo ✅ Web interface is ACCESSIBLE
    echo    Open: http://%SERVER_IP% in your browser
)
del temp_http.txt 2>nul
echo.

echo ==========================================
echo 📊 Detailed Status Report
echo ==========================================
echo.
echo Driver Service Details:
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl status web-agent-driver --no-pager -l | head -15"
echo.
echo Web App Service Details:
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl status web-agent-app --no-pager -l | head -15"
echo.

echo ==========================================
echo 🔍 Quick Troubleshooting
echo ==========================================
echo.
echo To view logs, run:
echo   ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP%
echo   sudo journalctl -u web-agent-app -f
echo.
echo To restart services:
echo   ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP%
echo   sudo systemctl restart web-agent-app
echo   sudo systemctl restart web-agent-driver
echo.

pause

