"""
Embedding service for document vectorization.

Uses sentence-transformers for generating embeddings.
"""

from typing import List

from sentence_transformers import SentenceTransformer

from src.core.config import get_config
from src.core.logging_setup import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    
    def __init__(self, model_name: str = None):
        config = get_config()
        self.model_name = model_name or config.EMBEDDING_MODEL
        self._model = None
        
        logger.info("embedding_service_initialized", model=self.model_name)
    
    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("loading_embedding_model", model=self.model_name)
            self._model = SentenceTransformer(self.model_name)
            logger.info("embedding_model_loaded", model=self.model_name)
        
        return self._model
    
    def embed_text(self, text: str) -> List[float]:
        if not text or not text.strip():
            logger.warning("empty_text_embedding_requested")
            return [0.0] * self.model.get_sentence_embedding_dimension()
        
        logger.debug("generating_embedding", text_length=len(text))
        
        embedding = self.model.encode(text, convert_to_numpy=True)
        
        return embedding.tolist()
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            logger.warning("empty_batch_embedding_requested")
            return []
        
        logger.info("generating_batch_embeddings", count=len(texts))
        
        embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        
        return embeddings.tolist()
    
    def embed_document(self, document: str, chunk_size: int = None, chunk_overlap: int = None) -> List[List[float]]:
        config = get_config()
        chunk_size = chunk_size or config.CHUNK_SIZE
        chunk_overlap = chunk_overlap or config.CHUNK_OVERLAP
        
        chunks = self._chunk_text(document, chunk_size, chunk_overlap)
        
        logger.info(
            "embedding_document",
            doc_length=len(document),
            num_chunks=len(chunks)
        )
        
        return self.embed_batch(chunks)
    
    def _chunk_text(self, text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            
            if chunk.strip():
                chunks.append(chunk)
            
            start += chunk_size - chunk_overlap
        
        return chunks
    
    def get_embedding_dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()
