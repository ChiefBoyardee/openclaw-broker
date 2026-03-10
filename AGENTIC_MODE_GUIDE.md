# OpenClaw Agentic Mode Guide

## Overview

Agentic Mode is a new streaming, bidirectional communication system between the broker, runner, and Discord bot. It enables:

- **Real-time streaming responses** - See LLM thinking and tool execution as it happens
- **Multi-turn tool loops** - Runner can call tools, get results, think, and continue
- **Discord-native capabilities** - LLM can orchestrate reactions, embeds, file uploads
- **Bidirectional tool execution** - Tools can be executed by either runner or bot

## Architecture

```mermaid
flowchart TB
    subgraph Discord
        User[User Message]
        Bot[Discord Bot]
        Agentic[AgenticSession Handler]
    end

    subgraph Broker
        API[FastAPI Endpoints]
        Jobs[(Job Queue)]
        Chunks[(Job Chunks Stream)]
        ToolCalls[(Bidirectional Tool Calls)]
    end

    subgraph Runner
        Poll[Job Polling]
        LLM[LLM Agent Loop]
        Stream[Stream Output]
    end

    User --> Bot
    Bot --> Agentic
    Agentic -->|POST /jobs| API
    API --> Jobs

    Poll -->|GET /jobs/next| API
    Poll --> LLM
    LLM -->|Chunks| Stream
    Stream -->|POST /jobs/{id}/chunks| Chunks
    Chunks -->|SSE /jobs/{id}/stream| Agentic

    LLM -->|POST /jobs/{id}/tool_calls| ToolCalls
    ToolCalls -->|GET| Agentic
    Agentic -->|POST /tool_calls/{id}/result| ToolCalls
```

## Configuration

### Broker Configuration

Add to your broker environment:

```bash
# Enable streaming endpoints
ENABLE_STREAMING=true
MAX_CHUNK_AGE_SECONDS=3600

# Database is automatically extended with:
# - job_chunks table (for streaming results)
# - job_tool_calls table (for bidirectional execution)
```

### Runner Configuration

Add to your runner environment (all have sensible defaults):

```bash
# LLM Mode (defaults to agentic_streaming)
LLM_MODE=agentic_streaming  # Set to 'simple' for legacy behavior
ENABLE_BIDIRECTIONAL_TOOLS=true  # Already enabled by default
STREAMING_HEARTBEAT_SECONDS=30

# Existing configuration still works
BROKER_URL=http://your-broker:8000
WORKER_TOKEN=your-worker-token
```

### Discord Bot Configuration

Add to your bot environment (all have sensible defaults):

```bash
# Agentic Mode (all enabled by default)
AGENTIC_MODE=true  # Already enabled by default
AGENTIC_AUTO_TRIGGER=true  # Already enabled by default
AGENTIC_MAX_STREAM_WAIT=300
AGENTIC_DEFAULT_MAX_STEPS=10

# Broker connection
BROKER_URL=http://your-broker:8000
BOT_TOKEN=your-bot-token
```

### Required Dependencies

The bot requires `aiohttp` for async HTTP streaming:

```bash
pip install aiohttp
```

## New Endpoints

### Broker Streaming Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/jobs/{id}/chunks` | POST | Runner posts chunks to stream |
| `/jobs/{id}/chunks` | GET | Bot polls for chunks (fallback) |
| `/jobs/{id}/stream` | GET | Server-Sent Events stream |
| `/jobs/{id}/tool_calls` | POST | Runner creates bidirectional tool call |
| `/jobs/{id}/tool_calls` | GET | Bot gets pending tool calls |
| `/tool_calls/{id}` | GET | Poll for tool call status |
| `/tool_calls/{id}/result` | POST | Bot reports tool result |
| `/tool_calls/{id}/fail` | POST | Bot reports tool failure |
| `/capabilities` | GET | Broker capabilities including streaming |

### Chunk Types

Chunks can be of the following types:

- `thinking` - LLM reasoning/thinking step
- `message` - Intermediate message to user
- `tool_call` - Tool execution request
- `tool_result` - Tool execution result
- `progress` - Progress update
- `final` - Final result (ends stream)
- `heartbeat` - Keep-alive signal

## Usage

### Manual Agentic Mode

Users can explicitly request agentic mode:

```
!agentic Search for authentication code in the discord_bot folder,
 then look up any security best practices on the web,
 and finally create a summary of your findings
```

The bot will:
1. Stream progress updates
2. Show thinking steps with 🤔 reactions
3. Call repo tools (grep, readfile) as needed
4. Call browser tools (search, navigate) as needed
5. Send intermediate messages
6. Deliver final result with ✅ reaction

### Auto-Trigger Agentic Mode

When `AGENTIC_AUTO_TRIGGER=true`, high-confidence tool intents automatically use agentic mode:

```
User: "Search for the auth code in my repos, then look up OAuth2 best practices"
→ Bot detects high-confidence tool intent
→ Automatically uses agentic mode for multi-turn execution
```

### Discord-Native Tools

The LLM can now use Discord-specific tools:

- `discord_send_message` - Send intermediate updates
- `discord_add_reaction` - Add progress reactions
- `discord_send_embed` - Send formatted embeds
- `discord_upload_file` - Upload files

## New Files Created

### Broker
- `broker/streaming.py` - Streaming infrastructure and database management

### Runner
- `runner/streaming_client.py` - Client for posting chunks to broker

### Discord Bot
- `discord_bot/streaming_client.py` - SSE/polling client for receiving chunks
- `discord_bot/agentic_session.py` - Session management and Discord integration
- `discord_bot/discord_tools.py` - Discord-native tool definitions

### Updated Files
- `broker/app.py` - Added streaming endpoints and SSE support
- `runner/runner.py` - Added `llm_agentic` command and streaming integration
- `runner/llm_loop.py` - Added `run_llm_tool_loop_streaming()` function
- `runner/tool_registry.py` - Added tool categories and Discord tools
- `discord_bot/bot.py` - Added `agentic` command and auto-trigger integration

## Tool Categories

Tools are now categorized by execution location:

| Category | Tools | Execution |
|----------|-------|-----------|
| `RUNNER_LOCAL` | repo_*, browser_*, github_*, website_*, nginx_* | Runner only |
| `BIDIRECTIONAL` | (future) | Either runner or bot |
| `BOT_ONLY` | discord_* | Discord bot only |

When a BOT_ONLY tool is called in the runner, it returns a placeholder and creates a bidirectional tool call for the bot to execute.

## Backward Compatibility

The system maintains full backward compatibility:

- Existing `llm_task` jobs work unchanged
- All existing commands (`ask`, `chat`, `repos`, etc.) continue to work
- Features are enabled by default but can be disabled:
  - Set `LLM_MODE=simple` to disable runner streaming
  - Set `AGENTIC_MODE=false` to disable bot agentic mode
  - Set `ENABLE_STREAMING=false` to disable broker streaming

## Migration Steps

**Features are enabled by default!** Simply restart your services:

1. **Update Broker** (no breaking changes)
   ```bash
   # Restart broker with new streaming endpoints
   python -m broker.app
   ```

2. **Update Runner** (streaming enabled by default)
   ```bash
   # Install aiohttp if not already available
   pip install aiohttp

   # Restart runner (LLM_MODE defaults to agentic_streaming)
   python -m runner.runner
   ```

3. **Update Bot** (agentic mode enabled by default)
   ```bash
   # Restart bot (AGENTIC_MODE defaults to true)
   python -m discord_bot.bot
   ```

4. **Test**
   ```
   !agentic Test streaming mode with a simple web search
   ```

**To disable features (if needed):**
```bash
# Runner - disable streaming
LLM_MODE=simple

# Bot - disable agentic mode  
AGENTIC_MODE=false

# Broker - disable streaming
ENABLE_STREAMING=false
```

## Troubleshooting

### Stream Not Starting

Check broker logs for:
- `ENABLE_STREAMING=true` is set
- Database migrations ran successfully (job_chunks and job_tool_calls tables exist)

### Tool Calls Not Executing

Check:
- Bot has `AGENTIC_MODE=true` (enabled by default)
- Runner has `ENABLE_BIDIRECTIONAL_TOOLS=true` (enabled by default)
- Both using same `BROKER_URL`
- `aiohttp` is installed (`pip install aiohttp`)

### SSE Connection Issues

Fallback to polling:
```python
config = AgenticConfig(use_sse=False)  # Use polling instead of SSE
```

## Performance Considerations

- **Chunk Cleanup**: Old chunks are automatically cleaned up after `MAX_CHUNK_AGE_SECONDS`
- **Heartbeat**: Runners send heartbeats every `STREAMING_HEARTBEAT_SECONDS` to keep jobs alive
- **Lease Extension**: Running jobs with active streams have extended leases
- **Memory**: Each chunk is stored in SQLite; large outputs are truncated

## Future Enhancements

Planned improvements:
- WebSocket support for even lower latency
- Tool result streaming (progressive tool output)
- Multi-user collaborative agentic sessions
- Tool result caching and replay
