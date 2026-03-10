# OpenClaw Conversational Features

This guide covers the conversational memory and personality system for the Discord bot, enabling natural conversations with persistent memory and customizable personalities.

## Overview

The conversational system provides:
- **Persistent Memory**: SQLite-based storage of conversation history
- **RAG (Retrieval Augmented Generation)**: Semantic search for relevant context
- **User Knowledge**: Automatic extraction and storage of user preferences/facts
- **Multiple Personalities**: Switchable bot personas with consistent voice
- **Personality Consistency**: Automatic enforcement to prevent "persona drift"

## Quick Start

### 1. Enable Conversation Features

Set environment variables in your `bot.env`:

```bash
# Enable memory system
MEMORY_ENABLED=true

# Choose embedding provider
EMBEDDING_PROVIDER=openai  # Options: openai, local, mock, none
OPENAI_API_KEY=sk-your-key-here
EMBEDDING_MODEL=text-embedding-3-small

# Default personality
DEFAULT_PERSONA=helpful_assistant

# Database location
MEMORY_DB_PATH=/opt/openclaw-bot/discord_bot_memory.db
```

### 2. Install Dependencies

For OpenAI embeddings:
```bash
pip install openai
```

For local embeddings (no API costs):
```bash
pip install sentence-transformers
```

### 3. Start Chatting

In Discord:
```
Hi there! Remember I like Python
```

## Discord Commands

### Natural Language (No Command Needed)
Just type naturally - the bot understands conversation and maintains persistent memory automatically.

```
Hello!
What was I working on yesterday?
Remember that I prefer dark mode
```

### `persona [name]`
Switch between bot personalities.

```
persona                    # List available personas
persona sassy_bot         # Switch to sassy personality
persona professional_dev  # Switch to professional mode
```

**Available Personas:**
- `helpful_assistant` - Friendly, knowledgeable, balanced (default)
- `sassy_bot` - Witty, sarcastic, playful
- `professional_dev` - Formal, technical, precise
- `wise_mentor` - Patient, encouraging, teaching-focused
- `curious_explorer` - Enthusiastic, asks questions, makes connections

### `memory [command]`
Manage conversation memory.

```
memory status     # Show memory statistics
memory clear      # Clear conversation history
memory on         # Enable memory
memory off        # Disable memory (conversations not stored)
```

### `remember <fact>`
Explicitly tell the bot to remember something.

```
remember I work at Acme Corp
remember My favorite color is blue
remember Use Australian spelling
```

### `history [n]`
Show recent conversation history.

```
history        # Show last 10 messages
history 20     # Show last 20 messages
```

## Architecture

### Memory System

```
User Message
     ↓
┌─────────────────┐
│  Discord Bot    │
│  (bot.py)       │
└────────┬────────┘
         ↓
┌─────────────────┐
│  Chat Manager   │
│  (chat_commands)│
└────────┬────────┘
         ↓
┌─────────────────┐     ┌─────────────────┐
│   Memory        │────→│  SQLite DB      │
│   (memory.py)   │     │  (messages,     │
│                 │     │   embeddings,   │
│  - Recent msgs  │     │   knowledge)    │
│  - Semantic     │     └─────────────────┘
│    search       │
│  - User facts   │
│  - Summaries    │
└────────┬────────┘
         ↓
┌─────────────────┐
│  Personality    │
│  (personality)  │
│                 │
│  - System prompt│
│  - Voice settings│
│  - Consistency  │
└────────┬────────┘
         ↓
┌─────────────────┐
│  LLM via Broker │
│  (llm_task job) │
└─────────────────┘
         ↓
    Response
```

### Memory Layers

1. **Working Memory** (Immediate)
   - Last 10 messages in conversation
   - Kept in prompt verbatim

2. **Episodic Memory** (Short-term)
   - Summaries of older conversation segments
   - Retrieved via semantic search

3. **Semantic Memory** (Long-term)
   - Extracted user facts/preferences
   - Persistent across conversations

### Context Building

When you send a message, the system builds context:

1. **Persona System Prompt** - Defines bot personality
2. **User Knowledge** - Your preferences and facts
3. **Conversation Summary** - Overview of long conversations
4. **Recent Messages** - Last 10 messages (verbatim)
5. **Semantically Similar** - Past messages related to current query

Total context limited to ~3000 tokens (configurable).

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_ENABLED` | `true` | Enable/disable memory system |
| `EMBEDDING_PROVIDER` | `none` | Provider: `openai`, `local`, `mock`, `none` |
| `OPENAI_API_KEY` | - | Required for OpenAI embeddings |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI model name |
| `DEFAULT_PERSONA` | `helpful_assistant` | Default personality |
| `MEMORY_DB_PATH` | `discord_bot_memory.db` | Database file location |
| `CONVERSATION_TIMEOUT_MINUTES` | `30` | Session timeout |

### Embedding Options

#### OpenAI (Best Quality)
```bash
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small  # or text-embedding-3-large
```
- Pros: High quality, fast, 1536 dimensions
- Cons: API costs (~$0.10 per 1M tokens)

#### Local (No API Costs)
```bash
EMBEDDING_PROVIDER=local
```
- Uses `sentence-transformers` with `all-MiniLM-L6-v2`
- Pros: Free, runs locally, 384 dimensions
- Cons: Lower quality than OpenAI, requires ~150MB model

#### Mock (Testing)
```bash
EMBEDDING_PROVIDER=mock
```
- Generates random embeddings
- Pros: No dependencies, fast
- Cons: No semantic meaning (not for production)

#### None (Memory Only)
```bash
EMBEDDING_PROVIDER=none
```
- Disables semantic search
- Pros: No dependencies, lowest resource usage
- Cons: Only recent messages used (no RAG)

## Personality System

### Persona Drift Prevention

LLMs naturally "drift" from their assigned personality over 8-10 turns. The system prevents this via:

1. **Periodic Reinforcement** - Re-injects persona every N turns (configurable per persona)
2. **Consistency Checking** - Scores responses against persona traits
3. **Dynamic Adaptation** - Adjusts based on user feedback

### Creating Custom Personas

Add to `discord_bot/personality.py`:

```python
"my_custom_bot": PersonaConfig(
    name="My Custom Bot",
    system_prompt="""You are [description].

PERSONALITY:
- [Trait 1]
- [Trait 2]

SPEECH PATTERNS:
- [Pattern 1]
- [Pattern 2]

BOUNDARIES:
- [Rule 1]
- [Rule 2]""",
    voice_settings={
        "temperature": 0.7,
        "top_p": 0.9,
        "presence_penalty": 0.3,
        "frequency_penalty": 0.3
    },
    use_emojis=True,
    signature_phrase="[Optional sign-off]"
)
```

### Voice Settings

Per-persona LLM parameters:

| Setting | Range | Effect |
|---------|-------|--------|
| `temperature` | 0.0-2.0 | Creativity (lower = more focused) |
| `top_p` | 0.0-1.0 | Nucleus sampling diversity |
| `presence_penalty` | -2.0-2.0 | Encourage/discourage new topics |
| `frequency_penalty` | -2.0-2.0 | Reduce repetition |

## Knowledge Extraction

The bot automatically extracts facts from conversations:

**Fact Types:**
- `preference` - Likes, dislikes, choices
- `fact` - Information about the user
- `task` - Commitments, goals, TODOs
- `constraint` - Limitations, requirements
- `topic` - Areas of interest

**Extraction Triggers:**
- Every 10 messages
- Explicit `remember` command
- High-importance user statements

**Confidence Scoring:**
- Explicit statements: 0.9 (high)
- Inferred facts: 0.5 (medium)
- Repeated facts: Increase confidence

## Database Schema

### Tables

**conversations** - All messages
- `id`, `conversation_id`, `user_id`, `role`, `content`
- `timestamp`, `token_count`, `importance_score`, `metadata`

**message_embeddings** - Vector embeddings
- `message_id`, `embedding` (BLOB)

**user_knowledge** - Extracted facts
- `id`, `user_id`, `fact_type`, `content`, `confidence`
- `timestamp`, `access_count`

**conversation_summaries** - Rolling summaries
- `id`, `conversation_id`, `summary_text`, `message_count`

**user_settings** - User preferences
- `user_id`, `preferred_persona`, `conversation_style`
- `max_history_messages`, `memory_enabled`

### Backup

Database is a single SQLite file. Back up:
```bash
cp discord_bot_memory.db discord_bot_memory.db.backup.$(date +%Y%m%d)
```

## Privacy & Security

### Data Storage
- All data stored locally in SQLite
- No conversation data sent to LLM provider (only current query)
- Embeddings are vector representations (not reversible)

### Sensitive Information
The system attempts to avoid storing:
- Passwords, API keys, tokens
- Credit card numbers
- Personal addresses

Use `memory off` to disable storage for sensitive discussions.

### Clear Your Data
```
memory clear
```

## Troubleshooting

### "Chat mode requires broker integration"
- The broker must be running and accessible
- Check `BROKER_URL` in bot.env

### Embeddings not working
```bash
# Check provider
python -c "from discord_bot.embeddings import create_embedding_provider; \
           p = create_embedding_provider('openai'); print(p.name)"

# Test local embeddings
python -c "from discord_bot.embeddings import LocalEmbeddingProvider; \
           p = LocalEmbeddingProvider(); print(p.embed_sync('test'))"
```

### Database errors
```bash
# Check database integrity
sqlite3 discord_bot_memory.db "PRAGMA integrity_check;"

# View stats
sqlite3 discord_bot_memory.db "SELECT COUNT(*) FROM conversations;"
```

### Memory not persisting
- Check `MEMORY_ENABLED=true`
- Verify database path is writable
- Check disk space

## Performance

### Resource Usage

| Component | RAM | Disk | Notes |
|-----------|-----|------|-------|
| SQLite DB | - | ~10MB per 1000 msgs | Minimal |
| OpenAI Embeddings | - | - | ~0.1s per request |
| Local Embeddings | ~300MB | ~150MB model | One-time load |
| Persona System | - | - | Negligible |

### Optimization Tips

1. **Use local embeddings** for cost savings at scale
2. **Enable summaries** for long conversations (auto-enabled)
3. **Set session timeout** to free memory (`CONVERSATION_TIMEOUT_MINUTES`)
4. **Clear old conversations** periodically

## API Reference

### For Developers

```python
from discord_bot.memory import get_memory
from discord_bot.personality import get_personality_engine
from discord_bot.embeddings import create_embedding_provider

# Initialize
embedding_provider = create_embedding_provider('openai')
memory = get_memory('bot_memory.db', embedding_provider)
personality = get_personality_engine('helpful_assistant')

# Store message
memory.add_message(
    conversation_id='dm_123_456',
    user_id='123',
    role='user',
    content='Hello!'
)

# Get context
context = memory.get_conversation_context(
    conversation_id='dm_123_456',
    user_id='123',
    query='What did I say earlier?',
    max_tokens=3000
)

# Switch persona
persona = personality.get_persona('sassy_bot')
```

## Using Conversational Features

All conversations now maintain persistent personality and context:

| Use Case | How |
|----------|-----|
| Natural chat | Just type naturally - no command needed |
| Tool-intensive task | `agentic <request>` with routing hints |
| Conversation with memory | Just start typing - memory is automatic |
| Coding with context | "Remember I use Python..." |

## References

Based on research from:
- Mem0 memory architecture (2024)
- LangChain conversation patterns
- Character.AI persona design
- Persona drift research (Li et al., 2024)
- OpenAI GPT-5 steerability guidelines
- Anthropic Claude reflection techniques
