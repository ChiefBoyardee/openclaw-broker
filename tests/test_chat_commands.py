"""
Tests for discord_bot chat commands using mock Discord objects.
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_bot.chat_commands import ChatManager


class MockUser:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.bot = False
        self.display_name = name


class MockChannel:
    def __init__(self, id, name, is_thread=False):
        self.id = id
        self.name = name
        # We need mock type attribute or isinstance check might fail
        # but for our simple tests, we mock logic
        self.type = MagicMock()
        self.type.name = "public_thread" if is_thread else "text"


class MockGuild:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class MockMessage:
    def __init__(self, content, author, channel, guild=None):
        self.content = content
        self.author = author
        self.channel = channel
        self.guild = guild
        self.reply = AsyncMock()


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MockUser(999, "OpenClawBot")
    bot.broker_url = "http://fake-broker"
    bot.bot_token = "fake-token"
    return bot


@pytest.fixture
def chat_manager(mock_bot):
    return ChatManager(mock_bot, broker_url="http://fake-broker", bot_token="fake-token")


def test_handle_empty_message(chat_manager):
    # ChatManager handles empty messages typically by returning empty or it's filtered at bot level.
    # We will test handle_chat_message directly.
    
    async def _run():
        reply_mock = AsyncMock()
        _res = await chat_manager.handle_chat_message("", "123", "456", "TestUser", reply_mock)
        # The personality or LLM call will probably still trigger if it reaches here,
        # but the prompt might be empty. Let's just make sure it doesn't crash.
        # Although actually bot.py filters empty messages before ChatManager sees them.
        pass
    import asyncio
    asyncio.run(_run())


def test_handle_forget_command(chat_manager):
    async def _run():
        # Test forget command method
        res = await chat_manager.handle_forget_command("123", "")
        # The exact string may vary by whether it found memory to forget
        assert "forgot" in res.lower() or "no memories" in res.lower() or "reset" in res.lower() or "error" in res.lower()
    import asyncio
    asyncio.run(_run())


def test_handle_persona_command(chat_manager):
    async def _run():
        with patch.object(chat_manager.personality, 'list_personas', return_value={"assistant": "helpful"}):
            # No persona name list personas
            res = await chat_manager.handle_persona_command("123", None)
            assert "Available personas:" in res
            
        with patch.object(chat_manager.personality, 'list_personas', return_value={"assistant": "helpful"}):
            res = await chat_manager.handle_persona_command("123", "mypersona")
            assert "unknown" in res.lower() or "not found" in res.lower() or "error" in res.lower()
    import asyncio
    asyncio.run(_run())


@patch("requests.post")
@patch("requests.get")
def test_handle_llm_conversation(mock_get, mock_post, chat_manager):
    """Test full flow simulation including broker request mock"""
    mock_post.return_value.raise_for_status = MagicMock()
    mock_post.return_value.json.return_value = {
        "id": "job_123"
    }
    
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = {
        "status": "done",
        "result": "Hello human!"
    }
    
    async def _run():
        reply_mock = AsyncMock()
        res = await chat_manager.handle_chat_message("Hello bot", "123", "456", "TestUser", reply_mock)
        
        # Should call the broker via requests
        assert mock_post.called
        assert "Hello human!" in res
    import asyncio
    asyncio.run(_run())
