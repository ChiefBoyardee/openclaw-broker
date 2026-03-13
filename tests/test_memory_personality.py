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


# ---------- Capabilities Block ----------

def test_build_system_prompt_includes_capabilities():
    """build_system_prompt() injects capabilities block into every persona."""
    try:
        from discord_bot.personality import PersonalityEngine, CAPABILITIES_BLOCK

        engine = PersonalityEngine()
        persona = engine.get_persona("helpful_assistant")
        prompt = engine.build_system_prompt(
            persona, "conv-1", "user-1",
            enforce_consistency=False,
            include_self_memory=False  # Avoid DB dependency
        )
        # Must contain key phrases from capabilities block
        assert "PERSISTENT MEMORY" in prompt
        assert "NEVER" in prompt and "memory" in prompt
        assert "YOUR CAPABILITIES" in prompt
    except ImportError:
        pass


def test_capabilities_in_all_default_personas():
    """Every default persona gets capabilities injected."""
    try:
        from discord_bot.personality import PersonalityEngine, DEFAULT_PERSONAS

        engine = PersonalityEngine()
        for key in DEFAULT_PERSONAS:
            persona = engine.get_persona(key)
            prompt = engine.build_system_prompt(
                persona, f"conv-{key}", "user-1",
                enforce_consistency=False,
                include_self_memory=False
            )
            assert "YOUR CAPABILITIES" in prompt, f"Persona '{key}' missing capabilities"
    except ImportError:
        pass


# ---------- Personality Template ----------

def test_personality_template_is_valid():
    """PERSONALITY_TEMPLATE has all required keys."""
    try:
        from discord_bot.personality import PERSONALITY_TEMPLATE

        required_keys = {"name", "system_prompt", "voice_settings"}
        assert required_keys.issubset(set(PERSONALITY_TEMPLATE.keys()))
        assert isinstance(PERSONALITY_TEMPLATE["voice_settings"], dict)
        assert "temperature" in PERSONALITY_TEMPLATE["voice_settings"]
    except ImportError:
        pass


def test_create_persona_from_template_rejects_defaults():
    """create_persona_from_template rejects uncustomized name/prompt."""
    try:
        from discord_bot.personality import create_persona_from_template
        import pytest

        # No overrides at all -> should fail
        try:
            create_persona_from_template({})
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

        # Only name but not prompt -> should fail
        try:
            create_persona_from_template({"name": "TestBot"})
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
    except ImportError:
        pass


def test_create_persona_from_template_succeeds():
    """create_persona_from_template creates valid PersonaConfig with overrides."""
    try:
        from discord_bot.personality import create_persona_from_template, PersonaConfig

        config = create_persona_from_template({
            "name": "Pirate Bot",
            "system_prompt": "You are a pirate. Arrr!",
            "use_emojis": True,
            "voice_settings": {"temperature": 0.9},
            "signature_phrase": "Arrr! 🏴‍☠️",
        })
        assert isinstance(config, PersonaConfig)
        assert config.name == "Pirate Bot"
        assert config.use_emojis is True
        assert config.voice_settings["temperature"] == 0.9
        # Inherits defaults for unset voice fields
        assert "top_p" in config.voice_settings
        assert config.signature_phrase == "Arrr! 🏴‍☠️"
    except ImportError:
        pass


def test_add_custom_persona_from_dict():
    """add_custom_persona_from_dict registers persona and it can be retrieved."""
    try:
        from discord_bot.personality import PersonalityEngine

        engine = PersonalityEngine()
        engine.add_custom_persona_from_dict("ninja", {
            "name": "Ninja Bot",
            "system_prompt": "You are a stealthy ninja. Speak in whispers.",
        })
        persona = engine.get_persona("ninja")
        assert persona.name == "Ninja Bot"
        assert "ninja" in engine.list_personas()
    except ImportError:
        pass


# ---------- File-based Persona Loading ----------

def test_load_custom_personas_from_valid_file():
    """load_custom_personas_from_file parses a valid JSON file."""
    try:
        from discord_bot.personality import load_custom_personas_from_file
        import tempfile

        data = json.dumps({
            "_comment": ["Ignored"],
            "test_bot": {
                "name": "Test Bot",
                "system_prompt": "You are a test bot."
            }
        })
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(path, 'w') as f:
                f.write(data)
            loaded = load_custom_personas_from_file(path)
            assert "test_bot" in loaded
            assert loaded["test_bot"].name == "Test Bot"
            assert "_comment" not in loaded  # meta keys skipped
        finally:
            os.unlink(path)
    except ImportError:
        pass


def test_load_custom_personas_skips_invalid_entries():
    """Invalid entries are skipped without crashing."""
    try:
        from discord_bot.personality import load_custom_personas_from_file
        import tempfile

        data = json.dumps({
            "good": {
                "name": "Good Bot",
                "system_prompt": "You are good."
            },
            "bad_no_name": {
                "system_prompt": "Missing name."
            },
            "bad_not_dict": "just a string"
        })
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(path, 'w') as f:
                f.write(data)
            loaded = load_custom_personas_from_file(path)
            assert "good" in loaded
            assert "bad_no_name" not in loaded
            assert "bad_not_dict" not in loaded
        finally:
            os.unlink(path)
    except ImportError:
        pass


def test_load_custom_personas_missing_file():
    """load_custom_personas returns 0 for missing file."""
    try:
        from discord_bot.personality import PersonalityEngine

        engine = PersonalityEngine()
        result = engine.load_custom_personas("/nonexistent/personas.json")
        assert result == 0
    except ImportError:
        pass


def test_load_custom_personas_malformed_json():
    """load_custom_personas handles malformed JSON gracefully."""
    try:
        from discord_bot.personality import PersonalityEngine
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(path, 'w') as f:
                f.write("{bad json!!!}")
            engine = PersonalityEngine()
            result = engine.load_custom_personas(path)
            assert result == 0  # Graceful failure
        finally:
            os.unlink(path)
    except ImportError:
        pass


def test_shipped_example_file_loads():
    """The shipped custom_personas.json.example is valid and loads correctly."""
    try:
        from discord_bot.personality import load_custom_personas_from_file

        example_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "discord_bot", "custom_personas.json.example"
        )
        if os.path.isfile(example_path):
            loaded = load_custom_personas_from_file(example_path)
            assert len(loaded) > 0, "Example file should contain at least one persona"
            assert "urgo" in loaded
            assert loaded["urgo"].name == "Urgo"
    except ImportError:
        pass
