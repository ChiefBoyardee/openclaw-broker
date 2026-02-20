"""
Tool registry and dispatcher for LLM tool-calling (Sprint 5). OpenAI function-calling schema; dispatch to runner helpers.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


# OpenAI-style tool definitions (function name, description, parameters schema)
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "repo_list",
            "description": "List allowlisted git repos available on the runner.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_status",
            "description": "Get git status (branch, dirty, porcelain) for a repo.",
            "parameters": {
                "type": "object",
                "properties": {"repo": {"type": "string", "description": "Repo name from allowlist"}},
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_last_commit",
            "description": "Get last commit hash, author, date, subject for a repo.",
            "parameters": {
                "type": "object",
                "properties": {"repo": {"type": "string", "description": "Repo name from allowlist"}},
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_grep",
            "description": "Search for a query in a repo (ripgrep or git grep).",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repo name from allowlist"},
                    "query": {"type": "string", "description": "Search query"},
                    "path": {"type": "string", "description": "Optional path prefix to limit search"},
                },
                "required": ["repo", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_readfile",
            "description": "Read a file in a repo by path and line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repo name from allowlist"},
                    "path": {"type": "string", "description": "Relative path within repo"},
                    "start_line": {"type": "integer", "description": "First line (1-based)", "default": 1},
                    "end_line": {"type": "integer", "description": "Last line (inclusive)", "default": 200},
                },
                "required": ["repo", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_echo",
            "description": "Create a plan (echo scaffold) with the given text; returns plan_id for approve.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Plan summary or description"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_echo",
            "description": "Approve a plan by plan_id (echo scaffold).",
            "parameters": {
                "type": "object",
                "properties": {"plan_id": {"type": "string", "description": "Plan ID from plan_echo"}},
                "required": ["plan_id"],
            },
        },
    },
]


def get_tools_schema(allowed_tools: set[str]) -> list[dict[str, Any]]:
    """Return OpenAI tools list filtered to allowed_tools (names from TOOL_DEFINITIONS)."""
    names = {d["function"]["name"] for d in TOOL_DEFINITIONS}
    return [
        d for d in TOOL_DEFINITIONS
        if d["function"]["name"] in allowed_tools and d["function"]["name"] in names
    ]


def dispatch(
    name: str,
    args: dict[str, Any],
    repo_context: Optional[dict[str, str]],
    *,
    runner_bridge: Any,
) -> str:
    """
    Execute one tool by name with args. runner_bridge must have methods:
    repo_list(), repo_status(repo), repo_last_commit(repo), repo_grep(repo, query, path),
    repo_readfile(repo, path, start_line, end_line), plan_echo(text), approve_echo(plan_id).
    Returns result string (JSON or plain). Raises ValueError if tool not allowed or args invalid.
    """
    allowed = getattr(runner_bridge, "allowed_tools", None)
    if allowed is not None and name not in allowed:
        raise ValueError(f"tool not allowed: {name}")
    # Apply repo_context defaults
    repo = args.get("repo") or (repo_context or {}).get("repo")
    path_hint = (repo_context or {}).get("path_hint") or ""

    if name == "repo_list":
        return runner_bridge.repo_list()
    if name == "repo_status":
        if not repo:
            raise ValueError("repo required")
        return runner_bridge.repo_status(repo)
    if name == "repo_last_commit":
        if not repo:
            raise ValueError("repo required")
        return runner_bridge.repo_last_commit(repo)
    if name == "repo_grep":
        if not repo:
            raise ValueError("repo required")
        query = args.get("query", "")
        path = args.get("path") or path_hint
        return runner_bridge.repo_grep(repo, query, path or "")
    if name == "repo_readfile":
        if not repo:
            raise ValueError("repo required")
        path = args.get("path", "")
        if not path:
            raise ValueError("path required")
        start = int(args.get("start_line", 1))
        end = int(args.get("end_line", 200))
        return runner_bridge.repo_readfile(repo, path, start, end)
    if name == "plan_echo":
        text = args.get("text", "")
        return runner_bridge.plan_echo(text)
    if name == "approve_echo":
        plan_id = (args.get("plan_id") or "").strip()
        if not plan_id:
            raise ValueError("plan_id required")
        return runner_bridge.approve_echo(plan_id)
    raise ValueError(f"unknown tool: {name}")


def parse_tool_args(arguments: str) -> dict[str, Any]:
    """Parse tool call arguments JSON string. Returns dict or raises."""
    if not (arguments or arguments.strip()):
        return {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid tool arguments JSON: {e}") from e
