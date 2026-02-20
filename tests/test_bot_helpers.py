"""Unit tests for discord_bot helpers: truncate_for_display, _format_repo_envelope, is_allowed, redact."""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_bot.bot import (
    truncate_for_display,
    _format_repo_envelope,
    is_allowed,
    redact,
    MAX_DISPLAY_LEN,
)


# --- truncate_for_display ---


def test_truncate_under_limit():
    short = "hello"
    assert truncate_for_display(short, "job-1") == short


def test_truncate_at_limit():
    exact = "x" * MAX_DISPLAY_LEN
    assert truncate_for_display(exact, "job-2") == exact


def test_truncate_over_limit():
    long_text = "a" * (MAX_DISPLAY_LEN + 100)
    out = truncate_for_display(long_text, "jid-99")
    assert len(out) == MAX_DISPLAY_LEN + len("… (use `status jid-99` for full output).")
    assert out.startswith("a" * MAX_DISPLAY_LEN)
    assert "status jid-99" in out


# --- _format_repo_envelope ---


def test_format_repo_envelope_error():
    env = {"ok": False, "error": "repo not found"}
    assert _format_repo_envelope(env, "j1") == "Error: repo not found"


def test_format_repo_envelope_error_unknown():
    env = {"ok": False}
    assert _format_repo_envelope(env, "j1") == "Error: unknown"


def test_format_repo_envelope_repo_list():
    env = {
        "ok": True,
        "command": "repo_list",
        "data": {"repos": [{"name": "r1", "path": "/p/r1"}, {"name": "r2", "path": "/p/r2"}]},
    }
    out = _format_repo_envelope(env, "j2")
    assert "**r1**" in out and "`/p/r1`" in out
    assert "**r2**" in out and "`/p/r2`" in out


def test_format_repo_envelope_repo_list_empty():
    env = {"ok": True, "command": "repo_list", "data": {"repos": []}}
    assert _format_repo_envelope(env, "j") == "(no repos)"


def test_format_repo_envelope_repo_status():
    env = {
        "ok": True,
        "command": "repo_status",
        "data": {"branch": "main", "dirty": True, "porcelain": " M x"},
    }
    out = _format_repo_envelope(env, "j")
    assert "**Branch:** main" in out
    assert "**Dirty:** True" in out
    assert "```" in out and "M x" in out


def test_format_repo_envelope_repo_last_commit():
    env = {
        "ok": True,
        "command": "repo_last_commit",
        "data": {"hash": "abc", "author": "A", "date": "2025-01-01", "subject": "fix"},
    }
    out = _format_repo_envelope(env, "j")
    assert "**abc**" in out and "**A**" in out and "fix" in out


def test_format_repo_envelope_repo_grep():
    env = {"ok": True, "command": "repo_grep", "data": {"matches": "file:1:line1"}}
    out = _format_repo_envelope(env, "j")
    assert "file:1:line1" in out


def test_format_repo_envelope_repo_grep_no_matches():
    env = {"ok": True, "command": "repo_grep", "data": {"matches": ""}}
    assert _format_repo_envelope(env, "j") == "(no matches)"


def test_format_repo_envelope_repo_readfile():
    env = {
        "ok": True,
        "command": "repo_readfile",
        "data": {"path": "README.md", "start": 1, "end": 2, "content": "line1\nline2"},
    }
    out = _format_repo_envelope(env, "j")
    assert "README.md" in out and "1-2" in out
    assert "line1" in out and "line2" in out


def test_format_repo_envelope_no_data():
    env = {"ok": True, "command": "repo_list", "data": None}
    assert _format_repo_envelope(env, "j") == "(no data)"


def test_format_repo_envelope_truncated_note():
    env = {"ok": True, "command": "repo_list", "data": {"repos": []}, "truncated": True}
    assert "*(truncated)*" in _format_repo_envelope(env, "j")


# --- is_allowed ---


class _DMChannelPlaceholder:
    """Minimal placeholder so we can patch discord.DMChannel for isinstance checks."""
    pass


def test_is_allowed_dm_author_in_allowlist():
    channel = _DMChannelPlaceholder()
    channel.id = 999
    with patch("discord_bot.bot.ALLOWLIST_IDS", {"123"}), patch("discord_bot.bot.ALLOWED_CHANNEL_ID", ""):
        with patch("discord_bot.bot.discord.DMChannel", _DMChannelPlaceholder):
            assert is_allowed(channel, "123") is True


def test_is_allowed_dm_author_not_in_allowlist():
    channel = _DMChannelPlaceholder()
    channel.id = 999
    with patch("discord_bot.bot.ALLOWLIST_IDS", {"123"}), patch("discord_bot.bot.ALLOWED_CHANNEL_ID", ""):
        with patch("discord_bot.bot.discord.DMChannel", _DMChannelPlaceholder):
            assert is_allowed(channel, "456") is False


def test_is_allowed_channel_allowed_when_channel_id_matches():
    channel = MagicMock()
    channel.id = 888
    channel.__class__ = type("GuildChannel", (), {})  # not DM
    with patch("discord_bot.bot.ALLOWLIST_IDS", {"123"}), patch("discord_bot.bot.ALLOWED_CHANNEL_ID", "888"):
        # isinstance(channel, discord.DMChannel) will be False, so we check channel.id == ALLOWED_CHANNEL_ID
        assert is_allowed(channel, "123") is True


def test_is_allowed_channel_denied_when_channel_id_mismatch():
    channel = MagicMock()
    channel.id = 777
    with patch("discord_bot.bot.ALLOWLIST_IDS", {"123"}), patch("discord_bot.bot.ALLOWED_CHANNEL_ID", "888"):
        assert is_allowed(channel, "123") is False


# --- redact ---


def test_redact_no_tokens():
    assert redact("hello world") == "hello world"


def test_redact_replaces_bot_token():
    with patch("discord_bot.bot.BOT_TOKEN", "secret-bot"):
        assert redact("Broker error: secret-bot") == "Broker error: ***"


def test_redact_replaces_discord_token():
    with patch("discord_bot.bot.DISCORD_TOKEN", "secret-discord"):
        assert redact("Token: secret-discord") == "Token: ***"
