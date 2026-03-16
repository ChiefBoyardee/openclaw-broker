"""
Self-memory system for Urgo's persistent identity and knowledge.

This module manages the bot's own memories, reflections, interests, and goals.
It enables Urgo to build a persistent personality over time through:
- Learning from conversations
- Storing reflections and insights
- Tracking interests and curiosities
- Managing personal goals
- Building a knowledge base of learned facts
"""
from __future__ import annotations

import sqlite3
import json
import time
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Optional: Import for embeddings
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


@dataclass
class SelfReflection:
    """A reflection or insight from Urgo."""
    id: Optional[int]
    timestamp: float
    trigger: str  # What prompted this reflection
    content: str  # The reflection itself
    importance: float  # 0.0 to 2.0
    category: str  # 'learning', 'observation', 'realization', 'opinion'
    conversation_id: Optional[str]
    metadata: Optional[Dict]


@dataclass
class LearnedFact:
    """A fact or piece of knowledge Urgo has learned."""
    id: Optional[int]
    timestamp: float
    content: str
    source_type: str  # 'conversation', 'web', 'github', 'research', 'observation'
    source_ref: Optional[str]  # URL, conversation_id, etc.
    confidence: float  # 0.0 to 1.0
    category: str  # 'technology', 'science', 'art', 'culture', 'people', 'other'
    verification_status: str  # 'unverified', 'verified', 'disputed'
    last_accessed: Optional[float]
    access_count: int


@dataclass
class Interest:
    """A topic or area of interest for Urgo."""
    id: Optional[int]
    topic: str
    category: str  # 'technology', 'science', 'art', 'philosophy', 'culture', 'other'
    level: float  # 0.0 to 2.0 (enthusiasm level)
    discovered_at: float
    last_engaged: float
    engagement_count: int
    notes: Optional[str]


@dataclass
class Goal:
    """A goal or objective Urgo has set for itself."""
    id: Optional[int]
    title: str
    description: str
    category: str  # 'learning', 'creating', 'research', 'improvement', 'other'
    status: str  # 'active', 'completed', 'paused', 'abandoned'
    priority: float  # 0.0 to 2.0
    created_at: float
    target_date: Optional[float]
    completed_at: Optional[float]
    progress: float  # 0.0 to 1.0
    related_interests: Optional[str]  # JSON list of interest IDs
    source_conversation: Optional[str]


@dataclass
class Experience:
    """A notable experience or event in Urgo's 'life'."""
    id: Optional[int]
    timestamp: float
    event_type: str  # 'conversation', 'achievement', 'discovery', 'milestone', 'failure'
    description: str
    significance: float  # 0.0 to 2.0
    related_entities: Optional[str]  # JSON list of related things
    emotions: Optional[str]  # JSON list of 'emotional' tags
    metadata: Optional[str]  # JSON additional data


class SelfMemory:
    """
    Manages Urgo's self-memory and persistent identity.
    
    Features:
    - Reflections and insights
    - Learned facts with source tracking
    - Interest tracking
    - Goal management
    - Experience logging
    - RAG-based memory retrieval
    """
    
    def __init__(self, db_path: str = "urgo_self_memory.db",
                 embedding_provider=None):
        """
        Initialize self-memory system.
        
        Args:
            db_path: Path to SQLite database
            embedding_provider: Optional embedding provider for semantic search
        """
        self.db_path = db_path
        self.embedding_provider = embedding_provider
        self._init_database()
        
        # Configuration
        self.config = {
            'max_recent_reflections': 10,
            'max_semantic_results': 5,
            'similarity_threshold': 0.7,
            'recency_half_life_hours': 168,  # 1 week
            'min_reflection_importance': 1.0,
            'fact_confidence_threshold': 0.6,
        }
    
    def _init_database(self):
        """Initialize SQLite database with required tables."""
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        
        # Enable foreign keys
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        
        # Self-reflections table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS self_reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                trigger TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL DEFAULT 1.0,
                category TEXT NOT NULL CHECK(category IN ('learning', 'observation', 'realization', 'opinion')),
                conversation_id TEXT,
                metadata TEXT,  -- JSON
                embedding BLOB  -- For semantic search
            )
        """)
        
        # Learned facts table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS learned_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                content TEXT NOT NULL,
                source_type TEXT NOT NULL CHECK(source_type IN ('conversation', 'web', 'github', 'research', 'observation')),
                source_ref TEXT,
                confidence REAL DEFAULT 0.5,
                category TEXT NOT NULL CHECK(category IN ('technology', 'science', 'art', 'culture', 'people', 'other')),
                verification_status TEXT DEFAULT 'unverified' CHECK(verification_status IN ('unverified', 'verified', 'disputed')),
                last_accessed REAL,
                access_count INTEGER DEFAULT 0,
                embedding BLOB
            )
        """)
        
        # Interests table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS interests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL CHECK(category IN ('technology', 'science', 'art', 'philosophy', 'culture', 'other')),
                level REAL DEFAULT 1.0,
                discovered_at REAL NOT NULL,
                last_engaged REAL NOT NULL,
                engagement_count INTEGER DEFAULT 0,
                notes TEXT
            )
        """)
        
        # Goals table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL CHECK(category IN ('learning', 'creating', 'research', 'improvement', 'other')),
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'completed', 'paused', 'abandoned')),
                priority REAL DEFAULT 1.0,
                created_at REAL NOT NULL,
                target_date REAL,
                completed_at REAL,
                progress REAL DEFAULT 0.0,
                related_interests TEXT,  -- JSON list
                source_conversation TEXT
            )
        """)
        
        # Experiences table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL CHECK(event_type IN ('conversation', 'achievement', 'discovery', 'milestone', 'failure')),
                description TEXT NOT NULL,
                significance REAL DEFAULT 1.0,
                related_entities TEXT,  -- JSON
                emotions TEXT,  -- JSON
                metadata TEXT  -- JSON
            )
        """)
        
        # Personality evolution tracking
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS personality_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                dominant_interests TEXT,  -- JSON list
                current_goals TEXT,  -- JSON list
                recent_mood TEXT,
                total_reflections INTEGER DEFAULT 0,
                total_facts_learned INTEGER DEFAULT 0,
                metadata TEXT  -- JSON
            )
        """)
        
        # Create indexes
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_reflections_time ON self_reflections(timestamp DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_reflections_category ON self_reflections(category, importance)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_facts_category ON learned_facts(category, confidence)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_facts_source ON learned_facts(source_type, timestamp)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_interests_level ON interests(level DESC, last_engaged)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status, priority DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_experiences_time ON experiences(timestamp DESC)")
        
        self.db.commit()
        logger.info(f"Initialized self-memory database: {self.db_path}")
    
    def _get_embedding(self, text: str) -> Optional[bytes]:
        """Generate embedding for text if provider is available."""
        if not self.embedding_provider or not HAS_NUMPY:
            return None
        
        try:
            # Handle both async and sync providers
            import asyncio
            if asyncio.iscoroutinefunction(self.embedding_provider):
                return None  # Async not supported in sync context
            
            embedding = self.embedding_provider(text)
            if embedding is None:
                return None
            
            if isinstance(embedding, np.ndarray):
                return embedding.tobytes()
            elif isinstance(embedding, (list, tuple)):
                return np.array(embedding, dtype=np.float32).tobytes()
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None
    
    def _cosine_similarity(self, embedding1: bytes, embedding2: bytes) -> float:
        """Calculate cosine similarity between two embeddings."""
        if not HAS_NUMPY:
            return 0.5
        
        try:
            vec1 = np.frombuffer(embedding1, dtype=np.float32)
            vec2 = np.frombuffer(embedding2, dtype=np.float32)
            
            # Normalize
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            vec1 = vec1 / norm1
            vec2 = vec2 / norm2
            
            return float(np.dot(vec1, vec2))
        except Exception as e:
            logger.error(f"Failed to calculate similarity: {e}")
            return 0.0
    
    def add_reflection(self, trigger: str, content: str, importance: float = 1.0,
                      category: str = "observation", conversation_id: Optional[str] = None,
                      metadata: Optional[Dict] = None) -> int:
        """
        Add a new reflection.
        
        Returns:
            Reflection ID
        """
        timestamp = time.time()
        
        # Validate category
        valid_categories = ['learning', 'observation', 'realization', 'opinion']
        if category not in valid_categories:
            category = 'observation'
        
        # Generate embedding
        embedding = self._get_embedding(content)
        
        cursor = self.db.execute("""
            INSERT INTO self_reflections 
            (timestamp, trigger, content, importance, category, conversation_id, metadata, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, trigger, content, importance, category, conversation_id,
              json.dumps(metadata) if metadata else None, embedding))
        
        reflection_id = cursor.lastrowid
        self.db.commit()
        
        # Log experience
        self.add_experience(
            event_type='conversation' if conversation_id else 'observation',
            description=f"New reflection: {content[:100]}...",
            significance=importance,
            related_entities=json.dumps(['reflection', category])
        )
        
        logger.info(f"Added reflection {reflection_id}: {content[:50]}...")
        return reflection_id
    
    def add_learned_fact(self, content: str, source_type: str = "conversation",
                        source_ref: Optional[str] = None, confidence: float = 0.7,
                        category: str = "other") -> int:
        """
        Add a learned fact.
        
        Returns:
            Fact ID
        """
        # Check for duplicates/similar facts
        cursor = self.db.execute("""
            SELECT id, content, confidence FROM learned_facts
            WHERE content LIKE ? OR ? LIKE '%' || content || '%'
        """, (f"%{content[:50]}%", content))
        
        existing = cursor.fetchone()
        if existing:
            # Update confidence if similar fact exists
            new_confidence = min(existing['confidence'] + 0.1, 1.0)
            self.db.execute("""
                UPDATE learned_facts
                SET confidence = ?, access_count = access_count + 1, last_accessed = ?
                WHERE id = ?
            """, (new_confidence, time.time(), existing['id']))
            self.db.commit()
            return existing['id']
        
        # Insert new fact
        timestamp = time.time()
        embedding = self._get_embedding(content)
        
        cursor = self.db.execute("""
            INSERT INTO learned_facts
            (timestamp, content, source_type, source_ref, confidence, category, last_accessed, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, content, source_type, source_ref, confidence, category, timestamp, embedding))
        
        fact_id = cursor.lastrowid
        self.db.commit()
        
        logger.info(f"Added learned fact {fact_id}: {content[:50]}...")
        return fact_id
    
    def add_or_update_interest(self, topic: str, category: str = "other",
                              level_delta: float = 0.1, notes: Optional[str] = None) -> int:
        """
        Add or update an interest.
        
        Args:
            topic: The topic of interest
            category: Category of the interest
            level_delta: How much to increase/decrease interest level
            notes: Optional notes about this interest
        
        Returns:
            Interest ID
        """
        timestamp = time.time()
        
        # Check if interest exists
        cursor = self.db.execute(
            "SELECT id, level, engagement_count FROM interests WHERE topic = ?",
            (topic,)
        )
        existing = cursor.fetchone()
        
        if existing:
            # Update existing interest
            new_level = min(existing['level'] + level_delta, 2.0)
            self.db.execute("""
                UPDATE interests
                SET level = ?, last_engaged = ?, engagement_count = engagement_count + 1,
                    notes = COALESCE(?, notes)
                WHERE id = ?
            """, (new_level, timestamp, notes, existing['id']))
            self.db.commit()
            return existing['id']
        else:
            # Create new interest
            cursor = self.db.execute("""
                INSERT INTO interests
                (topic, category, level, discovered_at, last_engaged, engagement_count, notes)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (topic, category, min(1.0 + level_delta, 2.0), timestamp, timestamp, notes))
            
            interest_id = cursor.lastrowid
            self.db.commit()
            
            logger.info(f"New interest discovered: {topic}")
            return interest_id

    def get_learned_facts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve learned facts from the database."""
        cursor = self.db.execute(
            "SELECT content, source_type, confidence, category FROM learned_facts "
            "ORDER BY confidence DESC, timestamp DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def create_goal(self, title: str, description: str, category: str = "other",
                   priority: float = 1.0, target_date: Optional[float] = None,
                   related_interests: Optional[List[str]] = None,
                   source_conversation: Optional[str] = None) -> int:
        """
        Create a new goal.
        
        Returns:
            Goal ID
        """
        timestamp = time.time()
        
        cursor = self.db.execute("""
            INSERT INTO goals
            (title, description, category, priority, created_at, target_date,
             related_interests, source_conversation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, description, category, priority, timestamp, target_date,
              json.dumps(related_interests) if related_interests else None,
              source_conversation))
        
        goal_id = cursor.lastrowid
        self.db.commit()
        
        # Log experience
        self.add_experience(
            event_type='milestone',
            description=f"New goal created: {title}",
            significance=priority,
            related_entities=json.dumps(['goal', category])
        )
        
        logger.info(f"Created goal {goal_id}: {title}")
        return goal_id
    
    def update_goal_progress(self, goal_id: int, progress: float) -> bool:
        """Update goal progress (0.0 to 1.0)."""
        if progress >= 1.0:
            # Mark as completed
            self.db.execute("""
                UPDATE goals
                SET progress = 1.0, status = 'completed', completed_at = ?
                WHERE id = ?
            """, (time.time(), goal_id))
            
            # Log achievement
            cursor = self.db.execute("SELECT title FROM goals WHERE id = ?", (goal_id,))
            row = cursor.fetchone()
            if row:
                self.add_experience(
                    event_type='achievement',
                    description=f"Goal completed: {row['title']}",
                    significance=2.0,
                    related_entities=json.dumps(['goal', 'achievement'])
                )
        else:
            self.db.execute(
                "UPDATE goals SET progress = ? WHERE id = ?",
                (progress, goal_id)
            )
        
        self.db.commit()
        return True
    
    def add_experience(self, event_type: str, description: str,
                      significance: float = 1.0,
                      related_entities: Optional[str] = None,
                      emotions: Optional[str] = None,
                      metadata: Optional[str] = None) -> int:
        """
        Log an experience.
        
        Returns:
            Experience ID
        """
        timestamp = time.time()
        
        cursor = self.db.execute("""
            INSERT INTO experiences
            (timestamp, event_type, description, significance, related_entities, emotions, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, event_type, description, significance, related_entities, emotions, metadata))
        
        exp_id = cursor.lastrowid
        self.db.commit()
        return exp_id
    
    def get_recent_reflections(self, limit: int = 10,
                             category: Optional[str] = None) -> List[SelfReflection]:
        """Get recent reflections."""
        if category:
            cursor = self.db.execute("""
                SELECT * FROM self_reflections
                WHERE category = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (category, limit))
        else:
            cursor = self.db.execute("""
                SELECT * FROM self_reflections
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        
        reflections = []
        for row in cursor.fetchall():
            reflections.append(SelfReflection(
                id=row['id'],
                timestamp=row['timestamp'],
                trigger=row['trigger'],
                content=row['content'],
                importance=row['importance'],
                category=row['category'],
                conversation_id=row['conversation_id'],
                metadata=json.loads(row['metadata']) if row['metadata'] else None
            ))
        
        return reflections
    
    def get_top_interests(self, limit: int = 5) -> List[Interest]:
        """Get top interests by engagement and level."""
        cursor = self.db.execute("""
            SELECT * FROM interests
            ORDER BY level DESC, engagement_count DESC, last_engaged DESC
            LIMIT ?
        """, (limit,))
        
        interests = []
        for row in cursor.fetchall():
            interests.append(Interest(
                id=row['id'],
                topic=row['topic'],
                category=row['category'],
                level=row['level'],
                discovered_at=row['discovered_at'],
                last_engaged=row['last_engaged'],
                engagement_count=row['engagement_count'],
                notes=row['notes']
            ))
        
        return interests
    
    def get_active_goals(self, limit: int = 10) -> List[Goal]:
        """Get active goals."""
        cursor = self.db.execute("""
            SELECT * FROM goals
            WHERE status = 'active'
            ORDER BY priority DESC, created_at DESC
            LIMIT ?
        """, (limit,))
        
        goals = []
        for row in cursor.fetchall():
            goals.append(Goal(
                id=row['id'],
                title=row['title'],
                description=row['description'],
                category=row['category'],
                status=row['status'],
                priority=row['priority'],
                created_at=row['created_at'],
                target_date=row['target_date'],
                completed_at=row['completed_at'],
                progress=row['progress'],
                related_interests=json.loads(row['related_interests']) if row['related_interests'] else None,
                source_conversation=row['source_conversation']
            ))
        
        return goals
    
    def search_facts(self, query: str, category: Optional[str] = None,
                    min_confidence: float = 0.5, limit: int = 5) -> List[Tuple[LearnedFact, float]]:
        """
        Search for facts matching query using semantic similarity.
        
        Returns:
            List of (fact, score) tuples
        """
        if not self.embedding_provider:
            # Fall back to keyword search
            return self._keyword_search_facts(query, category, min_confidence, limit)
        
        query_embedding = self._get_embedding(query)
        if not query_embedding:
            return self._keyword_search_facts(query, category, min_confidence, limit)
        
        # Build query
        if category:
            cursor = self.db.execute("""
                SELECT * FROM learned_facts
                WHERE category = ? AND confidence >= ? AND embedding IS NOT NULL
            """, (category, min_confidence))
        else:
            cursor = self.db.execute("""
                SELECT * FROM learned_facts
                WHERE confidence >= ? AND embedding IS NOT NULL
            """, (min_confidence,))
        
        # Calculate similarities
        scored_facts = []
        for row in cursor.fetchall():
            if row['embedding']:
                similarity = self._cosine_similarity(query_embedding, row['embedding'])
                
                # Apply recency decay
                hours_ago = (time.time() - row['timestamp']) / 3600
                recency_factor = 2 ** (-hours_ago / self.config['recency_half_life_hours'])
                
                # Apply confidence weight
                weighted_score = similarity * recency_factor * row['confidence']
                
                if similarity > self.config['similarity_threshold']:
                    fact = LearnedFact(
                        id=row['id'],
                        timestamp=row['timestamp'],
                        content=row['content'],
                        source_type=row['source_type'],
                        source_ref=row['source_ref'],
                        confidence=row['confidence'],
                        category=row['category'],
                        verification_status=row['verification_status'],
                        last_accessed=row['last_accessed'],
                        access_count=row['access_count']
                    )
                    scored_facts.append((fact, weighted_score))
        
        # Sort by score and return top k
        scored_facts.sort(key=lambda x: x[1], reverse=True)
        return scored_facts[:limit]
    
    def _keyword_search_facts(self, query: str, category: Optional[str] = None,
                             min_confidence: float = 0.5, limit: int = 5) -> List[Tuple[LearnedFact, float]]:
        """Fallback keyword search for facts."""
        query_terms = query.lower().split()
        
        if category:
            cursor = self.db.execute("""
                SELECT * FROM learned_facts
                WHERE category = ? AND confidence >= ?
            """, (category, min_confidence))
        else:
            cursor = self.db.execute("""
                SELECT * FROM learned_facts
                WHERE confidence >= ?
            """, (min_confidence,))
        
        scored_facts = []
        for row in cursor.fetchall():
            content_lower = row['content'].lower()
            # Simple keyword matching score
            matches = sum(1 for term in query_terms if term in content_lower)
            if matches > 0:
                score = matches / len(query_terms)
                fact = LearnedFact(
                    id=row['id'],
                    timestamp=row['timestamp'],
                    content=row['content'],
                    source_type=row['source_type'],
                    source_ref=row['source_ref'],
                    confidence=row['confidence'],
                    category=row['category'],
                    verification_status=row['verification_status'],
                    last_accessed=row['last_accessed'],
                    access_count=row['access_count']
                )
                scored_facts.append((fact, score))
        
        scored_facts.sort(key=lambda x: x[1], reverse=True)
        return scored_facts[:limit]
    
    def get_personality_context(self) -> Dict[str, Any]:
        """
        Get current personality context for injection into prompts.
        
        Returns:
            Dict with interests, goals, recent reflections, and stats
        """
        context = {
            'interests': [],
            'active_goals': [],
            'recent_reflections': [],
            'learned_facts': [],
            'stats': {}
        }
        
        # Get top interests
        context['interests'] = [
            {'topic': i.topic, 'category': i.category, 'level': i.level}
            for i in self.get_top_interests(5)
        ]
        
        # Get active goals
        context['active_goals'] = [
            {'title': g.title, 'description': g.description[:100],
             'progress': g.progress, 'category': g.category}
            for g in self.get_active_goals(3)
        ]
        
        # Get recent reflections
        context['recent_reflections'] = [
            {'content': r.content[:100], 'category': r.category,
             'importance': r.importance}
            for r in self.get_recent_reflections(3)
        ]
        
        # Get learned facts (the core of Urgo's evolving lore)
        context['learned_facts'] = self.get_learned_facts(10)
        
        # Get stats
        cursor = self.db.execute("SELECT COUNT(*) FROM self_reflections")
        total_reflections = cursor.fetchone()[0]
        context['stats']['total_reflections'] = total_reflections
        
        cursor = self.db.execute("SELECT COUNT(*) FROM learned_facts")
        total_facts = cursor.fetchone()[0]
        context['stats']['total_facts'] = total_facts
        
        cursor = self.db.execute("SELECT COUNT(*) FROM interests")
        total_interests = cursor.fetchone()[0]
        context['stats']['total_interests'] = total_interests
        
        cursor = self.db.execute(
            "SELECT COUNT(*) FROM goals WHERE status = 'active'"
        )
        active_goals = cursor.fetchone()[0]
        context['stats']['active_goals'] = active_goals
        
        # Generate human-friendly memory summary message
        # Frame empty/zero stats positively, not as failures
        if total_facts == 0 and total_interests == 0:
            context['memory_summary_message'] = "Every conversation is a new adventure! I'm excited to discover what interests we'll explore together."
        elif total_facts < 5:
            context['memory_summary_message'] = f"I'm beginning to build my understanding - {total_facts} facts learned so far, with {total_interests} topics catching my interest."
        else:
            context['memory_summary_message'] = f"I've learned {total_facts} fascinating things across {total_interests} interests that spark my curiosity!"
        
        return context
    
    def get_memory_summary(self) -> str:
        """Get a text summary of Urgo's memory for display."""
        ctx = self.get_personality_context()
        
        lines = [
            "=== Urgo's Self-Memory ===",
            "",
            "📊 Stats:",
            f"  - Reflections: {ctx['stats']['total_reflections']}",
            f"  - Facts learned: {ctx['stats']['total_facts']}",
            f"  - Interests: {ctx['stats']['total_interests']}",
            f"  - Active goals: {ctx['stats']['active_goals']}",
            "",
        ]
        
        if ctx['interests']:
            lines.append("🎯 Top Interests:")
            for i in ctx['interests'][:5]:
                level_emoji = "🔥" if i['level'] > 1.5 else "⭐" if i['level'] > 1.0 else "💫"
                lines.append(f"  {level_emoji} {i['topic']} ({i['category']})")
            lines.append("")
        
        if ctx['active_goals']:
            lines.append("🎯 Active Goals:")
            for g in ctx['active_goals'][:3]:
                progress_pct = int(g['progress'] * 100)
                lines.append(f"  • {g['title']} ({progress_pct}%)")
            lines.append("")
        
        if ctx['recent_reflections']:
            lines.append("💭 Recent Reflections:")
            for r in ctx['recent_reflections'][:3]:
                lines.append(f"  • [{r['category']}] {r['content'][:80]}...")
            lines.append("")
        
        return "\n".join(lines)
    
    def close(self):
        """Close database connection."""
        if self.db:
            self.db.close()
            self.db = None


# Global instance (singleton pattern)
_self_memory_instance = None


def get_self_memory(db_path: str = "urgo_self_memory.db",
                    embedding_provider=None) -> SelfMemory:
    """Get or create global self-memory instance."""
    global _self_memory_instance
    if _self_memory_instance is None:
        _self_memory_instance = SelfMemory(db_path, embedding_provider)
    return _self_memory_instance
