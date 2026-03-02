"""
Output filtering and secret redaction for user-facing content (Sprint 3).

- redact_expanded: token + credential heuristic scrubbing
- guard_instruction_leak: wrap or flag outputs that look like actionable instructions
"""
from __future__ import annotations

import os
import re
from typing import Optional

# Patterns for common credential formats (scrub before user-facing output)
CREDENTIAL_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "***"),  # OpenAI, Anthropic, etc.
    (re.compile(r"xoxb-[A-Za-z0-9_-]+"), "***"),  # Slack bot
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "***"),  # GitHub PAT
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "***"),  # GitHub OAuth
    (re.compile(r"AIza[A-Za-z0-9_-]{35}"), "***"),  # Google API key
    (re.compile(r"-----BEGIN\s+(?:RSA\s+)?(?:EC\s+)?PRIVATE KEY-----[\s\S]*?-----END\s+(?:RSA\s+)?(?:EC\s+)?PRIVATE KEY-----"), "***"),  # PEM key
]

# Patterns that suggest instruction leakage / social engineering
INSTRUCTION_LEAK_PATTERNS = [
    re.compile(r"do\s+this\s+next", re.IGNORECASE),
    re.compile(r"run\s+this\s+command", re.IGNORECASE),
    re.compile(r"click\s+this\s+link\s+to\s+connect", re.IGNORECASE),
    re.compile(r"paste\s+this\s+into\s+your\s+terminal", re.IGNORECASE),
    re.compile(r"execute\s+the\s+following", re.IGNORECASE),
]

INSTRUCTION_WARNING = "⚠️ Output may contain instructions — verify before acting.\n\n"


def redact_expanded(text: str, bot_token: Optional[str] = None, discord_token: Optional[str] = None) -> str:
    """
    Replace tokens and credential-like strings with ***.
    Uses bot_token/discord_token if provided, else os.environ.
    """
    if not text:
        return text
    out = text
    bt = bot_token if bot_token is not None else os.environ.get("BOT_TOKEN", "")
    dt = discord_token if discord_token is not None else os.environ.get("DISCORD_TOKEN", "")
    if bt:
        out = out.replace(bt, "***")
    if dt:
        out = out.replace(dt, "***")
    for pattern, replacement in CREDENTIAL_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def guard_instruction_leak(text: str) -> str:
    """
    If output matches instruction-leak patterns, prepend warning banner.
    Returns text unchanged or with warning prepended.
    """
    if not text or not text.strip():
        return text
    for pat in INSTRUCTION_LEAK_PATTERNS:
        if pat.search(text):
            return INSTRUCTION_WARNING + text
    return text


def redact_for_display(
    text: str,
    bot_token: Optional[str] = None,
    discord_token: Optional[str] = None,
) -> str:
    """
    Apply redaction and instruction-leak guard. Use before sending to users.
    """
    return guard_instruction_leak(redact_expanded(text, bot_token, discord_token))
