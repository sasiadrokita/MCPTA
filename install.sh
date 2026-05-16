#!/bin/bash
# ============================================================
#  Antigravity - Main Installer Script
#  This script runs ON the Raspberry Pi (via SSH from setup_pi.sh).
#  Do NOT run this manually unless you know what you're doing.
# ============================================================

set -e

PI_USER="mateusz"
INSTALL_DIR="/home/${PI_USER}/MCPTA"
VENV="$INSTALL_DIR/venv"
GITHUB_REPO="https://github.com/sasiadrokita/MCPTA.git"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[OK]${NC} $1"; }
step() { echo ""; echo -e "${YELLOW}>>> $1${NC}"; }

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🛸 Antigravity Installer                   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""

# --- 1. System update ---
step "Updating system packages (this may take a few minutes)..."
sudo apt-get update -y
sudo apt-get upgrade -y
log "System updated."

# --- 2. Install system dependencies ---
step "Installing system dependencies..."
sudo apt-get install -y python3 python3-venv python3-pip redis-server git curl
sudo systemctl enable redis-server
sudo systemctl start redis-server
log "Dependencies installed."

# --- 3. Clone repository ---
step "Cloning Antigravity repository from GitHub..."
if [ -d "$INSTALL_DIR" ]; then
    echo "  Directory already exists, pulling latest changes..."
    cd "$INSTALL_DIR" && git pull
else
    git clone "$GITHUB_REPO" "$INSTALL_DIR"
fi
log "Repository ready at $INSTALL_DIR"

# --- 4. Move GCP key into project ---
step "Setting up Google Cloud credentials..."
if [ -f "$HOME/gcp-backup-key.json" ]; then
    mv "$HOME/gcp-backup-key.json" "$INSTALL_DIR/gcp-backup-key.json"
    log "GCP key moved to project directory."
else
    echo -e "${YELLOW}[WARN] gcp-backup-key.json not found in home dir, skipping.${NC}"
fi

# --- 5. Create Python venv and install requirements ---
step "Creating Python virtual environment..."
cd "$INSTALL_DIR"
python3 -m venv venv
log "Virtual environment created."

step "Installing Python dependencies (pip install)..."
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r requirements.txt --quiet
"$VENV/bin/pip" install google-cloud-storage --quiet
log "Python packages installed."

# --- 6. Restore data from Google Cloud backup ---
step "Restoring latest backup from Google Cloud Storage..."
"$VENV/bin/python" "$INSTALL_DIR/cloud_restore.py" --auto
log "Data restored from cloud backup."

# --- 7. Install systemd service for the Bot ---
step "Configuring bot as system service (auto-start on boot)..."
sudo tee /etc/systemd/system/antigravity.service > /dev/null <<EOF
[Unit]
Description=Antigravity AI Trading Engine
After=network-online.target redis.service
Wants=network-online.target

[Service]
Type=simple
User=${PI_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python autonomic_engine.py
Restart=always
RestartSec=15
StandardOutput=append:${INSTALL_DIR}/engine.log
StandardError=append:${INSTALL_DIR}/engine.log

[Install]
WantedBy=multi-user.target
EOF
log "Bot service file created."

# --- 8. Install systemd service for the Dashboard ---
step "Configuring dashboard as system service..."
sudo tee /etc/systemd/system/antigravity-dashboard.service > /dev/null <<EOF
[Unit]
Description=Antigravity Dashboard
After=network-online.target antigravity.service
Wants=network-online.target

[Service]
Type=simple
User=${PI_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python dashboard.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
log "Dashboard service file created."

# --- 9. Enable and start services ---
step "Enabling and starting all services..."
sudo systemctl daemon-reload
sudo systemctl enable antigravity.service
sudo systemctl enable antigravity-dashboard.service
sudo systemctl start antigravity.service
sleep 5
sudo systemctl start antigravity-dashboard.service
log "All services started."

# --- Final Status Report ---
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ Antigravity Installation Complete!              ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Bot status:       $(systemctl is-active antigravity.service)                          ║${NC}"
echo -e "${GREEN}║  Dashboard status: $(systemctl is-active antigravity-dashboard.service)                          ║${NC}"
echo -e "${GREEN}║  Dashboard URL:    http://MCPTA.local:5000           ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║  Useful commands:                                    ║${NC}"
echo -e "${GREEN}║  sudo systemctl status antigravity.service           ║${NC}"
echo -e "${GREEN}║  sudo systemctl restart antigravity-dashboard.service║${NC}"
echo -e "${GREEN}║  tail -f ~/MCPTA/engine.log                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
