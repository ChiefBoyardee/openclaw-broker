# Security

## Token handling

- **No secrets in git.** All tokens and credentials live in env files (e.g. `broker.env`, `bot.env`, `runner.env`) outside the repo or in deployment paths like `/opt/openclaw-broker/broker.env`.
- **Broker tokens:** The broker expects two env vars: `WORKER_TOKEN` (for workers calling `GET /jobs/next`, `POST /jobs/{id}/result`, and `POST /jobs/{id}/fail`) and `BOT_TOKEN` (for the Discord bot calling `POST /jobs` and `GET /jobs/{id}`). Generate with e.g. `openssl rand -hex 32`. Jobs can end in `done` or `failed`; workers post failures via `/fail` so the bot can show errors. Running jobs have a lease (`LEASE_SECONDS`); if a worker dies, the job is requeued after the lease expires so it is not stuck forever.
- **Discord:** The bot uses `DISCORD_TOKEN` (Discord application token) and `BOT_TOKEN` (same value as broker’s `BOT_TOKEN`). `ALLOWED_USER_ID` restricts which Discord user can use the bot.
- **Runner:** Uses `WORKER_TOKEN` (same as broker’s `WORKER_TOKEN`) to authenticate to the broker. Keep this token only on worker machines.

## Tailnet-only binding (production)

- Run the broker on a VPS that is on your Tailscale tailnet. Set `BROKER_HOST` to the Tailscale interface IP (e.g. `100.x.x.x` from `tailscale ip -4`) so the broker listens only on the tailnet, not on the public internet.
- In systemd, `EnvironmentFile=/opt/openclaw-broker/broker.env` supplies `BROKER_HOST` and `BROKER_PORT`. Do not bind to `0.0.0.0` unless you have other protections (e.g. firewall).
- The Discord bot and runner should reach the broker over the tailnet (use the broker’s Tailscale URL in `BROKER_URL`).

## File and process isolation

- Use a dedicated user (e.g. `openclaw`) for the broker and Discord bot services. The install scripts reference this user in the systemd templates.
- Restrict read access to env files: `chmod 600 /opt/openclaw-broker/broker.env` and similar for `bot.env` and `runner.env` so only the service user (and root) can read them.
