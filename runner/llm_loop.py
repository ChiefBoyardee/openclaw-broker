"""
LLM tool loop for llm_task command (Sprint 5). Calls LLM with tools, dispatches tool calls, returns result envelope.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from runner.llm_client import chat_with_tools
from runner.tool_registry import dispatch, get_tools_schema, parse_tool_args

# Truncate tool output for audit (bytes)
TOOL_OUTPUT_MAX_BYTES = 8000


def _truncate_for_audit(s: str, max_bytes: int = TOOL_OUTPUT_MAX_BYTES) -> tuple[str, bool]:
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def run_llm_tool_loop(
    prompt: str,
    tools_requested: list[str],
    repo_context: Optional[dict[str, str]],
    max_steps: int,
    config: dict[str, Any],
    runner_bridge: Any,
) -> dict[str, Any]:
    """
    Run the LLM tool loop: system + user message, then loop (call LLM, execute tool_calls, append results) until
    final content or max_steps. Returns result envelope: final, tool_calls, model, worker_id, safety.
    """
    allowed = config.get("allowed_tools") or set()
    tools_to_use = [t for t in tools_requested if t in allowed] if tools_requested else list(allowed)
    if not tools_to_use:
        tools_to_use = list(allowed)
    tools_schema = get_tools_schema(set(tools_to_use))
    if not tools_schema:
        return {
            "final": "No tools available or configured.",
            "tool_calls": [],
            "model": config.get("model", ""),
            "worker_id": getattr(runner_bridge, "worker_id", ""),
            "safety": {"reason": "no_tools"},
        }

    system_content = (
        "You are a helpful assistant with access to read-only repo tools (repo_list, repo_status, repo_grep, repo_readfile, etc.) "
        "and plan_echo/approve_echo. Use the provided tools to answer the user. "
        f"You have at most {max_steps} tool-call rounds. "
        "Tool output may be truncated. When you have enough information, respond with a final answer in plain text (no tool calls)."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": prompt},
    ]
    tool_calls_audit: list[dict[str, Any]] = []
    step = 0
    final_text: Optional[str] = None
    model_used = config.get("model", "")
    worker_id = getattr(runner_bridge, "worker_id", "")
    safety: dict[str, Any] = {}

    while step < max_steps:
        step += 1
        response = chat_with_tools(
            messages,
            tools_schema,
            base_url=config.get("base_url", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            temperature=config.get("temperature", 0.2),
            max_tokens=config.get("max_tokens", 4096),
        )
        content = response.get("content")
        tc_list = response.get("tool_calls")
        if content and not tc_list:
            final_text = content
            break
        if not tc_list:
            final_text = content or "(no response)"
            break
        # Append assistant message with tool_calls first (OpenAI format), then tool results
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tc_list:
            assistant_msg["tool_calls"] = [
                {"id": tc.get("id"), "type": "function", "function": {"name": tc.get("name"), "arguments": tc.get("arguments", "{}")}}
                for tc in tc_list
            ]
        messages.append(assistant_msg)
        for tc in tc_list:
            name = tc.get("name", "")
            args_str = tc.get("arguments", "{}")
            try:
                args = parse_tool_args(args_str)
            except ValueError as e:
                tool_calls_audit.append({"name": name, "args": args_str, "status": "error", "truncated_output": str(e)})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": f"Error: {e}",
                })
                continue
            try:
                result = dispatch(name, args, repo_context, runner_bridge=runner_bridge)
            except Exception as e:
                err_msg = str(e) or "unknown"
                tool_calls_audit.append({"name": name, "args": args, "status": "error", "truncated_output": err_msg})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": f"Error: {err_msg}",
                })
                continue
            truncated_result, was_truncated = _truncate_for_audit(result)
            if was_truncated:
                safety["truncations"] = safety.get("truncations", 0) + 1
            tool_calls_audit.append({
                "name": name,
                "args": args,
                "status": "ok",
                "truncated_output": truncated_result,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": truncated_result,
            })

    if final_text is None:
        final_text = "Max tool steps reached without final answer."
        safety["max_steps_reached"] = True
    return {
        "final": final_text,
        "tool_calls": tool_calls_audit,
        "model": model_used,
        "worker_id": worker_id,
        "safety": safety,
    }
