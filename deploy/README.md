# Hosting on a VPS

## What to buy
The bot checks the market once an hour and uses well under 200 MB of RAM. The smallest plan is enough
(1 vCPU, 1 GB RAM, 10+ GB disk, Ubuntu 22.04 or 24.04), typically 4-6 USD/month:
Hetzner, DigitalOcean, Vultr, Contabo, or an Indonesian provider (IDCloudHost, Biznet Gio).
Latency does not matter for an hourly bot. Check Hyperliquid's terms for your region; do not use a VPS to get around
location restrictions.

## Setup (about 10 minutes)
    ssh root@<vps-ip>
    curl -fsSLO https://raw.githubusercontent.com/xrizer/money-maker/main/deploy/setup.sh   # or scp it
    bash setup.sh
Then follow the printed steps (edit `.env`, `systemctl start moneymaker`, watch `journalctl -u moneymaker -f`).

## Dashboard from your computer
    ssh -L 8080:127.0.0.1:8080 <you>@<vps-ip>
Open http://127.0.0.1:8080/dashboard.html. The port is never opened to the internet (firewall allows SSH only).

## Safety checklist
- API/agent wallet key only (cannot withdraw). Never the main wallet key.
- `.env` is chmod 600 and owned by the `moneymaker` user; the bot runs as that user, not root.
- Use SSH keys and disable password login (`PasswordAuthentication no` in /etc/ssh/sshd_config).
- Same order as before: testnet dry run -> testnet live -> small mainnet.
- The service restarts automatically after a crash or reboot. Open positions keep their exchange stop-loss/take-profit
  while the bot is down; the paused/running setting and daily/monthly baselines are saved on disk.
- If the VPS dies, nothing is lost but the decision loop. Check the dashboard now and then; a "No update" banner means stopped.

## Update
    bash /home/moneymaker/money-maker/deploy/update.sh

## Not tested here
These scripts were syntax-checked but not run on a real VPS. Try them first on a throwaway server with `LIVE=false`.
