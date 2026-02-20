"""
LLM config for runner (Sprint 5). Reads env for OpenAI-compatible endpoint and tool loop limits.
"""
from __future__ import annotations

import os


def get_llm_config() -> dict:
    """Read LLM-related env and return config dict. Keys: base_url, api_key, model, temperature, max_tokens, max_steps, allowed_tools."""
    provider = os.environ.get("LLM_PROVIDER", "openai_compat").strip().lower()
    base_url = (os.environ.get("LLM_BASE_URL", "") or "").strip().rstrip("/")
    api_key = (os.environ.get("LLM_API_KEY", "") or "").strip()
    model = (os.environ.get("LLM_MODEL", "") or "").strip()
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
    max_steps = int(os.environ.get("LLM_TOOL_LOOP_MAX_STEPS", "6"))
    allowed_str = (os.environ.get("LLM_ALLOWED_TOOLS", "") or "").strip()
    allowed_tools = {t.strip() for t in allowed_str.split(",") if t.strip()} if allowed_str else set()
    if not allowed_tools:
        # Default Sprint 5 allowlist
        allowed_tools = {
            "repo_list",
            "repo_status",
            "repo_last_commit",
            "repo_grep",
            "repo_readfile",
            "plan_echo",
            "approve_echo",
        }
    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "max_steps": max_steps,
        "allowed_tools": allowed_tools,
    }
