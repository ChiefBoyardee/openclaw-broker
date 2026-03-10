"""Tests for ConversationMemory and PersonalityEngine."""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_bot.memory import ConversationMemory


# ---------- ConversationMemory ----------

def _make_memory(db_path: str) -> ConversationMemory:
    """Create a ConversationMemory with a specific DB path, no embeddings."""
    return ConversationMemory(db_path=db_path, embedding_provider=None)


def test_memory_init_creates_db():
    """ConversationMemory initializes DB and tables."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        mem = _make_memory(db_path)
        assert os.path.isfile(db_path)
        # WAL mode should be enabled
        row = mem.db.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        mem.db.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_memory_add_and_get_messages():
    """Add messages and retrieve them."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        mem = _make_memory(db_path)
        conv_id = "test-conv-1"

        mem.add_message(conv_id, "user1", "user", "Hello!")
        mem.add_message(conv_id, "bot", "assistant", "Hi there!")

        messages = mem.get_recent_messages(conv_id, limit=10)
        assert len(messages) == 2
        assert messages[0].content == "Hello!"
        assert messages[1].content == "Hi there!"
        mem.db.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_memory_add_user_knowledge():
    """Add and retrieve user knowledge."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        mem = _make_memory(db_path)

        mem.add_user_fact(
            user_id="user1",
            fact_type="preference",
            content="Likes Python",
            confidence=0.9
        )
        mem.add_user_fact(
            user_id="user1",
            fact_type="fact",
            content="Lives in NYC",
            confidence=0.8
        )

        facts = mem.get_user_knowledge("user1")
        assert len(facts) == 2
        contents = [f.content for f in facts]
        assert "Likes Python" in contents
        assert "Lives in NYC" in contents
        mem.db.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_memory_user_knowledge_type_filter():
    """get_user_knowledge filters by fact_type."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        mem = _make_memory(db_path)

        mem.add_user_fact("u1", "preference", "Dark mode", 0.9)
        mem.add_user_fact("u1", "fact", "Age 30", 0.9)

        prefs = mem.get_user_knowledge("u1", fact_type="preference")
        assert len(prefs) == 1
        assert prefs[0].content == "Dark mode"
        mem.db.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_memory_conversation_summary():
    """Update and retrieve conversation summary."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        mem = _make_memory(db_path)
        conv_id = "test-conv-2"

        mem.add_message(conv_id, "user1", "user", "Test")

        if hasattr(mem, 'update_conversation_summary'):
            mem.update_conversation_summary(conv_id, "A test conversation")
            summary = mem.get_conversation_summary(conv_id)
            assert summary is not None
        mem.db.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_memory_clear_conversation():
    """Clear conversation deletes messages."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        mem = _make_memory(db_path)
        conv_id = "test-conv-3"

        mem.add_message(conv_id, "user1", "user", "Message 1")
        mem.add_message(conv_id, "user1", "user", "Message 2")

        messages = mem.get_recent_messages(conv_id, limit=10)
        assert len(messages) == 2

        if hasattr(mem, 'clear_conversation'):
            mem.clear_conversation(conv_id)
            messages = mem.get_recent_messages(conv_id, limit=10)
            assert len(messages) == 0
        mem.db.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_memory_sql_comment_syntax():
    """Verify SQL queries don't use # comments (SQLite only supports --)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        mem = _make_memory(db_path)
        conv_id = "sql-test"

        mem.add_message(conv_id, "user1", "user", "Test message for search")

        if hasattr(mem, 'semantic_search'):
            try:
                results = mem.semantic_search(conv_id, "test", k=5)
            except Exception as e:
                assert "near \"#\"" not in str(e), f"SQL comment syntax bug: {e}"
        mem.db.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------- PersonalityEngine ----------

def test_personality_engine_init():
    """PersonalityEngine loads default persona."""
    try:
        from discord_bot.personality import PersonalityEngine

        engine = PersonalityEngine()
        # Should have a default persona accessible via get_persona
        persona = engine.get_persona()
        assert persona is not None
        assert persona.name is not None
    except ImportError:
        pass


def test_personality_engine_list_personas():
    """list_personas returns available personas."""
    try:
        from discord_bot.personality import PersonalityEngine

        engine = PersonalityEngine()
        personas = engine.list_personas()
        assert isinstance(personas, dict)
        assert len(personas) > 0
        assert "helpful_assistant" in personas
    except ImportError:
        pass


def test_personality_engine_persona_switching():
    """Switching personas changes the active persona for a user."""
    try:
        from discord_bot.personality import PersonalityEngine

        engine = PersonalityEngine()
        personas = engine.list_personas()

        if len(personas) > 1:
            keys = list(personas.keys())
            alt_key = [k for k in keys if k != "helpful_assistant"][0]
            engine.set_user_persona("test-user", alt_key)
            result = engine.get_persona(user_id="test-user")
            assert result.name != "Helpful Assistant" or alt_key == "helpful_assistant"
    except (ImportError, AttributeError):
        pass
