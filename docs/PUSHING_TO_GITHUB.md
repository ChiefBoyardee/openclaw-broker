# Pushing this project to GitHub

## Sanitization checklist (already done for initial push)

- **No secrets in repo:** All tokens and credentials come from env (WORKER_TOKEN, BOT_TOKEN, DISCORD_TOKEN, ALLOWED_USER_ID). No real values are hardcoded.
- **.gitignore** excludes: `*.env` (except `*.env.example`), `*.db`, `.venv/`, `__pycache__/`, `.pytest_cache/`, logs.
- **Only example env files are committed:** `broker/broker.env.example`, `runner/runner.env.example`, `discord_bot/bot.env.example` — they contain placeholders like `your_worker_token_here`.
- **Tests** use fixed test tokens (`test-worker-token`, `test-bot-token`) in test code only; these are not real secrets.

Before any push, run:

```bash
git status
git diff
```

Confirm no `broker.env`, `bot.env`, `runner.env`, or `*.db` are staged. If you ever see them, run `git reset HEAD <file>` and add them to `.gitignore`.

## Create the GitHub repo and push

1. **Create a new repository on GitHub** (github.com → New repository). Name it e.g. `openclaw-broker`. Do **not** add a README, .gitignore, or license (we already have them).

2. **In this project directory** (with git already initialized and initial commit done):

   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/openclaw-broker.git
   git branch -M main
   git push -u origin main
   ```

   Use SSH if you prefer: `git@github.com:YOUR_USERNAME/openclaw-broker.git`.

3. **Tag the first release** (optional but recommended for versioning):

   ```bash
   git tag -a v0.1.0 -m "Sprint 1+2: protocol hardening, worker identity, approve scaffold, bot guardrails"
   git push origin v0.1.0
   ```

## Versioning going forward

- Use **semantic versioning** (e.g. v0.2.0 for new features, v0.1.1 for fixes).
- Tag releases after merging to `main` so you have a clear history (e.g. `v0.1.0`, `v0.2.0`).
- Keep secrets in env files only; never commit `broker.env`, `bot.env`, or `runner.env`.
