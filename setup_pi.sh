#!/bin/bash
# ============================================================
#  Antigravity - New Raspberry Pi Setup Script
#  Run this LOCALLY on your PC to configure a fresh Pi.
#  Usage: bash setup_pi.sh
# ============================================================

set -e

# --- Configuration ---
PI_USER="mateusz"
GCP_KEY_PATH="$HOME/Documents/gcp-backup-key.json"
GITHUB_REPO="https://github.com/sasiadrokita/MCPTA.git"

# --- Colors ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🛸 Antigravity - New Pi Setup Wizard       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""

# --- Step 1: Get Pi IP ---
read -p "$(echo -e ${YELLOW}[1/7] Enter new Raspberry Pi IP address: ${NC})" PI_IP

if [[ -z "$PI_IP" ]]; then
    echo -e "${RED}Error: IP address cannot be empty.${NC}"
    exit 1
fi

echo -e "${GREEN}Target: ${PI_USER}@${PI_IP}${NC}"
echo ""

# --- Step 2: Generate SSH key if needed ---
echo -e "${YELLOW}[2/7] Checking SSH keys...${NC}"
if [ ! -f "$HOME/.ssh/id_rsa.pub" ]; then
    echo "No SSH key found. Generating a new one..."
    ssh-keygen -t rsa -b 4096 -N "" -f "$HOME/.ssh/id_rsa"
    echo -e "${GREEN}SSH key generated.${NC}"
else
    echo -e "${GREEN}SSH key already exists.${NC}"
fi

# --- Step 3: Copy SSH key to Pi (one-time password entry) ---
echo ""
echo -e "${YELLOW}[3/7] Copying SSH key to Pi (you may need to enter Pi password once)...${NC}"
ssh-copy-id -o StrictHostKeyChecking=no "${PI_USER}@${PI_IP}"
echo -e "${GREEN}SSH key installed. Future connections will be passwordless.${NC}"

# --- Step 4: Set hostname to MCPTA ---
echo ""
echo -e "${YELLOW}[4/7] Setting hostname to 'MCPTA'...${NC}"
ssh "${PI_USER}@${PI_IP}" "
    echo 'MCPTA' | sudo tee /etc/hostname > /dev/null
    sudo sed -i 's/raspberrypi/MCPTA/g' /etc/hosts
    sudo sed -i 's/127.0.1.1.*/127.0.1.1\tMCPTA/g' /etc/hosts
"
echo -e "${GREEN}Hostname set to MCPTA.${NC}"

# --- Step 5: Install mDNS (avahi) for MCPTA.local access ---
echo ""
echo -e "${YELLOW}[5/7] Installing mDNS (avahi-daemon) for MCPTA.local access...${NC}"
ssh "${PI_USER}@${PI_IP}" "
    sudo apt-get install -y avahi-daemon > /dev/null 2>&1
    sudo systemctl enable avahi-daemon
    sudo systemctl start avahi-daemon
"
echo -e "${GREEN}mDNS configured. Pi will be accessible at MCPTA.local${NC}"

# --- Step 6: Copy GCP backup key ---
echo ""
echo -e "${YELLOW}[6/7] Copying Google Cloud credentials to Pi...${NC}"
if [ ! -f "$GCP_KEY_PATH" ]; then
    echo -e "${RED}Error: GCP key not found at ${GCP_KEY_PATH}${NC}"
    echo "Please place your gcp-backup-key.json in ~/Documents/ and re-run."
    exit 1
fi
scp "$GCP_KEY_PATH" "${PI_USER}@${PI_IP}:~/gcp-backup-key.json"
echo -e "${GREEN}GCP key copied.${NC}"

# --- Step 7: Run the main installer on Pi ---
echo ""
echo -e "${YELLOW}[7/7] Launching Antigravity installer on Pi...${NC}"
echo -e "${BLUE}(This will take several minutes - system upgrade + pip install)${NC}"
echo ""

# Stream the install.sh to the Pi and run it
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ssh "${PI_USER}@${PI_IP}" "bash -s" < "${SCRIPT_DIR}/install.sh"

# --- Done ---
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ Setup Complete!                         ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Dashboard:  http://MCPTA.local:5000         ║${NC}"
echo -e "${GREEN}║  SSH access: ssh ${PI_USER}@MCPTA.local            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
