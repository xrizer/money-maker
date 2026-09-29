#!/usr/bin/env bash
# Update the bot on the VPS. Run as root:  bash update.sh
set -euo pipefail
cd /home/moneymaker/money-maker
sudo -u moneymaker git pull --ff-only
sudo -u moneymaker venv/bin/pip install -q -r requirements.txt
systemctl restart moneymaker
systemctl --no-pager status moneymaker | head -5
