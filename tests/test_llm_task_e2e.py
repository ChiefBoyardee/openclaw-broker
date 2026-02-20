"""
Minimal e2e-style test: create llm_task job, simulate runner claim + POST result with canned envelope,
GET job as bot, assert result.final present and can be formatted (no crash).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["BROKER_DB"] = _tmp.name
os.environ["WORKER_TOKEN"] = "test-worker-token"
os.environ["BOT_TOKEN"] = "test-bot-token"

import json
import pytest
from fastapi.testclient import TestClient

import broker.app as broker_app_module
from broker.app import app

broker_app_module.WORKER_TOKEN = "test-worker-token"
broker_app_module.BOT_TOKEN = "test-bot-token"

client = TestClient(app)
worker_headers = {"X-Worker-Token": "test-worker-token", "X-Worker-Id": "w1", "X-Worker-Caps": '["llm:vllm","repo_tools"]'}
bot_headers = {"X-Bot-Token": "test-bot-token"}


def test_llm_task_job_create_claim_result_display():
    """Create llm_task job, claim with caps, POST canned result, GET job and parse final."""
    payload = json.dumps({"prompt": "What is 2+2?", "tools": ["repo_list"]})
    requires = '{"caps":["llm:vllm"]}'
    r = client.post("/jobs", headers=bot_headers, json={"command": "llm_task", "payload": payload, "requires": requires})
    assert r.status_code == 200
    jid = r.json()["id"]

    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200
    job = r.json().get("job")
    assert job is not None
    assert job["id"] == jid
    assert job["command"] == "llm_task"

    canned_envelope = {
        "final": "2 + 2 equals 4.",
        "tool_calls": [{"name": "repo_list", "args": {}, "status": "ok", "truncated_output": "{}"}],
        "model": "test",
        "worker_id": "w1",
        "safety": {},
    }
    r = client.post(f"/jobs/{jid}/result", headers=worker_headers, json={"result": json.dumps(canned_envelope)})
    assert r.status_code == 200

    r = client.get(f"/jobs/{jid}", headers=bot_headers)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "done"
    result_str = j.get("result")
    assert result_str
    parsed = json.loads(result_str)
    assert "final" in parsed
    assert parsed["final"] == "2 + 2 equals 4."
    # Bot formatting: extract final for display (no crash)
    display = parsed.get("final", result_str)
    assert "4" in display
