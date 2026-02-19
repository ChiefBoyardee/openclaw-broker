# Discord bot deployment (multi-instance)

The Discord bot can run as **multiple instances** on the same VPS, each with its own token, env file, venv, and state. This uses a systemd **template** unit and an install script.

## Overview

- **Template unit:** `openclaw-discord-bot@.service` — the `%i` is the instance name (e.g. `clawhub` → `openclaw-discord-bot@clawhub`).
- **Per-instance paths:**
  - `/opt/openclaw-bot-<instance>/` — working dir, `discord_bot/` code, `venv/`, `bot.env` (you create from `bot.env.example`).
  - `/var/lib/openclaw-bot-<instance>/` — optional state dir (writable by the service).
- **Env file:** `/opt/openclaw-bot-<instance>/bot.env`. Do not commit; create from `bot.env.example` and set secrets.
- **User:** Services run as `openclaw` (created by the install script if missing).

## Install one instance

From the repo root:

```bash
./deploy/install_bot_instance.sh <instance_name> [--enable]
```

Example:

```bash
./deploy/install_bot_instance.sh clawhub --enable
```

This will:

1. Create `openclaw` user/group if missing.
2. Create `/opt/openclaw-bot-clawhub/` and `/var/lib/openclaw-bot-clawhub/`.
3. Copy `discord_bot/` and create a venv with dependencies.
4. Copy `bot.env.example` to `/opt/openclaw-bot-clawhub/bot.env.example` (no `bot.env` — you create it).
5. Install the systemd template to `/etc/systemd/system/openclaw-discord-bot@.service` and run `daemon-reload`.
6. If `--enable`: `systemctl enable --now openclaw-discord-bot@clawhub`.

## After install: create bot.env

No secrets are created by the script. Do:

```bash
sudo cp /opt/openclaw-bot-<instance>/bot.env.example /opt/openclaw-bot-<instance>/bot.env
sudo $EDITOR /opt/openclaw-bot-<instance>/bot.env
```

Set at least:

- **DISCORD_TOKEN** — from Discord Developer Portal (each instance needs its own Discord Application and bot token).
- **BOT_TOKEN** — same as broker `X-Bot-Token` if sharing one broker; or a distinct token per instance.
- **ALLOWED_USER_ID** — Discord user ID allowed to use this bot.
- **BROKER_URL** — broker base URL (e.g. `http://127.0.0.1:8000` or Tailscale URL).

Then:

```bash
sudo chown openclaw:openclaw /opt/openclaw-bot-<instance>/bot.env
```

**INSTANCE_NAME** is set automatically by systemd to the instance name when using the template; you can override in `bot.env` if needed.

## Manage services

- Start: `sudo systemctl start openclaw-discord-bot@<instance>`
- Stop: `sudo systemctl stop openclaw-discord-bot@<instance>`
- Enable on boot: `sudo systemctl enable openclaw-discord-bot@<instance>`
- Logs: `journalctl -u openclaw-discord-bot@<instance> -f`

Example for instance `clawhub`:

```bash
journalctl -u openclaw-discord-bot@clawhub -f
```

Startup logs include the bot’s Discord username, instance name, and broker URL so you can confirm which instance is running.

## whoami command

From an allowlisted DM, send `whoami`. The bot replies with:

- Instance name  
- Bot user ID  
- Broker URL  
- Allowlisted user ID (or “not set”)

No broker call; useful to confirm which instance and config you’re talking to.

## Hardening (systemd unit)

The template unit uses:

- **NoNewPrivileges=true**, **PrivateTmp=true**
- **ProtectSystem=strict**, **ProtectHome=true**
- **ReadWritePaths=/opt/openclaw-bot-%i /var/lib/openclaw-bot-%i**

All code and working dir live under `/opt`, so the service cannot write outside those paths.

## Multiple instances

Install and run as many instances as you need, each with a different `<instance_name>` and its own `bot.env` (and thus its own Discord app/token and allowlist):

```bash
./deploy/install_bot_instance.sh clawhub --enable
./deploy/install_bot_instance.sh staging --enable
```

Create `/opt/openclaw-bot-staging/bot.env` separately with staging’s `DISCORD_TOKEN`, `ALLOWED_USER_ID`, etc., then start: `sudo systemctl start openclaw-discord-bot@staging`.
