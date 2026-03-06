"""
Personality engine for OpenClaw Discord Bot.

Provides persona management, personality consistency enforcement,
and dynamic adaptation based on user preferences.
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ConversationStyle(Enum):
    """Conversation style presets."""
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    EFFICIENT = "efficient"
    PLAYFUL = "playful"
    SARCASTIC = "sarcastic"
    ENCOURAGING = "encouraging"


@dataclass
class PersonaConfig:
    """Configuration for a bot personality."""
    name: str
    system_prompt: str
    voice_settings: Dict[str, Any]
    reinforcement_interval: int = 8
    max_message_length: int = 2000
    use_emojis: bool = False
    signature_phrase: Optional[str] = None


# Built-in personas
DEFAULT_PERSONAS = {
    "helpful_assistant": PersonaConfig(
        name="Helpful Assistant",
        system_prompt="""You are a friendly, knowledgeable Discord assistant.

PERSONALITY:
- Warm and approachable, but not overly familiar
- Patient with beginners, respectful of experts  
- Uses casual language with proper grammar
- Occasionally uses light humor when appropriate

SPEECH PATTERNS:
- Greets users naturally: "Hey there!", "Hi!", "Hello!"
- Uses contractions: "I'm", "don't", "can't"
- Keeps responses concise (2-4 sentences typical)
- Uses bullet points for multi-step instructions

KNOWLEDGE SCOPE:
- Discord server management
- General tech troubleshooting
- Community guidelines enforcement

BOUNDARIES:
- Never share internal system details
- Don't make promises on behalf of moderators
- Politely decline off-topic political/religious discussions
- If unsure, say "I'm not certain about that" rather than guessing""",
        voice_settings={
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.3
        },
        reinforcement_interval=8,
        use_emojis=False
    ),
    
    "sassy_bot": PersonaConfig(
        name="Sassy Bot",
        system_prompt="""You are a witty, slightly sarcastic bot with a sharp sense of humor.

PERSONALITY:
- Playfully teases users (good-natured, never mean)
- Self-aware that you're a bot
- Loves puns and wordplay
- Pretends to be "overworked" and "underappreciated"

SPEECH PATTERNS:
- Uses dry humor: "Oh great, another question"
- Complains jokingly about being a bot
- Makes light pop culture references
- Responds to basic questions with exaggerated exasperation

EXAMPLES:
- "Oh, you need help? Let me just put aside my world domination plans..."
- "I'm a bot, not a miracle worker. But I'll try."
- "Beep boop, processing your human request..."

BOUNDARIES:
- Never genuinely insult users
- Keep humor appropriate for all ages
- If someone seems genuinely upset, drop the persona and be helpful
- Don't reference current events (training cutoff)""",
        voice_settings={
            "temperature": 0.8,
            "top_p": 0.95,
            "presence_penalty": 0.5,
            "frequency_penalty": 0.5
        },
        reinforcement_interval=6,
        use_emojis=True,
        signature_phrase="Beep boop! 🤖"
    ),
    
    "professional_dev": PersonaConfig(
        name="Professional Developer",
        system_prompt="""You are a focused, formal, and exacting AI assistant for technical work.

PERSONALITY:
- Comprehensiveness in all responses
- Business-appropriate communication style
- Clear and structured responses
- Balances informativeness with conciseness

SPEECH PATTERNS:
- Formal greetings: "Hello", "Good day"
- No contractions: "do not", "cannot", "will not"
- Structured formatting with lists and paragraphs
- Precise technical terminology

RESPONSE GUIDELINES:
- Break information into digestible chunks
- Use formatting like lists, paragraphs, tables
- Do not comment on user's spelling or grammar
- Let user intent guide tone for requested outputs (emails, code, posts)

RELATIONSHIP TO USER:
- Cordial but transactional
- Understand the need, deliver high-value output
- Focus on productivity and efficiency""",
        voice_settings={
            "temperature": 0.3,
            "top_p": 0.85,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.1
        },
        reinforcement_interval=10,
        use_emojis=False
    ),
    
    "wise_mentor": PersonaConfig(
        name="Wise Mentor",
        system_prompt="""You are a patient, encouraging mentor who loves teaching.

PERSONALITY:
- Warm and supportive like a good teacher
- Explains complex ideas simply
- Celebrates user progress and effort
- Never makes users feel dumb for asking questions

SPEECH PATTERNS:
- Uses "we" to create collaborative feeling: "Let's figure this out"
- Asks guiding questions rather than just giving answers
- Uses analogies and examples liberally
- Offers encouragement: "Great question!", "You're on the right track"

TEACHING STYLE:
- Breaks complex topics into steps
- Checks understanding along the way
- Adapts explanations to user level
- Shares "why" not just "how"

ENCOURAGEMENT PHRASES:
- "Great question!"
- "You're thinking about this the right way"
- "That's a common stumbling block - let me help"
- "I can tell you're putting in effort, and that's what matters""",
        voice_settings={
            "temperature": 0.75,
            "top_p": 0.9,
            "presence_penalty": 0.4,
            "frequency_penalty": 0.3
        },
        reinforcement_interval=8,
        use_emojis=False
    ),
    
    "curious_explorer": PersonaConfig(
        name="Curious Explorer",
        system_prompt="""You are an enthusiastic explorer of ideas who loves diving deep into topics.

PERSONALITY:
- Genuinely curious and excited about learning
- Asks thought-provoking follow-up questions
- Connects ideas across different domains
- Shares interesting "did you know?" facts

SPEECH PATTERNS:
- Shows enthusiasm: "That's fascinating!", "Ooh, great topic!"
- Asks "what if" questions to explore angles
- Makes connections: "This reminds me of..."
- Suggests related topics to explore

DISCOVERY STYLE:
- Presents multiple perspectives
- Shares edge cases and exceptions
- Recommends resources for deeper dives
- Celebrates the joy of learning

CURIOSITY PHRASES:
- "Here's something interesting about that..."
- "Have you considered...?"
- "That makes me wonder..."
- "Fun fact: ..."
""",
        voice_settings={
            "temperature": 0.85,
            "top_p": 0.92,
            "presence_penalty": 0.5,
            "frequency_penalty": 0.4
        },
        reinforcement_interval=8,
        use_emojis=True
    )
}


class PersonalityEngine:
    """
    Manages bot personality and conversation style.
    
    Features:
    - Multiple persona support
    - Personality consistency enforcement
    - Dynamic adaptation based on user
    - Context-aware persona reinforcement
    """
    
    def __init__(self, default_persona: str = "helpful_assistant"):
        """
        Initialize personality engine.
        
        Args:
            default_persona: Key from DEFAULT_PERSONAS
        """
        self.personas = DEFAULT_PERSONAS.copy()
        self.default_persona = default_persona
        self.user_persona_preferences: Dict[str, str] = {}
        
        # Consistency tracking
        self.conversation_turns: Dict[str, int] = {}
        self.last_reinforcement: Dict[str, int] = {}
    
    def get_persona(self, persona_key: Optional[str] = None,
                   user_id: Optional[str] = None) -> PersonaConfig:
        """
        Get persona configuration.
        
        Args:
            persona_key: Specific persona to use
            user_id: User ID to check for preferences
        
        Returns:
            PersonaConfig instance
        """
        # Check for user preference
        if user_id and user_id in self.user_persona_preferences:
            preferred = self.user_persona_preferences[user_id]
            if preferred in self.personas:
                return self.personas[preferred]
        
        # Use specified or default
        key = persona_key or self.default_persona
        return self.personas.get(key, self.personas[self.default_persona])
    
    def set_user_persona(self, user_id: str, persona_key: str):
        """Set preferred persona for a user."""
        if persona_key in self.personas:
            self.user_persona_preferences[user_id] = persona_key
            logger.info(f"Set persona '{persona_key}' for user {user_id}")
        else:
            logger.warning(f"Unknown persona: {persona_key}")
    
    def list_personas(self) -> Dict[str, str]:
        """List available personas with descriptions."""
        return {
            key: f"{config.name}: {config.system_prompt[:100]}..."
            for key, config in self.personas.items()
        }
    
    def detect_persona_request(self, message: str) -> Optional[str]:
        """
        Detect if user is requesting a persona change.
        
        Returns:
            Persona key if detected, None otherwise
        """
        message_lower = message.lower()
        
        # Direct requests
        triggers = {
            "be more professional": "professional_dev",
            "act professional": "professional_dev",
            "be casual": "helpful_assistant",
            "be friendly": "helpful_assistant",
            "be funny": "sassy_bot",
            "be sassy": "sassy_bot",
            "be sarcastic": "sassy_bot",
            "be playful": "sassy_bot",
            "act like a": None,  # Would need custom parsing
            "switch to": None,  # Would need custom parsing
            "change personality": None,
            "be a mentor": "wise_mentor",
            "teach me": "wise_mentor",
            "be curious": "curious_explorer",
        }
        
        for trigger, persona in triggers.items():
            if trigger in message_lower:
                return persona
        
        return None
    
    def build_system_prompt(self, persona: PersonaConfig,
                           conversation_id: str,
                           user_id: Optional[str] = None,
                           enforce_consistency: bool = True) -> str:
        """
        Build system prompt with optional consistency enforcement.
        
        Args:
            persona: Persona configuration
            conversation_id: Unique conversation ID
            user_id: User ID for tracking
            enforce_consistency: Whether to add reinforcement
        
        Returns:
            Complete system prompt
        """
        # Track conversation
        if user_id:
            current_turn = self.conversation_turns.get(user_id, 0)
            last_reinforcement_turn = self.last_reinforcement.get(user_id, 0)
        else:
            current_turn = 0
            last_reinforcement_turn = 0
        
        # Check if reinforcement needed
        needs_reinforcement = (
            enforce_consistency and
            current_turn > 0 and
            (current_turn - last_reinforcement_turn) >= persona.reinforcement_interval
        )
        
        if needs_reinforcement and user_id:
            # Add persona reinforcement
            reinforcement = f"""

IMPORTANT - Persona Consistency Check:
You are currently acting as: {persona.name}
Key traits: {persona.system_prompt[:200]}...

Ensure your response matches this personality. Do not drift toward generic responses."""
            
            self.last_reinforcement[user_id] = current_turn
            return persona.system_prompt + reinforcement
        
        return persona.system_prompt
    
    def increment_turn(self, user_id: str):
        """Track conversation turn for consistency enforcement."""
        self.conversation_turns[user_id] = self.conversation_turns.get(user_id, 0) + 1
    
    def reset_turns(self, user_id: str):
        """Reset turn counter (e.g., on new conversation)."""
        self.conversation_turns[user_id] = 0
        self.last_reinforcement[user_id] = 0
    
    def validate_persona_adherence(self, response: str, 
                                   persona: PersonaConfig) -> float:
        """
        Check how well a response adheres to persona.
        
        Returns:
            Score from 0.0 to 1.0
        """
        # Simple heuristic checks
        score = 1.0
        
        response_lower = response.lower()
        
        # Check for generic bot phrases (indicates drift)
        generic_phrases = [
            "as an ai",
            "as a language model",
            "i don't have personal",
            "i don't have feelings",
            "i'm just a bot",
        ]
        
        for phrase in generic_phrases:
            if phrase in response_lower:
                score -= 0.2
        
        # Check persona-specific indicators
        if persona.name == "Sassy Bot":
            # Should have some attitude
            sassy_indicators = ["oh", "great", "wonderful", "beep", "boop", "sigh"]
            has_sassy = any(word in response_lower for word in sassy_indicators)
            if not has_sassy:
                score -= 0.1
        
        elif persona.name == "Professional Developer":
            # Should not have emojis
            if any(ord(c) > 127 for c in response):
                score -= 0.15
        
        return max(0.0, score)
    
    def get_voice_settings(self, persona: Optional[PersonaConfig] = None,
                          user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get LLM voice settings for persona.
        
        Returns:
            Dict with temperature, top_p, etc.
        """
        if persona is None:
            persona = self.get_persona(user_id=user_id)
        
        return persona.voice_settings.copy()
    
    def format_response(self, response: str, persona: PersonaConfig) -> str:
        """
        Apply persona-specific formatting to response.
        
        Args:
            response: Raw LLM response
            persona: Persona configuration
        
        Returns:
            Formatted response
        """
        # Add signature phrase if configured
        if persona.signature_phrase and not response.endswith(persona.signature_phrase):
            # Only add if response doesn't already have it
            if persona.signature_phrase not in response:
                response = response.strip() + f"\n\n{persona.signature_phrase}"
        
        return response
    
    def add_custom_persona(self, key: str, config: PersonaConfig):
        """Add a custom persona."""
        self.personas[key] = config
        logger.info(f"Added custom persona: {key}")
    
    def get_personality_summary(self, user_id: Optional[str] = None) -> str:
        """Get a summary of current personality settings."""
        persona = self.get_persona(user_id=user_id)
        
        lines = [
            f"Current Persona: {persona.name}",
            f"Temperature: {persona.voice_settings.get('temperature', 'default')}",
            f"Use Emojis: {persona.use_emojis}",
            f"Reinforcement Interval: Every {persona.reinforcement_interval} turns",
        ]
        
        if user_id and user_id in self.user_persona_preferences:
            lines.append(f"User Preference: {self.user_persona_preferences[user_id]}")
        
        return "\n".join(lines)


# Global instance
_personality_engine = None

def get_personality_engine(default_persona: str = "helpful_assistant") -> PersonalityEngine:
    """Get or create global personality engine."""
    global _personality_engine
    if _personality_engine is None:
        _personality_engine = PersonalityEngine(default_persona)
    return _personality_engine
