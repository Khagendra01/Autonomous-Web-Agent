#!/bin/bash
# Script to fix common deployment issues on the server

set -e

echo "=========================================="
echo "🔧 Fixing Common Issues"
echo "=========================================="

cd /home/ubuntu/Autonomous-Web-Agent

# Fix 1: Ensure Python environment is set up
echo "[1/8] Checking Python environment..."
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Fix 2: Install/upgrade dependencies
echo "[2/8] Installing dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# Fix 3: Install Playwright browsers
echo "[3/8] Installing Playwright browsers..."
playwright install chromium --quiet
playwright install-deps chromium --quiet

# Fix 4: Fix permissions
echo "[4/8] Fixing permissions..."
sudo chown -R ubuntu:ubuntu .
chmod +x deploy/*.sh setup_server.sh 2>/dev/null || true

# Fix 5: Check and fix .env file
echo "[5/8] Checking .env file..."
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env << EOF
# OpenAI API Key - ADD YOUR KEY HERE!
OPENAI_API_KEY=your_openai_api_key_here

# Flask Secret Key
SECRET_KEY=$SECRET_KEY
EOF
    echo "⚠️  Created .env file. Please add your API key!"
fi

# Fix 6: Verify service files have correct paths
echo "[6/8] Verifying service files..."
if [ -f "/etc/systemd/system/web-agent-driver.service" ]; then
    # Check if paths are correct
    if ! grep -q "/home/ubuntu/Autonomous-Web-Agent" /etc/systemd/system/web-agent-driver.service; then
        echo "⚠️  Service file paths may be incorrect"
    fi
fi

# Fix 7: Test if services can start manually
echo "[7/8] Testing service startup..."
# Test driver
echo "Testing driver server..."
timeout 3 python -m src.drivers.grpc_playwright_server 2>&1 | head -5 || echo "Driver test completed (timeout expected)"

# Fix 8: Reload systemd
echo "[8/8] Reloading systemd..."
sudo systemctl daemon-reload

echo ""
echo "=========================================="
echo "✅ Fixes applied!"
echo "=========================================="
echo ""
echo "Now restart services:"
echo "  sudo systemctl restart web-agent-driver"
echo "  sudo systemctl restart web-agent-app"
echo ""
echo "Check status:"
echo "  sudo systemctl status web-agent-driver"
echo "  sudo systemctl status web-agent-app"
echo ""

