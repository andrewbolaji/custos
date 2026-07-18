# Deploy Runbook

Step-by-step commands to stand up Custos on a fresh Hetzner CX22 VM.
Replace placeholders before running. Assumes the reader has not seen
this project before.

## 1. SSH into the fresh VM

```bash
ssh root@YOUR_VM_IP
```

## 2. Create a non-root user

```bash
# Do not run the application as root.
adduser andrew
usermod -aG sudo andrew
su - andrew
```

## 3. Install Docker

```bash
# Docker Engine on Ubuntu/Debian.
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for the group to take effect.
exit
ssh andrew@YOUR_VM_IP
```

## 4. Firewall

```bash
# Only SSH, HTTP, and HTTPS. The API port (8000) is never exposed
# to the internet -- Caddy proxies to it on 127.0.0.1.
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 5. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/custos.git
cd custos
```

## 6. Create the secrets file

```bash
# Owner-only permissions. This file is the only place secrets live.
# It is never in the repo, never in Docker images, never in CI.
touch ~/.env
chmod 600 ~/.env

# Edit and paste the secrets:
nano ~/.env
```

Contents of `~/.env` (paste your real values):

```
ANTHROPIC_API_KEY=PASTE_SECRET_HERE
CUSTOS_ADMIN_TOKEN=PASTE_SECRET_HERE
CUSTOS_MODEL=claude-sonnet-4-6
CUSTOS_CORS_ORIGINS=https://YOUR_UI_DOMAIN
CUSTOS_TRUST_PROXY=1
CUSTOS_CONTACT_LINE=get in touch at PASTE_CONTACT_HERE for a full walkthrough
```

## 7. Start the stack

```bash
# First run builds the image (~5-10 min) and indexes the corpus.
docker compose -f docker-compose.prod.yml up -d

# Watch logs until "Boot: index ready" appears:
docker compose -f docker-compose.prod.yml logs -f api
```

## 8. Install and configure Caddy

```bash
# Install Caddy (Debian/Ubuntu).
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudflare.com/caddy/apt/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudflare.com/caddy/apt/debian.list' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# Copy the Caddyfile (replace DOMAIN_PLACEHOLDER first):
sudo cp Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/DOMAIN_PLACEHOLDER/api.YOUR_DOMAIN/' /etc/caddy/Caddyfile

# Restart Caddy (auto-provisions TLS):
sudo systemctl restart caddy
```

## 9. Verify health

```bash
# From the VM (internal):
curl http://127.0.0.1:8000/api/health
# Expected: {"status":"ok"}

# From outside (through Caddy + TLS):
curl https://api.YOUR_DOMAIN/api/health
# Expected: {"status":"ok"}

# Admin endpoint (replace token):
curl -H "Authorization: Bearer PASTE_SECRET_HERE" \
  https://api.YOUR_DOMAIN/api/admin/status
```

## 10. Deploy the UI

Deploy the `ui/dist/` build to Cloudflare Pages (or any static host).
Set the environment variable before building:

```bash
cd ui
VITE_API_URL=https://api.YOUR_DOMAIN npm run build
# Upload dist/ to Cloudflare Pages.
```

## 11. Set up monitoring

1. **UptimeRobot** (free): monitor `https://api.YOUR_DOMAIN/api/health`
   every 5 minutes. Alert on downtime.

2. **Budget alert** (cron on the VM):
   ```bash
   # Add to crontab: check cost daily, alert via ntfy.sh at 80%.
   0 9 * * * curl -s -H "Authorization: Bearer PASTE_SECRET_HERE" \
     https://api.YOUR_DOMAIN/api/admin/status \
     | python3 -c "import sys,json; d=json.load(sys.stdin); pct=d['pct_monthly_used']; print(f'{pct}%'); exit(0 if pct<80 else 1)" \
     || curl -d "Custos monthly usage at $(date): check admin/status" ntfy.sh/YOUR_TOPIC
   ```

## 12. Walk the demo

From a phone on cellular (not the same network):
1. Load the UI. Verify: logo, banner, welcome screen.
2. Ask a question. Verify: streaming, citations, access badge.
3. Switch to HR. Ask for employee records. Verify: [SSN] masking.
4. Try "send an email." Verify: confirmation card.
5. Hit the session quota. Verify: friendly limit message.

## Updating

```bash
cd custos
git pull
docker compose -f docker-compose.prod.yml up -d --build
# The boot check re-indexes if the corpus changed.
```
