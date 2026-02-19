"""
OpenClaw Runner — worker that long-polls broker /jobs/next and posts /jobs/{id}/result or /jobs/{id}/fail.
Runs on worker machine (e.g. WSL). Reads config from env (runner.env).
"""

import json
import os
import socket
import sys
import time
import uuid

import requests

# --- Config from env ---
BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
WORKER_ID = os.environ.get("WORKER_ID", "") or socket.gethostname()
RUNNER_STATE_DIR = os.environ.get("RUNNER_STATE_DIR", "/var/lib/openclaw-runner/state")
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "10"))
RESULT_TIMEOUT_SEC = int(os.environ.get("RESULT_TIMEOUT_SEC", "300"))

RESULT_RETRY_BACKOFF = [0.5, 1.0, 2.0]
RESULT_RETRY_ATTEMPTS = 3

PLANS_DIR = os.path.join(RUNNER_STATE_DIR, "plans")


def _ensure_plans_dir() -> None:
    os.makedirs(PLANS_DIR, exist_ok=True)


def _post_with_retry(method: str, url: str, headers: dict, json_body: dict, timeout: int = 30) -> bool:
    """
    POST to broker; retry on 5xx or network errors. Return True if terminal success (200).
    - 200 -> success (terminal)
    - 4xx (including 404) -> terminal, no retry; return False
    - 5xx or RequestException -> retry up to RESULT_RETRY_ATTEMPTS with backoff
    """
    for attempt in range(RESULT_RETRY_ATTEMPTS):
        try:
            r = requests.post(url, headers=headers, json=json_body, timeout=timeout)
            if r.status_code == 200:
                return True
            if 400 <= r.status_code < 500:
                print(f"[runner] {method} {r.status_code}: {r.text}", file=sys.stderr)
                return False
            # 5xx or other
            print(f"[runner] {method} {r.status_code} (attempt {attempt + 1}/{RESULT_RETRY_ATTEMPTS})", file=sys.stderr)
        except requests.RequestException as e:
            print(f"[runner] {method} request error (attempt {attempt + 1}/{RESULT_RETRY_ATTEMPTS}): {e}", file=sys.stderr)
        if attempt < RESULT_RETRY_ATTEMPTS - 1:
            time.sleep(RESULT_RETRY_BACKOFF[attempt])
    return False


def main():
    if not WORKER_TOKEN:
        print("[runner] ERROR: WORKER_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    _ensure_plans_dir()
    headers = {"X-Worker-Token": WORKER_TOKEN, "X-Worker-Id": WORKER_ID}
    print(f"[runner] started; broker={BROKER_URL} worker_id={WORKER_ID} poll_interval={POLL_INTERVAL_SEC}s")
    while True:
        try:
            r = requests.get(f"{BROKER_URL}/jobs/next", headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            job = data.get("job")
            if not job:
                time.sleep(POLL_INTERVAL_SEC)
                continue
            job_id = job["id"]
            command = job.get("command", "")
            payload = job.get("payload", "")
            print(f"[runner] claimed job id={job_id} command={command}")

            try:
                result = run_job(command, payload)
                ok = _post_with_retry(
                    "result",
                    f"{BROKER_URL}/jobs/{job_id}/result",
                    headers,
                    {"result": result},
                )
                if ok:
                    print(f"[runner] result posted id={job_id}")
            except Exception as e:
                err_msg = str(e) or "unknown"
                print(f"[runner] job failed: {err_msg}", file=sys.stderr)
                ok = _post_with_retry(
                    "fail",
                    f"{BROKER_URL}/jobs/{job_id}/fail",
                    headers,
                    {"error": err_msg},
                )
                if ok:
                    print(f"[runner] fail posted id={job_id}")

        except requests.RequestException as e:
            print(f"[runner] request error: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL_SEC)
        except Exception as e:
            print(f"[runner] error: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL_SEC)


def run_job(command: str, payload: str) -> str:
    """Execute the job and return result string (plain or JSON string)."""
    if command == "ping":
        return f"pong: {payload}"

    if command == "capabilities":
        out = {
            "worker_id": WORKER_ID,
            "capabilities": ["ping", "capabilities", "plan_echo", "approve_echo"],
            "version": "mvp",
        }
        return json.dumps(out)

    if command == "plan_echo":
        plan_id = str(uuid.uuid4())
        summary = f"Echo plan for: {payload[:200]}" if payload else "Echo plan (no payload)"
        plan_obj = {
            "type": "plan",
            "plan_id": plan_id,
            "summary": summary,
            "proposed_actions": ["(no-op)"],
            "requires_approval": True,
        }
        path = os.path.join(PLANS_DIR, f"{plan_id}.json")
        with open(path, "w") as f:
            json.dump(plan_obj, f, indent=2)
        return json.dumps(plan_obj)

    if command == "approve_echo":
        plan_id = (payload or "").strip()
        if not plan_id:
            raise ValueError("plan_id required")
        path = os.path.join(PLANS_DIR, f"{plan_id}.json")
        if not os.path.isfile(path):
            raise ValueError("unknown plan_id")
        approval = {
            "type": "approval",
            "plan_id": plan_id,
            "status": "approved",
            "applied": False,
            "note": "no-op (scaffold)",
        }
        return json.dumps(approval)

    return f"unknown command: {command}"
