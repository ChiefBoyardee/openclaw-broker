"""Tests for prune_jobs script."""
import os
import sys
import sqlite3
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Need to run script as main
import subprocess


def test_prune_dry_run_does_not_delete():
    """--dry-run does not delete any rows."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE jobs (
                id TEXT PRIMARY KEY, created_at INTEGER, status TEXT,
                command TEXT, payload TEXT, result TEXT, finished_at INTEGER,
                error TEXT, started_at INTEGER, lease_until INTEGER,
                worker_id TEXT, requires TEXT
            )"""
        )
        now = int(time.time())
        old_ts = now - (2 * 86400)  # 2 days ago
        conn.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("j1", old_ts, "done", "ping", "", "ok", old_ts, None, None, None, None, None),
        )
        conn.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("j2", old_ts, "failed", "ping", "", None, old_ts, "err", None, None, None, None),
        )
        conn.commit()
        conn.close()

        env = os.environ.copy()
        env["BROKER_DB"] = db_path
        result = subprocess.run(
            [sys.executable, "scripts/prune_jobs.py", "--dry-run", "--days", "1", "--db", db_path],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert "Jobs to prune" in result.stdout
        assert "Dry run" in result.stdout

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        conn.close()
        assert count == 2
    finally:
        os.unlink(db_path)


def test_prune_with_yes_deletes_old():
    """--yes deletes old done/failed jobs."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE jobs (
                id TEXT PRIMARY KEY, created_at INTEGER, status TEXT,
                command TEXT, payload TEXT, result TEXT, finished_at INTEGER,
                error TEXT, started_at INTEGER, lease_until INTEGER,
                worker_id TEXT, requires TEXT
            )"""
        )
        now = int(time.time())
        old = now - (40 * 86400)
        conn.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("j-old", old, "done", "ping", "", "ok", old, None, None, None, None, None),
        )
        conn.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("j-recent", now - 100, "done", "ping", "", "ok", now - 50, None, None, None, None, None),
        )
        conn.commit()
        conn.close()

        env = os.environ.copy()
        env["BROKER_DB"] = db_path
        result = subprocess.run(
            [sys.executable, "scripts/prune_jobs.py", "--days", "30", "--yes", "--db", db_path],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT id FROM jobs").fetchall()
        conn.close()
        ids = [r[0] for r in rows]
        assert "j-old" not in ids
        assert "j-recent" in ids
    finally:
        os.unlink(db_path)
