"""
LLM client for runner (Sprint 5). OpenAI-compatible chat with tools (single call).
"""
from __future__ import annotations

from typing import Any

from openai import OpenAI


def chat_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """
    Call OpenAI-compatible chat completions with tools.
    messages: list of {"role": "user"|"system"|"assistant", "content": str} or assistant with "tool_calls".
    tools: list of {"type": "function", "function": {"name": str, "description": str, "parameters": {...}}}.
    Returns the message dict from choices[0].message (content, tool_calls, etc.).
    """
    client = OpenAI(base_url=base_url or None, api_key=api_key or "not-needed")
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    choice = response.choices[0] if response.choices else None
    if not choice or not choice.message:
        return {"content": None, "tool_calls": None}
    msg = choice.message
    out = {"content": (msg.content or "").strip() if msg.content else None}
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "name": getattr(tc.function, "name", "") if tc.function else "",
                "arguments": getattr(tc.function, "arguments", "{}") if tc.function else "{}",
            }
            for tc in msg.tool_calls
        ]
    else:
        out["tool_calls"] = None
    return out
