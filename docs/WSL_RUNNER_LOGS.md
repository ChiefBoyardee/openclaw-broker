# WSL runner log rotation

On WSL there is no systemd; the runner is started via [runner/start.sh](../runner/start.sh), which writes logs to a file. Without rotation, that file can grow without bound.

---

## Log path

From `runner/start.sh`:

- **LOG_DIR:** `/var/log/openclaw-runner`
- **LOG_FILE:** `/var/log/openclaw-runner/runner.log`

The script creates the directory if needed and appends to `runner.log` on every run.

---

## logrotate

Use **logrotate** to rotate the runner log by size or time.

### Example config

Create `/etc/logrotate.d/openclaw-runner` (on the WSL host or Linux box where the runner runs):

```
/var/log/openclaw-runner/runner.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

- **daily** — rotate once per day (use `size 50M` instead to rotate when the file reaches 50 MiB).
- **rotate 7** — keep 7 rotated files.
- **compress** / **delaycompress** — compress rotated files (delaycompress skips compressing the most recent rotated file so it can still be written).
- **missingok** — do not error if the log file is missing.
- **notifempty** — do not rotate if the file is empty.
- **copytruncate** — copy the file then truncate the original, so the runner does not need to be restarted to release the handle.

### Install and apply

1. **Install logrotate** (if needed):
   ```bash
   sudo apt-get update && sudo apt-get install logrotate
   ```

2. **Create the config:**
   ```bash
   sudo tee /etc/logrotate.d/openclaw-runner << 'EOF'
   /var/log/openclaw-runner/runner.log {
       daily
       rotate 7
       compress
       delaycompress
       missingok
       notifempty
       copytruncate
   }
   EOF
   ```

3. **Dry run** (no changes):
   ```bash
   sudo logrotate -d /etc/logrotate.d/openclaw-runner
   ```

4. **Run once** (e.g. to test):
   ```bash
   sudo logrotate -f /etc/logrotate.d/openclaw-runner
   ```

logrotate is usually run daily by cron (e.g. `/etc/cron.daily/logrotate`). No need to restart the runner.

---

## See also

- [runner/start.sh](../runner/start.sh) — defines `LOG_DIR` and `LOG_FILE`.
- [MULTI_WORKER_LLM_SMOKE.md](MULTI_WORKER_LLM_SMOKE.md) — runner setup and env.
