"""
Embedding providers for conversation memory and RAG.

Supports:
- OpenAI embeddings (text-embedding-3-small, text-embedding-3-large, ada-002)
- Local embeddings via sentence-transformers
- Mock embeddings (for testing without external dependencies)
"""

import os
import logging
from typing import Optional, List
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""
    
    @abstractmethod
    async def embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text. Returns list of floats or None on error."""
        pass
    
    @abstractmethod
    def embed_sync(self, text: str) -> Optional[List[float]]:
        """Synchronous version of embed."""
        pass
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider name."""
        pass


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI API embedding provider."""
    
    DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }
    
    def __init__(self, api_key: Optional[str] = None, model: str = "text-embedding-3-small"):
        """
        Initialize OpenAI embedding provider.
        
        Args:
            api_key: OpenAI API key (or from OPENAI_API_KEY env var)
            model: Model name (text-embedding-3-small, text-embedding-3-large, ada-002)
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self._client = None
        
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY or pass api_key.")
        
        if model not in self.DIMENSIONS:
            raise ValueError(f"Unknown model: {model}. Choose from: {list(self.DIMENSIONS.keys())}")
        
        try:
            import openai
            self._client = openai.AsyncOpenAI(api_key=self.api_key)
            logger.info(f"OpenAI embedding provider initialized ({model})")
        except ImportError:
            raise ImportError("openai package required. Install: pip install openai")
    
    async def embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding via OpenAI API."""
        if not self._client:
            return None
        
        try:
            # Truncate to token limit (approximate: 4 chars per token)
            truncated = text[:8000]
            
            response = await self._client.embeddings.create(
                model=self.model,
                input=truncated
            )
            
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"OpenAI embedding error: {e}")
            return None
    
    def embed_sync(self, text: str) -> Optional[List[float]]:
        """Synchronous embedding (not recommended for async apps)."""
        import asyncio
        try:
            return asyncio.run(self.embed(text))
        except Exception as e:
            logger.error(f"Sync embedding error: {e}")
            return None
    
    @property
    def dimension(self) -> int:
        return self.DIMENSIONS.get(self.model, 1536)
    
    @property
    def name(self) -> str:
        return f"openai-{self.model}"


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local embedding provider using sentence-transformers."""
    
    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    DIMENSIONS = {
        "all-MiniLM-L6-v2": 384,
        "all-mpnet-base-v2": 768,
        "all-distilroberta-v1": 768,
        "paraphrase-multilingual-MiniLM-L12-v2": 384,
    }
    
    def __init__(self, model_name: Optional[str] = None, device: str = "cpu"):
        """
        Initialize local embedding provider.
        
        Args:
            model_name: sentence-transformers model name
            device: "cpu" or "cuda" (if available)
        """
        self.model_name = model_name or self.DEFAULT_MODEL
        self.device = device
        self._model = None
        
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading local embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name, device=device)
            logger.info(f"Local embedding provider initialized ({self.model_name})")
        except ImportError:
            raise ImportError(
                "sentence-transformers required. Install: pip install sentence-transformers"
            )
    
    async def embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding locally."""
        return self.embed_sync(text)
    
    def embed_sync(self, text: str) -> Optional[List[float]]:
        """Generate embedding synchronously."""
        if not self._model:
            return None
        
        try:
            # Truncate if needed
            truncated = text[:10000]

            # Generate embedding
            embedding = self._model.encode(truncated, convert_to_numpy=True)

            # Convert to list of floats
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Local embedding error: {e}")
            return None
    
    @property
    def dimension(self) -> int:
        return self.DIMENSIONS.get(self.model_name, 384)
    
    @property
    def name(self) -> str:
        return f"local-{self.model_name}"


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock embedding provider for testing (generates random embeddings)."""
    
    def __init__(self, dimension: int = 384, seed: int = 42):
        """
        Initialize mock provider.
        
        Args:
            dimension: Embedding dimension
            seed: Random seed for reproducibility
        """
        self._dimension = dimension
        self._seed = seed
        import random
        self._rng = random.Random(seed)
        logger.info(f"Mock embedding provider initialized (dim={dimension})")
    
    def _generate(self, text: str) -> List[float]:
        """Generate deterministic mock embedding based on text hash."""
        import hashlib
        import random
        
        # Use text hash as seed for reproducibility
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        rng = random.Random(hash_val)
        
        # Generate embedding
        return [rng.random() * 2 - 1 for _ in range(self._dimension)]
    
    async def embed(self, text: str) -> Optional[List[float]]:
        return self._generate(text)
    
    def embed_sync(self, text: str) -> Optional[List[float]]:
        return self._generate(text)
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    @property
    def name(self) -> str:
        return f"mock-{self._dimension}d"


class LiteLLMEmbeddingProvider(EmbeddingProvider):
    """LiteLLM embedding provider for multiple backends (OpenAI, Anthropic, etc.)."""
    
    def __init__(self, model: str = "openai/text-embedding-3-small"):
        """
        Initialize LiteLLM provider.
        
        Args:
            model: LiteLLM model string (e.g., "openai/text-embedding-3-small",
                  "anthropic/claude", "cohere/embed-english-v3")
        """
        self.model = model
        self._dimension = 1536  # Default, varies by model
        
        try:
            import importlib.util
            if not importlib.util.find_spec("litellm"):
                raise ImportError("litellm required. Install: pip install litellm")
            logger.info(f"LiteLLM embedding provider initialized ({model})")
        except ImportError:
            raise ImportError("litellm required. Install: pip install litellm")
    
    async def embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding via LiteLLM."""
        try:
            import litellm
            
            response = await litellm.aembedding(
                model=self.model,
                input=text[:8000]
            )
            
            return response.data[0]["embedding"]
        except Exception as e:
            logger.error(f"LiteLLM embedding error: {e}")
            return None
    
    def embed_sync(self, text: str) -> Optional[List[float]]:
        """Synchronous embedding."""
        import asyncio
        try:
            return asyncio.run(self.embed(text))
        except Exception as e:
            logger.error(f"Sync embedding error: {e}")
            return None
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    @property
    def name(self) -> str:
        return f"litellm-{self.model.replace('/', '-')}"


def create_embedding_provider(
    provider_type: str = "auto",
    **kwargs
) -> Optional[EmbeddingProvider]:
    """
    Factory function to create embedding provider.
    
    Args:
        provider_type: 'openai', 'local', 'litellm', 'mock', or 'auto'
        **kwargs: Provider-specific arguments
    
    Returns:
        EmbeddingProvider instance or None if creation fails
    
    Examples:
        # OpenAI
        provider = create_embedding_provider('openai', api_key='sk-...')
        
        # Local (sentence-transformers)
        provider = create_embedding_provider('local', model_name='all-MiniLM-L6-v2')
        
        # Auto-detect (tries local, then openai if keys available)
        provider = create_embedding_provider('auto')
    """
    provider_type = provider_type.lower()
    
    if provider_type == "auto":
        # Try local first (no API costs), then OpenAI
        try:
            return LocalEmbeddingProvider(**kwargs)
        except ImportError:
            logger.info("Local embeddings not available, trying OpenAI...")
        
        try:
            return OpenAIEmbeddingProvider(**kwargs)
        except (ValueError, ImportError) as e:
            logger.warning(f"OpenAI embeddings not available: {e}")
        
        # Fallback to mock
        logger.warning("Falling back to mock embeddings (not for production)")
        return MockEmbeddingProvider()
    
    elif provider_type == "openai":
        return OpenAIEmbeddingProvider(**kwargs)
    
    elif provider_type == "local":
        return LocalEmbeddingProvider(**kwargs)
    
    elif provider_type == "litellm":
        return LiteLLMEmbeddingProvider(**kwargs)
    
    elif provider_type == "mock":
        dimension = kwargs.get('dimension', 384)
        return MockEmbeddingProvider(dimension)
    
    elif provider_type == "none" or provider_type == "":
        return None
    
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    try:
        import numpy as np
        
        a = np.array(vec1)
        b = np.array(vec2)
        
        # Normalize
        a_norm = a / np.linalg.norm(a)
        b_norm = b / np.linalg.norm(b)
        
        return float(np.dot(a_norm, b_norm))
    except ImportError:
        # Fallback to pure Python
        import math
        
        dot = sum(x * y for x, y in zip(vec1, vec2))
        norm1 = math.sqrt(sum(x * x for x in vec1))
        norm2 = math.sqrt(sum(x * x for x in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot / (norm1 * norm2)


# Global provider instance
_global_provider: Optional[EmbeddingProvider] = None

def get_global_provider() -> Optional[EmbeddingProvider]:
    """Get global embedding provider instance."""
    global _global_provider
    return _global_provider

def set_global_provider(provider: Optional[EmbeddingProvider]):
    """Set global embedding provider instance."""
    global _global_provider
    _global_provider = provider
    logger.info(f"Global embedding provider set: {provider.name if provider else 'None'}")
