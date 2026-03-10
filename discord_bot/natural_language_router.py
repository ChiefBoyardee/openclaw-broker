"""
Natural Language Intent Router for OpenClaw Discord Bot.

This module provides intent detection for natural language queries, enabling
the bot to understand and route user messages to appropriate handlers without
requiring explicit command prefixes.

Intent Categories:
- casual_chat: General conversation, greetings, questions about self
- repo_explore: List repos, show repo contents, explore projects
- repo_search: Search for code, files, patterns in repositories
- file_read: Read specific files from repositories
- github_ops: GitHub operations (issues, repos, PRs)
- web_research: Web browsing and research tasks
- website_manage: Website/blog management
- system_status: Bot capabilities, status, help
- memory_ops: User memory management (remember, forget, etc.)
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    """Result of intent detection."""
    intent: str  # The detected intent category
    confidence: float  # 0.0 to 1.0 confidence score
    entities: Dict[str, Any]  # Extracted entities (repo, query, path, etc.)
    suggested_tools: List[str]  # Tools that might be needed
    raw_message: str  # Original message for logging


class NaturalLanguageRouter:
    """
    Routes natural language messages to appropriate intents.
    
    Uses pattern matching for fast, deterministic intent detection.
    Optionally can use LLM-based classification for ambiguous cases.
    """
    
    # Intent patterns - ordered by specificity (most specific first)
    INTENT_PATTERNS = {
        "memory_ops": {
            "patterns": [
                r"\bremember\s+(?:that\s+)?(.+)",
                r"\bforget\s+(?:that\s+)?(.+)",
                r"\bwhat\s+do\s+you\s+(?:know|remember)\s+about\s+me",
                r"\bshow\s+(?:me\s+)?my\s+memories",
                r"\bclear\s+(?:my\s+)?memory",
            ],
            "keywords": ["remember", "forget", "memories", "what do you know"],
            "suggested_tools": [],
            "description": "Memory management operations",
        },
        "conversations_manage": {
            "patterns": [
                r"\b(?:show|list)\s+(?:me\s+)?my\s+conversations",
                r"\bstart\s+(?:a\s+)?new\s+conversation",
                r"\bswitch\s+(?:to\s+)?(?:conversation\s+)?(\d+|[a-f0-9]+)",
                r"\bresume\s+(?:my\s+)?(?:last\s+)?conversation",
                r"\brename\s+(?:this\s+)?conversation\s+(?:to\s+)?(.+)",
            ],
            "keywords": ["conversations", "conversation history", "switch conversation"],
            "suggested_tools": [],
            "description": "Conversation management",
        },
        "file_read": {
            "patterns": [
                r"\b(?:show|read|display|get)\s+(?:me\s+)?(?:the\s+)?(?:content\s+of\s+)?(?:file\s+)?['\"]?(.+?)['\"]?(?:\s+(?:from|in)\s+(?:repo\s+)?['\"]?(.+?)['\"]?)?",
                r"\bwhat(?:'s|\s+is)\s+in\s+['\"]?(.+?)['\"]?(?:\s+(?:from|in)\s+(?:repo\s+)?['\"]?(.+?)['\"]?)?",
                r"\bopen\s+(?:the\s+)?file\s+['\"]?(.+?)['\"]?(?:\s+(?:from|in)\s+(?:repo\s+)?['\"]?(.+?)['\"]?)?",
                r"\bread\s+(?:me\s+)?(?:the\s+)?readme(?:\s+(?:from|in)\s+(?:repo\s+)?['\"]?(.+?)['\"]?)?",
                r"\bshow\s+(?:me\s+)?(?:the\s+)?main\.\w+(?:\s+(?:from|in)\s+(?:repo\s+)?['\"]?(.+?)['\"]?)?",
            ],
            "keywords": ["show me the file", "read the file", "what's in", "content of", "open the file"],
            "suggested_tools": ["repo_readfile"],
            "description": "Read files from repositories",
        },
        "repo_search": {
            "patterns": [
                r"\b(?:search|find|grep|look\s+for)\s+(?:for\s+)?['\"]?(.+?)['\"]?(?:\s+(?:in|within|across)\s+(?:the\s+)?(?:repo\s+)?['\"]?(.+?)['\"]?)?",
                r"\b(?:search|find)\s+(?:the\s+)?(?:code|files?)\s+(?:for\s+)?['\"]?(.+?)['\"]?",
                r"\bwhere\s+(?:is|are)\s+(.+?)\s+(?:defined|used|mentioned)",
                r"\bfind\s+(?:all\s+)?(?:instances?|occurrences?|matches?)\s+of\s+['\"]?(.+?)['\"]?",
                r"\b(?:show|find)\s+(?:me\s+)?(?:all\s+)?files?\s+(?:that\s+)?(?:contain|have|match)\s+['\"]?(.+?)['\"]?",
            ],
            "keywords": ["search for", "find", "grep", "look for", "where is", "find all"],
            "suggested_tools": ["repo_grep"],
            "description": "Search for code patterns in repositories",
        },
        "repo_explore": {
            "patterns": [
                r"\b(?:list|show)\s+(?:me\s+)?(?:all\s+)?(?:my\s+)?repos?(?:itories)?",
                r"\bwhat\s+repos?\s+(?:do\s+I\s+have|are\s+(?:available|there))",
                r"\b(?:show|explore|browse)\s+(?:the\s+)?(?:repo\s+)?['\"]?(.+?)['\"]?(?:\s+(?:project|repository))?",
                r"\bwhat\s+(?:is|are)\s+(?:in|inside)\s+(?:the\s+)?(?:repo\s+)?['\"]?(.+?)['\"]?",
                r"\bshow\s+(?:me\s+)?(?:the\s+)?(?:structure|layout|files?)\s+(?:of|in)\s+(?:the\s+)?(?:repo\s+)?['\"]?(.+?)['\"]?",
                r"\b(?:get|show)\s+(?:me\s+)?(?:the\s+)?(?:last\s+)?commit\s+(?:in|for|from)\s+(?:the\s+)?(?:repo\s+)?['\"]?(.+?)['\"]?",
                r"\bwhat\s+(?:is\s+the\s+)?status\s+(?:of\s+)?(?:the\s+)?(?:repo\s+)?['\"]?(.+?)['\"]?",
            ],
            "keywords": ["list repos", "what repos", "explore", "show me the repo", "browse"],
            "suggested_tools": ["repo_list", "repo_status", "repo_last_commit"],
            "description": "Explore repository contents and status",
        },
        "github_ops": {
            "patterns": [
                r"\b(?:create|make|open)\s+(?:a\s+)?(?:new\s+)?(?:github\s+)?(?:issue|pr|pull\s+request)",
                r"\b(?:list|show)\s+(?:me\s+)?(?:my\s+)?(?:github\s+)?(?:repos?|issues?)",
                r"\b(?:check|look\s+at)\s+(?:my\s+)?(?:github\s+)?(?:issues?|notifications?)",
                r"\b(?:search|find)\s+(?:on\s+)?github\s+for\s+['\"]?(.+?)['\"]?",
            ],
            "keywords": ["github", "create issue", "list issues", "pull request", "my repos on github"],
            "suggested_tools": ["github_list_repos", "github_list_issues", "github_create_issue"],
            "description": "GitHub operations",
        },
        "web_research": {
            "patterns": [
                r"\b(?:search|look\s+up|research|find)\s+(?:on\s+)?(?:the\s+)?(?:web|internet)\s+for\s+['\"]?(.+?)['\"]?",
                r"\b(?:go\s+to|visit|open)\s+(?:the\s+)?(?:website|url|page)\s+['\"]?(.+?)['\"]?",
                r"\b(?:what|tell\s+me|find\s+out)\s+(?:about|regarding)\s+['\"]?(.+?)['\"]?(?:\s+(?:from|on)\s+(?:the\s+)?(?:web|internet))?",
                r"\b(?:browse|navigate\s+to)\s+['\"]?(.+?)['\"]?",
                r"\b(?:extract|get|scrape)\s+(?:the\s+)?(?:content|article|text)\s+(?:from|of)\s+['\"]?(.+?)['\"]?",
            ],
            "keywords": ["search the web", "look up", "research", "on the internet", "browse to"],
            "suggested_tools": ["browser_navigate", "browser_search", "browser_extract_article"],
            "description": "Web browsing and research",
        },
        "website_manage": {
            "patterns": [
                r"\b(?:update|manage|edit)\s+(?:my\s+)?(?:website|blog|site)",
                r"\b(?:create|write|publish)\s+(?:a\s+)?(?:new\s+)?(?:blog\s+)?post",
                r"\b(?:regenerate|rebuild|refresh)\s+(?:my\s+)?(?:website|site)",
                r"\b(?:show|check)\s+(?:my\s+)?(?:website|nginx)\s+(?:status|stats)",
            ],
            "keywords": ["website", "blog", "my site", "nginx", "publish post"],
            "suggested_tools": ["website_get_stats", "website_create_post", "nginx_get_status"],
            "description": "Website and blog management",
        },
        "system_status": {
            "patterns": [
                r"\b(?:what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|help|commands)",
                r"\b(?:show\s+)?(?:me\s+)?(?:your\s+)?status",
                r"\b(?:what|which)\s+(?:workers|capabilities|features)\s+(?:are\s+)?(?:available|online)",
                r"\bhow\s+(?:do\s+I|to)\s+use\s+(?:you|this\s+bot)",
                r"\bping\s+(?:the\s+)?(?:broker|worker|system)",
            ],
            "keywords": ["what can you do", "help", "capabilities", "status", "ping"],
            "suggested_tools": ["ping", "capabilities"],
            "description": "System status and capabilities",
        },
        "persona_switch": {
            "patterns": [
                r"\b(?:switch|change)\s+(?:to\s+)?(?:the\s+)?(.+?)\s+(?:persona|personality|mode)",
                r"\b(?:be\s+)?(?:more\s+)?(serious|professional|casual|friendly|formal|silly|playful)",
                r"\bact\s+(?:like\s+)?(?:a\s+)?(.+)",
                r"\b(?:switch|change)\s+(?:your\s+)?(?:tone|style|personality)",
            ],
            "keywords": ["switch persona", "change personality", "be more professional", "act like"],
            "suggested_tools": [],
            "description": "Switch bot persona/personality",
        },
    }
    
    # Casual chat catch-all patterns (lowest priority)
    CASUAL_PATTERNS = [
        r"\b(?:hi|hello|hey|greetings|howdy|hola|bonjour)\b",
        r"\bhow\s+are\s+you\b",
        r"\bwhat\s+(?:is\s+your\s+name|are\s+you|do\s+you\s+do)\b",
        r"\bthank\s*(?:you|s)\b",
        r"\b(?:good\s+(?:morning|afternoon|evening|night))\b",
        r"\btell\s+me\s+(?:about\s+yourself|a\s+(?:joke|story))",
        r"\b(?:nice|great|awesome|cool|wow)\b",
    ]
    
    def __init__(self, use_llm_fallback: bool = False):
        """
        Initialize the router.
        
        Args:
            use_llm_fallback: Whether to use LLM for ambiguous intent detection
        """
        self.use_llm_fallback = use_llm_fallback
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile regex patterns for performance."""
        self._compiled_patterns = {}
        for intent, config in self.INTENT_PATTERNS.items():
            self._compiled_patterns[intent] = [
                re.compile(p, re.IGNORECASE) for p in config["patterns"]
            ]
        self._compiled_casual = [re.compile(p, re.IGNORECASE) for p in self.CASUAL_PATTERNS]
    
    def detect_intent(self, message: str) -> IntentResult:
        """
        Detect the intent of a natural language message.
        
        Args:
            message: The user's natural language message
            
        Returns:
            IntentResult with detected intent, confidence, and extracted entities
        """
        message_lower = message.lower().strip()
        
        # Check each intent in order of specificity
        for intent, config in self.INTENT_PATTERNS.items():
            # Try pattern matching first
            for pattern in self._compiled_patterns[intent]:
                match = pattern.search(message)
                if match:
                    entities = self._extract_entities(intent, match, message)
                    confidence = self._calculate_confidence(intent, message, entities, match)
                    
                    logger.info(f"Detected intent '{intent}' with confidence {confidence:.2f} for message: {message[:50]}...")
                    
                    return IntentResult(
                        intent=intent,
                        confidence=confidence,
                        entities=entities,
                        suggested_tools=config["suggested_tools"],
                        raw_message=message
                    )
            
            # Try keyword matching if no pattern matched
            keyword_matches = sum(1 for kw in config["keywords"] if kw in message_lower)
            if keyword_matches > 0:
                confidence = min(0.5 + (keyword_matches * 0.1), 0.7)  # Max 0.7 for keyword-only
                entities = self._extract_entities_from_keywords(intent, message)
                
                logger.info(f"Detected intent '{intent}' via keywords (confidence {confidence:.2f})")
                
                return IntentResult(
                    intent=intent,
                    confidence=confidence,
                    entities=entities,
                    suggested_tools=config["suggested_tools"],
                    raw_message=message
                )
        
        # Check for casual chat patterns
        for pattern in self._compiled_casual:
            if pattern.search(message):
                logger.debug(f"Detected casual_chat intent for message: {message[:50]}...")
                return IntentResult(
                    intent="casual_chat",
                    confidence=0.8,
                    entities={},
                    suggested_tools=[],
                    raw_message=message
                )
        
        # Default to casual_chat with low confidence
        logger.debug(f"No specific intent detected, defaulting to casual_chat")
        return IntentResult(
            intent="casual_chat",
            confidence=0.3,
            entities={},
            suggested_tools=[],
            raw_message=message
        )
    
    def _extract_entities(self, intent: str, match: re.Match, message: str) -> Dict[str, Any]:
        """Extract relevant entities based on intent and regex match."""
        entities = {}
        groups = match.groups()
        
        if intent == "file_read":
            if groups:
                entities["file_path"] = groups[0].strip("'\"") if groups[0] else None
            if len(groups) > 1 and groups[1]:
                entities["repo"] = groups[1].strip("'\"")
        
        elif intent == "repo_search":
            if groups:
                entities["query"] = groups[0].strip("'\"")
            if len(groups) > 1 and groups[1]:
                entities["repo"] = groups[1].strip("'\"")
        
        elif intent == "repo_explore":
            if groups:
                entities["repo"] = groups[0].strip("'\"")
        
        elif intent == "memory_ops":
            if groups:
                entities["fact_content"] = groups[0].strip()
        
        elif intent == "conversations_manage":
            if groups:
                entities["conversation_id_or_name"] = groups[0].strip()
        
        elif intent == "persona_switch":
            if groups:
                entities["persona_name"] = groups[0].strip()
        
        elif intent == "web_research":
            if groups:
                entities["search_query"] = groups[0].strip("'\"")
        
        # Try to extract repo from common phrases if not already extracted
        if "repo" not in entities:
            repo_match = re.search(r"(?:in|from|for)\s+(?:the\s+)?(?:repo\s+)?['\"]?([^\s'\"]+)['\"]?", message, re.IGNORECASE)
            if repo_match:
                entities["repo"] = repo_match.group(1)
        
        return entities
    
    def _extract_entities_from_keywords(self, intent: str, message: str) -> Dict[str, Any]:
        """Extract entities when using keyword-based detection."""
        entities = {}
        
        # Try to extract file paths
        file_patterns = [
            r"(?:file|path)\s+['\"]?([^'\"\s]+\.\w+)['\"]?",
            r"(?:readme|main\.py|config\.json|\.env)",
        ]
        for pattern in file_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                entities["file_path"] = match.group(0)
                break
        
        # Try to extract search queries
        query_patterns = [
            r"(?:for|searching for|looking for)\s+['\"]?(.+?)['\"]?(?:\s+(?:in|from|within)|$)",
        ]
        for pattern in query_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                entities["query"] = match.group(1).strip()
                break
        
        return entities
    
    def _calculate_confidence(self, intent: str, message: str, entities: Dict, match: re.Match) -> float:
        """Calculate confidence score based on match quality."""
        base_confidence = 0.7  # Base confidence for pattern match
        
        # Boost confidence if we extracted key entities
        if entities:
            base_confidence += 0.1
        
        # Boost if the match covers most of the message
        match_ratio = len(match.group(0)) / len(message)
        if match_ratio > 0.5:
            base_confidence += 0.1
        
        # Cap at 0.95 to leave room for uncertainty
        return min(base_confidence, 0.95)
    
    def get_intent_description(self, intent: str) -> str:
        """Get human-readable description of an intent."""
        if intent in self.INTENT_PATTERNS:
            return self.INTENT_PATTERNS[intent]["description"]
        elif intent == "casual_chat":
            return "General conversation"
        return "Unknown intent"
    
    def get_all_intents(self) -> List[str]:
        """Get list of all supported intent categories."""
        return list(self.INTENT_PATTERNS.keys()) + ["casual_chat"]


# Global router instance
_router_instance: Optional[NaturalLanguageRouter] = None


def get_router(use_llm_fallback: bool = False) -> NaturalLanguageRouter:
    """Get or create the global router instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = NaturalLanguageRouter(use_llm_fallback=use_llm_fallback)
    return _router_instance


def detect_intent(message: str) -> IntentResult:
    """
    Convenience function to detect intent from a message.
    
    Example:
        result = detect_intent("Show me the main.py file from openclaw-broker")
        print(result.intent)  # "file_read"
        print(result.entities)  # {"file_path": "main.py", "repo": "openclaw-broker"}
    """
    router = get_router()
    return router.detect_intent(message)


if __name__ == "__main__":
    # Test the router
    test_messages = [
        "Show me the main.py file from openclaw-broker",
        "Search for authentication in the discord_bot folder",
        "What repos do I have?",
        "Remember that my favorite color is blue",
        "Create an issue for the memory bug",
        "Hello! How are you?",
        "What can you do?",
        "Switch to the professional persona",
        "Search the web for Python best practices",
        "Update my website",
        "This is just a casual message with no specific intent",
    ]
    
    router = NaturalLanguageRouter()
    
    for msg in test_messages:
        result = router.detect_intent(msg)
        print(f"\nMessage: {msg}")
        print(f"  Intent: {result.intent} (confidence: {result.confidence:.2f})")
        print(f"  Entities: {result.entities}")
        print(f"  Suggested tools: {result.suggested_tools}")
