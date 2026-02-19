"""
Small pytest suite for broker protocol: migration, job shape, idempotent result/fail, lease/requeue.
Uses a temp SQLite DB and FastAPI TestClient.
"""
import os
import sys
import tempfile

# Add repo root so "broker" package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Temp DB and tokens set before broker import so init_db/migrate_db use temp DB
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["BROKER_DB"] = _tmp.name
os.environ["WORKER_TOKEN"] = "test-worker-token"
os.environ["BOT_TOKEN"] = "test-bot-token"

import pytest
from fastapi.testclient import TestClient

import broker.app as broker_app_module
from broker.app import app

# Ensure tokens are set for dependency checks at request time
broker_app_module.WORKER_TOKEN = "test-worker-token"
broker_app_module.BOT_TOKEN = "test-bot-token"

client = TestClient(app)
worker_headers = {"X-Worker-Token": "test-worker-token"}
bot_headers = {"X-Bot-Token": "test-bot-token"}


def _create_job() -> str:
    r = client.post("/jobs", headers=bot_headers, json={"command": "ping", "payload": "x"})
    assert r.status_code == 200
    return r.json()["id"]


def _job_shape(j: dict) -> None:
    """Assert standard keys exist (value can be null)."""
    for k in ("id", "created_at", "started_at", "finished_at", "lease_until", "status", "command", "payload", "result", "error", "worker_id"):
        assert k in j, f"missing key {k}"


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "ts_bound": True}


def test_get_job_returns_standard_shape():
    jid = _create_job()
    r = client.get(f"/jobs/{jid}", headers=bot_headers)
    assert r.status_code == 200
    j = r.json()
    _job_shape(j)
    assert j["status"] == "queued"
    assert j["id"] == jid


def test_result_idempotent_when_done():
    _create_job()
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200
    job = r.json().get("job")
    assert job is not None
    claimed_id = job["id"]
    # Finish
    r = client.post(f"/jobs/{claimed_id}/result", headers=worker_headers, json={"result": "ok"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "done"}
    # Idempotent retry
    r = client.post(f"/jobs/{claimed_id}/result", headers=worker_headers, json={"result": "ignored"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "done"}


def test_result_idempotent_when_failed():
    jid = _create_job()
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.json().get("job") is not None
    # Fail it
    r = client.post(f"/jobs/{jid}/fail", headers=worker_headers, json={"error": "oops"})
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    # Posting result on failed -> 200 with note
    r = client.post(f"/jobs/{jid}/result", headers=worker_headers, json={"result": "ignored"})
    assert r.status_code == 200
    assert r.json().get("note") == "already failed; result ignored"


def test_fail_endpoint_and_idempotent():
    jid = _create_job()
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.json().get("job") is not None
    r = client.post(f"/jobs/{jid}/fail", headers=worker_headers, json={"error": "err"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "failed"}
    # GET job shows failed + error
    r = client.get(f"/jobs/{jid}", headers=bot_headers)
    assert r.json()["status"] == "failed"
    assert r.json()["error"] == "err"
    # Idempotent fail
    r = client.post(f"/jobs/{jid}/fail", headers=worker_headers, json={"error": "other"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "failed"}


def test_queued_result_returns_400():
    jid = _create_job()
    # Do not claim; try to post result
    r = client.post(f"/jobs/{jid}/result", headers=worker_headers, json={"result": "x"})
    assert r.status_code == 400


def test_lease_set_on_claim_and_requeue_after_expiry():
    _create_job()
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200
    job = r.json().get("job")
    assert job is not None
    assert job["status"] == "running"
    assert job.get("started_at") is not None
    assert job.get("lease_until") is not None
    _job_shape(job)


def test_ping_flow_end_to_end():
    _create_job()
    r = client.get("/jobs/next", headers=worker_headers)
    job = r.json().get("job")
    assert job is not None
    jid = job["id"]
    r = client.post(f"/jobs/{jid}/result", headers=worker_headers, json={"result": "pong: hello"})
    assert r.status_code == 200
    r = client.get(f"/jobs/{jid}", headers=bot_headers)
    j = r.json()
    assert j["status"] == "done"
    assert j["result"] == "pong: hello"
    _job_shape(j)


def test_claim_sets_worker_id():
    _create_job()
    r = client.get("/jobs/next", headers={**worker_headers, "X-Worker-Id": "test-worker-1"})
    assert r.status_code == 200
    job = r.json().get("job")
    assert job is not None
    assert job["worker_id"] == "test-worker-1"
    jid = job["id"]
    r = client.get(f"/jobs/{jid}", headers=bot_headers)
    assert r.json()["worker_id"] == "test-worker-1"


def test_requeue_clears_worker_id_then_second_claim_sets_new():
    """Requeue stale job (lease expired); second claim gets job and sets new worker_id."""
    import time as _time
    _create_job()
    # Claim with worker 1
    r = client.get("/jobs/next", headers={**worker_headers, "X-Worker-Id": "worker-one"})
    assert r.status_code == 200
    job = r.json().get("job")
    assert job is not None
    jid = job["id"]
    assert job["worker_id"] == "worker-one"
    # Force lease to be expired: set lease_until to 0 in DB
    with broker_app_module.db_conn() as conn:
        conn.execute("UPDATE jobs SET lease_until = 0 WHERE id = ?", (jid,))
    # Next GET /jobs/next will requeue (lease_until < now) and then claim with worker-two
    _time.sleep(1)
    r2 = client.get("/jobs/next", headers={**worker_headers, "X-Worker-Id": "worker-two"})
    assert r2.status_code == 200
    job2 = r2.json().get("job")
    assert job2 is not None
    assert job2["id"] == jid
    assert job2["worker_id"] == "worker-two"
