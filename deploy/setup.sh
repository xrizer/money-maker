#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu/Debian VPS. Run as root:  bash setup.sh
set -euo pipefail
REPO="${REPO:-https://github.com/xrizer/money-maker.git}"
USER_NAME=moneymaker
HOME_DIR=/home/$USER_NAME

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }

apt-get update -y
apt-get install -y python3 python3-venv python3-pip git ufw

# dedicated unprivileged user: the bot never runs as root
id "$USER_NAME" &>/dev/null || adduser --disabled-password --gecos "" "$USER_NAME"

# firewall: SSH only. The dashboard listens on 127.0.0.1 and is reached through an SSH tunnel.
ufw allow OpenSSH
ufw --force enable

if [ ! -d "$HOME_DIR/money-maker" ]; then
  sudo -u "$USER_NAME" git clone "$REPO" "$HOME_DIR/money-maker"
fi
cd "$HOME_DIR/money-maker"
sudo -u "$USER_NAME" python3 -m venv venv
sudo -u "$USER_NAME" venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  sudo -u "$USER_NAME" cp .env.example .env
fi
chmod 600 .env && chown "$USER_NAME:$USER_NAME" .env

install -m 644 deploy/moneymaker.service /etc/systemd/system/moneymaker.service
systemctl daemon-reload
systemctl enable moneymaker   # starts on boot; NOT started yet, so you can edit .env first

cat <<MSG

Done. Next:
  1. sudo -u $USER_NAME nano $HOME_DIR/money-maker/.env     (testnet keys, LIVE=false first)
  2. systemctl start moneymaker
  3. journalctl -u moneymaker -f                            (live log, Ctrl+C to leave)
  4. From YOUR computer:  ssh -L 8080:127.0.0.1:8080 <you>@<vps-ip>
     then open http://127.0.0.1:8080/dashboard.html
MSG
