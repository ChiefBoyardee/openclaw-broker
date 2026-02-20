"""
Unit tests for LLM tool loop: mocked chat_with_tools returns tool_calls then final; envelope has expected shape.
"""
import sys
sys.path.insert(0, ".")

import pytest
from unittest.mock import patch, MagicMock

from runner.llm_loop import run_llm_tool_loop


class MockBridge:
    allowed_tools = {"repo_list", "repo_grep"}
    worker_id = "test-worker"
    def repo_list(self):
        return '{"ok": true, "data": {"repos": [{"name": "x"}]}}'
    def repo_status(self, repo): return "{}"
    def repo_last_commit(self, repo): return "{}"
    def repo_grep(self, repo, query, path): return "{}"
    def repo_readfile(self, repo, path, start, end): return "{}"
    def plan_echo(self, text): return "{}"
    def approve_echo(self, plan_id): return "{}"


@patch("runner.llm_loop.chat_with_tools")
def test_llm_loop_produces_envelope_with_final(mock_chat):
    """Mock LLM returns final text immediately (no tool calls); envelope has final, tool_calls, model, worker_id."""
    mock_chat.return_value = {"content": "Here is the answer.", "tool_calls": None}
    config = {
        "base_url": "http://localhost:8000",
        "api_key": "",
        "model": "test-model",
        "temperature": 0.2,
        "max_tokens": 100,
        "allowed_tools": {"repo_list", "repo_grep"},
    }
    bridge = MockBridge()
    envelope = run_llm_tool_loop("What repos exist?", ["repo_list"], None, 6, config, bridge)
    assert envelope["final"] == "Here is the answer."
    assert envelope["tool_calls"] == []
    assert envelope["model"] == "test-model"
    assert envelope["worker_id"] == "test-worker"
    assert "safety" in envelope


@patch("runner.llm_loop.chat_with_tools")
def test_llm_loop_one_tool_then_final(mock_chat):
    """Mock LLM returns one tool_call (repo_list) then on second call returns final text."""
    call_count = [0]
    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "content": None,
                "tool_calls": [
                    {"id": "tc-1", "name": "repo_list", "arguments": "{}"},
                ],
            }
        return {"content": "The repo list is above.", "tool_calls": None}
    mock_chat.side_effect = side_effect
    config = {
        "base_url": "http://localhost:8000",
        "api_key": "",
        "model": "test-model",
        "temperature": 0.2,
        "max_tokens": 100,
        "allowed_tools": {"repo_list", "repo_grep"},
    }
    bridge = MockBridge()
    envelope = run_llm_tool_loop("List repos", ["repo_list"], None, 6, config, bridge)
    assert "The repo list is above" in envelope["final"]
    assert len(envelope["tool_calls"]) == 1
    assert envelope["tool_calls"][0]["name"] == "repo_list"
    assert envelope["tool_calls"][0]["status"] == "ok"
    assert mock_chat.call_count == 2
