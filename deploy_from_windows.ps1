# PowerShell deployment script for Oracle Cloud Ubuntu Server

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "🚀 Deploying to Oracle Cloud Ubuntu Server" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$SERVER_IP = "129.80.169.184"
$SSH_KEY = "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key"
$SERVER_USER = "ubuntu"
$REMOTE_PATH = "/home/ubuntu/Autonomous-Web-Agent"

# Step 1: Create deployment package
Write-Host "Step 1: Creating deployment package..." -ForegroundColor Yellow
if (Test-Path "deploy_temp") {
    Remove-Item -Recurse -Force "deploy_temp"
}
New-Item -ItemType Directory -Path "deploy_temp" | Out-Null

# Step 2: Copy files
Write-Host "Step 2: Copying files..." -ForegroundColor Yellow
$filesToCopy = @(
    "src",
    "browser-use",
    "templates",
    "deploy",
    "web_app.py",
    "requirements.txt",
    "setup_server.sh",
    "deploy_remote_setup.sh",
    "QUICK_START.md",
    "README.md",
    ".gitignore"
)

foreach ($item in $filesToCopy) {
    if (Test-Path $item) {
        if (Test-Path $item -PathType Container) {
            Copy-Item -Path $item -Destination "deploy_temp\$item" -Recurse -Force
        } else {
            Copy-Item -Path $item -Destination "deploy_temp\$item" -Force
        }
        Write-Host "  ✓ Copied $item" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ Skipped $item (not found)" -ForegroundColor Yellow
    }
}

# Step 3: Upload to server
Write-Host ""
Write-Host "Step 3: Uploading to server..." -ForegroundColor Yellow
$scpCommand = "scp -i `"$SSH_KEY`" -r deploy_temp\* ${SERVER_USER}@${SERVER_IP}:${REMOTE_PATH}/"
Invoke-Expression $scpCommand

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ Upload failed! Please check:" -ForegroundColor Red
    Write-Host "   - SSH key path is correct" -ForegroundColor Red
    Write-Host "   - Server is accessible" -ForegroundColor Red
    Write-Host "   - You have write permissions" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "  ✓ Upload complete" -ForegroundColor Green

# Step 4: Run setup on server
Write-Host ""
Write-Host "Step 4: Running setup on server..." -ForegroundColor Yellow
$setupCommand = "cd $REMOTE_PATH && chmod +x setup_server.sh deploy/*.sh deploy_remote_setup.sh 2>/dev/null; if [ -f deploy_remote_setup.sh ]; then ./deploy_remote_setup.sh; else ./setup_server.sh; fi"
$sshCommand = "ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP} `"$setupCommand`""
Invoke-Expression $sshCommand

# Step 5: Setup systemd services
Write-Host ""
Write-Host "Step 5: Setting up systemd services..." -ForegroundColor Yellow
$serviceCommand = "cd $REMOTE_PATH && sudo cp deploy/web-agent-driver.service /etc/systemd/system/ && sudo cp deploy/web-agent-app.service /etc/systemd/system/ && sudo systemctl daemon-reload"
$sshCommand = "ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP} `"$serviceCommand`""
Invoke-Expression $sshCommand
Write-Host "  ✓ Services configured" -ForegroundColor Green

# Step 6: Configure Nginx
Write-Host ""
Write-Host "Step 6: Configuring Nginx..." -ForegroundColor Yellow
$nginxCommand = "cd $REMOTE_PATH && sudo cp deploy/nginx.conf /etc/nginx/sites-available/web-agent && sudo ln -sf /etc/nginx/sites-available/web-agent /etc/nginx/sites-enabled/ && sudo rm -f /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx"
$sshCommand = "ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP} `"$nginxCommand`""
Invoke-Expression $sshCommand
Write-Host "  ✓ Nginx configured" -ForegroundColor Green

# Step 7: Configure firewall
Write-Host ""
Write-Host "Step 7: Configuring firewall..." -ForegroundColor Yellow
$firewallCommand = "sudo ufw allow 80/tcp && sudo ufw allow 22/tcp"
$sshCommand = "ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP} `"$firewallCommand`""
Invoke-Expression $sshCommand
Write-Host "  ✓ Firewall configured" -ForegroundColor Green

# Step 8: Start services
Write-Host ""
Write-Host "Step 8: Starting services..." -ForegroundColor Yellow
$startCommand = "cd $REMOTE_PATH && sudo systemctl enable web-agent-driver web-agent-app && sudo systemctl start web-agent-driver && sleep 2 && sudo systemctl start web-agent-app"
$sshCommand = "ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP} `"$startCommand`""
Invoke-Expression $sshCommand
Write-Host "  ✓ Services started" -ForegroundColor Green

# Step 9: Check status
Write-Host ""
Write-Host "Step 9: Checking service status..." -ForegroundColor Yellow
$statusCommand = "sudo systemctl status web-agent-driver --no-pager -l | head -20"
$sshCommand = "ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP} `"$statusCommand`""
Invoke-Expression $sshCommand

Write-Host ""
$statusCommand = "sudo systemctl status web-agent-app --no-pager -l | head -20"
$sshCommand = "ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP} `"$statusCommand`""
Invoke-Expression $sshCommand

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "✅ Deployment Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "🌐 Your application should be available at:" -ForegroundColor Cyan
Write-Host "   http://$SERVER_IP" -ForegroundColor White
Write-Host ""
Write-Host "📝 Next steps:" -ForegroundColor Yellow
Write-Host "   1. SSH to server and edit .env file:" -ForegroundColor White
Write-Host "      ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP}" -ForegroundColor Gray
Write-Host "      nano $REMOTE_PATH/.env" -ForegroundColor Gray
Write-Host ""
Write-Host "   2. Add your OPENAI_API_KEY to .env" -ForegroundColor White
Write-Host ""
Write-Host "   3. Restart services:" -ForegroundColor White
Write-Host "      sudo systemctl restart web-agent-app" -ForegroundColor Gray
Write-Host ""
Write-Host "Press Enter to exit..."
Read-Host

