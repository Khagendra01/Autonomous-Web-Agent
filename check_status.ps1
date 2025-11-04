# PowerShell status check script

$SERVER_IP = "129.80.169.184"
$SSH_KEY = "C:\Users\Khage\Downloads\ssh-key-2025-11-01 (2).key"
$SERVER_USER = "ubuntu"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "🔍 Checking Deployment Status" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Test 1: Server connectivity
Write-Host "[1/6] Testing server connectivity..." -ForegroundColor Yellow
$ping = Test-Connection -ComputerName $SERVER_IP -Count 1 -Quiet
if ($ping) {
    Write-Host "✅ Server is reachable" -ForegroundColor Green
} else {
    Write-Host "❌ Server is not reachable!" -ForegroundColor Red
    Write-Host "   Check if server is running and accessible" -ForegroundColor Red
}
Write-Host ""

# Test 2: SSH connection
Write-Host "[2/6] Checking SSH connection..." -ForegroundColor Yellow
try {
    $sshTest = ssh -i $SSH_KEY -o ConnectTimeout=5 "${SERVER_USER}@${SERVER_IP}" "echo 'SSH OK'" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ SSH connection successful" -ForegroundColor Green
    } else {
        Write-Host "❌ Cannot connect via SSH!" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ SSH connection failed!" -ForegroundColor Red
}
Write-Host ""

# Test 3: Driver service
Write-Host "[3/6] Checking gRPC Driver Service..." -ForegroundColor Yellow
$driverStatus = ssh -i $SSH_KEY "${SERVER_USER}@${SERVER_IP}" "sudo systemctl is-active web-agent-driver" 2>&1
if ($driverStatus -match "active") {
    Write-Host "✅ Driver service is RUNNING" -ForegroundColor Green
} else {
    Write-Host "❌ Driver service is NOT running" -ForegroundColor Red
    Write-Host "   Status: $driverStatus" -ForegroundColor Red
}
Write-Host ""

# Test 4: Web app service
Write-Host "[4/6] Checking Web App Service..." -ForegroundColor Yellow
$appStatus = ssh -i $SSH_KEY "${SERVER_USER}@${SERVER_IP}" "sudo systemctl is-active web-agent-app" 2>&1
if ($appStatus -match "active") {
    Write-Host "✅ Web app service is RUNNING" -ForegroundColor Green
} else {
    Write-Host "❌ Web app service is NOT running" -ForegroundColor Red
    Write-Host "   Status: $appStatus" -ForegroundColor Red
}
Write-Host ""

# Test 5: Nginx
Write-Host "[5/6] Checking Nginx..." -ForegroundColor Yellow
$nginxStatus = ssh -i $SSH_KEY "${SERVER_USER}@${SERVER_IP}" "sudo systemctl is-active nginx" 2>&1
if ($nginxStatus -match "active") {
    Write-Host "✅ Nginx is RUNNING" -ForegroundColor Green
} else {
    Write-Host "❌ Nginx is NOT running" -ForegroundColor Red
}
Write-Host ""

# Test 6: Web interface
Write-Host "[6/6] Testing Web Interface..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://$SERVER_IP" -TimeoutSec 5 -UseBasicParsing -ErrorAction SilentlyContinue
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ Web interface is ACCESSIBLE" -ForegroundColor Green
        Write-Host "   Open: http://$SERVER_IP in your browser" -ForegroundColor Cyan
    } else {
        Write-Host "⚠️  Web interface returned status: $($response.StatusCode)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ Web interface is NOT accessible" -ForegroundColor Red
    Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "   Try opening: http://$SERVER_IP in your browser" -ForegroundColor Yellow
}
Write-Host ""

# Detailed status
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "📊 Detailed Status Report" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Driver Service Details:" -ForegroundColor Yellow
ssh -i $SSH_KEY "${SERVER_USER}@${SERVER_IP}" "sudo systemctl status web-agent-driver --no-pager -l | head -15"
Write-Host ""

Write-Host "Web App Service Details:" -ForegroundColor Yellow
ssh -i $SSH_KEY "${SERVER_USER}@${SERVER_IP}" "sudo systemctl status web-agent-app --no-pager -l | head -15"
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "🔍 Quick Troubleshooting" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To view logs:" -ForegroundColor Yellow
Write-Host "  ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP}" -ForegroundColor Gray
Write-Host "  sudo journalctl -u web-agent-app -f" -ForegroundColor Gray
Write-Host ""
Write-Host "To restart services:" -ForegroundColor Yellow
Write-Host "  ssh -i `"$SSH_KEY`" ${SERVER_USER}@${SERVER_IP}" -ForegroundColor Gray
Write-Host "  sudo systemctl restart web-agent-app" -ForegroundColor Gray
Write-Host "  sudo systemctl restart web-agent-driver" -ForegroundColor Gray
Write-Host ""

Read-Host "Press Enter to exit"

