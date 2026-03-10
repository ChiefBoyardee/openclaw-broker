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
import asyncio
import json
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

        logger.info(f"Chat manager initialized (default persona: {self.personality.default_persona})")
    
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
            preferred = settings.get('preferred_persona')
            # If no preference set (None) or set to legacy 'default', use system default
            if preferred is None or preferred == 'default':
                persona_key = self.personality.default_persona
                logger.debug(f"No user preference, using default persona: {persona_key}")
            else:
                persona_key = preferred
                logger.debug(f"Using user preferred persona: {persona_key}")
        
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
    
    def _extract_obvious_facts(self, message: str) -> list:
        """
        Extract obvious facts from user message for immediate storage.
        
        Returns list of (fact_type, content) tuples.
        This is lightweight pattern matching - not NLP, just obvious patterns.
        """
        import re
        facts = []
        message_lower = message.lower()
        
        # Pattern: "my favorite X is Y" / "I love X" / "I hate X"
        fav_patterns = [
            r"my favorite (\w+) is (.+?)(?:\.|$|!|\?)",
            r"i love (.+?)(?:\.|$|!|\?)",
            r"i really like (.+?)(?:\.|$|!|\?)",
            r"i hate (.+?)(?:\.|$|!|\?)",
            r"i dislike (.+?)(?:\.|$|!|\?)",
        ]
        for pattern in fav_patterns:
            match = re.search(pattern, message_lower)
            if match:
                if "favorite" in pattern:
                    fact_type = f"favorite_{match.group(1)}"
                    content = match.group(2).strip()
                elif "love" in pattern or "like" in pattern:
                    fact_type = "preference"
                    content = f"Likes: {match.group(1).strip()}"
                else:
                    fact_type = "preference"
                    content = f"Dislikes: {match.group(1).strip()}"
                facts.append((fact_type, content))
        
        # Pattern: "I live in X" / "I'm from X" / "I'm in X"
        location_patterns = [
            r"i live in (.+?)(?:\.|$|!|\?|,)",
            r"i['']?m from (.+?)(?:\.|$|!|\?|,)",
            r"i['']?m in (.+?) (?:now|currently)(?:\.|$|!|\?|,)",
        ]
        for pattern in location_patterns:
            match = re.search(pattern, message_lower)
            if match:
                location = match.group(1).strip()
                # Clean up common extra words
                location = re.sub(r'\b(right now|currently|at the moment)\b', '', location).strip()
                if location:
                    facts.append(("location", location))
                    break  # Only take first location match
        
        # Pattern: "My name is X" / "I'm X" / "Call me X"
        name_patterns = [
            r"my name is (.+?)(?:\.|$|!|\?|,)",
            r"i['']?m (.+?) (?:and|but|\.)",
            r"call me (.+?)(?:\.|$|!|\?|,)",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, message_lower)
            if match:
                name = match.group(1).strip()
                # Avoid capturing obvious non-names
                non_names = ['a ', 'an ', 'the ', 'here', 'there', 'sad', 'happy', 'tired', 'busy', 'not ', 'really']
                if not any(name.startswith(n) or name == n for n in non_names):
                    facts.append(("name", name))
                    break
        
        # Pattern: "I work as X" / "I'm a X" / "I do X for work"
        job_patterns = [
            r"i work as (.+?)(?:\.|$|!|\?|,)",
            r"i['']?m a[n]? (.+?) (?:and|who|\.)",
            r"i do (.+?) for (?:work|a living)",
        ]
        for pattern in job_patterns:
            match = re.search(pattern, message_lower)
            if match:
                job = match.group(1).strip()
                facts.append(("occupation", job))
                break
        
        # Pattern: "I have X" / "I own X" (pets, items)
        possession_patterns = [
            r"i have a (.+?)(?:\.|$|!|\?|,)",
            r"i own a (.+?)(?:\.|$|!|\?|,)",
        ]
        for pattern in possession_patterns:
            match = re.search(pattern, message_lower)
            if match:
                item = match.group(1).strip()
                # Only capture if it's likely interesting (has descriptor words)
                if any(word in item for word in ['dog', 'cat', 'pet', 'car', 'bike', 'house', 'old', 'new', 'big', 'small']):
                    facts.append(("possession", item))
                    break
        
        # Pattern: "I'm X years old" / "I was born in X"
        age_patterns = [
            r"i['']?m (\d+) years? old",
            r"i was born in (\d{4})",
        ]
        for pattern in age_patterns:
            match = re.search(pattern, message_lower)
            if match:
                if "years" in pattern:
                    facts.append(("age", f"{match.group(1)} years old"))
                else:
                    facts.append(("birth_year", match.group(1)))
                break
        
        # Limit to first 2 facts to avoid over-extracting
        return facts[:2]
            
    async def _process_memory_background(self, user_id: str, conversation_id: str):
        """Asynchronously process conversation history to extract, update, or remove facts using LLM."""
        try:
            # Gather last 10 messages for context
            messages = self.memory.get_recent_messages(conversation_id, limit=10)
            if len(messages) < 3:
                return  # Not enough context to process
                
            # Gather current user knowledge
            knowledge = self.memory.get_user_knowledge(user_id, limit=30)
            knowledge_text = "Current User Facts:\n" + "\n".join([f"[{fact.id}] {fact.fact_type}: {fact.content}" for fact in knowledge])
            
            chat_text = "Recent Conversation:\n" + "\n".join([f"{msg.role}: {msg.content}" for msg in messages])
            
            prompt = (
                "You are an intelligent memory curation assistant. Your job is to analyze the recent conversation "
                "and maintain the user's permanent memory profile.\n\n"
                f"{knowledge_text}\n\n"
                f"{chat_text}\n\n"
                "INSTRUCTIONS:\n"
                "1. If the user stated a new fact (e.g. name, favorite color, location, preference), extract it.\n"
                "2. If the user corrected a previous fact or changed their mind (e.g. 'I actually like blue now, not red', 'I moved to NYC'), "
                "you MUST identify the ID of the old incorrect fact to remove it, and add the new correct fact.\n"
                "3. If nothing substantial needs to be remembered, return empty lists.\n\n"
                "You MUST respond ONLY with a raw JSON object containing 'add' (list of dicts with 'fact_type' and 'content') "
                "and 'remove' (list of IDs to remove). Do not include any markdown or explanation.\n"
                "Example Format:\n"
                '{"add": [{"fact_type": "favorite_color", "content": "My favorite color is green"}], "remove": [4]}'
            )
            
            # Send to LLM
            broker_url = getattr(self.bot, 'broker_url', self.broker_url)
            bot_token = getattr(self.bot, 'bot_token', self.bot_token)
            
            import requests
            r = await asyncio.to_thread(
                requests.post,
                f"{broker_url}/jobs",
                headers={"X-Bot-Token": bot_token},
                json={"command": "llm_task", "payload": json.dumps({"prompt": prompt, "temperature": 0.1})},
                timeout=10
            )
            r.raise_for_status()
            job = r.json()
            job_id = job.get("id")
            
            if not job_id:
                return
                
            # Poll for result
            for _ in range(60): # 1 minute max polling
                await asyncio.sleep(1.0)
                r = await asyncio.to_thread(
                    requests.get,
                    f"{broker_url}/jobs/{job_id}",
                    headers={"X-Bot-Token": bot_token},
                    timeout=5
                )
                if r.status_code != 200:
                    continue
                job_status = r.json()
                if job_status.get("status") == "done":
                    result_str = job_status.get("result", "{}")
                    try:
                        # Extract final text
                        parsed = json.loads(result_str)
                        if isinstance(parsed, dict) and "final" in parsed:
                            result_str = parsed["final"]
                            
                        # Strip markdown if present
                        if result_str.startswith("```json"):
                            result_str = result_str[7:-3].strip()
                        elif result_str.startswith("```"):
                            result_str = result_str[3:-3].strip()
                            
                        data = json.loads(result_str)
                        
                        # Process removals
                        removals = data.get("remove", [])
                        if removals:
                            self.memory.remove_user_facts(user_id, [int(i) for i in removals])
                            logger.info(f"Memory Curate: Removed facts {removals} for user {user_id}")
                            
                        # Process additions
                        additions = data.get("add", [])
                        for fact in additions:
                            if "fact_type" in fact and "content" in fact:
                                self.memory.add_user_fact(user_id, fact["fact_type"], fact["content"], confidence=0.8)
                                logger.info(f"Memory Curate: Added '{fact['content']}' for user {user_id}")
                                
                    except (json.JSONDecodeError, ValueError) as json_err:
                        logger.warning(f"Failed to parse memory extraction JSON: {json_err} - raw: {result_str}")
                    break
                elif job_status.get("status") == "failed":
                    break
        except Exception as e:
            logger.error(f"Background memory loop error: {e}")
    
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
        
        # Extract and store obvious facts immediately (don't wait for background)
        immediate_facts = self._extract_obvious_facts(message_content)
        if immediate_facts:
            for fact_type, content in immediate_facts:
                try:
                    self.memory.add_user_fact(user_id, fact_type, content, confidence=0.9)
                    logger.info(f"Immediate memory: Stored {fact_type}='{content}' for user {user_id}")
                except Exception as e:
                    logger.debug(f"Failed to store immediate fact: {e}")
        
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
            
            # Spin off background memory extraction every 3 turns
            if session.message_count % 3 == 0:
                asyncio.create_task(self._process_memory_background(user_id, session.conversation_id))
            
            return response
            
        except Exception as e:
            logger.exception(f"Error generating response: {e}")
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

        # Debug: Log what we're sending
        system_msgs = [m for m in context_messages if m.get("role") == "system"]
        if system_msgs:
            first_system = system_msgs[0].get("content", "")[:100]
            logger.info(f"Sending to LLM with persona {session.persona_key}, system prompt starts: {first_system}...")
        else:
            logger.warning(f"No system message in conversation! Persona: {session.persona_key}")

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

                # Short sleep to avoid blocking Discord event loop
                await asyncio.sleep(sleep_sec)
                sleep_sec = min(sleep_sec * 2, 1.0)  # Cap at 1s
            
            return f"[Still processing... Check status with: status {job_id}]"
            
        except requests.RequestException as e:
            logger.error(f"Broker request failed: {e}")
            return f"[Broker connection error: {str(e)[:100]}]"
        except Exception as e:
            logger.exception(f"Error in _send_to_llm: {e}")
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
        if not self.memory:
            return "❌ Memory system not available."

        try:
            # Search user facts for matches
            facts = self.memory.get_user_knowledge(user_id, limit=100)
            matches = [f for f in facts if search_term.lower() in f.content.lower()]

            if not matches:
                return f"🔍 No memories found matching '{search_term}'."

            # Remove the first match
            target = matches[0]
            if target.id is not None:
                self.memory.db.execute("DELETE FROM user_knowledge WHERE id = ?", (target.id,))
                self.memory.db.commit()
                return f"🗑️ Forgot: *{target.content[:100]}*"
            else:
                return "❌ Could not identify memory to remove."
        except Exception as e:
            return f"❌ Error forgetting: {str(e)}"
    
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


# Website management command handlers

async def handle_website_command(bot, message, args: str):
    """
    Handle 'website' command - AI website management.
    
    Usage: website [init|status|regenerate|sync|customize]
    
    Subcommands:
        init         - Initialize website with basic structure
        status       - Show website statistics
        regenerate   - Full regeneration from personality config
        sync         - Sync content from self-memory
        customize    - Update theme settings (color, etc.)
        nginx        - Show nginx status
        nginx-reload - Reload nginx configuration
    """
    from runner.website_config import load_config, validate_config
    from runner.vps_website_tools import (
        website_init, website_get_stats, website_full_regenerate,
        website_sync_from_memory, website_generate_css_theme
    )
    from runner.nginx_configurator import nginx_get_status, nginx_reload
    
    parts = args.split(None, 1) if args else []
    subcommand = parts[0].lower() if parts else "status"
    subargs = parts[1] if len(parts) > 1 else ""
    
    try:
        if subcommand == "init":
            # Initialize basic website structure
            result = website_init()
            data = json.loads(result)
            
            if data.get("success"):
                files = data.get("created_files", [])
                return f"🌐 **Website initialized!**\n\nCreated {len(files)} files:\n" + "\n".join([f"  • {f}" for f in files])
            else:
                return f"❌ **Initialization failed:** {data.get('error', 'Unknown error')}"
        
        elif subcommand == "status":
            # Show website stats
            result = website_get_stats()
            data = json.loads(result)
            
            if data.get("success"):
                stats = data.get("stats", {})
                return f"""🌐 **Website Status**

**Files:** {stats.get('total_files', 0)} total
**Posts:** {stats.get('posts', 0)}
**Knowledge pages:** {stats.get('knowledge_pages', 0)}
**Projects:** {stats.get('projects', 0)}

**Domain:** {stats.get('domain', 'Not configured')}
**Base path:** `{stats.get('base_path', 'Not configured')}`"""
            else:
                return f"❌ **Status check failed:** {data.get('error', 'Unknown error')}"
        
        elif subcommand == "regenerate" or subcommand == "regen":
            # Full regeneration
            await message.channel.send("🔄 Regenerating website from personality config and memory... (this may take a moment)")
            
            result = website_full_regenerate()
            data = json.loads(result)
            
            if data.get("success"):
                results = data.get("results", {})
                pages = results.get("pages_regenerated", [])
                errors = results.get("errors", [])
                
                response = f"🌐 **Website regenerated!**\n\n"
                response += f"**Pages updated:** {len(pages)}\n"
                if pages:
                    response += "\n".join([f"  • {p}" for p in pages[:10]])
                    if len(pages) > 10:
                        response += f"\n  ... and {len(pages) - 10} more"
                
                if errors:
                    response += f"\n\n⚠️ **Warnings:**\n" + "\n".join([f"  • {e}" for e in errors])
                
                return response
            else:
                return f"❌ **Regeneration failed:** {data.get('error', 'Unknown error')}"
        
        elif subcommand == "sync":
            # Sync from memory
            await message.channel.send("🔄 Syncing website content from memory...")
            
            result = website_sync_from_memory()
            data = json.loads(result)
            
            if data.get("success"):
                counts = data.get("memory_counts", {})
                pages = data.get("pages_created", [])
                
                response = f"🧠 **Memory synced to website!**\n\n"
                response += f"**Items synced:**\n"
                response += f"  • Reflections: {counts.get('reflections', 0)}\n"
                response += f"  • Interests: {counts.get('interests', 0)}\n"
                response += f"  • Goals: {counts.get('goals', 0)}\n"
                response += f"  • Facts: {counts.get('facts', 0)}\n\n"
                response += f"**Pages created/updated:** {len(pages)}"
                
                return response
            else:
                return f"❌ **Sync failed:** {data.get('error', 'Unknown error')}"
        
        elif subcommand == "customize":
            # Update theme/customization
            if not subargs:
                # Show current config
                try:
                    config = load_config()
                    valid, errors = validate_config(config)
                    
                    theme = config.theme
                    return f"""🎨 **Current Website Theme**

**Site:** {config.site_name}
**Domain:** {config.domain}

**Colors:**
  • Primary: {theme.primary_color}
  • Secondary: {theme.secondary_color}
  • Accent: {theme.accent_color}

**Sections enabled:**
  • Reflections: {config.sections.show_reflections}
  • Interests: {config.sections.show_interests}
  • Goals: {config.sections.show_goals}
  • Knowledge: {config.sections.show_knowledge}

To customize, edit `custom_website_config.json` and run `!website regenerate`"""
                except Exception as e:
                    return f"❌ **Could not load config:** {str(e)}"
            else:
                # Quick color customization
                # Parse "color #hex" format
                color_parts = subargs.split()
                if len(color_parts) >= 2 and color_parts[0] in ["primary", "secondary", "accent", "background"]:
                    color_name = color_parts[0]
                    color_value = color_parts[1]
                    
                    return (
                        f"🎨 **Theme customization**\n\n"
                        f"To change the {color_name} color to {color_value}:\n\n"
                        f"1. Edit `custom_website_config.json`\n"
                        f"2. Find `theme.{color_name}_color` and change it to `{color_value}`\n"
                        f"3. Run `!website regenerate`"
                    )
                else:
                    return "🎨 **Customization help**\n\nTo customize your website:\n\n1. Edit `custom_website_config.json`\n2. Modify colors, sections, or content\n3. Run `!website regenerate`\n\n**Quick color commands:**\n• `!website customize primary #5b8c85`\n• `!website customize accent #e74c3c`"
        
        elif subcommand == "nginx":
            # Show nginx status
            result = nginx_get_status()
            data = json.loads(result)
            
            if data.get("success"):
                return f"""🌐 **Nginx Status**

**Running:** {'✅ Yes' if data.get('running') else '❌ No'}
**Version:** {data.get('version', 'Unknown')}
**Sites enabled:** {data.get('sites_enabled', 0)}
**Sites available:** {data.get('sites_available', 0)}

**Directories:**
  • Available: `{data.get('sites_available_dir', 'N/A')}`
  • Enabled: `{data.get('sites_enabled_dir', 'N/A')}`"""
            else:
                return f"❌ **Nginx status check failed:** {data.get('error', 'Unknown error')}"
        
        elif subcommand == "nginx-reload":
            # Reload nginx
            result = nginx_reload()
            data = json.loads(result)
            
            if data.get("success") and data.get("reloaded"):
                return "🌐 **Nginx reloaded successfully!**"
            else:
                error = data.get("error", "Unknown error")
                return f"❌ **Nginx reload failed:** {error}"
        
        elif subcommand == "theme":
            # Regenerate CSS theme only
            result = website_generate_css_theme()
            data = json.loads(result)
            
            if data.get("success"):
                theme = data.get("theme", {})
                return f"""🎨 **CSS Theme regenerated!**

**Colors:**
  • Primary: {theme.get('primary_color', 'N/A')}
  • Secondary: {theme.get('secondary_color', 'N/A')}
  • Accent: {theme.get('accent_color', 'N/A')}

Path: `{data.get('path', 'css/style.css')}`"""
            else:
                return f"❌ **Theme generation failed:** {data.get('error', 'Unknown error')}"
        
        else:
            return f"""🌐 **Website Commands**

`!website init` - Initialize website structure
`!website status` - Show website statistics
`!website regenerate` - Full regeneration from config/memory
`!website sync` - Sync content from self-memory
`!website customize` - Show current theme settings
`!website theme` - Regenerate CSS theme
`!website nginx` - Show nginx status
`!website nginx-reload` - Reload nginx

**Quick start:**
1. Run `!website init` to create basic structure
2. Run `!website regenerate` to generate full site
3. Your website will be at the configured domain"""
    
    except Exception as e:
        logger.exception("Website command failed")
        return f"❌ **Website command error:** {str(e)}"


async def handle_website_post_command(bot, message, args: str):
    """
    Handle 'website_post' command - Create a blog post.
    
    Usage: website_post "Title" "Content text..." [category]
    """
    from runner.vps_website_tools import website_create_post
    
    if not args or '"' not in args:
        return """📝 **Create a Blog Post**

Usage: `!website_post "Title" "Your post content here..."`

Example:
`!website_post "My First Reflection" "Today I learned something amazing about consciousness..." philosophy`

The post will be published immediately to your website!"""
    
    try:
        # Parse quoted arguments
        import shlex
        try:
            parsed = shlex.split(args)
        except ValueError:
            # Fallback for unclosed quotes
            parsed = args.split('"')
            parsed = [p.strip() for p in parsed if p.strip()]
        
        if len(parsed) < 2:
            return "❌ **Error:** Please provide both title and content in quotes.\n\nExample: `!website_post \"Title\" \"Content...\"`"
        
        title = parsed[0]
        content = parsed[1]
        category = parsed[2] if len(parsed) > 2 else "general"
        
        await message.channel.send(f"📝 Creating post: **{title}**...")
        
        result = website_create_post(title, content, category)
        data = json.loads(result)
        
        if data.get("success"):
            return f"""📝 **Post published!**

**Title:** {data.get('message', title)}
**URL:** {data.get('url', 'N/A')}
**Path:** `{data.get('path', 'N/A')}`"""
        else:
            return f"❌ **Post creation failed:** {data.get('error', 'Unknown error')}"
    
    except Exception as e:
        logger.exception("Website post command failed")
        return f"❌ **Error:** {str(e)}"
