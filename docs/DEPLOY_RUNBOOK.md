# Deploy Runbook

Step-by-step commands to stand up Custos on a fresh Hetzner CX22 VM.
Assumes the reader has not seen this project before.

## DNS Setup (do this FIRST, before the VM)

Create these records in the Cloudflare dashboard:

| Record | Name | Value | Proxy status |
|--------|------|-------|-------------|
| A | `api.custos` | VM IPv4 address | **DNS only (grey cloud)** |

**WARNING: The API record MUST be DNS-only, NOT proxied (orange cloud).**

If proxied through Cloudflare, every request reaches Caddy from a Cloudflare
edge IP. The TCP remote address becomes Cloudflare's IP, not the visitor's,
so per-IP rate limiting treats all visitors on earth as a handful of IPs,
silently destroying the primary cost control. It would look fine and enforce
nothing.

DNS-only keeps the visitor's real IP in the TCP connection, which is what the
Caddyfile's `{remote_host}` and `CUSTOS_TRUST_PROXY=1` assume.

If Cloudflare proxying is ever wanted for DDoS protection, the rate limiter
must first be changed to key on the `CF-Connecting-IP` header instead of the
TCP remote address. Do not flip that toggle without making that code change.

The UI hostnames (`custos.andrewbolaji.com` and `demo.aintellectsolutions.com`)
are added as **custom domains inside the Cloudflare Pages project**. Pages
creates the necessary DNS records itself; do not create them manually.

**DNS must resolve before starting Caddy.** Let's Encrypt validates over HTTP
against the real hostname. If the A record is not live, validation fails and
repeated attempts hit Let's Encrypt rate limits (5 failures per hour).

## 1. SSH into the fresh VM

```bash
ssh root@VM_IP
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
ssh andrew@VM_IP
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
git clone https://github.com/andrewbolaji/custos.git
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
CUSTOS_CORS_ORIGINS=https://custos.andrewbolaji.com,https://demo.aintellectsolutions.com
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

**Only do this AFTER the DNS A record for `api.custos.andrewbolaji.com` resolves
to the VM IP.** Let's Encrypt will fail otherwise.

```bash
# Install Caddy (Debian/Ubuntu).
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudflare.com/caddy/apt/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudflare.com/caddy/apt/debian.list' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# Deploy the Caddyfile:
sudo cp Caddyfile /etc/caddy/Caddyfile

# Restart Caddy (auto-provisions TLS via Let's Encrypt):
sudo systemctl restart caddy
```

## 9. Verify health

```bash
# From the VM (internal):
curl http://127.0.0.1:8000/api/health
# Expected: {"status":"ok"}

# From outside (through Caddy + TLS):
curl https://api.custos.andrewbolaji.com/api/health
# Expected: {"status":"ok"}

# Admin endpoint:
curl -H "Authorization: Bearer PASTE_SECRET_HERE" \
  https://api.custos.andrewbolaji.com/api/admin/status
```

## 10. Deploy the UI

Build the frontend with the production API origin:

```bash
cd ui
VITE_API_URL=https://api.custos.andrewbolaji.com npm run build
```

Upload `dist/` to a Cloudflare Pages project. Add two custom domains
in the Pages project settings:
- `custos.andrewbolaji.com`
- `demo.aintellectsolutions.com`

Pages creates the DNS records for these automatically.

## 11. Set up monitoring

1. **UptimeRobot** (free): monitor `https://api.custos.andrewbolaji.com/api/health`
   every 5 minutes. Alert on downtime.

2. **Budget alert** (cron on the VM):

   The script `scripts/budget-alert.sh` queries the admin endpoint,
   checks monthly usage percentage, and posts to an ntfy.sh topic
   when 50% or 80% is first crossed. It does not re-alert on every
   run; state resets on month rollover.

   ```bash
   # Create a config file for the cron environment:
   cat > ~/.custos-alert-env << 'ENVEOF'
   CUSTOS_ADMIN_URL=https://api.custos.andrewbolaji.com/api/admin/status
   CUSTOS_ADMIN_TOKEN=PASTE_SECRET_HERE
   NTFY_TOPIC=PASTE_YOUR_NTFY_TOPIC
   ENVEOF
   chmod 600 ~/.custos-alert-env

   # Add to crontab (runs every 6 hours):
   crontab -e
   # Paste this line:
   0 */6 * * * . ~/.custos-alert-env && ~/custos/scripts/budget-alert.sh
   ```

   Set the ntfy topic to a private topic on ntfy.sh (free, no signup).
   Subscribe on your phone to receive push notifications.

## 12. Walk the demo

From a phone on cellular (not the same network):
1. Load `https://custos.andrewbolaji.com`. Verify: logo, banner, welcome screen.
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
