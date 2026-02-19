"""Unit test for whoami reply formatting (discord_bot.bot.format_whoami)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_bot.bot import format_whoami


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
