#!/bin/bash
# Deployment script for Oracle Cloud Ubuntu server

set -e

echo "=========================================="
echo "🚀 Deploying Autonomous Web Agent"
echo "=========================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Update system
echo -e "${YELLOW}📦 Updating system packages...${NC}"
sudo apt-get update
sudo apt-get upgrade -y

# Install Python and dependencies
echo -e "${YELLOW}🐍 Installing Python and dependencies...${NC}"
sudo apt-get install -y python3 python3-pip python3-venv python3-dev
sudo apt-get install -y build-essential
sudo apt-get install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2

# Install Nginx
echo -e "${YELLOW}🌐 Installing Nginx...${NC}"
sudo apt-get install -y nginx

# Install Playwright browsers (if needed)
echo -e "${YELLOW}🎭 Installing Playwright browsers...${NC}"
if [ -d "venv" ]; then
    source venv/bin/activate
    playwright install chromium
    playwright install-deps chromium
fi

# Create systemd service directory if it doesn't exist
sudo mkdir -p /etc/systemd/system

# Set permissions
echo -e "${YELLOW}🔐 Setting permissions...${NC}"
chmod +x deploy/start_services.sh
chmod +x deploy/stop_services.sh

echo -e "${GREEN}✅ Deployment preparation complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Copy systemd service files: sudo cp deploy/*.service /etc/systemd/system/"
echo "2. Copy nginx config: sudo cp deploy/nginx.conf /etc/nginx/sites-available/web-agent"
echo "3. Enable nginx site: sudo ln -s /etc/nginx/sites-available/web-agent /etc/nginx/sites-enabled/"
echo "4. Start services: ./deploy/start_services.sh"
echo "5. Check status: sudo systemctl status web-agent-driver web-agent-app"

