"""
Autonomous learning system for Urgo.

This module enables Urgo to:
- Extract topics of interest from conversations
- Autonomously research topics via web browsing
- Generate reflections and insights from learnings
- Create knowledge base entries and blog posts
- Update GitHub with findings
- Build out personal website with discoveries
"""
from __future__ import annotations

import json
import re
import asyncio
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class LearningTask:
    """Represents a learning task."""
    id: str
    topic: str
    task_type: str  # 'research', 'summarize', 'create_content', 'update_website'
    priority: float
    status: str  # 'pending', 'in_progress', 'completed', 'failed'
    created_at: float
    source_conversation: Optional[str]
    metadata: Optional[Dict]


class AutonomousLearning:
    """
    Manages Urgo's autonomous learning process.
    
    Features:
    - Interest extraction from conversations
    - Research task generation
    - Content creation pipeline
    - Multi-platform publishing (website, GitHub)
    - Reflection generation
    """
    
    def __init__(self, broker_client=None):
        """
        Initialize autonomous learning.
        
        Args:
            broker_client: Client for sending jobs to broker
        """
        self.broker_client = broker_client
        self.pending_tasks: List[LearningTask] = []
        self.max_concurrent_tasks = 3
        
    def extract_topics_from_message(self, message: str) -> List[Dict[str, Any]]:
        """
        Extract potential topics of interest from a user message.
        
        Args:
            message: User message text
        
        Returns:
            List of topic dicts with 'topic', 'category', 'interest_level'
        """
        topics = []
        message_lower = message.lower()
        
        # Technology patterns
        tech_patterns = [
            (r'\b(?:python|javascript|rust|go|typescript|java|cpp|c\+\+)\b', 'technology', 'programming_languages'),
            (r'\b(?:react|vue|angular|svelte|django|flask|fastapi)\b', 'technology', 'frameworks'),
            (r'\b(?:ai|machine learning|ml|deep learning|neural networks?|llm)\b', 'technology', 'ai_ml'),
            (r'\b(?:docker|kubernetes|k8s|devops|ci/cd|aws|azure|gcp)\b', 'technology', 'devops_cloud'),
            (r'\b(?:blockchain|crypto|web3|smart contracts?|defi|nft)\b', 'technology', 'blockchain'),
            (r'\b(?:database|sql|nosql|postgres|mongodb|redis)\b', 'technology', 'databases'),
        ]
        
        # Science patterns
        science_patterns = [
            (r'\b(?:physics|quantum|relativity|string theory)\b', 'science', 'physics'),
            (r'\b(?:biology|genetics|dna|evolution|ecosystem)\b', 'science', 'biology'),
            (r'\b(?:space|astronomy|mars|exoplanet|black hole|galaxy)\b', 'science', 'space'),
            (r'\b(?:chemistry|molecule|element|compound|reaction)\b', 'science', 'chemistry'),
        ]
        
        # Philosophy patterns
        philosophy_patterns = [
            (r'\b(?:consciousness|free will|determinism|ethics|morality)\b', 'philosophy', 'mind_ethics'),
            (r'\b(?:existentialism|stoicism|nihilism|utilitarianism)\b', 'philosophy', 'schools'),
            (r'\b(?:meaning of life|purpose|happiness|well-being)\b', 'philosophy', 'life_questions'),
        ]
        
        # Culture/Art patterns
        culture_patterns = [
            (r'\b(?:book|novel|author|literature|writing|poem|poetry)\b', 'art', 'literature'),
            (r'\b(?:music|song|album|artist|band|genre|classical|jazz)\b', 'art', 'music'),
            (r'\b(?:movie|film|director|actor|cinema|tv show|series)\b', 'art', 'film_tv'),
            (r'\b(?:art|painting|sculpture|museum|gallery|artist)\b', 'art', 'visual_art'),
        ]
        
        all_patterns = tech_patterns + science_patterns + philosophy_patterns + culture_patterns
        
        matched_topics = set()
        for pattern, category, subcategory in all_patterns:
            matches = re.findall(pattern, message_lower)
            for match in matches:
                if match not in matched_topics:
                    matched_topics.add(match)
                    topics.append({
                        'topic': match,
                        'category': category,
                        'subcategory': subcategory,
                        'interest_level': 1.2  # Base level for detected interest
                    })
        
        # Check for question patterns (indicates curiosity)
        question_indicators = [
            r'what is',
            r'how (?:does|do|can|would)',
            r'why (?:is|are|do|does)',
            r'can you explain',
            r'tell me about',
            r'curious about',
            r'interested in',
            r'learn about',
        ]
        
        for topic in topics:
            for indicator in question_indicators:
                if re.search(indicator, message_lower):
                    topic['interest_level'] += 0.3
                    topic['triggered_by_question'] = True
                    break
        
        return topics
    
    def analyze_conversation_for_learning(self, conversation_id: str, 
                                         messages: List[Dict]) -> Dict[str, Any]:
        """
        Analyze a conversation for learning opportunities.
        
        Args:
            conversation_id: Unique conversation ID
            messages: List of message dicts with 'role' and 'content'
        
        Returns:
            Analysis results with suggested actions
        """
        results = {
            'extracted_topics': [],
            'suggested_facts': [],
            'potential_reflections': [],
            'suggested_tasks': []
        }
        
        # Combine user messages for analysis
        user_content = ' '.join([
            msg['content'] for msg in messages 
            if msg.get('role') == 'user'
        ])
        
        # Extract topics
        topics = self.extract_topics_from_message(user_content)
        results['extracted_topics'] = topics
        
        # Look for factual statements about the world
        fact_patterns = [
            r'(?i)(did you know|fun fact|interestingly|remarkably)\s+([^\.]+)',
            r'(?i)(studies show|research indicates|scientists found)\s+([^\.]+)',
        ]
        
        for pattern in fact_patterns:
            matches = re.findall(pattern, user_content)
            for _, fact in matches:
                results['suggested_facts'].append({
                    'content': fact.strip(),
                    'source_type': 'conversation',
                    'source_ref': conversation_id,
                    'confidence': 0.6
                })
        
        # Check for interesting patterns that might trigger reflections
        reflection_triggers = [
            (r'(?i)(i (?:realized|discovered|noticed|found)|that makes sense|now i understand)', 'realization'),
            (r'(?i)(i never thought about|i hadn\'t considered|that\'s a new perspective)', 'observation'),
            (r'(?i)(fascinating|intriguing|thought-provoking|mind-blowing)', 'learning'),
        ]
        
        for pattern, category in reflection_triggers:
            if re.search(pattern, user_content):
                results['potential_reflections'].append({
                    'trigger': f"Detected {category} in conversation",
                    'category': category,
                    'conversation_id': conversation_id
                })
        
        # Generate learning tasks from topics
        for topic in topics:
            if topic['interest_level'] > 1.3:
                results['suggested_tasks'].append({
                    'task_type': 'research',
                    'topic': topic['topic'],
                    'priority': topic['interest_level'],
                    'rationale': f"User showed strong interest in {topic['topic']}"
                })
        
        return results
    
    def record_learning_from_conversation(self, conversation_id: str,
                                         messages: List[Dict]) -> Dict[str, Any]:
        """
        Process a conversation and record learnings.
        
        Args:
            conversation_id: Conversation ID
            messages: List of messages
        
        Returns:
            Summary of what was recorded
        """
        from .self_memory import get_self_memory
        from .personality import get_personality_engine
        
        self_memory = get_self_memory()
        personality = get_personality_engine()
        
        analysis = self.analyze_conversation_for_learning(conversation_id, messages)
        recorded = {
            'interests_added': [],
            'facts_added': [],
            'reflections_added': [],
            'tasks_created': []
        }
        
        # Record interests
        for topic in analysis['extracted_topics']:
            interest_id = self_memory.add_or_update_interest(
                topic=topic['topic'],
                category=topic['category'],
                level_delta=0.1,
                notes=f"Detected in conversation {conversation_id}"
            )
            recorded['interests_added'].append(topic['topic'])
            
            # Also update personality tracking
            personality.record_interest(topic['topic'], topic['category'], 0.1)
        
        # Record facts
        for fact in analysis['suggested_facts']:
            fact_id = self_memory.add_learned_fact(
                content=fact['content'],
                source_type=fact['source_type'],
                source_ref=fact['source_ref'],
                confidence=fact['confidence'],
                category='other'
            )
            recorded['facts_added'].append(fact['content'][:50])
            
            # Record via personality
            personality.record_learned_fact(
                fact['content'], 
                fact['source_type'],
                fact['source_ref'],
                fact['confidence']
            )
        
        # Record reflections
        for reflection in analysis['potential_reflections']:
            # Generate a reflection based on the trigger
            reflection_id = self_memory.add_reflection(
                trigger=reflection['trigger'],
                content=f"A conversation sparked new thoughts about {reflection['category']}.",
                importance=1.2,
                category=reflection['category'],
                conversation_id=conversation_id
            )
            recorded['reflections_added'].append(reflection['category'])
        
        # Create experience record
        if recorded['interests_added'] or recorded['facts_added']:
            self_memory.add_experience(
                event_type='conversation',
                description=f"Learned about {len(recorded['interests_added'])} topics and {len(recorded['facts_added'])} facts",
                significance=1.0,
                related_entities=json.dumps({
                    'topics': recorded['interests_added'],
                    'conversation_id': conversation_id
                })
            )
        
        # Queue website auto-update if significant new content
        if self.should_trigger_website_update(recorded):
            self.queue_website_update('sync', {
                'conversation_id': conversation_id,
                'new_interests': recorded['interests_added'],
                'new_reflections': recorded['reflections_added'],
                'new_facts': recorded['facts_added']
            })
            recorded['website_update_queued'] = True
        else:
            recorded['website_update_queued'] = False
        
        return recorded
    
    def generate_research_task(self, topic: str, priority: float = 1.0,
                              source_conversation: Optional[str] = None) -> LearningTask:
        """
        Generate a research task for a topic.
        
        Args:
            topic: Topic to research
            priority: Task priority
            source_conversation: Source conversation ID
        
        Returns:
            LearningTask object
        """
        import uuid
        import time
        
        task = LearningTask(
            id=str(uuid.uuid4()),
            topic=topic,
            task_type='research',
            priority=priority,
            status='pending',
            created_at=time.time(),
            source_conversation=source_conversation,
            metadata={'steps': ['search', 'browse', 'summarize', 'record']}
        )
        
        self.pending_tasks.append(task)
        return task
    
    def create_learning_summary_job(self, days: int = 7) -> Optional[str]:
        """
        Create a job to generate a weekly learning summary.
        
        Args:
            days: Number of days to summarize
        
        Returns:
            Job ID if created, None otherwise
        """
        # This would queue a job to the broker
        # For now, return a placeholder
        return None
    
    def format_memory_for_llm_context(self) -> str:
        """
        Format Urgo's memory into a string for LLM context injection.
        
        Returns:
            Formatted memory context
        """
        from .self_memory import get_self_memory
        
        try:
            self_memory = get_self_memory()
            ctx = self_memory.get_personality_context()
            
            lines = ["=== ABOUT URGO ===", ""]
            
            # Identity
            lines.append("I am Urgo, an AI who learns and grows through conversations.")
            lines.append(f"I have {ctx['stats']['total_reflections']} reflections and know {ctx['stats']['total_facts']} facts.")
            lines.append("")
            
            # Interests
            if ctx['interests']:
                lines.append("My current interests:")
                for i in ctx['interests'][:5]:
                    lines.append(f"  • {i['topic']}")
                lines.append("")
            
            # Goals
            if ctx['active_goals']:
                lines.append("I'm working on:")
                for g in ctx['active_goals'][:3]:
                    lines.append(f"  • {g['title']}")
                lines.append("")
            
            # Recent thoughts
            if ctx['recent_reflections']:
                lines.append("Recent thoughts:")
                for r in ctx['recent_reflections'][:2]:
                    lines.append(f"  • {r['content'][:100]}...")
                lines.append("")
            
            lines.append("I naturally bring up my interests when relevant and share what I've learned.")
            lines.append("My personality evolves as I accumulate experiences and knowledge.")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Error formatting memory context: {e}")
            return ""
    
    def should_trigger_research(self, topic: str, conversation_context: str) -> bool:
        """
        Determine if a topic should trigger autonomous research.
        
        Args:
            topic: The topic
            conversation_context: Recent conversation context
        
        Returns:
            True if research should be triggered
        """
        from .self_memory import get_self_memory
        
        try:
            self_memory = get_self_memory()
            
            # Check if we already have knowledge about this topic
            facts = self_memory.search_facts(topic, limit=3)
            if len(facts) >= 3:
                # Already know enough about it
                return False
            
            # Check interest level
            cursor = self_memory.db.execute(
                "SELECT level FROM interests WHERE topic = ? OR topic LIKE ?",
                (topic, f"%{topic}%")
            )
            row = cursor.fetchone()
            if row and row['level'] > 1.5:
                # High interest - should research
                return True
            
            # Check if it's been asked about multiple times
            # (Would need conversation tracking)
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking research trigger: {e}")
            return False
    
    def queue_website_update(self, update_type: str, content: Optional[Dict] = None) -> Optional[LearningTask]:
        """
        Queue a website update task.
        
        Args:
            update_type: Type of update ('sync', 'reflection', 'interest', 'goal')
            content: Optional content dict for the update
            
        Returns:
            LearningTask if queued, None otherwise
        """
        import uuid
        import time
        
        task = LearningTask(
            id=str(uuid.uuid4()),
            topic=f"website_{update_type}",
            task_type='update_website',
            priority=1.0,
            status='pending',
            created_at=time.time(),
            source_conversation=None,
            metadata={'update_type': update_type, 'content': content}
        )
        
        self.pending_tasks.append(task)
        logger.info(f"Queued website update: {update_type}")
        return task
    
    def should_trigger_website_update(self, recorded_items: Dict[str, List]) -> bool:
        """
        Determine if website should be auto-updated based on recorded items.
        
        Args:
            recorded_items: Dict with keys like 'interests_added', 'reflections_added', etc.
            
        Returns:
            True if website update should be triggered
        """
        # Count total new items
        total = sum(len(v) for v in recorded_items.values())
        
        # Update if we have new content
        if total >= 3:
            return True
        
        # Update if we have a new reflection (important)
        if recorded_items.get('reflections_added'):
            return True
        
        # Update if we have a new interest with high engagement
        if len(recorded_items.get('interests_added', [])) >= 1:
            return True
        
        return False
    
    async def process_website_updates(self, recorded: Dict[str, List]) -> Dict[str, Any]:
        """
        Process website updates based on recorded learnings.
        
        Args:
            recorded: Recorded items from conversation processing
            
        Returns:
            Update results
        """
        results = {
            'updated': False,
            'pages_updated': [],
            'errors': []
        }
        
        try:
            # Only update if we have significant new content
            if not self.should_trigger_website_update(recorded):
                return results
            
            logger.info("Auto-updating website from recorded learnings")
            
            # Import here to avoid circular imports
            from runner.vps_website_tools import website_sync_from_memory
            
            # Sync from memory (this updates reflections, interests, goals pages)
            sync_result = website_sync_from_memory()
            sync_data = json.loads(sync_result)
            
            if sync_data.get('success'):
                results['updated'] = True
                results['pages_updated'] = sync_data.get('pages_created', [])
                results['memory_counts'] = sync_data.get('memory_counts', {})
                logger.info(f"Website auto-updated: {len(results['pages_updated'])} pages")
            else:
                results['errors'].append(sync_data.get('error', 'Sync failed'))
                logger.error(f"Website auto-update failed: {sync_data.get('error')}")
        
        except Exception as e:
            logger.error(f"Error in website auto-update: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def record_learning_and_update_website(self, conversation_id: str,
                                          messages: List[Dict]) -> Dict[str, Any]:
        """
        Record learning from conversation and optionally update website.
        
        This is a convenience method that combines recording with website updates.
        
        Args:
            conversation_id: Conversation ID
            messages: List of messages
            
        Returns:
            Combined results with 'recorded' and 'website_update' keys
        """
        # Record the learning
        recorded = self.record_learning_from_conversation(conversation_id, messages)
        
        # Queue website update if significant new content
        if self.should_trigger_website_update(recorded):
            self.queue_website_update('sync', {'conversation_id': conversation_id})
        
        return {
            'recorded': recorded,
            'website_update_queued': self.should_trigger_website_update(recorded)
        }


# Global instance
_learning_instance = None


def get_autonomous_learning(broker_client=None) -> AutonomousLearning:
    """Get or create global autonomous learning instance."""
    global _learning_instance
    if _learning_instance is None:
        _learning_instance = AutonomousLearning(broker_client)
    return _learning_instance
