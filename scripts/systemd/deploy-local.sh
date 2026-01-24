#!/bin/bash
# Deploy Iris llama.cpp service on localhost (iris-desktop)
# Run this script with sudo

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

echo "=== Iris Local Services Deployment ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo $0"
    exit 1
fi

# Stop any running manual instance
echo "Stopping any running llama-server on port 11434..."
pkill -f "llama-server.*11434" 2>/dev/null || true
sleep 2

# Copy service file
echo "Installing service file..."
cp "$SCRIPT_DIR/iris-llama.service" "$SYSTEMD_DIR/"
chmod 644 "$SYSTEMD_DIR/iris-llama.service"

# Install sudoers config for passwordless service management
echo "Installing sudoers config for captain user..."
cp "$SCRIPT_DIR/iris-sudoers" /etc/sudoers.d/iris
chmod 440 /etc/sudoers.d/iris
# Validate sudoers syntax
if visudo -c -f /etc/sudoers.d/iris; then
    echo "✓ Sudoers config installed"
else
    echo "✗ Sudoers config has syntax errors - removing"
    rm /etc/sudoers.d/iris
fi

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service
echo "Enabling iris-llama service..."
systemctl enable iris-llama.service

# Start service
echo ""
echo "Starting iris-llama service..."
systemctl start iris-llama.service
sleep 5

# Show status
echo ""
echo "=== Service Status ==="
systemctl status iris-llama.service --no-pager -l || true

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Service installed and started:"
echo "  - iris-llama (port 11434) - Qwen3-32B on GPU 0"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status iris-llama"
echo "  sudo systemctl restart iris-llama"
echo "  sudo journalctl -u iris-llama -f"
echo ""
