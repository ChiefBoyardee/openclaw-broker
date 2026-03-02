#!/usr/bin/env python3
"""
Prune old done/failed jobs from the broker DB.

Usage:
  python scripts/prune_jobs.py --dry-run --days 30   # preview
  python scripts/prune_jobs.py --days 30 --yes       # actually delete

Run a backup first (see docs/BROKER_BACKUP_RETENTION.md).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune old done/failed jobs. Run backup first."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Delete jobs older than N days (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count, do not delete",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion (required unless --dry-run)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Broker DB path (default: BROKER_DB or /var/lib/openclaw-broker/broker.db)",
    )
    args = parser.parse_args()

    db_path = args.db or os.environ.get("BROKER_DB", "/var/lib/openclaw-broker/broker.db")
    if not os.path.isfile(db_path):
        print(f"[prune] DB not found: {db_path}", file=sys.stderr)
        return 1

    cutoff = int(time.time()) - (args.days * 86400)

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        cur = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('done','failed') AND finished_at IS NOT NULL AND finished_at < ?",
            (cutoff,),
        )
        (count,) = cur.fetchone()
        conn.close()
    except sqlite3.Error as e:
        print(f"[prune] DB error: {e}", file=sys.stderr)
        return 1

    print(f"[prune] Jobs to prune (done/failed, older than {args.days} days): {count}")
    if count == 0:
        return 0

    if args.dry_run:
        print("[prune] Dry run — no changes made")
        return 0

    if not args.yes:
        print("[prune] Use --yes to confirm deletion, or --dry-run to preview", file=sys.stderr)
        return 1

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        cur = conn.execute(
            "DELETE FROM jobs WHERE status IN ('done','failed') AND finished_at IS NOT NULL AND finished_at < ?",
            (cutoff,),
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        print(f"event=prune_executed deleted={deleted} days={args.days}", file=sys.stderr)
        print(f"[prune] Deleted {deleted} jobs")
    except sqlite3.Error as e:
        print(f"[prune] DB error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
