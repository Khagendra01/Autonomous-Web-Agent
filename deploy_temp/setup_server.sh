#!/bin/bash
# Quick setup script for Oracle Cloud Ubuntu server

echo "=========================================="
echo "🚀 Setting up Autonomous Web Agent Server"
echo "=========================================="

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Install Playwright browsers
echo "Installing Playwright browsers..."
playwright install chromium
playwright install-deps chromium

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cat > .env << EOF
# OpenAI API Key
OPENAI_API_KEY=your_openai_api_key_here

# Flask Secret Key (change this in production!)
SECRET_KEY=$(openssl rand -hex 32)
EOF
    echo "⚠️  Created .env file. Please edit it and add your API keys!"
fi

# Create templates directory if it doesn't exist
mkdir -p templates

# Make deploy scripts executable
chmod +x deploy/*.sh 2>/dev/null || true

echo ""
echo "=========================================="
echo "✅ Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit .env file and add your API keys: nano .env"
echo "2. Test locally: python web_app.py"
echo "3. For production deployment, follow deploy/README.md"
echo ""
echo "To start the driver server (in one terminal):"
echo "  source venv/bin/activate"
echo "  python -m src.drivers.grpc_playwright_server"
echo ""
echo "To start the web app (in another terminal):"
echo "  source venv/bin/activate"
echo "  python web_app.py"
echo ""

