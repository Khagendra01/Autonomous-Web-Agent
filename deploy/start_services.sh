#!/bin/bash
# Start all services for the web agent

set -e

echo "=========================================="
echo "🚀 Starting Web Agent Services"
echo "=========================================="

# Start gRPC driver server
echo "Starting gRPC driver server..."
sudo systemctl start web-agent-driver
sudo systemctl enable web-agent-driver

# Start Flask web app
echo "Starting Flask web application..."
sudo systemctl start web-agent-app
sudo systemctl enable web-agent-app

# Reload nginx
echo "Reloading Nginx..."
sudo systemctl reload nginx

# Show status
echo ""
echo "Service Status:"
sudo systemctl status web-agent-driver --no-pager -l
echo ""
sudo systemctl status web-agent-app --no-pager -l

echo ""
echo "✅ All services started!"
echo "🌐 Web interface should be available at: http://$(curl -s ifconfig.me || echo 'YOUR_SERVER_IP')"

