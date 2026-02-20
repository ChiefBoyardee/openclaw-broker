# Discord bot — VPS smoke test

Use this checklist to verify a full stack (broker, runner, bot) on a VPS or locally after deploy or code changes.

## 1) VPS install (templated systemd + env)

**Goal:** Prove the templated systemd unit + env file approach works end-to-end.

- On VPS: `git pull` the latest repo.
- Run the install script to create one instance (e.g. `urgoclaw`):
  - `/opt/openclaw-bot-urgoclaw/` (code, venv, deps)
  - `/var/lib/openclaw-bot-urgoclaw/`
  - systemd template installed and instance enabled: `openclaw-discord-bot@urgoclaw`
- Create `/opt/openclaw-bot-urgoclaw/bot.env` from the example and set:
  - `DISCORD_TOKEN`
  - `BOT_TOKEN` (must match broker’s `BOT_TOKEN`)
  - `BROKER_URL=http://<VPS_TS_IP>:8443` (or your broker URL)
  - `ALLOWLIST_USER_ID=<your Discord user ID>` (or `ALLOWED_USER_ID`)

**Pass criteria:**

- `systemctl status openclaw-discord-bot@urgoclaw` is active (green).
- `journalctl -u openclaw-discord-bot@urgoclaw -n 30` shows startup info (instance name, broker URL) with **no secrets**.
- DM `whoami` works and shows correct instance and broker URL.

## 2) End-to-end job flow (Discord → Broker → Runner → Discord)

**Goal:** Verify the real bot command path is fully functional.

- In DMs (as an allowlisted user) run:
  - `ping hello` → expect pong-style response.
  - `capabilities` → expect JSON-style response (worker ID, capabilities).
  - `status <job_id>` for a job from the ping (or any previous job).

**Pass criteria:**

- Bot replies within timeout **or** replies with “Still running. Job ID: …” and no exceptions in bot logs.
- Broker logs show `POST /jobs`, `GET /jobs/<id>`, etc.
- Runner logs show it claimed and finished jobs.

## 3) Unauthorized behavior

**Goal:** Allowlist and DM-only behavior are correct.

- DM from an **unauthorized** account (not in allowlist) → bot must reply **once** with a polite refusal (e.g. “You are not authorized to use this bot.”).
- If the bot is in a server channel: post as a non-allowlisted user → bot must **not** reply (no leaking output to channels).

**Pass criteria:**

- No reply in server channels to non-allowlisted users.
- Refusal message is polite and minimal.

## 4) Token safety

**Goal:** Tokens never appear in logs or in bot replies.

- **Logs:**  
  `journalctl -u openclaw-discord-bot@urgoclaw | grep -E "BOT_TOKEN|DISCORD_TOKEN"` must return **nothing** (or no matches).
- **Echo test:** In DM, send `ping BOT_TOKEN` (or a message containing your actual token). The bot must **never** echo the token back; the reply must show redacted content (e.g. `***`) if the token would otherwise appear.

**Pass criteria:**

- Tokens never appear in logs or in any bot message.

---

## Prerequisites (for steps below)

- Broker running (e.g. `systemctl status openclaw-broker` or `uvicorn broker.app:app --host 127.0.0.1 --port 8000`).
- Runner running with same `BROKER_URL` and `WORKER_TOKEN` as broker.
- One Discord bot instance running (e.g. `systemctl status openclaw-discord-bot@clawhub` or `python discord_bot/bot.py`).
- Your Discord user ID is in the bot allowlist (`ALLOWED_USER_ID` or `ALLOWLIST_USER_ID` in `bot.env`).
- You have a DM channel with the bot.

## Smoke steps (detailed)

1. **Start broker**  
   - `sudo systemctl start openclaw-broker` (or run manually).  
   - `curl -s http://127.0.0.1:8000/health` → `{"ok":true,"ts_bound":true}`.

2. **Start runner**  
   - Run runner with correct `BROKER_URL` and `WORKER_TOKEN`.  
   - Runner should log polling and no errors.

3. **Start bot instance**  
   - `sudo systemctl start openclaw-discord-bot@<instance>` (or run `python discord_bot/bot.py` with env loaded).  
   - **Verify logs:** `journalctl -u openclaw-discord-bot@<instance> -n 20 --no-pager`.  
   - Logs must show instance name and broker URL.  
   - Logs must **not** contain `DISCORD_TOKEN`, `BOT_TOKEN`, or any secret value.

4. **DM: whoami**  
   - Send `whoami` in a DM to the bot.  
   - Reply must include correct instance name, bot user ID, broker URL, and allowlist status.

5. **DM: ping**  
   - Send `ping hello`.  
   - You should get a “Job created: `<job_id>`. Waiting for result…” then a reply like `pong: hello`.

6. **DM: capabilities**  
   - Send `capabilities`.  
   - Reply should show worker ID and a list of capabilities.

7. **DM: repos**  
   - Send `repos`.  
   - Reply is either a list of repos (if runner has repos configured) or an error/no repos message.

8. **DM: grep / cat** (if a repo is configured on the runner)  
   - e.g. `grep <repo> <query>` and `cat <repo> README.md 1 5`.  
   - Replies should show grep matches or file snippet (or a clear error).

9. **DM: status**  
   - Send `status <job_id>` using a job ID from step 5 (or any previous job).  
   - Reply must show job status and result; long output must be truncated with “use `status <job_id>` for full output”.

10. **Unauthorized user**  
    - From a Discord account **not** in the allowlist, DM the bot with e.g. `ping test`.  
    - Bot must reply exactly once with a polite refusal (e.g. “You are not authorized to use this bot.”).  
    - In a server channel where the bot is present but the user is not allowlisted, the bot must **not** reply (no spam).

## Pass criteria

- All steps 1–9 complete without errors and with expected reply shapes.
- Step 10: unauthorized DM gets one refusal; no reply in channels.
- No tokens or secrets appear in bot (or broker/runner) logs.

## Rollback

If something fails after a deploy:

- Stop the bot: `sudo systemctl stop openclaw-discord-bot@<instance>`.
- Restore `bot.env` or code from backup if needed.
- See the main [DISCORD_BOT_DEPLOY.md](DISCORD_BOT_DEPLOY.md) rollback notes.
