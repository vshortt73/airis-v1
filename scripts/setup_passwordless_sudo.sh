#!/bin/bash
# Setup passwordless sudo for Ollama service management
# This is required for the nightly memory creation cron job

set -e

echo "=========================================="
echo "PASSWORDLESS SUDO SETUP"
echo "=========================================="
echo ""
echo "This script will configure passwordless sudo for systemctl commands"
echo "needed by the nightly memory creation cron job."
echo ""

# Get current user
CURRENT_USER=$(whoami)

echo "Current user: $CURRENT_USER"
echo ""

# Create sudoers.d entry (safer than editing /etc/sudoers directly)
SUDOERS_FILE="/etc/sudoers.d/iris-memory-cron"

echo "Creating sudoers rule: $SUDOERS_FILE"
echo ""

# Create temporary file with the rule
TEMP_FILE=$(mktemp)
cat > "$TEMP_FILE" << EOF
# Passwordless sudo for Iris nightly memory creation
# Allows systemctl management of Ollama services without password
# Created by setup_passwordless_sudo.sh on $(date)

$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl start ollama
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl stop ollama
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl start ollama-vision
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl stop ollama-vision
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl is-active ollama
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl is-active ollama-vision
EOF

echo "Sudoers rule contents:"
echo "---"
cat "$TEMP_FILE"
echo "---"
echo ""

# Validate syntax with visudo
echo "Validating syntax..."
if ! visudo -c -f "$TEMP_FILE" 2>&1; then
    echo "ERROR: Syntax validation failed"
    rm "$TEMP_FILE"
    exit 1
fi
echo "✓ Syntax valid"
echo ""

# Install the file (requires sudo)
echo "Installing sudoers rule (requires your password)..."
sudo install -m 0440 "$TEMP_FILE" "$SUDOERS_FILE"
rm "$TEMP_FILE"

echo "✓ Sudoers rule installed"
echo ""

# Test it
echo "Testing passwordless sudo..."
if sudo -n systemctl is-active ollama >/dev/null 2>&1 || sudo -n systemctl is-active ollama 2>&1 | grep -q "inactive"; then
    echo "✓ Passwordless sudo working!"
else
    echo "✗ Test failed - something went wrong"
    echo "You may need to run: sudo visudo -f $SUDOERS_FILE"
    exit 1
fi

echo ""
echo "=========================================="
echo "✓ SETUP COMPLETE"
echo "=========================================="
echo ""
echo "Passwordless sudo is now configured for:"
echo "  - systemctl start/stop ollama"
echo "  - systemctl start/stop ollama-vision"
echo "  - systemctl is-active checks"
echo ""
echo "The nightly memory creation cron job will now work unattended."
echo ""
echo "To remove this configuration later, run:"
echo "  sudo rm $SUDOERS_FILE"
echo ""
