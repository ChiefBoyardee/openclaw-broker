"""
Tests for the streaming/bidirectional communication system.

These tests verify:
- Broker chunk storage and retrieval
- Runner streaming client chunk posting
- Tool call lifecycle
- SSE streaming endpoints
"""

import json
import pytest
from unittest.mock import Mock, patch, AsyncMock

# Broker streaming tests
@pytest.mark.skipif(
    not __import__("os").environ.get("ENABLE_STREAMING"),
    reason="Streaming not enabled"
)
class TestBrokerStreaming:
    """Test broker streaming infrastructure."""

    def test_stream_manager_initialization(self, tmp_path):
        """Test stream manager creates tables."""
        from broker.streaming import JobStreamManager

        db_path = str(tmp_path / "test.db")
        manager = JobStreamManager(db_path)

        # Verify tables exist by adding a chunk
        chunk_id = manager.add_chunk("test-job", "message", "Hello")
        assert chunk_id is not None
        assert chunk_id > 0

    def test_add_and_get_chunks(self, tmp_path):
        """Test adding and retrieving chunks."""
        from broker.streaming import JobStreamManager

        db_path = str(tmp_path / "test.db")
        manager = JobStreamManager(db_path)

        # Add chunks
        _id1 = manager.add_chunk("job-1", "thinking", "Step 1")
        _id2 = manager.add_chunk("job-1", "message", "Hello user")
        _id3 = manager.add_chunk("job-1", "final", "Done")

        # Get all chunks
        chunks = manager.get_chunks("job-1")
        assert len(chunks) == 3
        assert chunks[0].chunk_type == "thinking"
        assert chunks[1].content == "Hello user"
        assert chunks[2].chunk_type == "final"

    def test_get_chunks_with_after_id(self, tmp_path):
        """Test retrieving chunks after a specific ID."""
        from broker.streaming import JobStreamManager

        db_path = str(tmp_path / "test.db")
        manager = JobStreamManager(db_path)

        id1 = manager.add_chunk("job-1", "thinking", "Step 1")
        _id2 = manager.add_chunk("job-1", "thinking", "Step 2")
        _id3 = manager.add_chunk("job-1", "message", "Result")

        # Get chunks after id1
        chunks = manager.get_chunks("job-1", after_id=id1)
        assert len(chunks) == 2
        assert chunks[0].content == "Step 2"

    def test_tool_call_lifecycle(self, tmp_path):
        """Test creating and completing tool calls."""
        from broker.streaming import JobStreamManager, ToolCallStatus

        db_path = str(tmp_path / "test.db")
        manager = JobStreamManager(db_path)

        # Create tool call
        tool_call_id = manager.create_tool_call(
            "job-1",
            "discord_send_message",
            {"message": "Hello"}
        )
        assert tool_call_id is not None

        # Verify pending
        pending = manager.get_pending_tool_calls("job-1")
        assert len(pending) == 1
        assert pending[0].tool_name == "discord_send_message"

        # Complete tool call
        success = manager.complete_tool_call(tool_call_id, '{"sent": true}')
        assert success is True

        # Verify no longer pending
        pending = manager.get_pending_tool_calls("job-1")
        assert len(pending) == 0

        # Verify status
        call = manager.get_tool_call(tool_call_id)
        assert call.status == ToolCallStatus.COMPLETED
        assert call.result == '{"sent": true}'

    def test_cleanup_old_chunks(self, tmp_path):
        """Test cleaning up old chunks."""
        from broker.streaming import JobStreamManager
        import time

        db_path = str(tmp_path / "test.db")
        manager = JobStreamManager(db_path)

        # Add chunks
        manager.add_chunk("job-1", "message", "Old")
        manager.add_chunk("job-2", "message", "Recent")

        # Cleanup with 0 seconds age (remove all)
        count = manager.cleanup_old_chunks(max_age_seconds=0)
        assert count >= 1

        # Verify chunks are gone
        chunks = manager.get_chunks("job-1")
        assert len(chunks) == 0


# Runner streaming client tests
class TestRunnerStreamingClient:
    """Test runner streaming client."""

    def test_client_initialization(self):
        """Test streaming client initializes correctly."""
        from runner.streaming_client import RunnerStreamClient

        client = RunnerStreamClient("test-job")
        assert client.job_id == "test-job"
        assert client.chunks_posted == 0

    @patch("runner.streaming_client.requests.post")
    def test_post_chunk_success(self, mock_post):
        """Test posting a chunk successfully."""
        from runner.streaming_client import RunnerStreamClient

        mock_post.return_value = Mock(status_code=200)
        client = RunnerStreamClient("test-job", worker_token="test-token")
        client.enabled = True

        success = client.post_chunk("message", "Hello", {"step": 1})

        assert success is True
        assert client.chunks_posted == 1
        mock_post.assert_called_once()

    @patch("runner.streaming_client.requests.post")
    def test_post_chunk_disabled(self, mock_post):
        """Test posting when disabled returns False."""
        from runner.streaming_client import RunnerStreamClient

        client = RunnerStreamClient("test-job")
        client.enabled = False

        success = client.post_chunk("message", "Hello")

        assert success is False
        mock_post.assert_not_called()

    @patch("runner.streaming_client.requests.post")
    def test_post_thinking(self, mock_post):
        """Test posting thinking step."""
        from runner.streaming_client import RunnerStreamClient

        mock_post.return_value = Mock(status_code=200)
        client = RunnerStreamClient("test-job", worker_token="test-token")
        client.enabled = True

        success = client.post_thinking("Analyzing...", step=1)

        assert success is True
        call_args = mock_post.call_args
        assert call_args[1]["json"]["chunk_type"] == "thinking"

    @patch("runner.streaming_client.requests.post")
    def test_post_final(self, mock_post):
        """Test posting final result."""
        from runner.streaming_client import RunnerStreamClient

        mock_post.return_value = Mock(status_code=200)
        client = RunnerStreamClient("test-job", worker_token="test-token")
        client.enabled = True

        success = client.post_final("Final answer here")

        assert success is True
        call_args = mock_post.call_args
        assert call_args[1]["json"]["chunk_type"] == "final"


# Tool registry category tests
class TestToolCategories:
    """Test tool category classification."""

    def test_get_tool_category_runner_local(self):
        """Test repo tools are runner-local."""
        from runner.tool_registry import get_tool_category, ToolCategory

        assert get_tool_category("repo_list") == ToolCategory.RUNNER_LOCAL
        assert get_tool_category("repo_status") == ToolCategory.RUNNER_LOCAL
        assert get_tool_category("browser_navigate") == ToolCategory.RUNNER_LOCAL

    def test_get_tool_category_bot_only(self):
        """Test Discord tools are bot-only."""
        from runner.tool_registry import get_tool_category, ToolCategory

        assert get_tool_category("discord_send_message") == ToolCategory.BOT_ONLY
        assert get_tool_category("discord_add_reaction") == ToolCategory.BOT_ONLY

    def test_is_bot_only_tool(self):
        """Test bot-only detection."""
        from runner.tool_registry import is_bot_only_tool

        assert is_bot_only_tool("discord_send_message") is True
        assert is_bot_only_tool("repo_list") is False

    def test_is_bidirectional_tool(self):
        """Test bidirectional detection."""
        from runner.tool_registry import is_bidirectional_tool

        # Discord tools are considered bidirectional for flexibility
        assert is_bidirectional_tool("discord_send_message") is True
        # Runner tools are not bidirectional
        assert is_bidirectional_tool("repo_list") is False


# Discord tools schema tests
class TestDiscordTools:
    """Test Discord-native tool definitions."""

    def test_get_discord_tools_schema(self):
        """Test getting Discord tools schema."""
        from discord_bot.discord_tools import get_discord_tools_schema

        schema = get_discord_tools_schema()
        assert len(schema) > 0

        tool_names = [tool["function"]["name"] for tool in schema]
        assert "discord_send_message" in tool_names
        assert "discord_send_embed" in tool_names
        assert "discord_add_reaction" in tool_names

    def test_get_discord_tool_names(self):
        """Test getting Discord tool names."""
        from discord_bot.discord_tools import get_discord_tool_names

        names = get_discord_tool_names()
        assert "discord_send_message" in names
        assert "discord_upload_file" in names


# Agentic session tests (async)
@pytest.mark.asyncio
class TestAgenticSession:
    """Test agentic session management."""

    async def test_session_creation(self):
        """Test creating an agentic session."""
        from discord_bot.agentic_session import AgenticSession, AgenticConfig, SessionContext
        from unittest.mock import Mock

        mock_message = Mock()
        mock_message.channel.id = 123
        mock_message.author.id = 456
        mock_message.author.display_name = "TestUser"

        config = AgenticConfig(max_steps=5)
        context = SessionContext(
            conversation_id="test-conv",
            user_id="456",
            channel_id="123",
            username="TestUser",
            persona_key="default",
            started_at=1234567890,
        )

        session = AgenticSession(
            message=mock_message,
            config=config,
            context=context,
        )

        assert session.config.max_steps == 5
        assert session.context.user_id == "456"
        assert session.is_running is False

    async def test_session_callbacks(self):
        """Test session callback registration."""
        from discord_bot.agentic_session import AgenticSession, AgenticConfig, SessionContext
        from unittest.mock import Mock

        mock_message = Mock()
        session = AgenticSession(
            message=mock_message,
            config=AgenticConfig(),
            context=SessionContext(
                conversation_id="test",
                user_id="1",
                channel_id="1",
                username="test",
                persona_key="default",
                started_at=0,
            ),
        )

        # Register callbacks
        async def on_message(msg): pass
        async def on_thinking(thought, step): pass
        async def on_complete(final): pass

        session.on_message(on_message)
        session.on_thinking(on_thinking)
        session.on_complete(on_complete)

        assert session._on_message == on_message
        assert session._on_thinking == on_thinking
        assert session._on_complete == on_complete


# Streaming client tests (async)
@pytest.mark.asyncio
class TestBotStreamingClient:
    """Test bot streaming client."""

    async def test_streaming_client_initialization(self):
        """Test streaming client initialization."""
        from discord_bot.streaming_client import BrokerStreamingClient

        client = BrokerStreamingClient(
            broker_url="http://test:8000",
            bot_token="test-token",
        )

        assert client.broker_url == "http://test:8000"
        assert client.bot_token == "test-token"

    @patch("aiohttp.ClientSession.get")
    async def test_poll_chunks(self, mock_get):
        """Test polling for chunks — mock returns one chunk then empty to allow idle timeout."""
        from discord_bot.streaming_client import BrokerStreamingClient

        call_count = 0

        async def _json_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "chunks": [
                        {"id": 1, "chunk_type": "message", "content": "Hello", "metadata": None, "created_at": 123}
                    ],
                    "count": 1,
                }
            return {"chunks": [], "count": 0}

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = _json_side_effect
        mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

        client = BrokerStreamingClient(
            broker_url="http://test:8000",
            bot_token="test-token",
        )
        client.enabled = True
        chunks = []
        async for chunk in client.poll_chunks("job-1", poll_interval=0.05, idle_timeout=0.3):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].content == "Hello"


# Integration test markers
@pytest.mark.integration
@pytest.mark.skipif(
    not __import__("os").environ.get("BROKER_URL"),
    reason="Integration tests require running broker"
)
class TestStreamingIntegration:
    """Integration tests requiring running broker."""

    async def test_full_agentic_flow(self):
        """
        Test full agentic flow:
        1. Create streaming job
        2. Runner claims and streams
        3. Bot receives chunks
        4. Tool call is bidirectional
        """
        # This test requires a running broker and runner
        # Marked as integration test to skip in CI
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
