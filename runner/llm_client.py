"""
LLM client for runner (Sprint 5). OpenAI-compatible chat with tools (single call).
Includes fallback parsing for Qwen3-style <tool_call> XML when llama-server
doesn't natively parse them (i.e. when --jinja flag is not used).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

# Regex patterns for Qwen3 native output format
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
# Fallback: some Qwen variants emit <toolname arg="val"> style XML
_XML_TOOL_RE = re.compile(
    r"<(browser_\w+|repo_\w+|github_\w+|website_\w+|plan_echo|approve_echo|discord_\w+|nginx_\w+)"
    r"([^>]*)(?:/>|>.*?</\1>)",
    re.DOTALL,
)


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks from content."""
    return _THINK_RE.sub("", text).strip()


def _parse_xml_attrs(attr_string: str) -> dict[str, str]:
    """Parse XML-style attributes like 'url="https://..." wait_for_load="true"'."""
    attrs = {}
    for match in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', attr_string):
        attrs[match.group(1)] = match.group(2)
    return attrs


def _extract_tool_calls_from_content(content: str) -> tuple[list[dict] | None, str | None]:
    """
    Extract tool calls from raw LLM content when tool_calls field is null.
    Handles two formats:
      1. Qwen3 standard: <tool_call>{"name":"...", "arguments":{...}}</tool_call>
      2. XML-style: <browser_navigate url="...">
    Returns (tool_calls_list, remaining_content).
    """
    if not content:
        return None, content

    tool_calls = []

    # Try standard <tool_call> format first
    for match in _TOOL_CALL_RE.finditer(content):
        try:
            tc_data = json.loads(match.group(1))
            name = tc_data.get("name", "")
            arguments = tc_data.get("arguments", {})
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments)
            tool_calls.append({
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "name": name,
                "arguments": arguments,
            })
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse <tool_call> JSON: {e}")

    # Fallback: try XML-style <toolname attr="val">
    if not tool_calls:
        for match in _XML_TOOL_RE.finditer(content):
            name = match.group(1)
            attrs = _parse_xml_attrs(match.group(2))
            if attrs or name:
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "name": name,
                    "arguments": json.dumps(attrs),
                })

    if tool_calls:
        # Strip tool call XML and think blocks from remaining content
        remaining = _TOOL_CALL_RE.sub("", content)
        remaining = _XML_TOOL_RE.sub("", remaining)
        remaining = _strip_think_blocks(remaining).strip()
        # If only whitespace/empty after stripping, no user-facing content
        return tool_calls, remaining if remaining else None

    return None, content


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
    Includes fallback parsing for Qwen3 <tool_call> XML when the server
    doesn't natively parse tool calls (e.g. llama-server without --jinja).
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
    raw_content = (msg.content or "").strip() if msg.content else None

    # Check for native tool_calls first (works with --jinja)
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        # Strip <think> from content even when tool_calls are native
        clean_content = _strip_think_blocks(raw_content) if raw_content else None
        return {
            "content": clean_content if clean_content else None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": getattr(tc.function, "name", "") if tc.function else "",
                    "arguments": getattr(tc.function, "arguments", "{}") if tc.function else "{}",
                }
                for tc in msg.tool_calls
            ],
        }

    # Fallback: parse <tool_call> / XML from raw content
    if raw_content:
        extracted_calls, remaining_content = _extract_tool_calls_from_content(raw_content)
        if extracted_calls:
            logger.info(f"Extracted {len(extracted_calls)} tool call(s) from raw content (fallback parser)")
            return {
                "content": remaining_content,
                "tool_calls": extracted_calls,
            }
        # No tool calls found — this is a final answer, strip <think> blocks
        clean_content = _strip_think_blocks(raw_content)
        return {
            "content": clean_content if clean_content else None,
            "tool_calls": None,
        }

    return {"content": raw_content, "tool_calls": None}
