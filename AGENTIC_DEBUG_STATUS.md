# Agentic Streaming Implementation - Debug Status Summary

## What Was Implemented

We implemented a full bidirectional streaming system between the broker, runner, and Discord bot to enable multi-turn agentic conversations:

### New Components
1. **Broker Streaming** (`broker/streaming.py`, `broker/app.py`)
   - Job chunks table for streaming results
   - Bidirectional tool calls table
   - SSE endpoint and HTTP polling endpoints
   - 9 new streaming API endpoints

2. **Runner Streaming** (`runner/streaming_client.py`, `runner/runner.py`, `runner/llm_loop.py`)
   - Runner client to post chunks to broker
   - `run_llm_tool_loop_streaming()` function
   - `llm_agentic` command
   - Job ID passing from main loop to `run_job()`

3. **Bot Streaming** (`discord_bot/streaming_client.py`, `discord_bot/agentic_session.py`, `discord_bot/discord_tools.py`)
   - SSE/polling client to receive chunks
   - AgenticSession for managing streaming conversations
   - Discord-native tools (send_message, embed, reaction)

4. **Integration** (`discord_bot/bot.py`)
   - Agentic mode is now DEFAULT for almost all requests
   - Only simple conversational queries use quick chat

## The Core Problem

**Symptom**: When user asks "Can you visit https://en.wikipedia.org/wiki/Duckport_Canal and tell me something interesting?"

**What Happens**:
1. Bot acknowledges the request with initial message
2. Bot shows "thinking" indicator
3. **Nothing follows up** - no tool execution results, no final answer
4. The conversation hangs/dies after initial acknowledgment

**Root Cause Hypothesis**: The streaming chunks are either:
- Not being posted from runner to broker
- Not being received/parsed by bot from broker
- The flow is breaking somewhere in the pipeline

## Fixes Applied (Chronological)

### 1. Initial Implementation
- Created all streaming infrastructure
- Added job_chunks and job_tool_calls tables
- Created streaming clients on both runner and bot

### 2. Syntax Error Fix (chat_commands.py)
**Problem**: `""""` (4 quotes) instead of `"""` (3 quotes) on line 1159
**Fix**: Fixed unterminated string literal
**Status**: ✅ Resolved

### 3. Job ID Not Passed (runner.py)
**Problem**: Runner main loop got `job_id` from claimed job but didn't pass it to `run_job()`
**Impact**: Streaming client couldn't be created - no chunks posted
**Fix**: 
- Changed `run_job(command, payload)` to `run_job(command, payload, job_id)`
- Updated `run_job()` function signature
- Updated streaming client creation to use passed `job_id`
**Status**: ✅ Applied, needs testing

### 4. Added Diagnostics & Logging
**Changes**:
- Added detailed logging in streaming clients
- Added intent detection logging
- Lowered confidence thresholds for triggering agentic mode
- Changed default to `use_sse=False` (polling) for reliability
- Added timeout handling with asyncio
- Added status message when agentic mode starts

### 5. Made Agentic Mode Default
**Changes**:
- Almost all requests now use agentic mode
- Only high-confidence "casual_chat" uses simple response
- ask/urgo commands now use agentic mode

## Configuration (All Enabled by Default)

```bash
# Broker - streaming enabled
ENABLE_STREAMING=true

# Runner - agentic streaming enabled
LLM_MODE=agentic_streaming
ENABLE_BIDIRECTIONAL_TOOLS=true

# Bot - agentic mode enabled
AGENTIC_MODE=true
AGENTIC_AUTO_TRIGGER=true
AGENTIC_IDLE_TIMEOUT=300       # Resets on heartbeats (primary timeout)
AGENTIC_ABSOLUTE_MAX_TIMEOUT=900  # Hard ceiling safety valve
AGENTIC_DEFAULT_MAX_STEPS=25
```

## Files Modified/Created

### New Files (7)
- `broker/streaming.py` - Streaming infrastructure
- `runner/streaming_client.py` - Runner chunk posting
- `discord_bot/streaming_client.py` - Bot chunk receiving
- `discord_bot/agentic_session.py` - Session management
- `discord_bot/discord_tools.py` - Discord-native tools
- `tests/test_streaming.py` - Tests
- `AGENTIC_MODE_GUIDE.md` - Documentation

### Modified Files (6)
- `broker/app.py` - Added streaming endpoints
- `runner/runner.py` - Added job_id passing, llm_agentic command
- `runner/llm_loop.py` - Added streaming loop
- `runner/tool_registry.py` - Added Discord tools
- `discord_bot/bot.py` - Added agentic-first routing
- `discord_bot/chat_commands.py` - Fixed syntax error
- `requirements.txt` - Added aiohttp

## Current State

- All code pushed to main branch
- Update.sh should pull latest changes
- Agentic mode is now default for ~90% of requests
- Polling (not SSE) is used for chunk retrieval (more reliable)
- Extensive logging added to diagnose issues

## What Still Needs Investigation

### 1. Chunk Flow Verification
**Need to verify**:
- Is runner posting chunks to broker? (Check broker logs for `chunk_added`)
- Is bot polling for chunks? (Check bot logs for `Starting chunk polling`)
- Are chunks being received? (Check for `First chunk received`)

### 2. Job Creation
**Need to verify**:
- Is the job being created with correct payload?
- Is `job_id` being passed correctly from bot to runner?

### 3. Streaming Client Initialization
**Need to verify**:
- Is streaming client being created with correct job_id?
- Is `STREAMING_ENABLED=true` being detected?
- Is worker_token present?

### 4. LLM Loop Execution
**Need to verify**:
- Is `run_llm_tool_loop_streaming()` actually being called?
- Is it calling the LLM API?
- Is it receiving tool_calls from the LLM?

### 5. Tool Execution
**Need to verify**:
- Are browser tools being dispatched?
- Is the runner executing browser_navigate?
- Are tool results being posted back as chunks?

## Debug Commands for Next Session

### Check Broker
```bash
# Check if chunks are being stored
sqlite3 /var/lib/openclaw-broker/broker.db "SELECT COUNT(*) FROM job_chunks;"
sqlite3 /var/lib/openclaw-broker/broker.db "SELECT * FROM job_chunks ORDER BY created_at DESC LIMIT 5;"
```

### Check Logs
```bash
# VPS - Bot logs
sudo journalctl -u openclaw-discord-bot@urgoclaw -f --since "5 minutes ago"

# WSL - Runner logs
sudo journalctl -u openclaw-runner -f --since "5 minutes ago"

# VPS - Broker logs
sudo journalctl -u openclaw-broker -f --since "5 minutes ago"
```

### Manual Test
```bash
# Test broker endpoint
curl -H "X-Bot-Token: $BOT_TOKEN" http://localhost:8000/capabilities

# Should return streaming_enabled: true
```

## Most Likely Culprits

1. **Chunks not being posted**: Runner streaming client not enabled or job_id not correct
2. **Polling not receiving**: Bot streaming client not connecting or empty response
3. **LLM not making tool calls**: LLM not recognizing it should use browser tools
4. **System prompt not informing LLM of tools**: The persona system prompt may not mention browser capabilities

## Critical Code Paths to Debug

1. **Runner**: `run_job()` line 357 - verify job_id is passed
2. **Runner**: `run_job()` lines 589-593 - verify streaming client created
3. **Runner**: `run_llm_tool_loop_streaming()` - verify chunks posted
4. **Bot**: `AgenticSession._create_job()` - verify job created with correct payload
5. **Bot**: `AgenticSession._process_stream()` - verify chunks received
6. **Bot**: `AgenticSession._handle_chunk()` - verify chunk types handled

## Next Steps for Next Agent

1. Add even more granular logging at each step of the pipeline
2. Verify the job_id is flowing correctly from bot → broker → runner → chunks → bot
3. Check if LLM is actually being called and returning tool_calls
4. Verify browser tools are being dispatched correctly
5. Test with a simple `!agentic ping` first to verify basic flow works
6. Check if there's a mismatch between chunk types expected vs sent