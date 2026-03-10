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
from typing import Optional, Dict, Callable, List
from dataclasses import dataclass
import logging

# Import our modules
from .memory import get_memory
from .personality import get_personality_engine

logger = logging.getLogger(__name__)


def format_thinking_as_spoilers(text: str) -> str:
    """
    Wrap thinking sections in Discord spoiler tags (||).
    This hides reasoning content behind a clickable black bar.
    Handles multiple formats: XML-style tags, markdown code blocks with unicode headers.
    """
    import re

    # Pattern 1: XML-style <thinking>...</thinking> tags (with or without attributes)
    xml_pattern = r'<thinking[^>]*>(.*?)</thinking>'

    # Pattern 2: Markdown code blocks with unicode "𝕥𝕙𝕚𝕟𝕜𝕚𝕟𝕘" header
    # Matches: ```\n𝕥𝕙𝕚𝕟𝕜𝕚𝕟𝕘\n...content...\n```
    unicode_pattern = r'```\n𝕥𝕙𝕚𝕟𝕜𝕚𝕟𝕘\n(.*?)\n```'

    # Pattern 3: Plain text blocks starting with "thinking" or "𝕥𝕙𝕚𝕟𝕜𝕚𝕟𝕘" followed by newline
    plain_pattern = r'^(𝕥𝕙𝕚𝕟𝕜𝕚𝕟𝕘|thinking)[ \t]*\n(.*?)(?=\n\n|\Z)'

    def wrap_in_spoilers(match):
        content = match.group(1).strip() if len(match.groups()) > 0 else match.group(0).strip()
        if not content or content.lower() in ('thinking', '𝕥𝕙𝕚𝕟𝕜𝕚𝕟𝕘'):
            return ""
        # Wrap in Discord spoiler syntax - adds a label to indicate it's reasoning
        return f"||🧠 *thinking*: {content}||"

    # Apply all patterns
    result = re.sub(xml_pattern, wrap_in_spoilers, text, flags=re.DOTALL | re.IGNORECASE)
    result = re.sub(unicode_pattern, wrap_in_spoilers, result, flags=re.DOTALL | re.IGNORECASE)
    result = re.sub(plain_pattern, wrap_in_spoilers, result, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)

    return result


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
    
    def _get_conversation_id(self, channel_id: str, user_id: str, 
                              conversation_id: str = None) -> str:
        """
        Get or generate conversation ID.
        
        If conversation_id is provided, use it (for resuming specific conversations).
        Otherwise, get the user's active conversation or create a new one.
        """
        if conversation_id:
            return conversation_id
        
        # Try to get user's active conversation
        active_conv = self.memory.get_active_conversation(user_id)
        if active_conv:
            # Verify this conversation is for the same channel
            convs = self.memory.get_user_conversations(user_id, channel_id, limit=1)
            if convs and convs[0]['conversation_id'] == active_conv:
                return active_conv
        
        # Create new conversation ID
        return f"{channel_id}_{user_id}_{int(time.time())}"
    
    def _get_or_create_session(self, user_id: str, channel_id: str,
                               persona_key: Optional[str] = None,
                               conversation_id: str = None,
                               resume_conversation: bool = True) -> ChatSession:
        """
        Get existing session or create new one.
        
        Args:
            user_id: Discord user ID
            channel_id: Discord channel ID
            persona_key: Personality to use
            conversation_id: Specific conversation to resume (optional)
            resume_conversation: Whether to auto-resume last conversation
        """
        # Determine conversation ID
        if conversation_id:
            target_conv_id = conversation_id
        elif resume_conversation:
            # Try to resume active conversation
            target_conv_id = self._get_conversation_id(channel_id, user_id)
        else:
            # Create new conversation
            target_conv_id = f"{channel_id}_{user_id}_{int(time.time())}"
        
        # Check for existing session in memory
        if target_conv_id in self.sessions:
            session = self.sessions[target_conv_id]
            
            # Check if timed out
            if time.time() - session.last_activity > self.session_timeout:
                logger.info(f"Session {target_conv_id} timed out, will refresh")
                self._end_session(target_conv_id)
            else:
                # Update activity
                session.last_activity = time.time()
                # Ensure this is set as active
                self.memory.set_active_conversation(user_id, target_conv_id, channel_id)
                return session
        
        # Check if conversation exists in database
        convs = self.memory.get_user_conversations(user_id, channel_id=channel_id, limit=10)
        existing_conv = None
        for conv in convs:
            if conv['conversation_id'] == target_conv_id:
                existing_conv = conv
                break
        
        # If not found, create new conversation in database
        if not existing_conv:
            self.memory.create_conversation(
                conversation_id=target_conv_id,
                channel_id=channel_id,
                user_id=user_id,
                title=f"Conversation with user {user_id[:8]}...",
                topic=None,
                is_group=False
            )
            logger.info(f"Created new conversation in database: {target_conv_id}")
        else:
            # Resume existing conversation
            logger.info(f"Resuming conversation: {target_conv_id} "
                       f"(messages: {existing_conv.get('message_count', 0)})")
        
        # Set as active conversation
        self.memory.set_active_conversation(user_id, target_conv_id, channel_id)
        
        # Get persona
        if persona_key is None:
            settings = self.memory.get_user_settings(user_id)
            preferred = settings.get('preferred_persona')
            if preferred is None or preferred == 'default':
                persona_key = self.personality.default_persona
            else:
                persona_key = preferred
        
        # Create new session
        session = ChatSession(
            user_id=user_id,
            channel_id=channel_id,
            conversation_id=target_conv_id,
            persona_key=persona_key,
            started_at=time.time(),
            last_activity=time.time(),
            message_count=existing_conv.get('message_count', 0) if existing_conv else 0
        )
        
        self.sessions[target_conv_id] = session
        logger.info(f"Created/Resumed chat session: {target_conv_id} with persona {persona_key}")
        
        return session
    
    def switch_conversation(self, user_id: str, channel_id: str, 
                           conversation_id: str = None) -> Optional[ChatSession]:
        """
        Switch to a different conversation.
        
        Args:
            user_id: Discord user ID
            channel_id: Discord channel ID
            conversation_id: Specific conversation ID to switch to, or None to create new
            
        Returns:
            The new session, or None if switch failed
        """
        # End current session if exists
        current_conv = self.memory.get_active_conversation(user_id)
        if current_conv and current_conv in self.sessions:
            self._end_session(current_conv)
        
        # If no conversation_id specified, create a new conversation
        if conversation_id is None:
            conversation_id = f"{channel_id}_{user_id}_{int(time.time())}"
            self.memory.create_conversation(
                conversation_id=conversation_id,
                channel_id=channel_id,
                user_id=user_id,
                title=f"New conversation {int(time.time()) % 10000}"
            )
        else:
            # Verify user has access to this conversation
            convs = self.memory.get_user_conversations(user_id, limit=100)
            conv_ids = [c['conversation_id'] for c in convs]
            if conversation_id not in conv_ids:
                logger.warning(f"User {user_id} tried to access unauthorized conversation {conversation_id}")
                return None
        
        # Create new session with the target conversation
        return self._get_or_create_session(
            user_id=user_id,
            channel_id=channel_id,
            conversation_id=conversation_id,
            resume_conversation=False
        )
    
    def get_user_conversations_list(self, user_id: str, channel_id: str = None) -> List[Dict]:
        """Get formatted list of user's conversations."""
        convs = self.memory.get_user_conversations(user_id, channel_id, limit=20)
        active_conv = self.memory.get_active_conversation(user_id)
        
        result = []
        for conv in convs:
            # Format timestamp
            last_activity = conv['last_activity']
            if isinstance(last_activity, (int, float)):
                from datetime import datetime
                dt = datetime.fromtimestamp(last_activity)
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = "Unknown"
            
            result.append({
                'id': conv['conversation_id'][:20] + "...",
                'full_id': conv['conversation_id'],
                'title': conv['title'] or "Untitled",
                'topic': conv['topic'],
                'messages': conv['message_count'],
                'participants': conv['participant_count'],
                'last_activity': time_str,
                'is_active': conv['conversation_id'] == active_conv,
                'is_group': conv['is_group']
            })
        
        return result
    
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
        # Note: fact_type must be one of: 'preference', 'fact', 'task', 'constraint', 'topic'
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
                    # Use 'preference' type with descriptive content
                    fact_type = "preference"
                    content = f"Favorite {match.group(1)}: {match.group(2).strip()}"
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
                    facts.append(("fact", f"Location: {location}"))
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
                    facts.append(("fact", f"Name: {name}"))
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
                facts.append(("fact", f"Occupation: {job}"))
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
                    facts.append(("fact", f"Has: {item}"))
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
                    facts.append(("fact", f"Age: {match.group(1)} years old"))
                else:
                    facts.append(("fact", f"Birth year: {match.group(1)}"))
                break
        
        # Limit to first 2 facts to avoid over-extracting
        if facts:
            logger.debug(f"Extracted {len(facts)} obvious facts from message: {facts}")
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
                                  reply_func,
                                  intent_result=None,
                                  enable_tools: bool = False) -> str:
        """
        Handle a chat message and generate response.

        Args:
            message_content: The message text
            user_id: Discord user ID
            channel_id: Discord channel ID
            username: User's display name
            reply_func: Async function to send reply
            intent_result: Optional IntentResult from natural language router
            enable_tools: Whether to enable tool usage for this message

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
            knowledge_lines = ["\n=== STORED USER KNOWLEDGE ==="]
            knowledge_lines.append("The following facts about this user were learned from previous conversations.")
            knowledge_lines.append("USE these facts naturally when answering questions about the user:")
            knowledge_lines.append("")

            for fact in context['user_knowledge']:
                # Format fact more explicitly based on content structure
                content = fact.content.strip()
                fact_type = fact.fact_type.lower()

                # If content already contains descriptive text like "Favorite color: orange",
                # format it to be more natural and actionable
                if ':' in content:
                    # Content is like "Favorite color: orange" - make it clearer
                    knowledge_lines.append(f"  • {content}")
                else:
                    # Content is plain - prepend the fact type
                    knowledge_lines.append(f"  • {fact_type}: {content}")

            knowledge_lines.append("")
            knowledge_lines.append("When asked about any of these topics, reference these facts confidently.")

            knowledge_text = "\n".join(knowledge_lines)
            system_prompt += knowledge_text
            logger.info(f"Added {len(context['user_knowledge'])} facts to system prompt for user {user_id[:8]}...")
            for fact in context['user_knowledge'][:3]:
                logger.debug(f"  Knowledge: {fact.fact_type} = {fact.content[:50]}...")
        else:
            logger.debug(f"No user knowledge found for user {user_id[:8]}...")

        # Add tool awareness if enabled via intent detection
        if enable_tools and intent_result:
            tool_descriptions = self._get_tool_descriptions_for_intent(intent_result.intent)
            if tool_descriptions:
                system_prompt += f"\n\n=== AVAILABLE TOOLS ===\n"
                system_prompt += f"You have access to these tools for this request:\n{tool_descriptions}\n"
                system_prompt += f"\nWhen the user's request requires information or actions beyond your knowledge, "
                system_prompt += f"use the appropriate tool. The tool results will be provided to help you respond."
                logger.info(f"Enabled tools for intent '{intent_result.intent}': {intent_result.suggested_tools}")

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
        
        # Store user message in memory (async version to avoid blocking)
        await self.memory.add_message_async(
            session.conversation_id,
            user_id,
            "user",
            message_content,
            metadata={"username": username}
        )
        
        # Extract and store obvious facts immediately (don't wait for background)
        immediate_facts = self._extract_obvious_facts(message_content)
        if immediate_facts:
            logger.info(f"Extracted {len(immediate_facts)} immediate facts from message for user {user_id[:8]}...")
            for fact_type, content in immediate_facts:
                try:
                    self.memory.add_user_fact(user_id, fact_type, content, confidence=0.9)
                    logger.info(f"Immediate memory: Stored {fact_type}='{content}' for user {user_id[:8]}...")
                except Exception as e:
                    logger.warning(f"Failed to store immediate fact: {e}")
        else:
            logger.debug(f"No obvious facts extracted from message for user {user_id[:8]}...")
        
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
            
            # Store assistant response in memory (async version to avoid blocking)
            await self.memory.add_message_async(
                session.conversation_id,
                user_id,
                "assistant",
                response
            )
            
            # Update session
            session.message_count += 1
            session.last_activity = time.time()
            self.personality.increment_turn(user_id)
            
            # Update conversation activity in database
            self.memory.update_conversation_activity(session.conversation_id)
            
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
            full_system = system_msgs[0].get("content", "")
            has_knowledge = "User information:" in full_system
            logger.info(f"Sending to LLM with persona {session.persona_key}, system prompt starts: {first_system}...")
            logger.info(f"System prompt contains user knowledge: {has_knowledge} (length: {len(full_system)} chars)")
            if has_knowledge:
                # Extract and log the knowledge section
                knowledge_start = full_system.find("User information:")
                knowledge_section = full_system[knowledge_start:knowledge_start+200]
                logger.info(f"Knowledge section: {knowledge_section}...")
        else:
            logger.warning(f"No system message in conversation! Persona: {session.persona_key}")

        # Build the payload for llm_task
        # Don't explicitly request tools - let the runner use its configured LLM_ALLOWED_TOOLS
        # This avoids "tools must be subset of LLM_ALLOWED_TOOLS" errors when the runner
        # hasn't been configured with website tools in its environment
        payload_obj = {
            "prompt": current_prompt,
            "conversation_history": [
                {"role": m["role"], "content": m["content"]}
                for m in context_messages
            ],
            "persona": session.persona_key,
            "temperature": voice_settings.get("temperature", 0.7),
            "max_tokens": voice_settings.get("max_tokens", 2000),
            # Note: omitting "tools" - runner will use its configured allowed_tools
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
                            return format_thinking_as_spoilers(parsed.get("final", result))
                    except json.JSONDecodeError:
                        pass
                    return format_thinking_as_spoilers(result)
                    
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
    
    async def handle_conversations_command(self, user_id: str,
                                            channel_id: str,
                                            subcommand: str = None,
                                            args: str = "") -> str:
        """
        Handle conversation management commands.
        
        Subcommands:
        - (none): List all conversations
        - new [title]: Create new conversation
        - switch <conversation_id>: Switch to a conversation
        - rename <title>: Rename current conversation
        - archive <conversation_id>: Archive a conversation
        """
        if subcommand is None or subcommand == "list":
            # List all conversations
            convs = self.get_user_conversations_list(user_id, channel_id)
            
            if not convs:
                return "📭 **No conversations yet.**\nStart chatting to create your first conversation!"
            
            lines = [f"📋 **Your Conversations** ({len(convs)} total):\n"]
            
            for i, conv in enumerate(convs[:10], 1):  # Show top 10
                active_marker = "✅ " if conv['is_active'] else "   "
                group_marker = "👥" if conv['is_group'] else "👤"
                lines.append(
                    f"{active_marker}{i}. **{conv['title']}** {group_marker}\n"
                    f"   🆔 `{conv['id']}`\n"
                    f"   💬 {conv['messages']} messages | 🕐 {conv['last_activity']}\n"
                )
            
            lines.append("\n💡 **Commands:**")
            lines.append("`conversations new [title]` - Start new conversation")
            lines.append("`conversations switch <number>` - Switch to conversation")
            lines.append("`conversations rename <title>` - Rename current")
            
            return "\n".join(lines)
        
        elif subcommand == "new":
            # Create new conversation
            title = args.strip() if args else f"Conversation {int(time.time()) % 10000}"
            
            # End current session
            current_conv = self.memory.get_active_conversation(user_id)
            if current_conv and current_conv in self.sessions:
                self._end_session(current_conv)
            
            # Create new conversation
            new_conv_id = f"{channel_id}_{user_id}_{int(time.time())}"
            self.memory.create_conversation(
                conversation_id=new_conv_id,
                channel_id=channel_id,
                user_id=user_id,
                title=title,
                is_group=False
            )
            
            # Set as active
            self.memory.set_active_conversation(user_id, new_conv_id, channel_id)
            
            return f"✅ **Created new conversation:** *{title}*\n" \
                   f"🆔 `{new_conv_id[:20]}...`\n" \
                   f"\n💡 Use `conversations` to see all your conversations."
        
        elif subcommand == "switch":
            if not args:
                return "❌ Please specify a conversation number or ID.\n" \
                       "Usage: `conversations switch <number>` or `conversations switch <id>`"
            
            # Get user's conversations to resolve number or ID
            convs = self.get_user_conversations_list(user_id, channel_id)
            
            # Try to parse as number first
            try:
                conv_num = int(args.strip())
                if 1 <= conv_num <= len(convs):
                    target_conv_id = convs[conv_num - 1]['full_id']
                    target_title = convs[conv_num - 1]['title']
                else:
                    return f"❌ Invalid conversation number. You have {len(convs)} conversations."
            except ValueError:
                # Try to find by partial ID match
                search = args.strip().lower()
                matching = [c for c in convs if search in c['full_id'].lower()]
                if len(matching) == 1:
                    target_conv_id = matching[0]['full_id']
                    target_title = matching[0]['title']
                elif len(matching) > 1:
                    return f"❌ Multiple conversations match '{args}'. Please be more specific."
                else:
                    return f"❌ No conversation found matching '{args}'. Use `conversations` to see available."
            
            # Switch to the conversation
            new_session = self.switch_conversation(user_id, channel_id, target_conv_id)
            
            if new_session:
                msg_count = new_session.message_count
                return f"✅ **Switched to:** *{target_title}*\n" \
                       f"💬 {msg_count} previous messages in this conversation\n" \
                       f"🆔 `{target_conv_id[:20]}...`"
            else:
                return "❌ Could not switch to that conversation."
        
        elif subcommand == "rename":
            if not args:
                return "❌ Please provide a new title.\nUsage: `conversations rename <new title>`"
            
            current_conv = self.memory.get_active_conversation(user_id)
            if not current_conv:
                return "❌ No active conversation to rename."
            
            new_title = args.strip()
            self.memory.rename_conversation(current_conv, new_title)
            
            return f"✅ **Renamed conversation to:** *{new_title}*"
        
        elif subcommand == "archive":
            if not args:
                return "❌ Please specify a conversation number or ID to archive."
            
            # Resolve conversation
            convs = self.get_user_conversations_list(user_id, channel_id)
            try:
                conv_num = int(args.strip())
                if 1 <= conv_num <= len(convs):
                    target_conv_id = convs[conv_num - 1]['full_id']
                    target_title = convs[conv_num - 1]['title']
                else:
                    return f"❌ Invalid conversation number."
            except ValueError:
                target_conv_id = args.strip()
                target_title = target_conv_id[:20] + "..."
            
            # Check if trying to archive active conversation
            current_conv = self.memory.get_active_conversation(user_id)
            if current_conv == target_conv_id:
                return "⚠️ Cannot archive your active conversation. Switch to another first."
            
            self.memory.archive_conversation(target_conv_id)
            return f"📦 **Archived:** *{target_title}*\nThis conversation is now hidden but preserved."
        
        elif subcommand == "resume":
            # Resume the most recent conversation
            convs = self.memory.get_user_conversations(user_id, channel_id, limit=1)
            if not convs:
                return "📭 No conversations to resume. Start a new one with `conversations new`."
            
            target_conv_id = convs[0]['conversation_id']
            target_title = convs[0]['title'] or "Untitled"
            
            # Check if already active
            current_conv = self.memory.get_active_conversation(user_id)
            if current_conv == target_conv_id:
                return f"✅ You're already in: *{target_title}*"
            
            new_session = self.switch_conversation(user_id, channel_id, target_conv_id)
            if new_session:
                return f"✅ **Resumed:** *{target_title}*\n" \
                       f"💬 {new_session.message_count} messages in this conversation"
            else:
                return "❌ Could not resume conversation."
        
        else:
            return f"❌ Unknown command: `{subcommand}`.\n" \
                   f"Available: `list`, `new`, `switch`, `rename`, `archive`, `resume`"
    
    async def handle_history_command(self, user_id: str,
                                     channel_id: str,
                                     limit: int = 10) -> str:
        """Show recent conversation history."""
        # Get the active conversation
        conversation_id = self.memory.get_active_conversation(user_id)
        
        if not conversation_id:
            # Fall back to creating a conversation ID if none active
            conversation_id = f"{channel_id}_{user_id}_{int(time.time())}"
        
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

    def _get_tool_descriptions_for_intent(self, intent: str) -> str:
        """
        Get human-readable tool descriptions for a given intent.

        Args:
            intent: The detected intent category

        Returns:
            String describing available tools for this intent
        """
        tool_descriptions = {
            "repo_explore": """- repo_list: List all available repositories
- repo_status: Get repository git status (branch, uncommitted changes)
- repo_last_commit: Show the most recent commit information""",

            "repo_search": """- repo_grep: Search for text patterns across all files in a repository
  Parameters: repo (required), query (required), path (optional)
  Example: repo="openclaw-broker", query="authentication", path="src/"""",

            "file_read": """- repo_readfile: Read the content of a specific file
  Parameters: repo (required), path (required), start/end line numbers (optional)
  Example: repo="openclaw-broker", path="main.py", start=1, end=50""",

            "github_ops": """- github_list_repos: List user's GitHub repositories
- github_list_issues: List issues in a GitHub repository
- github_create_issue: Create a new issue in a GitHub repository
  Parameters: repo (required), title (required), body (optional)""",

            "web_research": """- browser_navigate: Visit a specific URL
- browser_search: Search the web using a search engine
- browser_extract_article: Extract article content from a webpage
- browser_snapshot: Get the current page content and structure""",

            "website_manage": """- website_get_stats: Get website statistics
- website_create_post: Create a blog post
- website_sync_from_memory: Sync website content from memory
- nginx_get_status: Check nginx status""",
        }

        return tool_descriptions.get(intent, "")


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

async def handle_chat_command(bot, message, args: str, intent_result=None, enable_tools: bool = False):
    """
    Handle 'chat' command - conversational mode with memory.

    Usage: chat <message>

    Args:
        bot: The bot instance
        message: The Discord message
        args: The message content/text
        intent_result: Optional IntentResult from natural language routing
        enable_tools: Whether to enable tool descriptions in system prompt
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
        reply_func=reply_func,
        intent_result=intent_result,
        enable_tools=enable_tools
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


async def handle_conversations_command(bot, message, args: str):
    """
    Handle 'conversations' command - conversation management.
    
    Usage: conversations [list|new|switch|rename|archive|resume]
    
    Subcommands:
        list (default)     - Show all your conversations
        new [title]       - Create a new conversation
        switch <number>   - Switch to a different conversation
        rename <title>    - Rename the current conversation
        archive <number>  - Archive a conversation
        resume            - Resume your most recent conversation
    """
    broker_url = getattr(bot, 'broker_url', os.environ.get("BROKER_URL", "http://127.0.0.1:8000"))
    bot_token = getattr(bot, 'bot_token', os.environ.get("BOT_TOKEN", ""))
    
    manager = get_chat_manager(bot, broker_url, bot_token)
    
    parts = args.strip().split(None, 1) if args else []
    subcommand = parts[0].lower() if parts else None
    subargs = parts[1] if len(parts) > 1 else ""
    
    response = await manager.handle_conversations_command(
        str(message.author.id),
        str(message.channel.id),
        subcommand,
        subargs
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
