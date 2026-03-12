#!/bin/bash
# Install CamoManager as a systemd service (auto-start on boot)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
USER=$(whoami)

if [ "$EUID" -ne 0 ]; then
    echo "Run with sudo: sudo bash $0"
    exit 1
fi

# Get the actual user (not root)
REAL_USER=${SUDO_USER:-$USER}
REAL_HOME=$(eval echo ~$REAL_USER)

cat > /etc/systemd/system/camo-manager.service << EOF
[Unit]
Description=CamoManager Web UI
After=network.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$SCRIPT_DIR
Environment="PATH=$SCRIPT_DIR/venv/bin:/usr/bin:/bin"
ExecStart=$SCRIPT_DIR/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable camo-manager
systemctl start camo-manager

echo ""
echo "✅ CamoManager service installed!"
echo "   Status:  sudo systemctl status camo-manager"
echo "   Logs:    journalctl -u camo-manager -f"
echo "   Restart: sudo systemctl restart camo-manager"
echo "   Stop:    sudo systemctl stop camo-manager"
echo ""
