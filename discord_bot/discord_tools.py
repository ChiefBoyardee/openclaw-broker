"""
Discord-Native Tools for OpenClaw Agentic Mode

These tools are registered in the runner but executed by the Discord bot,
enabling the LLM to orchestrate Discord interactions directly.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Tool schemas for Discord-native tools
DISCORD_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "discord_send_message",
            "description": "Send a text message to the Discord channel. Use this to provide intermediate updates to the user during long-running tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message content to send (max 2000 chars)",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["info", "success", "warning", "error"],
                        "description": "Message type for styling",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_send_embed",
            "description": "Send a rich embed message to the Discord channel. Useful for structured data or formatted results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Embed title",
                    },
                    "description": {
                        "type": "string",
                        "description": "Embed description (main content)",
                    },
                    "color": {
                        "type": "integer",
                        "description": "Embed color as decimal (e.g., 3447003 for blue, 3066993 for green)",
                    },
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                                "inline": {"type": "boolean"},
                            },
                        },
                        "description": "Optional fields to add to the embed",
                    },
                    "url": {
                        "type": "string",
                        "description": "Optional URL for the title",
                    },
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_add_reaction",
            "description": "Add a reaction emoji to the user's message. Use sparingly to indicate progress or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "emoji": {
                        "type": "string",
                        "description": "The emoji to add (e.g., '👍', '✅', '🤔')",
                    },
                },
                "required": ["emoji"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_upload_file",
            "description": "Upload a file attachment to the channel. Use for code files, logs, or generated content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "File content as string",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Name of the file (e.g., 'output.txt')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional message to accompany the file",
                    },
                },
                "required": ["content", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_edit_message",
            "description": "Edit a previously sent message. Useful for updating progress messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "ID of the message to edit (use 'last' for most recent bot message)",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "New message content",
                    },
                },
                "required": ["message_id", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_reply",
            "description": "Reply directly to the user's message (creates a thread reply or direct reply).",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Reply content",
                    },
                    "mention": {
                        "type": "boolean",
                        "description": "Whether to mention the user in the reply",
                        "default": False,
                    },
                },
                "required": ["content"],
            },
        },
    },
]


def get_discord_tools_schema() -> List[Dict[str, Any]]:
    """Return the schema for Discord-native tools."""
    return DISCORD_TOOLS_SCHEMA


def get_discord_tool_names() -> List[str]:
    """Return the names of available Discord tools."""
    return [tool["function"]["name"] for tool in DISCORD_TOOLS_SCHEMA]


# Tool execution functions (called by AgenticSession)
# These return JSON strings for the LLM


def discord_send_message(message: str, msg_type: str = "info") -> str:
    """
    Send a message to Discord.

    This is a placeholder that returns the tool schema result.
    Actual execution happens in AgenticSession._run_discord_tool.
    """
    return json.dumps({
        "tool": "discord_send_message",
        "params": {"message": message, "type": msg_type},
        "status": "pending_execution",
    })


def discord_send_embed(
    title: str,
    description: str,
    color: int = 3447003,
    fields: Optional[List[Dict]] = None,
    url: Optional[str] = None,
) -> str:
    """
    Send an embed to Discord.

    This is a placeholder that returns the tool schema result.
    Actual execution happens in AgenticSession._run_discord_tool.
    """
    return json.dumps({
        "tool": "discord_send_embed",
        "params": {
            "title": title,
            "description": description,
            "color": color,
            "fields": fields or [],
            "url": url,
        },
        "status": "pending_execution",
    })


def discord_add_reaction(emoji: str) -> str:
    """
    Add a reaction to a message.

    This is a placeholder that returns the tool schema result.
    Actual execution happens in AgenticSession._run_discord_tool.
    """
    return json.dumps({
        "tool": "discord_add_reaction",
        "params": {"emoji": emoji},
        "status": "pending_execution",
    })


def discord_upload_file(content: str, filename: str, description: Optional[str] = None) -> str:
    """
    Upload a file to Discord.

    This is a placeholder that returns the tool schema result.
    Actual execution happens in AgenticSession._run_discord_tool.
    """
    return json.dumps({
        "tool": "discord_upload_file",
        "params": {
            "content": content[:1000] + "...",  # Truncate for preview
            "filename": filename,
            "description": description,
        },
        "status": "pending_execution",
        "size": len(content),
    })


def discord_edit_message(message_id: str, new_content: str) -> str:
    """
    Edit a previously sent message.

    This is a placeholder that returns the tool schema result.
    Actual execution happens in AgenticSession._run_discord_tool.
    """
    return json.dumps({
        "tool": "discord_edit_message",
        "params": {"message_id": message_id, "new_content": new_content},
        "status": "pending_execution",
    })


def discord_reply(content: str, mention: bool = False) -> str:
    """
    Reply to the user's message.

    This is a placeholder that returns the tool schema result.
    Actual execution happens in AgenticSession._run_discord_tool.
    """
    return json.dumps({
        "tool": "discord_reply",
        "params": {"content": content, "mention": mention},
        "status": "pending_execution",
    })


# Tool dispatch for runner compatibility
# These allow the runner to "call" the tools, but execution is deferred to the bot


def dispatch_discord_tool(name: str, args: Dict[str, Any]) -> str:
    """
    Dispatch a Discord tool call.

    Since Discord tools must be executed by the bot (not the runner),
    this returns a placeholder indicating the tool needs execution.
    The actual execution happens via bidirectional tool calls.
    """
    tool_map = {
        "discord_send_message": discord_send_message,
        "discord_send_embed": discord_send_embed,
        "discord_add_reaction": discord_add_reaction,
        "discord_upload_file": discord_upload_file,
        "discord_edit_message": discord_edit_message,
        "discord_reply": discord_reply,
    }

    tool_func = tool_map.get(name)
    if not tool_func:
        return json.dumps({"error": f"Unknown Discord tool: {name}"})

    try:
        return tool_func(**args)
    except Exception as e:
        logger.exception(f"Error dispatching Discord tool {name}: {e}")
        return json.dumps({"error": str(e), "tool": name})


# Tool categories for registry
def get_discord_capabilities() -> List[str]:
    """Return list of Discord tool capabilities."""
    return [f"discord:{tool['function']['name']}" for tool in DISCORD_TOOLS_SCHEMA]
