#!/usr/bin/env python3
"""
OpenClaw smoke script: minimal end-to-end check of broker + simulated worker/bot.
Uses an in-process broker (temp DB). Does not require Discord or external services.
Exit 0 only on full success and prints "Smoke OK". Failure: exit 1 and prints error to stderr.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

# Repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Temp DB and tokens before broker import
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["BROKER_DB"] = _tmp.name
os.environ["WORKER_TOKEN"] = os.environ.get("WORKER_TOKEN", "smoke-worker-token")
os.environ["BOT_TOKEN"] = os.environ.get("BOT_TOKEN", "smoke-bot-token")

from fastapi.testclient import TestClient

import broker.app as broker_app_module
from broker.app import app

broker_app_module.WORKER_TOKEN = os.environ["WORKER_TOKEN"]
broker_app_module.BOT_TOKEN = os.environ["BOT_TOKEN"]

client = TestClient(app)
worker_headers = {
    "X-Worker-Token": os.environ["WORKER_TOKEN"],
    "X-Worker-Id": "smoke-worker",
    "X-Worker-Caps": '["llm:vllm","repo_tools"]',
}
bot_headers = {"X-Bot-Token": os.environ["BOT_TOKEN"]}


def run() -> None:
    # 1) Health
    r = client.get("/health")
    assert r.status_code == 200, f"/health: {r.status_code}"
    assert r.json().get("ok") is True, "/health: ok not true"

    # 2) Create job (bot), claim (worker), result, get job (bot) -> done
    r = client.post("/jobs", headers=bot_headers, json={"command": "ping", "payload": "smoke"})
    assert r.status_code == 200, f"POST /jobs: {r.status_code}"
    jid = r.json()["id"]
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200, f"GET /jobs/next: {r.status_code}"
    job = r.json().get("job")
    assert job is not None and job["id"] == jid, "claim: job missing or id mismatch"
    r = client.post(f"/jobs/{jid}/result", headers=worker_headers, json={"result": "pong"})
    assert r.status_code == 200, f"POST result: {r.status_code}"
    r = client.get(f"/jobs/{jid}", headers=bot_headers)
    assert r.status_code == 200, f"GET job: {r.status_code}"
    assert r.json()["status"] == "done" and r.json().get("result") == "pong", "job not done or result mismatch"

    # 3) Fail path: create, claim, fail (use job id from claim for robustness)
    r = client.post("/jobs", headers=bot_headers, json={"command": "ping", "payload": "fail-test"})
    assert r.status_code == 200, f"POST /jobs fail-test: {r.status_code}"
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200, f"GET /jobs/next (fail path): {r.status_code}"
    job = r.json().get("job")
    assert job is not None, "fail path: no job claimed"
    jid2 = job["id"]
    r = client.post(f"/jobs/{jid2}/fail", headers=worker_headers, json={"error": "smoke fail"})
    assert r.status_code == 200, f"POST fail: {r.status_code}"
    r = client.get(f"/jobs/{jid2}", headers=bot_headers)
    assert r.status_code == 200, f"GET job (failed): {r.status_code}"
    assert r.json()["status"] == "failed" and "smoke fail" in (r.json().get("error") or ""), "job not failed or error mismatch"

    # 4) Caps: job with requires, worker with caps claims it
    r = client.post(
        "/jobs",
        headers=bot_headers,
        json={"command": "ping", "payload": "caps", "requires": '{"caps":["llm:vllm"]}'},
    )
    assert r.status_code == 200, f"POST /jobs caps: {r.status_code}"
    jid3 = r.json()["id"]
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200, f"GET /jobs/next (caps): {r.status_code}"
    job = r.json().get("job")
    assert job is not None and job["id"] == jid3, "caps: job missing or id mismatch"
    r = client.post(f"/jobs/{jid3}/result", headers=worker_headers, json={"result": "ok"})
    assert r.status_code == 200, f"POST result (caps): {r.status_code}"

    # 5) llm_task: create, claim, POST canned result envelope, GET and parse
    payload = json.dumps({"prompt": "2+2?", "tools": ["repo_list"]})
    r = client.post(
        "/jobs",
        headers=bot_headers,
        json={"command": "llm_task", "payload": payload, "requires": '{"caps":["llm:vllm"]}'},
    )
    assert r.status_code == 200, f"POST /jobs llm_task: {r.status_code}"
    jid4 = r.json()["id"]
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200, f"GET /jobs/next (llm_task): {r.status_code}"
    job = r.json().get("job")
    assert job is not None and job["id"] == jid4, "llm_task: job missing or id mismatch"
    envelope = {"final": "4", "tool_calls": [], "model": "smoke", "worker_id": "smoke-worker", "safety": {}}
    r = client.post(f"/jobs/{jid4}/result", headers=worker_headers, json={"result": json.dumps(envelope)})
    assert r.status_code == 200, f"POST result (llm_task): {r.status_code}"
    r = client.get(f"/jobs/{jid4}", headers=bot_headers)
    assert r.status_code == 200, f"GET job (llm_task): {r.status_code}"
    assert r.json()["status"] == "done", "llm_task job not done"
    parsed = json.loads(r.json()["result"])
    assert parsed.get("final") == "4", "llm_task result final mismatch"

    print("Smoke OK")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"Smoke failed: {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
