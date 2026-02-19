#!/bin/bash
# Setup nightly memory creation cron job

# Database password — must be set in environment
if [ -z "$AIRIS_DB_PASSWORD" ]; then
    echo "ERROR: AIRIS_DB_PASSWORD not set. Export it before running this script."
    exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NIGHTLY_SCRIPT="$SCRIPT_DIR/nightly_memory_creation.sh"

echo "=========================================="
echo "NIGHTLY MEMORY CREATION - CRON SETUP"
echo "=========================================="
echo ""

# Check if script exists
if [ ! -f "$NIGHTLY_SCRIPT" ]; then
    echo "ERROR: Nightly script not found: $NIGHTLY_SCRIPT"
    exit 1
fi

# Check if already executable
if [ ! -x "$NIGHTLY_SCRIPT" ]; then
    echo "Making script executable..."
    chmod +x "$NIGHTLY_SCRIPT"
fi

# Proposed cron schedule
echo "Proposed cron job (runs at 3:00 AM daily):"
echo ""
echo "0 3 * * * AIRIS_DB_PASSWORD=\$AIRIS_DB_PASSWORD /iris-v3/scripts/nightly_memory_creation.sh >> /iris-v3/logs/memory_creation/cron.log 2>&1"
echo ""
echo "=========================================="
echo "INSTALLATION OPTIONS:"
echo "=========================================="
echo ""
echo "Option 1: Install automatically (current user)"
echo "  This will add the cron job to your crontab"
echo ""
echo "Option 2: Manual installation"
echo "  Copy the cron line above and run: crontab -e"
echo ""
read -p "Install automatically? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Get current crontab
    TEMP_CRON=$(mktemp)
    crontab -l > "$TEMP_CRON" 2>/dev/null || true

    # Check if already exists
    if grep -q "nightly_memory_creation.sh" "$TEMP_CRON"; then
        echo ""
        echo "WARNING: Nightly memory creation job already exists in crontab"
        echo "Existing entry:"
        grep "nightly_memory_creation.sh" "$TEMP_CRON"
        echo ""
        read -p "Replace with new entry? (y/n): " -n 1 -r
        echo ""

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            # Remove old entry
            grep -v "nightly_memory_creation.sh" "$TEMP_CRON" > "$TEMP_CRON.tmp"
            mv "$TEMP_CRON.tmp" "$TEMP_CRON"
        else
            echo "Keeping existing entry. Aborting."
            rm "$TEMP_CRON"
            exit 0
        fi
    fi

    # Add new entry
    echo "0 3 * * * AIRIS_DB_PASSWORD=\$AIRIS_DB_PASSWORD /iris-v3/scripts/nightly_memory_creation.sh >> /iris-v3/logs/memory_creation/cron.log 2>&1" >> "$TEMP_CRON"

    # Install crontab
    crontab "$TEMP_CRON"
    rm "$TEMP_CRON"

    echo ""
    echo "✓ Cron job installed successfully"
    echo ""
    echo "Current crontab:"
    crontab -l | grep "nightly_memory_creation"
else
    echo ""
    echo "Skipping automatic installation"
    echo "To install manually, run: crontab -e"
    echo "Then add the cron line shown above"
fi

echo ""
echo "=========================================="
echo "IMPORTANT: SUDO CONFIGURATION"
echo "=========================================="
echo ""
echo "The script needs passwordless sudo for systemctl."
echo "Add this line to /etc/sudoers (use: sudo visudo):"
echo ""
echo "$(whoami) ALL=(ALL) NOPASSWD: /bin/systemctl"
echo ""
echo "Or for specific commands only:"
echo "$(whoami) ALL=(ALL) NOPASSWD: /bin/systemctl start ollama, /bin/systemctl stop ollama, /bin/systemctl start ollama-vision, /bin/systemctl stop ollama-vision, /bin/systemctl is-active ollama, /bin/systemctl is-active ollama-vision"
echo ""
echo "=========================================="
echo "TESTING"
echo "=========================================="
echo ""
echo "To test the script manually (without waiting for 3am):"
echo "  AIRIS_DB_PASSWORD=\$AIRIS_DB_PASSWORD $NIGHTLY_SCRIPT"
echo ""
echo "To test a dry run (checks only, no memory creation):"
echo "  You can manually verify each phase by reading the script"
echo ""
