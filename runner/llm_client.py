"""
LLM client for runner (Sprint 5). OpenAI-compatible chat with tools (single call).
Includes fallback parsing for Qwen3-style tool calls when llama-server
doesn't natively parse them into structured tool_calls.

Handles three raw-text formats:
  1. <tool_call>{"name":"...", "arguments":{...}}</tool_call>  (Qwen3 standard)
  2. <toolname attr="val">  (XML-style)
  3. toolname("arg")  or  toolname(key="val", ...)  (Python function-call style)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

# ── Known tool names (used for function-call-style detection) ──
_KNOWN_TOOLS = {
    "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
    "browser_search", "browser_extract_article", "browser_close",
    "repo_list", "repo_status", "repo_last_commit", "repo_grep", "repo_readfile",
    "plan_echo", "approve_echo",
    "github_create_repo", "github_list_repos", "github_create_issue",
    "github_list_issues", "github_read_file", "github_write_file",
    "github_search_repos", "github_search_code", "github_get_user",
    "website_init", "website_write_file", "website_read_file",
    "website_list_files", "website_create_post", "website_create_knowledge_page",
    "website_update_about", "website_get_stats",
    "nginx_generate_config", "nginx_install_config", "nginx_enable_site",
    "nginx_disable_site", "nginx_remove_config", "nginx_test_config",
    "nginx_reload", "nginx_get_status",
    "discord_send_message", "discord_send_embed", "discord_add_reaction",
    "discord_upload_file", "discord_edit_message", "discord_reply",
}

# ── Regex patterns ──
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_XML_TOOL_RE = re.compile(
    r"<(browser_\w+|repo_\w+|github_\w+|website_\w+|plan_echo|approve_echo|discord_\w+|nginx_\w+)"
    r"([^>]*)(?:/>|>.*?</\1>)",
    re.DOTALL,
)
# Python function-call style: tool_name("arg") or tool_name(key="val", key2="val2")
_FUNC_CALL_NAMES = "|".join(re.escape(t) for t in sorted(_KNOWN_TOOLS, key=len, reverse=True))
_FUNC_CALL_RE = re.compile(
    rf"(?:^|\s)({_FUNC_CALL_NAMES})\s*\(([^)]*)\)",
    re.MULTILINE,
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


def _parse_func_args(args_string: str, func_name: str) -> dict[str, str]:
    """
    Parse function-call-style arguments.
    Handles: "https://example.com"  →  {"url": "https://example.com"}
    Handles: key="val", key2="val2"  →  {"key": "val", "key2": "val2"}
    Handles: "query text"  →  {"query": "query text"}
    """
    args_string = args_string.strip()
    if not args_string:
        return {}

    # Try key="val" style first
    kwargs = {}
    for match in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', args_string):
        kwargs[match.group(1)] = match.group(2)
    if kwargs:
        return kwargs

    # Single positional string argument — infer the parameter name
    # Strip surrounding quotes
    if (args_string.startswith('"') and args_string.endswith('"')) or \
       (args_string.startswith("'") and args_string.endswith("'")):
        val = args_string[1:-1]
    else:
        val = args_string

    # Map to the most likely parameter name based on the tool
    param_map = {
        "browser_navigate": "url",
        "browser_search": "query",
        "browser_type": "text",
        "browser_click": "selector",
        "repo_status": "repo",
        "repo_last_commit": "repo",
        "repo_grep": "query",
        "repo_readfile": "path",
        "plan_echo": "text",
        "approve_echo": "plan_id",
    }
    param_name = param_map.get(func_name, "input")
    return {param_name: val}


def _extract_tool_calls_from_content(content: str) -> tuple[list[dict] | None, str | None]:
    """
    Extract tool calls from raw LLM content when tool_calls field is null.
    Returns (tool_calls_list, remaining_content).
    """
    if not content:
        return None, content

    tool_calls = []

    # 1. Try standard <tool_call>{"name":"...", "arguments":{...}}</tool_call>
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
            logger.info(f"Fallback parser: extracted <tool_call> → {name}")
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse <tool_call> JSON: {e}")

    # 2. Try XML-style <toolname attr="val">
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
                logger.info(f"Fallback parser: extracted XML-style → {name}({attrs})")

    # 3. Try Python function-call style: tool_name("arg") or tool_name(key="val")
    if not tool_calls:
        for match in _FUNC_CALL_RE.finditer(content):
            name = match.group(1).strip()
            raw_args = match.group(2)
            args = _parse_func_args(raw_args, name)
            tool_calls.append({
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "name": name,
                "arguments": json.dumps(args),
            })
            logger.info(f"Fallback parser: extracted func-call-style → {name}({args})")

    if tool_calls:
        # Strip tool call patterns and think blocks from remaining content
        remaining = _TOOL_CALL_RE.sub("", content)
        remaining = _XML_TOOL_RE.sub("", remaining)
        remaining = _FUNC_CALL_RE.sub("", remaining)
        remaining = _strip_think_blocks(remaining).strip()
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
    Includes fallback parsing for Qwen3 tool calls when the server
    doesn't natively parse them.
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
        logger.warning("LLM returned no choices/message")
        return {"content": None, "tool_calls": None}

    msg = choice.message
    raw_content = (msg.content or "").strip() if msg.content else None
    native_tool_calls = msg.tool_calls if hasattr(msg, "tool_calls") else None

    # Debug: log what the LLM actually returned
    logger.info(f"LLM response: content_len={len(raw_content) if raw_content else 0}, "
                f"has_native_tool_calls={bool(native_tool_calls)}, "
                f"finish_reason={choice.finish_reason}")
    if raw_content:
        logger.debug(f"LLM raw content (first 500 chars): {raw_content[:500]}")
    if native_tool_calls:
        for tc in native_tool_calls:
            logger.info(f"Native tool_call: {tc.function.name if tc.function else '?'}("
                       f"{tc.function.arguments[:100] if tc.function else '?'})")

    # Check for native tool_calls first (works with chatml-function-calling / --jinja)
    if native_tool_calls:
        clean_content = _strip_think_blocks(raw_content) if raw_content else None
        return {
            "content": clean_content if clean_content else None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": getattr(tc.function, "name", "") if tc.function else "",
                    "arguments": getattr(tc.function, "arguments", "{}") if tc.function else "{}",
                }
                for tc in native_tool_calls
            ],
        }

    # Fallback: parse tool calls from raw content
    if raw_content:
        extracted_calls, remaining_content = _extract_tool_calls_from_content(raw_content)
        if extracted_calls:
            logger.info(f"Extracted {len(extracted_calls)} tool call(s) from raw content (fallback parser)")
            return {
                "content": remaining_content,
                "tool_calls": extracted_calls,
                "fallback_parsed": True,
            }
        # No tool calls found — final answer, strip <think> blocks
        clean_content = _strip_think_blocks(raw_content)
        return {
            "content": clean_content if clean_content else None,
            "tool_calls": None,
        }

    return {"content": raw_content, "tool_calls": None}
