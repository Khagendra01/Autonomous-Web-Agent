@echo off
REM Automated deployment script for Windows to Oracle Cloud
echo ==========================================
echo 🚀 Deploying to Oracle Cloud Ubuntu Server
echo ==========================================
echo.

set SERVER_IP=129.80.169.184
set SSH_KEY="C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key"
set SERVER_USER=ubuntu
set REMOTE_PATH=/home/ubuntu/Autonomous-Web-Agent

echo Step 1: Creating deployment package...
if exist deploy_temp rmdir /s /q deploy_temp
mkdir deploy_temp

echo Step 2: Copying files...
xcopy /E /I /Y src deploy_temp\src
xcopy /E /I /Y browser-use deploy_temp\browser-use
xcopy /E /I /Y templates deploy_temp\templates
xcopy /E /I /Y deploy deploy_temp\deploy
copy web_app.py deploy_temp\
copy requirements.txt deploy_temp\
copy setup_server.sh deploy_temp\
copy deploy_remote_setup.sh deploy_temp\ 2>nul
copy QUICK_START.md deploy_temp\
copy README.md deploy_temp\
copy .gitignore deploy_temp\

echo Step 3: Uploading to server...
scp -i %SSH_KEY% -r deploy_temp\* %SERVER_USER%@%SERVER_IP%:%REMOTE_PATH%/

if errorlevel 1 (
    echo.
    echo ❌ Upload failed! Please check:
    echo    - SSH key path is correct
    echo    - Server is accessible
    echo    - You have write permissions
    pause
    exit /b 1
)

echo.
echo Step 4: Running setup on server...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && chmod +x setup_server.sh deploy/*.sh deploy_remote_setup.sh 2>/dev/null; if [ -f deploy_remote_setup.sh ]; then ./deploy_remote_setup.sh; else ./setup_server.sh; fi"

echo.
echo Step 5: Setting up systemd services...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && sudo cp deploy/web-agent-driver.service /etc/systemd/system/ && sudo cp deploy/web-agent-app.service /etc/systemd/system/ && sudo systemctl daemon-reload"

echo.
echo Step 6: Configuring Nginx...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && sudo cp deploy/nginx.conf /etc/nginx/sites-available/web-agent && sudo ln -sf /etc/nginx/sites-available/web-agent /etc/nginx/sites-enabled/ && sudo rm -f /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx"

echo.
echo Step 7: Configuring firewall...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo ufw allow 80/tcp && sudo ufw allow 22/tcp"

echo.
echo Step 8: Starting services...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "cd %REMOTE_PATH% && sudo systemctl enable web-agent-driver web-agent-app && sudo systemctl start web-agent-driver && sleep 2 && sudo systemctl start web-agent-app"

echo.
echo ==========================================
echo ✅ Deployment Complete!
echo ==========================================
echo.
echo 🌐 Your application should be available at:
echo    http://%SERVER_IP%
echo.
echo 📝 Next steps:
echo    1. SSH to server and edit .env file:
echo       ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP%
echo       nano %REMOTE_PATH%/.env
echo.
echo    2. Add your OPENAI_API_KEY to .env
echo.
echo    3. Restart services:
echo       sudo systemctl restart web-agent-app
echo.
echo Press any key to check service status...
pause

echo.
echo Checking service status...
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl status web-agent-driver --no-pager -l | head -20"
echo.
ssh -i %SSH_KEY% %SERVER_USER%@%SERVER_IP% "sudo systemctl status web-agent-app --no-pager -l | head -20"

echo.
echo ==========================================
echo 🎉 Done! Check http://%SERVER_IP% in your browser
echo ==========================================
pause

