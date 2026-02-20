# Deploy and update (CI/CD)

This doc describes how to run tests automatically, update services after a `git pull`, and optionally deploy to the VPS from GitHub Actions.

---

## CI (tests on push/PR)

GitHub Actions runs tests on every push and pull request to `main`/`master`.

- **Workflow:** [.github/workflows/ci.yml](../.github/workflows/ci.yml)
- **What it does:** Checks out the repo, installs dependencies from `requirements.txt`, runs `pytest tests/` on Python 3.11 and 3.12.
- **No setup required:** Works as long as the repo is on GitHub and Actions are enabled.

---

## Updating after a pull

After you `git pull` on a host, run the appropriate update script so services run the new code and (on VPS) bot instances get the latest `discord_bot` copy.

### VPS (broker + Discord bots)

From the **repo root** on the VPS:

```bash
bash deploy/scripts/update_vps.sh
```

This will:

1. **Pull** the latest code (skip with `--no-pull` if you already pulled).
2. **Broker:** Install/refresh dependencies in `.venv-broker` and restart `openclaw-broker`.
3. **Bots:** For each `/opt/openclaw-bot-<instance>/`, copy the latest `discord_bot` and `requirements.txt`, run `pip install` in that instance’s venv, and restart `openclaw-discord-bot@<instance>`.

Requires `sudo` for `systemctl restart`. The broker’s DB migration (e.g. new columns) runs automatically on broker startup.

### Jetson (runner with systemd)

From the **repo root** on the Jetson:

```bash
bash deploy/scripts/update_runner_jetson.sh
```

This pulls (unless `--no-pull`), refreshes `.venv-runner`, and runs `sudo systemctl restart openclaw-runner`.

### WSL (runner, no systemd)

From the **repo root** on WSL:

```bash
bash deploy/scripts/update_runner_wsl.sh
```

This pulls (unless `--no-pull`) and refreshes `.venv-runner`. You must **restart the runner process yourself** (e.g. stop the current `runner/start.sh`, then start it again).

---

## Optional CD (auto-deploy VPS from GitHub)

A second workflow can deploy to the VPS when you push to `main`: it SSHs into the host, runs `git pull`, then `update_vps.sh --no-pull`.

- **Workflow:** [.github/workflows/deploy-vps.yml](../.github/workflows/deploy-vps.yml)
- **Trigger:** Push to `main`/`master` (and optional manual `workflow_dispatch`). The deploy job runs only when the repository variable `DEPLOY_ENABLED` is set to `true`.

### Required setup

1. **On the VPS**
   - Clone the repo (e.g. `/opt/openclaw/openclaw-broker`) and complete broker + bot install so `deploy/scripts/update_vps.sh` works when run from that directory.
   - Ensure the user you deploy as can run `sudo systemctl restart openclaw-broker` and `sudo systemctl restart openclaw-discord-bot@*` without a password (e.g. sudoers rule), or that the SSH user is root.

2. **In the GitHub repo**
   - **Settings → Secrets and variables → Actions → Variables.** Add a **variable** (not a secret):
     - `DEPLOY_ENABLED` = `true` — Enables the deploy job on push to main. If this variable is not set, the deploy job is skipped (CI still runs).
   - **Secrets.** Add:
     - `DEPLOY_HOST` — VPS hostname or IP.
     - `DEPLOY_USER` — SSH user (e.g. `openclaw` or `root`).
     - `DEPLOY_SSH_KEY` — Private key for SSH (paste the full key, including `-----BEGIN ... KEY-----` / `-----END ... KEY-----`).
     - `DEPLOY_REPO_PATH` (optional) — Path to the repo on the VPS (default: `/opt/openclaw/openclaw-broker`).

3. **Behavior**
   - On push to `main`, if `DEPLOY_ENABLED` is `true`, the workflow SSHs to the VPS, `cd`s to the repo path, runs `git pull`, then `bash deploy/scripts/update_vps.sh --no-pull`.
   - If `DEPLOY_ENABLED` is not set, the deploy job is skipped so CI still runs.

### Disabling CD

Remove `.github/workflows/deploy-vps.yml`, or delete the `DEPLOY_ENABLED` variable, or delete the deploy secrets; the CI workflow is unchanged.

---

## Summary

| Where        | After pull / deploy        | Script / workflow |
|-------------|----------------------------|--------------------|
| GitHub      | Run tests                  | CI workflow (automatic) |
| VPS         | Update broker + bots       | `deploy/scripts/update_vps.sh` or deploy workflow |
| Jetson      | Update runner              | `deploy/scripts/update_runner_jetson.sh` |
| WSL         | Update runner (+ restart)  | `deploy/scripts/update_runner_wsl.sh` then restart runner |
