"""Tests for redaction heuristics and instruction-leak guard."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_bot.redaction import redact_expanded, guard_instruction_leak, redact_for_display


def test_redact_expanded_sk_prefix():
    """sk- style API keys are redacted."""
    text = "Use key sk-abc123def456ghi789jkl012mno345pqr"
    out = redact_expanded(text)
    assert "sk-abc123" not in out
    assert "***" in out


def test_redact_expanded_ghp_prefix():
    """ghp_ GitHub tokens are redacted."""
    text = "Token ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    out = redact_expanded(text)
    assert "ghp_" not in out
    assert "***" in out


def test_redact_expanded_aiza_prefix():
    """AIza Google API keys are redacted."""
    text = "Key: AIzaSyB1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q"
    out = redact_expanded(text)
    assert "AIza" not in out or out.count("***") >= 1


def test_redact_expanded_xoxb_prefix():
    """xoxb- Slack tokens are redacted."""
    text = "Slack xoxb-12345-abcdef"
    out = redact_expanded(text)
    assert "xoxb-" not in out
    assert "***" in out


def test_redact_expanded_no_false_positive():
    """Normal text without credentials is unchanged."""
    text = "Hello world, the answer is 42. Use repo_list to list repos."
    out = redact_expanded(text)
    assert out == text


def test_redact_expanded_with_explicit_tokens():
    """Explicit bot/discord tokens are redacted when passed."""
    text = "Error: my-secret-bot-token"
    out = redact_expanded(text, bot_token="my-secret-bot-token", discord_token="")
    assert "my-secret-bot-token" not in out
    assert "***" in out


def test_guard_instruction_leak_detects_run_command():
    """Pattern 'run this command' triggers warning."""
    text = "To fix it, run this command: curl example.com"
    out = guard_instruction_leak(text)
    assert "verify before acting" in out
    assert "run this command" in out


def test_guard_instruction_leak_detects_paste_terminal():
    """Pattern 'paste this into your terminal' triggers warning."""
    text = "Paste this into your terminal to connect"
    out = guard_instruction_leak(text)
    assert "verify before acting" in out


def test_guard_instruction_leak_no_false_positive():
    """Normal text without instruction patterns is unchanged."""
    text = "The repo has 3 files. Check the README for details."
    out = guard_instruction_leak(text)
    assert out == text
    assert "verify before acting" not in out


def test_redact_for_display_combines_both():
    """redact_for_display applies both redaction and instruction guard."""
    text = "Your key is sk-abc123def456ghi789jkl012 and run this command to connect"
    out = redact_for_display(text)
    assert "sk-abc123" not in out
    assert "verify before acting" in out
