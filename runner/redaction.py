"""
Output redaction for runner (Sprint 3). Scrubs credential-like strings before storing in DB.
"""
from __future__ import annotations

import os
import re

# Patterns for common credential formats
CREDENTIAL_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "***"),
    (re.compile(r"xoxb-[A-Za-z0-9_-]+"), "***"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "***"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "***"),
    (re.compile(r"AIza[A-Za-z0-9_-]{35}"), "***"),
    (re.compile(r"-----BEGIN\s+(?:RSA\s+)?(?:EC\s+)?PRIVATE KEY-----[\s\S]*?-----END\s+(?:RSA\s+)?(?:EC\s+)?PRIVATE KEY-----"), "***"),
]


def redact_output(text: str) -> str:
    """
    Scrub credential-like patterns from text. Used before storing in broker DB.
    Enable with RUNNER_REDACT_OUTPUT=1 (default on).
    """
    if not text:
        return text
    out = text
    for pattern, replacement in CREDENTIAL_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def should_redact_output() -> bool:
    """True if RUNNER_REDACT_OUTPUT is enabled (default True)."""
    return os.environ.get("RUNNER_REDACT_OUTPUT", "1").strip() in ("1", "true", "yes")
