"""
Persistent conversation memory and RAG for OpenClaw Discord Bot.

This module provides:
- SQLite-based conversation storage with vector embeddings
- Semantic search for relevant past messages
- User knowledge extraction and preferences
- Conversation summarization
- Hierarchical memory management
"""

import sqlite3
import json
import time
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Optional: Only import if available
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    logger.warning("numpy not available, vector operations will be limited")

# Import embeddings
try:
    from .embeddings import EmbeddingProvider, cosine_similarity
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False


@dataclass
class Message:
    """Represents a conversation message."""
    id: Optional[int]
    conversation_id: str
    user_id: str
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: float
    embedding: Optional[bytes] = None
    metadata: Optional[Dict] = None


@dataclass
class UserFact:
    """Represents a learned fact about a user."""
    id: Optional[int]
    user_id: str
    fact_type: str  # 'preference', 'fact', 'task', 'constraint'
    content: str
    confidence: float
    timestamp: float
    access_count: int = 0


class ConversationMemory:
    """
    Manages persistent conversation memory with RAG capabilities.
    
    Features:
    - SQLite storage with optional vector embeddings
    - Semantic search for relevant context
    - User knowledge extraction
    - Conversation threading
    - Automatic summarization
    """
    
    def __init__(self, db_path: str = "discord_bot_memory.db", 
                 embedding_provider=None):
        """
        Initialize conversation memory.
        
        Args:
            db_path: Path to SQLite database
            embedding_provider: EmbeddingProvider instance or callable
        """
        self.db_path = db_path
        self.embedding_provider = embedding_provider
        self._init_database()
        
        # Configuration
        self.config = {
            'max_recent_messages': 10,
            'max_semantic_results': 5,
            'similarity_threshold': 0.7,
            'recency_half_life_hours': 24,
            'summary_interval': 20,  # Create summary every N messages
            'knowledge_extraction_interval': 10,
        }
    
    def _init_database(self):
        """Initialize SQLite database with required tables."""
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        
        # Enable foreign keys
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        
        # Conversations table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                token_count INTEGER DEFAULT 0,
                importance_score REAL DEFAULT 1.0,
                topic_id TEXT,
                metadata TEXT  -- JSON
            )
        """)
        
        # Vector embeddings table (stores embeddings as BLOB if sqlite-vec unavailable)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS message_embeddings (
                message_id INTEGER PRIMARY KEY,
                embedding BLOB,  -- Serialized numpy array or similar
                FOREIGN KEY (message_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        
        # Summaries table for long conversations
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                message_count INTEGER NOT NULL,
                start_timestamp REAL NOT NULL,
                end_timestamp REAL NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        
        # User knowledge/facts table (semantic memory)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS user_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                fact_type TEXT NOT NULL CHECK(fact_type IN ('preference', 'fact', 'task', 'constraint', 'topic')),
                content TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                timestamp REAL NOT NULL,
                last_accessed REAL,
                access_count INTEGER DEFAULT 0,
                source_message_ids TEXT  -- JSON array of source message IDs
            )
        """)
        
        # User preferences/settings
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                preferred_persona TEXT,
                conversation_style TEXT,
                max_history_messages INTEGER DEFAULT 50,
                memory_enabled INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        
        # Conversation metadata (for named conversations with topics)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_metadata (
                conversation_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                created_by_user_id TEXT NOT NULL,
                title TEXT,
                topic TEXT,
                is_group_conversation INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                message_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                last_activity REAL NOT NULL,
                metadata TEXT  -- JSON for extensibility
            )
        """)
        
        # Conversation participants (for multi-user support)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_participants (
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                joined_at REAL NOT NULL,
                last_read_timestamp REAL,
                is_active INTEGER DEFAULT 1,
                notification_preference TEXT DEFAULT 'all',  -- 'all', 'mentions', 'none'
                PRIMARY KEY (conversation_id, user_id),
                FOREIGN KEY (conversation_id) REFERENCES conversation_metadata(conversation_id) ON DELETE CASCADE
            )
        """)
        
        # User's active conversation tracking (for resumption)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS user_active_conversations (
                user_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                last_activity REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversation_metadata(conversation_id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, timestamp)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_conv_conversation ON conversations(conversation_id, timestamp)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_user ON user_knowledge(user_id, fact_type, confidence)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_summaries_conv ON conversation_summaries(conversation_id)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_conv_meta_channel ON conversation_metadata(channel_id, last_activity)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_conv_meta_user ON conversation_metadata(created_by_user_id, last_activity)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_participants_user ON conversation_participants(user_id, is_active)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_active_conv_user ON user_active_conversations(user_id)")

        # Tool execution results table (for conversation context)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS tool_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_input TEXT,  -- JSON of input parameters
                tool_result TEXT,  -- JSON of result data
                summary TEXT,  -- Human-readable summary for LLM context
                timestamp REAL NOT NULL,
                referenced_in INTEGER,  -- Message ID where this result was first shared
                access_count INTEGER DEFAULT 0,
                FOREIGN KEY (conversation_id) REFERENCES conversation_metadata(conversation_id) ON DELETE CASCADE
            )
        """)

        self.db.execute("CREATE INDEX IF NOT EXISTS idx_tool_results_conv ON tool_results(conversation_id, timestamp)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_tool_results_user ON tool_results(user_id, timestamp)")

        self.db.commit()
        logger.info(f"Initialized conversation memory database: {self.db_path}")
    
    def _get_embedding(self, text: str) -> Optional[bytes]:
        """Generate embedding for text if provider is available (sync version)."""
        if not self.embedding_provider:
            return None

        try:
            # Handle both EmbeddingProvider interface and callable
            if HAS_EMBEDDINGS and isinstance(self.embedding_provider, EmbeddingProvider):
                embedding = self.embedding_provider.embed_sync(text)
            else:
                # Legacy callable interface
                embedding = self.embedding_provider(text)
            
            if embedding is None:
                return None
            
            if HAS_NUMPY and isinstance(embedding, np.ndarray):
                return embedding.tobytes()
            elif isinstance(embedding, (list, tuple)):
                return np.array(embedding, dtype=np.float32).tobytes()
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None
    
    async def _get_embedding_async(self, text: str) -> Optional[bytes]:
        """Generate embedding for text if provider is available (async version)."""
        if not self.embedding_provider:
            return None

        try:
            import asyncio
            
            if HAS_EMBEDDINGS and isinstance(self.embedding_provider, EmbeddingProvider):
                # Use async version if available, otherwise run sync in executor
                if hasattr(self.embedding_provider, 'embed_async'):
                    embedding = await self.embedding_provider.embed_async(text)
                else:
                    # Run sync version in thread pool to avoid blocking
                    loop = asyncio.get_running_loop()
                    embedding = await loop.run_in_executor(
                        None, self.embedding_provider.embed_sync, text
                    )
            else:
                # Legacy callable interface - run in thread pool
                loop = asyncio.get_running_loop()
                embedding = await loop.run_in_executor(
                    None, self.embedding_provider, text
                )
            
            if embedding is None:
                return None
            
            if HAS_NUMPY and isinstance(embedding, np.ndarray):
                return embedding.tobytes()
            elif isinstance(embedding, (list, tuple)):
                return np.array(embedding, dtype=np.float32).tobytes()
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None
    
    def _cosine_similarity(self, embedding1: bytes, embedding2: bytes) -> float:
        """Calculate cosine similarity between two embeddings."""
        # Use imported cosine_similarity if available
        if HAS_EMBEDDINGS and HAS_NUMPY:
            try:
                vec1 = np.frombuffer(embedding1, dtype=np.float32)
                vec2 = np.frombuffer(embedding2, dtype=np.float32)
                return cosine_similarity(vec1.tolist(), vec2.tolist())
            except (ValueError, TypeError, FloatingPointError) as e:
                logger.error(f"Failed to calculate similarity: {e}")
                return 0.0
        
        if not HAS_NUMPY:
            return 0.5  # Neutral similarity if numpy unavailable

        try:
            vec1 = np.frombuffer(embedding1, dtype=np.float32)
            vec2 = np.frombuffer(embedding2, dtype=np.float32)

            # Normalize
            vec1 = vec1 / np.linalg.norm(vec1)
            vec2 = vec2 / np.linalg.norm(vec2)

            return float(np.dot(vec1, vec2))
        except (ValueError, TypeError, FloatingPointError) as e:
            logger.error(f"Failed to calculate similarity: {e}")
            return 0.0
    
    def add_message(self, conversation_id: str, user_id: str, 
                    role: str, content: str, 
                    metadata: Optional[Dict] = None) -> int:
        """
        Add a message to conversation history (sync version).
        
        Returns:
            Message ID
        """
        timestamp = time.time()
        token_count = len(content.split())  # Rough approximation
        
        # Calculate importance score
        importance = self._calculate_importance(content, role)
        
        # Insert message
        cursor = self.db.execute("""
            INSERT INTO conversations 
            (conversation_id, user_id, role, content, timestamp, token_count, importance_score, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (conversation_id, user_id, role, content, timestamp, 
              token_count, importance, json.dumps(metadata) if metadata else None))
        
        message_id = cursor.lastrowid
        
        # Store embedding if available (sync version)
        embedding = self._get_embedding(content)
        if embedding:
            self.db.execute("""
                INSERT INTO message_embeddings (message_id, embedding)
                VALUES (?, ?)
            """, (message_id, embedding))
        
        self.db.commit()

        # Update message count in conversation metadata
        self.update_message_count(conversation_id)

        # Check if we should create summary or extract knowledge
        self._maybe_create_summary(conversation_id)
        self._maybe_extract_knowledge(user_id, conversation_id)

        return message_id

    async def add_message_async(self, conversation_id: str, user_id: str,
                                 role: str, content: str,
                                 metadata: Optional[Dict] = None) -> int:
        """
        Add a message to conversation history (async version - non-blocking).
        
        Returns:
            Message ID
        """
        import asyncio
        
        timestamp = time.time()
        token_count = len(content.split())  # Rough approximation
        
        # Calculate importance score
        importance = self._calculate_importance(content, role)
        
        # Insert message
        cursor = self.db.execute("""
            INSERT INTO conversations 
            (conversation_id, user_id, role, content, timestamp, token_count, importance_score, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (conversation_id, user_id, role, content, timestamp, 
              token_count, importance, json.dumps(metadata) if metadata else None))
        
        message_id = cursor.lastrowid
        
        # Store embedding if available (async version - non-blocking)
        embedding = await self._get_embedding_async(content)
        if embedding:
            self.db.execute("""
                INSERT INTO message_embeddings (message_id, embedding)
                VALUES (?, ?)
            """, (message_id, embedding))
        
        self.db.commit()

        # Update message count in conversation metadata (run in thread pool to avoid blocking)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.update_message_count, conversation_id)

        # Check if we should create summary or extract knowledge
        # Run these in thread pool to avoid blocking
        await loop.run_in_executor(None, self._maybe_create_summary, conversation_id)
        await loop.run_in_executor(None, self._maybe_extract_knowledge, user_id, conversation_id)

        return message_id

    def _calculate_importance(self, content: str, role: str) -> float:
        """Calculate importance score for a message."""
        base_score = 1.0
        
        # Role-based weighting
        role_weights = {
            'user': 1.2,
            'assistant': 1.0,
            'system': 0.8
        }
        base_score *= role_weights.get(role, 1.0)
        
        # Content-based signals
        content_lower = content.lower()
        
        # Factual statements
        if any(word in content_lower for word in ['is', 'are', 'was', 'were', 'means']):
            base_score *= 1.1
        
        # User preferences
        if any(word in content_lower for word in ['like', 'love', 'hate', 'prefer', 'want']):
            base_score *= 1.3
        
        # Tasks/commitments
        if any(word in content_lower for word in ['will', 'going to', 'plan', 'need to']):
            base_score *= 1.2
        
        # Questions (less important to remember)
        if content.strip().endswith('?'):
            base_score *= 0.8
        
        return min(base_score, 2.0)
    
    def get_recent_messages(self, conversation_id: str, 
                            limit: int = None) -> List[Message]:
        """Get recent messages from a conversation."""
        limit = limit or self.config['max_recent_messages']
        
        cursor = self.db.execute("""
            SELECT c.*, e.embedding
            FROM conversations c
            LEFT JOIN message_embeddings e ON c.id = e.message_id
            WHERE c.conversation_id = ?
            ORDER BY c.timestamp DESC
            LIMIT ?
        """, (conversation_id, limit))
        
        messages = []
        for row in cursor.fetchall():
            messages.append(Message(
                id=row['id'],
                conversation_id=row['conversation_id'],
                user_id=row['user_id'],
                role=row['role'],
                content=row['content'],
                timestamp=row['timestamp'],
                embedding=row['embedding'],
                metadata=json.loads(row['metadata']) if row['metadata'] else None
            ))
        
        # Return in chronological order
        return list(reversed(messages))
    
    def search_similar_messages(self, conversation_id: str, query: str,
                                 k: int = None) -> List[Tuple[Message, float]]:
        """
        Search for semantically similar messages.
        
        Returns:
            List of (message, similarity_score) tuples
        """
        if not self.embedding_provider:
            return []
        
        k = k or self.config['max_semantic_results']
        
        # Get query embedding
        query_embedding = self._get_embedding(query)
        if not query_embedding:
            return []
        
        # Get all messages with embeddings from this conversation
        cursor = self.db.execute("""
            SELECT c.*, e.embedding
            FROM conversations c
            JOIN message_embeddings e ON c.id = e.message_id
            WHERE c.conversation_id = ?
            ORDER BY c.timestamp DESC
            LIMIT 1000  -- Reasonable limit for in-memory search
        """, (conversation_id,))
        
        # Calculate similarities
        scored_messages = []
        for row in cursor.fetchall():
            if row['embedding']:
                similarity = self._cosine_similarity(query_embedding, row['embedding'])
                
                # Apply recency decay
                hours_ago = (time.time() - row['timestamp']) / 3600
                recency_factor = 2 ** (-hours_ago / self.config['recency_half_life_hours'])
                
                # Apply importance weight
                weighted_score = similarity * recency_factor * row['importance_score']
                
                if similarity > self.config['similarity_threshold']:
                    message = Message(
                        id=row['id'],
                        conversation_id=row['conversation_id'],
                        user_id=row['user_id'],
                        role=row['role'],
                        content=row['content'],
                        timestamp=row['timestamp'],
                        embedding=row['embedding'],
                        metadata=json.loads(row['metadata']) if row['metadata'] else None
                    )
                    scored_messages.append((message, weighted_score))
        
        # Sort by score and return top k
        scored_messages.sort(key=lambda x: x[1], reverse=True)
        return scored_messages[:k]
    
    def get_user_knowledge(self, user_id: str,
                           fact_type: Optional[str] = None,
                           min_confidence: float = 0.5,
                           limit: int = 10) -> List[UserFact]:
        """Get stored knowledge about a user."""
        query = """
            SELECT * FROM user_knowledge
            WHERE user_id = ? AND confidence >= ?
        """
        params = [user_id, min_confidence]

        if fact_type:
            query += " AND fact_type = ?"
            params.append(fact_type)

        query += " ORDER BY confidence DESC, access_count DESC LIMIT ?"
        params.append(limit)

        cursor = self.db.execute(query, params)

        facts = []
        for row in cursor.fetchall():
            facts.append(UserFact(
                id=row['id'],
                user_id=row['user_id'],
                fact_type=row['fact_type'],
                content=row['content'],
                confidence=row['confidence'],
                timestamp=row['timestamp'],
                access_count=row['access_count']
            ))

        # Update access count
        if facts:
            fact_ids = [f.id for f in facts]
            placeholders = ','.join('?' * len(fact_ids))
            self.db.execute(f"""
                UPDATE user_knowledge
                SET access_count = access_count + 1,
                    last_accessed = ?
                WHERE id IN ({placeholders})
            """, [time.time()] + fact_ids)
            self.db.commit()

        if facts:
            logger.info(f"Retrieved {len(facts)} facts for user {user_id[:8]}...")
            for fact in facts[:3]:
                logger.info(f"  Fact #{fact.id}: {fact.fact_type} = {fact.content[:50]}...")
        else:
            logger.info(f"No facts found for user {user_id[:8]}... (type={fact_type}, min_conf={min_confidence})")

        return facts
    
    def add_user_fact(self, user_id: str, fact_type: str, content: str,
                     confidence: float = 0.5, source_message_ids: List[int] = None):
        """Add a fact about a user."""
        # Check for existing similar fact
        cursor = self.db.execute("""
            SELECT id, confidence FROM user_knowledge
            WHERE user_id = ? AND fact_type = ? AND (
                content LIKE ? OR ? LIKE '%' || content || '%'
            )
        """, (user_id, fact_type, f"%{content[:50]}%", content))

        existing = cursor.fetchone()

        if existing:
            # Update confidence if fact already exists
            new_confidence = min(existing['confidence'] + 0.1, 1.0)
            self.db.execute("""
                UPDATE user_knowledge
                SET confidence = ?, timestamp = ?, access_count = access_count + 1
                WHERE id = ?
            """, (new_confidence, time.time(), existing['id']))
            logger.debug(f"Updated fact confidence for user {user_id[:8]}...: {fact_type} = {content[:50]}...")
        else:
            # Insert new fact
            self.db.execute("""
                INSERT INTO user_knowledge
                (user_id, fact_type, content, confidence, timestamp, source_message_ids)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, fact_type, content, confidence, time.time(),
                  json.dumps(source_message_ids) if source_message_ids else None))
            logger.info(f"Stored new fact for user {user_id[:8]}...: {fact_type} = {content[:50]}...")

        self.db.commit()
    
    def remove_user_facts(self, user_id: str, fact_ids: List[int]):
        """Remove previously stored facts for a user by their IDs."""
        if not fact_ids:
            return
            
        placeholders = ','.join('?' * len(fact_ids))
        self.db.execute(f"""
            DELETE FROM user_knowledge
            WHERE user_id = ? AND id IN ({placeholders})
        """, [user_id] + fact_ids)
        self.db.commit()
    
    def get_conversation_context(self, conversation_id: str, user_id: str,
                                  query: str = None,
                                  max_tokens: int = 2000) -> Dict[str, Any]:
        """
        Get comprehensive conversation context for LLM.
        
        Returns:
            Dict with 'recent_messages', 'similar_messages', 'user_knowledge', 'summary'
        """
        context = {
            'recent_messages': [],
            'similar_messages': [],
            'user_knowledge': [],
            'tool_results': [],
            'summary': None,
            'estimated_tokens': 0
        }

        used_tokens = 0
        token_budget = max_tokens

        # 1. Get summary if available
        summary = self.db.execute("""
            SELECT summary_text FROM conversation_summaries
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (conversation_id,)).fetchone()

        if summary:
            summary_tokens = len(summary['summary_text'].split())
            if used_tokens + summary_tokens < token_budget * 0.3:
                context['summary'] = summary['summary_text']
                used_tokens += summary_tokens

        # 2. Get user knowledge
        knowledge = self.get_user_knowledge(user_id, limit=5)
        knowledge_text = ""
        for fact in knowledge:
            knowledge_text += f"- {fact.fact_type}: {fact.content}\n"

        knowledge_tokens = len(knowledge_text.split())
        if used_tokens + knowledge_tokens < token_budget * 0.2:
            context['user_knowledge'] = knowledge
            used_tokens += knowledge_tokens

        # 3. Get recent tool results (for follow-up queries)
        tool_results = self.get_recent_tool_results(conversation_id, limit=3)
        if tool_results:
            tool_context_text = "Recent tool results:\n"
            for tr in tool_results:
                tool_context_text += f"- {tr['tool_name']}: {tr['summary'][:100]}...\n"
            tool_tokens = len(tool_context_text.split())
            if used_tokens + tool_tokens < token_budget * 0.15:
                context['tool_results'] = tool_results
                used_tokens += tool_tokens
                logger.info(f"Added {len(tool_results)} recent tool results to context")

        # 4. Get recent messages
        recent = self.get_recent_messages(conversation_id,
                                          limit=self.config['max_recent_messages'])
        for msg in recent:
            msg_tokens = len(msg.content.split())
            if used_tokens + msg_tokens < token_budget * 0.4:
                context['recent_messages'].append(msg)
                used_tokens += msg_tokens

        # 5. Get semantically similar messages
        if query:
            similar = self.search_similar_messages(conversation_id, query)
            for msg, score in similar[:3]:  # Top 3
                msg_tokens = len(msg.content.split())
                if used_tokens + msg_tokens < token_budget:
                    context['similar_messages'].append((msg, score))
                    used_tokens += msg_tokens

        context['estimated_tokens'] = used_tokens

        logger.debug(f"Built context for conv {conversation_id[:20]}...:"
                    f"{len(context['recent_messages'])} recent msgs, "
                    f"{len(context['user_knowledge'])} facts, "
                    f"summary={'yes' if context['summary'] else 'no'}, "
                    f"~{used_tokens} tokens")

        return context

    def _maybe_create_summary(self, conversation_id: str):
        """Create a summary if message count threshold reached."""
        count = self.db.execute(
            "SELECT COUNT(*) FROM conversations WHERE conversation_id = ?",
            (conversation_id,)
        ).fetchone()[0]
        
        if count > 0 and count % self.config['summary_interval'] == 0:
            # Get messages to summarize
            cursor = self.db.execute("""
                SELECT role, content, timestamp
                FROM conversations
                WHERE conversation_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (conversation_id, self.config['summary_interval']))
            
            messages = cursor.fetchall()
            if len(messages) >= 10:
                # Summary creation is async, should be called externally
                # For now, just mark that summary is needed
                logger.info(f"Summary threshold reached for {conversation_id}")
    
    def create_summary(self, conversation_id: str, messages: List[Dict]) -> str:
        """
        Create a summary of messages.
        
        This should be called with LLM-generated summary.
        """
        if not messages:
            return ""
        
        summary_text = messages[0].get('summary', '')  # Expected to be LLM-generated
        
        start_time = min(m['timestamp'] for m in messages)
        end_time = max(m['timestamp'] for m in messages)
        
        self.db.execute("""
            INSERT INTO conversation_summaries
            (conversation_id, summary_text, message_count, start_timestamp, end_timestamp, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conversation_id, summary_text, len(messages), start_time, end_time, time.time()))
        
        self.db.commit()
        return summary_text
    
    def _maybe_extract_knowledge(self, user_id: str, conversation_id: str):
        """Trigger knowledge extraction if threshold reached."""
        count = self.db.execute(
            "SELECT COUNT(*) FROM conversations WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, user_id)
        ).fetchone()[0]
        
        if count > 0 and count % self.config['knowledge_extraction_interval'] == 0:
            logger.info(f"Knowledge extraction threshold reached for {user_id}")
    
    def extract_knowledge_with_llm(self, user_id: str, 
                                   llm_extractor_func) -> List[UserFact]:
        """
        Extract knowledge using an LLM.
        
        Args:
            llm_extractor_func: Async function that takes conversation text
                              and returns extracted facts
        """
        # Get recent conversation
        cursor = self.db.execute("""
            SELECT role, content
            FROM conversations
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT 20
        """, (user_id,))
        
        messages = cursor.fetchall()
        if len(messages) < 5:
            return []
        
        # Format for LLM (reserved for future LLM-based fact extraction)
        _ = "\n".join([
            f"{m['role']}: {m['content']}" for m in reversed(messages)
        ])

        # This would call an LLM to extract facts
        # For now, return empty - actual implementation would use llm_extractor_func
        return []
    
    def get_user_settings(self, user_id: str) -> Dict[str, Any]:
        """Get user settings."""
        cursor = self.db.execute(
            "SELECT * FROM user_settings WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        
        if cursor:
            return {
                'user_id': cursor['user_id'],
                'preferred_persona': cursor['preferred_persona'],
                'conversation_style': cursor['conversation_style'],
                'max_history_messages': cursor['max_history_messages'],
                'memory_enabled': bool(cursor['memory_enabled']),
                'created_at': cursor['created_at'],
                'updated_at': cursor['updated_at']
            }
        
        # Return defaults
        return {
            'user_id': user_id,
            'preferred_persona': None,  # None means use system default
            'conversation_style': 'balanced',
            'max_history_messages': 50,
            'memory_enabled': True,
            'created_at': time.time(),
            'updated_at': time.time()
        }
    
    def update_user_settings(self, user_id: str, **kwargs):
        """Update user settings."""
        # Check if user exists
        existing = self.db.execute(
            "SELECT 1 FROM user_settings WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        
        if existing:
            # Update
            allowed_fields = ['preferred_persona', 'conversation_style', 
                            'max_history_messages', 'memory_enabled']
            updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
            
            if updates:
                set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
                params = list(updates.values()) + [time.time(), user_id]
                
                self.db.execute(f"""
                    UPDATE user_settings
                    SET {set_clause}, updated_at = ?
                    WHERE user_id = ?
                """, params)
        else:
            # Insert
            self.db.execute("""
                INSERT INTO user_settings
                (user_id, preferred_persona, conversation_style,
                 max_history_messages, memory_enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id,
                  kwargs.get('preferred_persona', None),
                  kwargs.get('conversation_style', 'balanced'),
                  kwargs.get('max_history_messages', 50),
                  int(kwargs.get('memory_enabled', True)),
                  time.time(), time.time()))
        
        self.db.commit()
    
    def clear_conversation(self, conversation_id: str, keep_summary: bool = True):
        """Clear a conversation's message history."""
        if keep_summary:
            # Delete messages but keep summaries and knowledge
            self.db.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,)
            )
        else:
            # Delete everything
            self.db.execute(
                "DELETE FROM conversation_summaries WHERE conversation_id = ?",
                (conversation_id,)
            )
            self.db.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,)
            )
        
        self.db.commit()
        logger.info(f"Cleared conversation {conversation_id}")
    
    def clear_user_memory(self, user_id: str, keep_settings: bool = True):
        """Clear all memory for a user."""
        self.db.execute("DELETE FROM user_knowledge WHERE user_id = ?", (user_id,))
        self.db.execute(
            "DELETE FROM conversations WHERE user_id = ?",
            (user_id,)
        )
        
        if not keep_settings:
            self.db.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
        
        self.db.commit()
        logger.info(f"Cleared memory for user {user_id}")
    
    # --- Conversation Management Methods ---
    
    def create_conversation(self, conversation_id: str, channel_id: str, 
                           user_id: str, title: str = None, 
                           topic: str = None, is_group: bool = False) -> str:
        """
        Create a new conversation with metadata.
        
        Args:
            conversation_id: Unique ID for the conversation
            channel_id: Discord channel ID
            user_id: Creating user ID
            title: Optional conversation title
            topic: Optional topic/description
            is_group: Whether this is a multi-user conversation
            
        Returns:
            The conversation_id
        """
        timestamp = time.time()
        
        # Insert conversation metadata
        self.db.execute("""
            INSERT OR REPLACE INTO conversation_metadata
            (conversation_id, channel_id, created_by_user_id, title, topic, 
             is_group_conversation, is_active, created_at, last_activity, metadata)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (conversation_id, channel_id, user_id, title or f"Conversation with {user_id}",
              topic, int(is_group), timestamp, timestamp,
              json.dumps({"created_by": user_id})))
        
        # Add creator as participant
        self.db.execute("""
            INSERT OR REPLACE INTO conversation_participants
            (conversation_id, user_id, joined_at, is_active, notification_preference)
            VALUES (?, ?, ?, 1, 'all')
        """, (conversation_id, user_id, timestamp))
        
        # Set as active conversation for this user
        self.set_active_conversation(user_id, conversation_id, channel_id)
        
        self.db.commit()
        logger.info(f"Created conversation {conversation_id} for user {user_id}")
        return conversation_id
    
    def get_or_create_conversation(self, conversation_id: str, channel_id: str,
                                    user_id: str, title: str = None) -> str:
        """Get existing conversation or create new one."""
        existing = self.db.execute(
            "SELECT conversation_id FROM conversation_metadata WHERE conversation_id = ?",
            (conversation_id,)
        ).fetchone()
        
        if existing:
            # Update activity and ensure user is participant
            self.update_conversation_activity(conversation_id)
            self._ensure_participant(conversation_id, user_id)
            return conversation_id
        
        return self.create_conversation(conversation_id, channel_id, user_id, title)
    
    def _ensure_participant(self, conversation_id: str, user_id: str):
        """Ensure a user is a participant in a conversation."""
        existing = self.db.execute(
            "SELECT 1 FROM conversation_participants WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, user_id)
        ).fetchone()
        
        if not existing:
            self.db.execute("""
                INSERT INTO conversation_participants
                (conversation_id, user_id, joined_at, is_active)
                VALUES (?, ?, ?, 1)
            """, (conversation_id, user_id, time.time()))
            self.db.commit()
    
    def get_user_conversations(self, user_id: str, channel_id: str = None,
                              active_only: bool = True, limit: int = 10) -> List[Dict]:
        """
        Get all conversations for a user.
        
        Args:
            user_id: The user to get conversations for
            channel_id: Optional filter by channel
            active_only: Only return non-archived conversations
            limit: Max number to return
        """
        query = """
            SELECT DISTINCT 
                cm.conversation_id,
                cm.channel_id,
                cm.title,
                cm.topic,
                cm.is_group_conversation,
                cm.message_count,
                cm.last_activity,
                cm.created_at,
                (SELECT COUNT(*) FROM conversation_participants 
                 WHERE conversation_id = cm.conversation_id) as participant_count,
                (SELECT conversation_id FROM user_active_conversations 
                 WHERE user_id = ?) as active_conversation_id
            FROM conversation_metadata cm
            JOIN conversation_participants cp ON cm.conversation_id = cp.conversation_id
            WHERE cp.user_id = ?
        """
        params = [user_id, user_id]
        
        if channel_id:
            query += " AND cm.channel_id = ?"
            params.append(channel_id)
        
        if active_only:
            query += " AND cm.is_active = 1"
        
        query += " ORDER BY cm.last_activity DESC LIMIT ?"
        params.append(limit)
        
        cursor = self.db.execute(query, params)
        conversations = []
        
        for row in cursor:
            conversations.append({
                'conversation_id': row['conversation_id'],
                'channel_id': row['channel_id'],
                'title': row['title'],
                'topic': row['topic'],
                'is_group': bool(row['is_group_conversation']),
                'message_count': row['message_count'],
                'last_activity': row['last_activity'],
                'created_at': row['created_at'],
                'participant_count': row['participant_count'],
                'is_active_conversation': row['conversation_id'] == row['active_conversation_id']
            })
        
        return conversations
    
    def get_active_conversation(self, user_id: str) -> Optional[str]:
        """Get the currently active conversation for a user."""
        cursor = self.db.execute(
            "SELECT conversation_id FROM user_active_conversations WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        
        if cursor:
            # Verify conversation still exists and is active
            conv = self.db.execute(
                "SELECT 1 FROM conversation_metadata WHERE conversation_id = ? AND is_active = 1",
                (cursor['conversation_id'],)
            ).fetchone()
            if conv:
                return cursor['conversation_id']
        
        # If no active conversation, find most recent
        recent = self.db.execute("""
            SELECT cm.conversation_id
            FROM conversation_metadata cm
            JOIN conversation_participants cp ON cm.conversation_id = cp.conversation_id
            WHERE cp.user_id = ? AND cm.is_active = 1
            ORDER BY cm.last_activity DESC
            LIMIT 1
        """, (user_id,)).fetchone()
        
        if recent:
            return recent['conversation_id']
        
        return None
    
    def set_active_conversation(self, user_id: str, conversation_id: str, 
                                 channel_id: str = None):
        """Set the active conversation for a user."""
        if channel_id is None:
            # Get channel from conversation metadata
            conv = self.db.execute(
                "SELECT channel_id FROM conversation_metadata WHERE conversation_id = ?",
                (conversation_id,)
            ).fetchone()
            if conv:
                channel_id = conv['channel_id']
            else:
                channel_id = "unknown"
        
        timestamp = time.time()
        
        self.db.execute("""
            INSERT OR REPLACE INTO user_active_conversations
            (user_id, conversation_id, channel_id, last_activity)
            VALUES (?, ?, ?, ?)
        """, (user_id, conversation_id, channel_id, timestamp))
        
        # Also update the conversation activity
        self.update_conversation_activity(conversation_id)
        
        # Ensure user is a participant
        self._ensure_participant(conversation_id, user_id)
        
        self.db.commit()
        logger.info(f"Set active conversation {conversation_id} for user {user_id}")
    
    def update_conversation_activity(self, conversation_id: str):
        """Update the last activity timestamp for a conversation."""
        self.db.execute(
            "UPDATE conversation_metadata SET last_activity = ? WHERE conversation_id = ?",
            (time.time(), conversation_id)
        )
        self.db.commit()
    
    def add_conversation_participant(self, conversation_id: str, user_id: str,
                                     notification_pref: str = 'all'):
        """Add a user to an existing conversation (for group chats)."""
        existing = self.db.execute(
            "SELECT 1 FROM conversation_participants WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, user_id)
        ).fetchone()
        
        if existing:
            # Just update notification preference
            self.db.execute("""
                UPDATE conversation_participants 
                SET notification_preference = ?
                WHERE conversation_id = ? AND user_id = ?
            """, (notification_pref, conversation_id, user_id))
        else:
            self.db.execute("""
                INSERT INTO conversation_participants
                (conversation_id, user_id, joined_at, is_active, notification_preference)
                VALUES (?, ?, ?, 1, ?)
            """, (conversation_id, user_id, time.time(), notification_pref))
            
            # Mark as group conversation
            self.db.execute(
                "UPDATE conversation_metadata SET is_group_conversation = 1 WHERE conversation_id = ?",
                (conversation_id,)
            )
        
        self.db.commit()
        logger.info(f"Added user {user_id} to conversation {conversation_id}")
    
    def get_conversation_participants(self, conversation_id: str) -> List[Dict]:
        """Get all participants in a conversation."""
        cursor = self.db.execute("""
            SELECT user_id, joined_at, last_read_timestamp, 
                   is_active, notification_preference
            FROM conversation_participants
            WHERE conversation_id = ?
            ORDER BY joined_at
        """, (conversation_id,))
        
        return [{
            'user_id': row['user_id'],
            'joined_at': row['joined_at'],
            'last_read': row['last_read_timestamp'],
            'is_active': bool(row['is_active']),
            'notification_pref': row['notification_preference']
        } for row in cursor]
    
    def rename_conversation(self, conversation_id: str, new_title: str):
        """Rename a conversation."""
        self.db.execute(
            "UPDATE conversation_metadata SET title = ? WHERE conversation_id = ?",
            (new_title, conversation_id)
        )
        self.db.commit()
    
    def archive_conversation(self, conversation_id: str):
        """Archive (soft-delete) a conversation."""
        self.db.execute(
            "UPDATE conversation_metadata SET is_active = 0 WHERE conversation_id = ?",
            (conversation_id,)
        )
        self.db.execute(
            "UPDATE conversation_participants SET is_active = 0 WHERE conversation_id = ?",
            (conversation_id,)
        )
        self.db.commit()
        logger.info(f"Archived conversation {conversation_id}")
    
    def update_message_count(self, conversation_id: str):
        """Update the message count for a conversation."""
        self.db.execute("""
            UPDATE conversation_metadata 
            SET message_count = (SELECT COUNT(*) FROM conversations WHERE conversation_id = ?)
            WHERE conversation_id = ?
        """, (conversation_id, conversation_id))
        self.db.commit()

    def store_tool_result(self, conversation_id: str, user_id: str,
                          tool_name: str, tool_input: Dict,
                          tool_result: Dict, summary: str,
                          referenced_in: int = None) -> int:
        """
        Store a tool execution result for conversation context.

        Args:
            conversation_id: The conversation ID
            user_id: User ID who triggered the tool
            tool_name: Name of the tool/command executed
            tool_input: Input parameters (dict, will be JSON serialized)
            tool_result: Raw result data (dict, will be JSON serialized)
            summary: Human-readable summary for LLM context
            referenced_in: Message ID where this result was first shared

        Returns:
            The ID of the stored tool result
        """
        cursor = self.db.execute("""
            INSERT INTO tool_results
            (conversation_id, user_id, tool_name, tool_input, tool_result, summary, timestamp, referenced_in)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            conversation_id, user_id, tool_name,
            json.dumps(tool_input) if tool_input else None,
            json.dumps(tool_result) if tool_result else None,
            summary,
            time.time(),
            referenced_in
        ))
        self.db.commit()

        logger.info(f"Stored tool result for {tool_name} in conversation {conversation_id[:20]}...")
        return cursor.lastrowid

    def get_recent_tool_results(self, conversation_id: str, limit: int = 5) -> List[Dict]:
        """
        Get recent tool execution results for a conversation.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of results to return

        Returns:
            List of tool result dicts with keys: id, tool_name, tool_input,
            tool_result, summary, timestamp, access_count
        """
        cursor = self.db.execute("""
            SELECT id, tool_name, tool_input, tool_result, summary, timestamp, access_count
            FROM tool_results
            WHERE conversation_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (conversation_id, limit))

        results = []
        result_ids = []

        for row in cursor.fetchall():
            results.append({
                'id': row['id'],
                'tool_name': row['tool_name'],
                'tool_input': json.loads(row['tool_input']) if row['tool_input'] else {},
                'tool_result': json.loads(row['tool_result']) if row['tool_result'] else {},
                'summary': row['summary'],
                'timestamp': row['timestamp'],
                'access_count': row['access_count']
            })
            result_ids.append(row['id'])

        # Update access count
        if result_ids:
            placeholders = ','.join('?' * len(result_ids))
            self.db.execute(f"""
                UPDATE tool_results
                SET access_count = access_count + 1
                WHERE id IN ({placeholders})
            """, result_ids)
            self.db.commit()

        logger.debug(f"Retrieved {len(results)} recent tool results for conversation {conversation_id[:20]}...")
        return list(reversed(results))  # Return in chronological order

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        stats = {}
        
        # Message counts
        cursor = self.db.execute("SELECT COUNT(*) FROM conversations")
        stats['total_messages'] = cursor.fetchone()[0]
        
        # Unique users
        cursor = self.db.execute("SELECT COUNT(DISTINCT user_id) FROM conversations")
        stats['unique_users'] = cursor.fetchone()[0]
        
        # Unique conversations
        cursor = self.db.execute("SELECT COUNT(DISTINCT conversation_id) FROM conversations")
        stats['unique_conversations'] = cursor.fetchone()[0]
        
        # Knowledge facts
        cursor = self.db.execute("SELECT COUNT(*) FROM user_knowledge")
        stats['knowledge_facts'] = cursor.fetchone()[0]
        
        # Summaries
        cursor = self.db.execute("SELECT COUNT(*) FROM conversation_summaries")
        stats['summaries'] = cursor.fetchone()[0]
        
        # Conversation metadata stats
        cursor = self.db.execute("SELECT COUNT(*) FROM conversation_metadata WHERE is_active = 1")
        stats['active_named_conversations'] = cursor.fetchone()[0]
        
        cursor = self.db.execute("SELECT COUNT(*) FROM conversation_participants WHERE is_active = 1")
        stats['active_participants'] = cursor.fetchone()[0]
        
        cursor = self.db.execute("SELECT COUNT(DISTINCT user_id) FROM conversation_participants WHERE is_active = 1")
        stats['users_in_conversations'] = cursor.fetchone()[0]
        
        return stats
    
    def close(self):
        """Close database connection."""
        if self.db:
            self.db.close()
            self.db = None


# Global instance (singleton pattern)
_memory_instance = None

def get_memory(db_path: str = "discord_bot_memory.db",
               embedding_provider=None) -> ConversationMemory:
    """Get or create global memory instance."""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = ConversationMemory(db_path, embedding_provider)
    return _memory_instance
