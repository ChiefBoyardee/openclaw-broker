"""
Capability parsing and matching for broker job routing.
Workers advertise caps via X-Worker-Caps; jobs may require caps via requires JSON.
"""
from __future__ import annotations

import json
from typing import Optional


def parse_worker_caps(header_value: Optional[str]) -> set[str]:
    """Parse X-Worker-Caps: JSON array or comma-separated list. Returns set of cap strings."""
    if not header_value or not (header_value := header_value.strip()):
        return set()
    if header_value.startswith("["):
        try:
            arr = json.loads(header_value)
            return set(str(c).strip() for c in arr if c)
        except (json.JSONDecodeError, TypeError):
            pass
    return {c.strip() for c in header_value.split(",") if c.strip()}


def job_required_caps(requires: Optional[str]) -> Optional[set[str]]:
    """Parse job requires JSON e.g. {"caps": ["llm:vllm"]}. Returns set of caps or None if invalid/null."""
    if not requires or not (requires := requires.strip()):
        return None
    try:
        obj = json.loads(requires)
        caps = obj.get("caps")
        if caps is None:
            return None
        return set(str(c).strip() for c in caps if c is not None and str(c).strip()) if caps else set()
    except (json.JSONDecodeError, TypeError):
        return None


def job_matches_worker(requires: Optional[str], worker_caps: set[str]) -> bool:
    """True if job can be claimed by worker: requires is NULL/empty or job required caps ⊆ worker_caps."""
    required = job_required_caps(requires)
    if required is None or len(required) == 0:
        return True
    return required <= worker_caps


# Allowed job commands (Sprint 3). Unknown commands are rejected with 400.
ALLOWED_COMMANDS = frozenset({
    "ping",
    "capabilities",
    "plan_echo",
    "approve_echo",
    "repo_list",
    "repo_status",
    "repo_last_commit",
    "repo_grep",
    "repo_readfile",
    "llm_task",
})


def is_command_allowed(command: str) -> bool:
    """True if command is in the allowlist."""
    return (command or "").strip() in ALLOWED_COMMANDS
