#!/bin/bash
set -e

# ============================================================================
# Airis v1 — Client Box Installer
# Run on a fresh Ubuntu machine. Installs everything from scratch.
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/vshortt73/airis-v1/main/scripts/install.sh | bash
#   # or after cloning:
#   ./scripts/install.sh
# ============================================================================

echo ""
echo "============================================"
echo "  Airis v1 — Client Box Installer"
echo "============================================"
echo ""

# ── 1. System packages ──
echo "── Installing system packages ──"
sudo apt update -qq
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib git curl

# Ensure PostgreSQL is running
sudo systemctl enable --now postgresql
echo "  ✓ PostgreSQL installed and running"

# ── 2. pgvector ──
echo ""
echo "── Installing pgvector ──"
PG_VERSION=$(pg_config --version | grep -oP '\d+' | head -1)
sudo apt install -y "postgresql-${PG_VERSION}-pgvector" || {
    echo "Could not install pgvector for PostgreSQL $PG_VERSION."
    echo "Try: sudo apt install postgresql-*-pgvector"
    exit 1
}

# ── 3. Python venv ──
echo ""
echo "── Setting up Python environment ──"
VENV_PATH="/venv/airis"
if [ ! -d "$VENV_PATH" ]; then
    sudo mkdir -p /venv
    sudo chown "$(whoami):$(id -gn)" /venv
    python3 -m venv "$VENV_PATH"
    echo "  ✓ Created venv at $VENV_PATH"
else
    echo "  ✓ Venv already exists at $VENV_PATH"
fi

# ── 4. Clone repo ──
echo ""
echo "── Cloning Airis ──"
INSTALL_DIR="/airis-v1"
if [ ! -d "$INSTALL_DIR/.git" ]; then
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$(whoami):$(id -gn)" "$INSTALL_DIR"
    git clone https://github.com/vshortt73/airis-v1.git "$INSTALL_DIR"
    echo "  ✓ Cloned to $INSTALL_DIR"
else
    echo "  ✓ Repo already exists at $INSTALL_DIR, pulling latest"
    cd "$INSTALL_DIR" && git pull
fi

# ── 5. Python packages ──
echo ""
echo "── Installing Python packages ──"
source "$VENV_PATH/bin/activate"
echo "  Installing PyTorch (CPU-only)..."
pip install -q torch --index-url https://download.pytorch.org/whl/cpu
echo "  Installing Airis requirements..."
pip install -q -r "$INSTALL_DIR/requirements-client.txt"
echo "  ✓ Python packages installed"

# ── 6. Database setup ──
echo ""
echo "── Setting up database ──"
read -rsp "Choose a database password for airisuser: " DB_PASS < /dev/tty
echo ""

# Check if user/db already exist
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='airisuser'" | grep -q 1; then
    echo "  ✓ User airisuser already exists"
else
    sudo -u postgres psql -c "CREATE USER airisuser WITH PASSWORD '$DB_PASS';"
    echo "  ✓ Created user airisuser"
fi

if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='airisdb'" | grep -q 1; then
    echo "  ✓ Database airisdb already exists"
else
    sudo -u postgres psql -c "CREATE DATABASE airisdb OWNER airisuser;"
    echo "  ✓ Created database airisdb"
fi

sudo -u postgres psql -d airisdb -c "CREATE EXTENSION IF NOT EXISTS vector;" -q
sudo -u postgres psql -d airisdb -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;" -q
echo "  ✓ Extensions installed"

# ── 7. Embedding model ──
echo ""
echo "── Embedding model ──"
MODEL_DIR="/models/llm_models/huggingface/models/all-mpnet-base-v2"
if [ -d "$MODEL_DIR" ]; then
    echo "  ✓ Embedding model found at $MODEL_DIR"
else
    echo "  The embedding model (all-mpnet-base-v2, ~420MB) is not installed locally."
    echo "  You can either:"
    echo "    1. Copy it from the facility server:"
    echo "       scp -r user@server:/models/llm_models/huggingface/models/all-mpnet-base-v2 $MODEL_DIR"
    echo "    2. Let Airis download it from HuggingFace on first start (requires internet)"
    echo ""
    sudo mkdir -p "$(dirname $MODEL_DIR)"
    sudo chown -R "$(whoami):$(id -gn)" /models
fi

# ── 8. Deployment config ──
echo ""
echo "── Deployment configuration ──"
echo "The client box connects to a facility inference server (sglang)"
echo "running on the network. Enter the URL for that server."
echo ""
read -rp "Inference server URL [http://localhost:11434]: " INFERENCE_URL < /dev/tty
INFERENCE_URL="${INFERENCE_URL:-http://localhost:11434}"

read -rp "Airis server port [9000]: " AIRIS_PORT < /dev/tty
AIRIS_PORT="${AIRIS_PORT:-9000}"

# ── 9. Bootstrap ──
echo ""
echo "── Running Airis bootstrap ──"
export AIRIS_DB_PASSWORD="$DB_PASS"
export AIRIS_INFERENCE_URL="$INFERENCE_URL"
export AIRIS_PORT
"$INSTALL_DIR/scripts/bootstrap_airisdb.sh"

# ── 10. Install systemd service ──
echo ""
echo "── Installing systemd service ──"
sudo cp "$INSTALL_DIR/scripts/airis.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable airis
echo "  ✓ Service installed and enabled"

echo ""
echo "============================================"
echo "  ✓ Airis installation complete!"
echo "============================================"
echo ""
echo "  Start:   sudo systemctl start airis"
echo "  Stop:    sudo systemctl stop airis"
echo "  Logs:    sudo journalctl -u airis -f"
echo "  Manual:  $INSTALL_DIR/scripts/start.sh"
echo ""
