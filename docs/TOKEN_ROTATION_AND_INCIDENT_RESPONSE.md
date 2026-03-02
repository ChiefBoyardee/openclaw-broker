# Token Rotation & Incident Response

This document describes how to rotate tokens, respond to compromise incidents, and maintain least-privilege posture for OpenClaw.

---

## BOT_TOKEN / WORKER_TOKEN rotation

1. Generate new tokens: `openssl rand -hex 32`
2. Update **broker** env: edit `broker.env` (e.g. `/opt/openclaw-broker/broker.env`), set `WORKER_TOKEN` and `BOT_TOKEN`
3. Update **all bot instances**: edit each `bot.env` (e.g. `/opt/openclaw-bot-<instance>/bot.env`), set `BOT_TOKEN`
4. Update **all runner instances**: edit each `runner.env`, set `WORKER_TOKEN`
5. Restart services in order: broker first, then runners, then bots
   - `sudo systemctl restart openclaw-broker`
   - `sudo systemctl restart openclaw-runner` (per runner)
   - `sudo systemctl restart openclaw-discord-bot@<instance>` (per bot)

---

## Discord token rotation

1. Open [Discord Developer Portal](https://discord.com/developers/applications) → your application → Bot
2. Click **Reset Token**; confirm
3. Copy the new token
4. Update each bot instance's `bot.env`: set `DISCORD_TOKEN`
5. Restart all bot instances: `sudo systemctl restart openclaw-discord-bot@<instance>`

---

## LLM API key rotation

The LLM key lives only in runner env; it is never sent to the broker or bot.

1. Update each runner's `runner.env`: set `LLM_API_KEY`
2. Restart runners: `sudo systemctl restart openclaw-runner` (or restart the runner process on WSL)

No broker or bot changes needed.

---

## Post-incident checklist

After a suspected token compromise:

1. **Rotate** the compromised token(s) using the steps above
2. **Invalidate sessions** if applicable (Discord token reset effectively does this for the bot)
3. **Review logs** for anomalies:
   - Broker: stderr / journal logs (`journalctl -u openclaw-broker`)
   - Bot: stderr / journal logs per instance
   - Runner: stderr / runner log files (e.g. `/var/log/openclaw-runner/runner.log`)
4. **Prune DB** if job results may contain exfiltrated data: run backup first, then prune (see [BROKER_BACKUP_RETENTION.md](BROKER_BACKUP_RETENTION.md) and `scripts/prune_jobs.py`)

---

## File permissions and ownership

- **Env files** (`*.env`): `chmod 0600` — readable only by the process user
- **Broker DB** (`broker.db`): `chmod 0600` — readable/writable only by broker process
- **Ownership**: Run broker, bot, and runner as a dedicated user (e.g. `openclaw`); ensure `*.env` and DB are owned by that user

Example after install:
```bash
chown openclaw:openclaw /opt/openclaw-broker/broker.env
chmod 0600 /opt/openclaw-broker/broker.env
```

---

## Environment separation

Use **separate tokens** for dev, staging, and prod when applicable. Do not reuse prod tokens in dev. This limits blast radius if a dev token is compromised.

---

## Future enhancement

Optional: broker could accept multiple active tokens (e.g. `BOT_TOKEN_ALT`) for rolling rotation without downtime. Not implemented; document here as a potential follow-up.
