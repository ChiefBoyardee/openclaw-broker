"""Unit test for whoami reply formatting (discord_bot.bot.format_whoami, whoami_broker_url_display)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_bot.bot import format_whoami, whoami_broker_url_display


def test_format_whoami_with_allowed_user():
    out = format_whoami(
        instance_name="clawhub",
        bot_user_id="123456789",
        broker_url="http://127.0.0.1:8000",
        allowed_user_id="987654321",
    )
    assert "**Instance:** clawhub" in out
    assert "**Bot user ID:** 123456789" in out
    assert "**Broker URL:** http://127.0.0.1:8000" in out
    assert "**Allowlisted user ID:** 987654321" in out


def test_format_whoami_without_allowed_user():
    out = format_whoami(
        instance_name="default",
        bot_user_id="111",
        broker_url="https://broker.example",
        allowed_user_id="",
    )
    assert "**Instance:** default" in out
    assert "**Allowlisted user ID:** not set" in out


def test_whoami_broker_url_mode_full():
    """full: show URL unchanged."""
    url = "http://127.0.0.1:8000"
    assert whoami_broker_url_display(url, "full") == url
    out = format_whoami("i", "b", whoami_broker_url_display(url, "full"), "u")
    assert "**Broker URL:** http://127.0.0.1:8000" in out


def test_whoami_broker_url_mode_masked():
    """masked: scheme + host only (no path)."""
    url = "https://broker.tail12345.ts.net:8443/jobs"
    display = whoami_broker_url_display(url, "masked")
    assert display == "https://broker.tail12345.ts.net:8443"
    assert "/jobs" not in display
    out = format_whoami("i", "b", display, "u")
    assert "**Broker URL:** https://broker.tail12345.ts.net:8443" in out
    assert "/jobs" not in out


def test_whoami_broker_url_mode_hidden():
    """hidden: show (hidden) and do not reveal URL."""
    url = "https://secret.internal:9999"
    display = whoami_broker_url_display(url, "hidden")
    assert display == "(hidden)"
    assert "secret" not in display
    out = format_whoami("i", "b", display, "u")
    assert "**Broker URL:** (hidden)" in out
    assert "secret" not in out
    assert "internal" not in out
