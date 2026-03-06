"""
Chat command handlers for conversational Discord bot with memory.

This module provides:
- chat: Conversational mode with memory and personality
- persona: Switch between bot personalities
- memory: Memory management commands
- remember/forget: Explicit memory control
"""

import os
import time
from typing import Optional, Dict, Callable
from dataclasses import dataclass
import logging

# Import our modules
from .memory import get_memory
from .personality import get_personality_engine

logger = logging.getLogger(__name__)


@dataclass
class ChatSession:
    """Represents an active chat session."""
    user_id: str
    channel_id: str
    conversation_id: str
    persona_key: str
    started_at: float
    last_activity: float
    message_count: int = 0


class ChatManager:
    """
    Manages conversational chat sessions with memory and personality.
    
    This integrates the memory and personality systems to provide
    a cohesive conversational experience.
    """
    
    def __init__(self, bot_instance, broker_url: str, bot_token: str,
                 run_job_func: Optional[Callable] = None):
        """
        Initialize chat manager.
        
        Args:
            bot_instance: The Discord bot instance
            broker_url: URL of the OpenClaw broker
            bot_token: Bot token for broker authentication
            run_job_func: Function to run jobs (e.g., _run_job_and_reply)
        """
        self.bot = bot_instance
        self.broker_url = broker_url
        self.bot_token = bot_token
        self.run_job_func = run_job_func
        
        # Initialize subsystems
        self.memory = get_memory()
        self.personality = get_personality_engine()
        
        # Active sessions
        self.sessions: Dict[str, ChatSession] = {}  # conversation_id -> session
        
        # Configuration
        self.session_timeout = 1800  # 30 minutes
        self.max_context_messages = 20
        
        logger.info("Chat manager initialized")
    
    def _get_conversation_id(self, channel_id: str, user_id: str) -> str:
        """Generate unique conversation ID."""
        return f"{channel_id}_{user_id}"
    
    def _get_or_create_session(self, user_id: str, channel_id: str,
                               persona_key: Optional[str] = None) -> ChatSession:
        """Get existing session or create new one."""
        conversation_id = self._get_conversation_id(channel_id, user_id)
        
        # Check for existing session
        if conversation_id in self.sessions:
            session = self.sessions[conversation_id]
            
            # Check if timed out
            if time.time() - session.last_activity > self.session_timeout:
                logger.info(f"Session {conversation_id} timed out, creating new")
                self._end_session(conversation_id)
            else:
                # Update activity
                session.last_activity = time.time()
                return session
        
        # Create new session
        if persona_key is None:
            # Check user preferences
            settings = self.memory.get_user_settings(user_id)
            persona_key = settings.get('preferred_persona', 'helpful_assistant')
        
        session = ChatSession(
            user_id=user_id,
            channel_id=channel_id,
            conversation_id=conversation_id,
            persona_key=persona_key,
            started_at=time.time(),
            last_activity=time.time(),
            message_count=0
        )
        
        self.sessions[conversation_id] = session
        logger.info(f"Created new chat session: {conversation_id} with persona {persona_key}")
        
        return session
    
    def _end_session(self, conversation_id: str):
        """End a chat session."""
        if conversation_id in self.sessions:
            session = self.sessions[conversation_id]
            
            # Reset personality turn counter
            self.personality.reset_turns(session.user_id)
            
            # Remove from active sessions
            del self.sessions[conversation_id]
            
            logger.info(f"Ended chat session: {conversation_id}")
    
    async def handle_chat_message(self, message_content: str, user_id: str,
                                  channel_id: str, username: str,
                                  reply_func) -> str:
        """
        Handle a chat message and generate response.
        
        Args:
            message_content: The message text
            user_id: Discord user ID
            channel_id: Discord channel ID
            username: User's display name
            reply_func: Async function to send reply
        
        Returns:
            Response text
        """
        # Check for persona change request
        requested_persona = self.personality.detect_persona_request(message_content)
        
        # Get or create session
        session = self._get_or_create_session(user_id, channel_id, requested_persona)
        
        # If persona was requested, update session
        if requested_persona:
            session.persona_key = requested_persona
            self.personality.set_user_persona(user_id, requested_persona)
            
            # Reset for new persona
            self.personality.reset_turns(user_id)
            
            await reply_func(f"🎭 Switched to **{self.personality.get_persona(requested_persona).name}** persona!")
        
        # Get persona configuration
        persona = self.personality.get_persona(session.persona_key, user_id)
        
        # Get conversation context from memory
        context = self.memory.get_conversation_context(
            session.conversation_id,
            user_id,
            query=message_content,
            max_tokens=3000
        )
        
        # Build messages for LLM
        messages = []
        
        # System prompt with persona
        system_prompt = self.personality.build_system_prompt(
            persona,
            session.conversation_id,
            user_id,
            enforce_consistency=True
        )
        
        # Add user knowledge if available
        if context['user_knowledge']:
            knowledge_text = "User information:\n"
            for fact in context['user_knowledge']:
                knowledge_text += f"- {fact.fact_type}: {fact.content}\n"
            system_prompt += f"\n\n{knowledge_text}"
        
        messages.append({"role": "system", "content": system_prompt})
        
        # Add conversation summary if available
        if context['summary']:
            messages.append({
                "role": "system",
                "content": f"Previous conversation summary: {context['summary']}"
            })
        
        # Add recent messages (formatted as user/assistant)
        for msg in context['recent_messages']:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })
        
        # Add semantically similar messages as context
        for msg, score in context['similar_messages']:
            messages.append({
                "role": "system",
                "content": f"[Relevant from earlier conversation]: {msg.content}"
            })
        
        # Add current message
        messages.append({"role": "user", "content": message_content})
        
        # Store user message in memory
        self.memory.add_message(
            session.conversation_id,
            user_id,
            "user",
            message_content,
            metadata={"username": username}
        )
        
        # Get voice settings
        voice_settings = self.personality.get_voice_settings(persona, user_id)
        
        # Send to broker for processing (through existing job system)
        # This uses the llm_task mechanism but with conversation context
        try:
            # Note: reply_func is not used here as we return the response
            # The actual Discord reply happens in the caller
            response = await self._send_to_llm(messages, voice_settings, session, None)
            
            # Validate persona adherence
            adherence_score = self.personality.validate_persona_adherence(response, persona)
            
            if adherence_score < 0.7:
                logger.warning(f"Persona adherence low ({adherence_score:.2f}), may need reinforcement")
            
            # Format response
            response = self.personality.format_response(response, persona)
            
            # Store assistant response in memory
            self.memory.add_message(
                session.conversation_id,
                user_id,
                "assistant",
                response
            )
            
            # Update session
            session.message_count += 1
            session.last_activity = time.time()
            self.personality.increment_turn(user_id)
            
            return response
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return f"I'm having trouble thinking right now... Error: {str(e)[:100]}"
    
    async def _send_to_llm(self, messages: list, voice_settings: dict,
                          session: ChatSession, message_obj) -> str:
        """
        Send conversation to LLM via broker using the bot's job system.
        
        This creates an llm_task job that the runner processes with full context.
        """
        import json
        import requests
        import time
        
        # Get broker config from environment or bot instance
        broker_url = getattr(self.bot, 'broker_url', self.broker_url)
        bot_token = getattr(self.bot, 'bot_token', self.bot_token)
        
        # Create payload with conversation context
        current_prompt = messages[-1]["content"] if messages else ""
        context_messages = messages[:-1] if len(messages) > 1 else []
        
        # Build the payload for llm_task
        payload_obj = {
            "prompt": current_prompt,
            "conversation_history": [
                {"role": m["role"], "content": m["content"]} 
                for m in context_messages
            ],
            "persona": session.persona_key,
            "temperature": voice_settings.get("temperature", 0.7),
            "max_tokens": voice_settings.get("max_tokens", 2000),
        }
        
        payload_json = json.dumps(payload_obj)
        
        # Call broker directly
        try:
            # Create job
            r = requests.post(
                f"{broker_url}/jobs",
                headers={"X-Bot-Token": bot_token},
                json={"command": "llm_task", "payload": payload_json},
                timeout=(5, 15),
            )
            r.raise_for_status()
            job = r.json()
            job_id = job.get("id")
            
            if not job_id:
                return "[Error: Failed to create conversation job]"
            
            # Poll for result
            deadline = time.monotonic() + 120  # 2 minute timeout
            sleep_sec = 0.5
            
            while time.monotonic() < deadline:
                r = requests.get(
                    f"{broker_url}/jobs/{job_id}",
                    headers={"X-Bot-Token": bot_token},
                    timeout=(5, 15),
                )
                r.raise_for_status()
                job = r.json()
                
                status = job.get("status", "")
                if status == "done":
                    result = job.get("result", "(no result)")
                    try:
                        parsed = json.loads(result)
                        if isinstance(parsed, dict):
                            return parsed.get("final", result)
                    except json.JSONDecodeError:
                        pass
                    return result
                    
                if status == "failed":
                    err = job.get("error") or job.get("result") or "unknown"
                    return f"[Error: {err}]"
                
                time.sleep(sleep_sec)
                sleep_sec = min(sleep_sec * 2, 2.0)
            
            return f"[Still processing... Check status with: status {job_id}]"
            
        except requests.RequestException as e:
            logger.error(f"Broker request failed: {e}")
            return f"[Broker connection error: {str(e)[:100]}]"
        except Exception as e:
            logger.error(f"Error in _send_to_llm: {e}")
            return f"[Error generating response: {str(e)[:100]}]"
    
    async def handle_persona_command(self, user_id: str, 
                                     requested_persona: Optional[str] = None) -> str:
        """Handle persona switch command."""
        if requested_persona is None:
            # List available personas
            personas = self.personality.list_personas()
            lines = ["Available personas:"]
            for key, desc in personas.items():
                lines.append(f"- **{key}**: {desc[:50]}...")
            lines.append("\nUse `persona <name>` to switch.")
            return "\n".join(lines)
        
        # Try to switch persona
        persona = self.personality.get_persona(requested_persona)
        
        if persona.name == self.personality.get_persona().name and requested_persona not in self.personality.personas:
            return f"Unknown persona: '{requested_persona}'. Use `persona` to see available options."
        
        # Update user preference
        self.personality.set_user_persona(user_id, requested_persona)
        
        # Update session if active
        conversation_id = self._get_conversation_id("dm", user_id)  # Simplified
        if conversation_id in self.sessions:
            self.sessions[conversation_id].persona_key = requested_persona
        
        return f"🎭 Switched to **{persona.name}** persona!\n\n{persona.system_prompt[:200]}..."
    
    async def handle_memory_command(self, user_id: str, 
                                    subcommand: Optional[str] = None,
                                    args: str = "") -> str:
        """Handle memory management commands."""
        if subcommand is None or subcommand == "status":
            # Show memory status
            settings = self.memory.get_user_settings(user_id)
            knowledge = self.memory.get_user_knowledge(user_id, limit=5)
            
            lines = ["🧠 **Your Memory Status**"]
            lines.append(f"Memory enabled: {'Yes' if settings['memory_enabled'] else 'No'}")
            lines.append(f"Max history: {settings['max_history_messages']} messages")
            lines.append(f"Preferred persona: {settings['preferred_persona']}")
            lines.append(f"\nStored facts: {len(knowledge)}")
            
            if knowledge:
                lines.append("\n**Recent facts:**")
                for fact in knowledge[:3]:
                    lines.append(f"- {fact.fact_type}: {fact.content[:50]}...")
            
            return "\n".join(lines)
        
        elif subcommand == "clear":
            # Clear conversation history
            self.memory.clear_user_memory(user_id, keep_settings=True)
            
            # End active sessions
            for conv_id in list(self.sessions.keys()):
                if self.sessions[conv_id].user_id == user_id:
                    self._end_session(conv_id)
            
            return "🗑️ Cleared your conversation history and memory. Your settings are preserved."
        
        elif subcommand == "on":
            self.memory.update_user_settings(user_id, memory_enabled=True)
            return "✅ Memory is now **enabled**. I'll remember our conversations."
        
        elif subcommand == "off":
            self.memory.update_user_settings(user_id, memory_enabled=False)
            return "⏸️ Memory is now **disabled**. I won't store new conversations."
        
        else:
            return "Unknown memory command. Use: `memory status`, `memory clear`, `memory on/off`"
    
    async def handle_remember_command(self, user_id: str, 
                                      content: str,
                                      fact_type: str = "fact") -> str:
        """Explicitly remember something."""
        if not content:
            return "What would you like me to remember? Usage: `remember <something>`"
        
        # Add to knowledge
        self.memory.add_user_fact(
            user_id=user_id,
            fact_type=fact_type,
            content=content,
            confidence=0.9  # High confidence for explicit memories
        )
        
        return f"✅ Remembered: *{content[:100]}*"
    
    async def handle_forget_command(self, user_id: str,
                                    search_term: str) -> str:
        """Forget something matching search term."""
        # This would search and remove matching facts
        # Simplified implementation
        return f"🔍 Searching for '{search_term}' to forget... (implementation needed)"
    
    async def handle_history_command(self, user_id: str,
                                     channel_id: str,
                                     limit: int = 10) -> str:
        """Show recent conversation history."""
        conversation_id = self._get_conversation_id(channel_id, user_id)
        messages = self.memory.get_recent_messages(conversation_id, limit=limit)
        
        if not messages:
            return "No conversation history found."
        
        lines = [f"📜 **Recent Conversation History** (last {len(messages)} messages):\n"]
        
        for msg in messages:
            role_emoji = "👤" if msg.role == "user" else "🤖"
            timestamp = time.strftime("%H:%M", time.localtime(msg.timestamp))
            content_preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
            lines.append(f"{role_emoji} [{timestamp}] {content_preview}")
        
        return "\n".join(lines)
    
    def cleanup_sessions(self):
        """Clean up timed-out sessions."""
        now = time.time()
        expired = [
            conv_id for conv_id, session in self.sessions.items()
            if now - session.last_activity > self.session_timeout
        ]
        
        for conv_id in expired:
            self._end_session(conv_id)
        
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")


# Global chat manager instance
_chat_manager_instance = None

def get_chat_manager(bot, broker_url: str, bot_token: str) -> ChatManager:
    """Get or create global chat manager instance."""
    global _chat_manager_instance
    if _chat_manager_instance is None:
        _chat_manager_instance = ChatManager(
            bot_instance=bot,
            broker_url=broker_url,
            bot_token=bot_token
        )
    return _chat_manager_instance


# Command handlers for bot.py integration

async def handle_chat_command(bot, message, args: str):
    """
    Handle 'chat' command - conversational mode with memory.
    
    Usage: chat <message>
    """
    if not args:
        return "Start a conversation with me! Usage: `chat <your message>`"
    
    # Get broker URL and token from bot
    broker_url = getattr(bot, 'broker_url', os.environ.get("BROKER_URL", "http://127.0.0.1:8000"))
    bot_token = getattr(bot, 'bot_token', os.environ.get("BOT_TOKEN", ""))
    
    # Get chat manager
    manager = get_chat_manager(bot, broker_url, bot_token)
    
    async def reply_func(text):
        await message.channel.send(text)
    
    response = await manager.handle_chat_message(
        message_content=args,
        user_id=str(message.author.id),
        channel_id=str(message.channel.id),
        username=message.author.display_name,
        reply_func=reply_func
    )
    
    return response


async def handle_persona_command(bot, message, args: str):
    """
    Handle 'persona' command - switch personalities.
    
    Usage: persona [name]
    """
    broker_url = getattr(bot, 'broker_url', os.environ.get("BROKER_URL", "http://127.0.0.1:8000"))
    bot_token = getattr(bot, 'bot_token', os.environ.get("BOT_TOKEN", ""))
    
    manager = get_chat_manager(bot, broker_url, bot_token)
    
    requested = args.strip() if args else None
    response = await manager.handle_persona_command(
        str(message.author.id),
        requested
    )
    return response


async def handle_memory_command(bot, message, args: str):
    """
    Handle 'memory' command - memory management.
    
    Usage: memory [status|clear|on|off]
    """
    broker_url = getattr(bot, 'broker_url', os.environ.get("BROKER_URL", "http://127.0.0.1:8000"))
    bot_token = getattr(bot, 'bot_token', os.environ.get("BOT_TOKEN", ""))
    
    manager = get_chat_manager(bot, broker_url, bot_token)
    
    parts = args.strip().split() if args else []
    subcommand = parts[0] if parts else None
    
    response = await manager.handle_memory_command(
        str(message.author.id),
        subcommand,
        " ".join(parts[1:]) if len(parts) > 1 else ""
    )
    return response


async def handle_remember_command(bot, message, args: str):
    """
    Handle 'remember' command.
    
    Usage: remember <something>
    """
    broker_url = getattr(bot, 'broker_url', os.environ.get("BROKER_URL", "http://127.0.0.1:8000"))
    bot_token = getattr(bot, 'bot_token', os.environ.get("BOT_TOKEN", ""))
    
    manager = get_chat_manager(bot, broker_url, bot_token)
    
    response = await manager.handle_remember_command(
        str(message.author.id),
        args
    )
    return response


async def handle_history_command(bot, message, args: str):
    """
    Handle 'history' command.
    
    Usage: history [count]
    """
    broker_url = getattr(bot, 'broker_url', os.environ.get("BROKER_URL", "http://127.0.0.1:8000"))
    bot_token = getattr(bot, 'bot_token', os.environ.get("BOT_TOKEN", ""))
    
    manager = get_chat_manager(bot, broker_url, bot_token)
    
    limit = int(args.strip()) if args and args.strip().isdigit() else 10
    
    response = await manager.handle_history_command(
        str(message.author.id),
        str(message.channel.id),
        limit=limit
    )
    return response
