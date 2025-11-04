#!/bin/bash
# Remote setup script that runs on the server
# This is called automatically by the deployment scripts

set -e

echo "=========================================="
echo "🔧 Setting up Autonomous Web Agent"
echo "=========================================="

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip --quiet

# Install requirements
echo "📥 Installing Python dependencies..."
pip install -r requirements.txt --quiet

# Install Playwright browsers
echo "🎭 Installing Playwright browsers..."
playwright install chromium --quiet
playwright install-deps chromium --quiet

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "📝 Creating .env file..."
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env << EOF
# OpenAI API Key - ADD YOUR KEY HERE!
OPENAI_API_KEY=your_openai_api_key_here

# Flask Secret Key
SECRET_KEY=$SECRET_KEY
EOF
    echo "⚠️  Created .env file. Please edit it and add your API keys!"
fi

# Create templates directory if it doesn't exist
mkdir -p templates

# Make deploy scripts executable
chmod +x deploy/*.sh 2>/dev/null || true
chmod +x setup_server.sh 2>/dev/null || true

# Fix permissions
chown -R $USER:$USER . 2>/dev/null || true

echo ""
echo "=========================================="
echo "✅ Setup complete!"
echo "=========================================="

