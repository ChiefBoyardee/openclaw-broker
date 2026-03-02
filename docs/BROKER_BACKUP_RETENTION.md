# Broker backup and retention

This doc describes how to back up the broker SQLite database, optional retention/pruning, and what data is sensitive.

---

## Backup

The broker stores all jobs (including results and errors) in a single SQLite file. The path is set by **`BROKER_DB`** (default: `/var/lib/openclaw-broker/broker.db`). Deploy scripts and systemd typically use this path.

### Option 1: Copy while service is stopped

1. Stop the broker: `sudo systemctl stop openclaw-broker` (or stop the process that runs the broker).
2. Copy the DB file (and WAL files if present):
   ```bash
   cp /var/lib/openclaw-broker/broker.db /backup/openclaw-broker.db.$(date +%Y%m%d)
   # With WAL mode, also copy the WAL and shared-memory files for a consistent backup:
   cp /var/lib/openclaw-broker/broker.db-wal /backup/ 2>/dev/null || true
   cp /var/lib/openclaw-broker/broker.db-shm /backup/ 2>/dev/null || true
   ```
3. Start the broker: `sudo systemctl start openclaw-broker`.

### Option 2: Online backup (recommended)

Use SQLite’s backup API so the broker can stay running. From the host:

```bash
sqlite3 /var/lib/openclaw-broker/broker.db ".backup /backup/openclaw-broker.db.$(date +%Y%m%d)"
```

This creates a single consistent snapshot file. With WAL enabled, the backup includes committed data up to the point of the backup. No need to copy `-wal`/`-shm` when using `.backup`.

### WAL mode note

The broker enables **WAL** (Write-Ahead Logging) and sets **`PRAGMA synchronous=NORMAL`**, which is the recommended setting for WAL and safe for this workload. WAL creates `broker.db-wal` and `broker.db-shm` next to `broker.db`. For a file-copy backup while the service is stopped, copy all three. For online backup, use `sqlite3 .backup` as above so you get one consistent file.

---

## Retention and pruning

The broker does **not** delete old jobs automatically. The `jobs` table can grow. To prune:

- Delete finished jobs older than a given age (e.g. 30 days). Only **done** and **failed** jobs are safe to delete; do not delete **queued** or **running** rows.

**Manual one-liner (example: delete done/failed older than 30 days):**

```bash
sqlite3 /var/lib/openclaw-broker/broker.db "DELETE FROM jobs WHERE status IN ('done','failed') AND finished_at IS NOT NULL AND finished_at < $(date -d '30 days ago' +%s);"
```

On macOS (no `date -d`):

```bash
sqlite3 /var/lib/openclaw-broker/broker.db "DELETE FROM jobs WHERE status IN ('done','failed') AND finished_at IS NOT NULL AND finished_at < $(date -v-30d +%s);"
```

**Prune script (optional):**

```bash
# Preview first
python scripts/prune_jobs.py --dry-run --days 30

# Actually delete (run backup first)
python scripts/prune_jobs.py --days 30 --yes
```

Run during low traffic. Use `--db /path/to/broker.db` if needed.

---

## What data is sensitive

- **Job payloads, results, and errors** are stored in the DB. Anyone with **`BOT_TOKEN`** can read all jobs (and thus results) via the broker API.
- **LLM outputs** (llm_task results) and **repo command outputs** may contain sensitive data; they live in the DB until pruned.
- **Backups** should be stored with restricted access (same as the live DB). Do not put backup files in world-readable locations.
- **Purge:** Run backup first, then `python scripts/prune_jobs.py --days N --yes` to remove old done/failed jobs. See [TOKEN_ROTATION_AND_INCIDENT_RESPONSE.md](TOKEN_ROTATION_AND_INCIDENT_RESPONSE.md) for post-incident checklist.
- Rotate **`BOT_TOKEN`** and **`WORKER_TOKEN`** if they are ever compromised.

---

## Ops / manual smoke checklist

After broker or bot changes, validate with:

1. **Unit tests:** `pytest tests/ -v --tb=short` — all pass.
2. **Bot create + poll:** From an allowlisted DM, send `ping hello`; bot should reply with a pong (runner must be connected to claim the job).
3. **Worker claim + result/fail:** Runner polls `GET /jobs/next`, runs job, posts result or fail; broker state moves to done/failed.
4. **Caps matching:** Job with `requires` caps is claimed only by a worker advertising those caps (see [MULTI_WORKER_LLM_SMOKE.md](MULTI_WORKER_LLM_SMOKE.md)).

---

## See also

- [Deploy and update](DEPLOY_AND_UPDATE.md) — how to update the broker after a pull.
- [Project review report](PROJECT_REVIEW_REPORT.md) — architecture and risk summary.
