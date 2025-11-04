#!/bin/bash
# Stop all services for the web agent

set -e

echo "=========================================="
echo "🛑 Stopping Web Agent Services"
echo "=========================================="

# Stop Flask web app
echo "Stopping Flask web application..."
sudo systemctl stop web-agent-app

# Stop gRPC driver server
echo "Stopping gRPC driver server..."
sudo systemctl stop web-agent-driver

echo "✅ All services stopped!"

