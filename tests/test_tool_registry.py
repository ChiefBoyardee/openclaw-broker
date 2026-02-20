"""
Unit tests for runner tool registry: allowed tools dispatch, unknown rejected, args validated.
No network; uses mock bridge.
"""
import sys
sys.path.insert(0, ".")

import pytest
from runner.tool_registry import (
    dispatch,
    get_tools_schema,
    parse_tool_args,
    TOOL_DEFINITIONS,
)


class MockBridge:
    """Minimal bridge for testing: only repo_list and plan_echo (no real I/O)."""
    allowed_tools = {"repo_list", "repo_status", "plan_echo", "approve_echo"}
    worker_id = "test-worker"

    def repo_list(self):
        return '{"ok": true, "data": {"repos": []}}'
    def repo_status(self, repo: str):
        return f'{{"ok": true, "repo": "{repo}"}}'
    def repo_last_commit(self, repo: str):
        return f'{{"ok": true, "repo": "{repo}"}}'
    def repo_grep(self, repo: str, query: str, path: str):
        return f'{{"ok": true, "repo": "{repo}"}}'
    def repo_readfile(self, repo: str, path: str, start: int, end: int):
        return f'{{"ok": true, "path": "{path}"}}'
    def plan_echo(self, text: str):
        return f'{{"plan_id": "test-plan", "summary": "{text[:50]}"}}'
    def approve_echo(self, plan_id: str):
        return f'{{"status": "approved", "plan_id": "{plan_id}"}}'


def test_get_tools_schema_returns_subset():
    schema = get_tools_schema({"repo_list", "repo_grep"})
    names = [t["function"]["name"] for t in schema]
    assert "repo_list" in names
    assert "repo_grep" in names
    assert len(schema) == 2


def test_get_tools_schema_empty_allowed():
    schema = get_tools_schema(set())
    assert schema == []


def test_parse_tool_args():
    assert parse_tool_args("{}") == {}
    assert parse_tool_args('{"repo": "x"}') == {"repo": "x"}
    with pytest.raises(ValueError, match="invalid tool arguments"):
        parse_tool_args("not json")


def test_dispatch_repo_list():
    bridge = MockBridge()
    out = dispatch("repo_list", {}, None, runner_bridge=bridge)
    assert "ok" in out or "repos" in out


def test_dispatch_plan_echo():
    bridge = MockBridge()
    out = dispatch("plan_echo", {"text": "hello"}, None, runner_bridge=bridge)
    assert "plan_id" in out or "summary" in out


def test_dispatch_repo_status_requires_repo():
    bridge = MockBridge()
    out = dispatch("repo_status", {"repo": "myrepo"}, None, runner_bridge=bridge)
    assert "ok" in out
    with pytest.raises(ValueError, match="repo required"):
        dispatch("repo_status", {}, None, runner_bridge=bridge)


def test_dispatch_unknown_tool_rejected():
    bridge = MockBridge()
    bridge.allowed_tools = None  # skip allowlist so we hit "unknown tool" path
    with pytest.raises(ValueError, match="unknown tool"):
        dispatch("nonexistent_tool", {}, None, runner_bridge=bridge)


def test_dispatch_tool_not_in_allowed_rejected():
    bridge = MockBridge()
    bridge.allowed_tools = {"repo_list"}
    with pytest.raises(ValueError, match="not allowed"):
        dispatch("repo_status", {"repo": "x"}, None, runner_bridge=bridge)
