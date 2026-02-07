"""
Vector store for document embeddings using LanceDB.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import lancedb
import pyarrow as pa

from src.core.config import get_config
from src.core.logging_setup import get_logger
from src.memory.embeddings import EmbeddingService

logger = get_logger(__name__)


class VectorStore:
    
    def __init__(self, db_path: Optional[str] = None, table_name: str = "documents", embedding_service: Optional[EmbeddingService] = None):
        config = get_config()
        self.db_path = db_path or config.LANCEDB_PATH
        self.table_name = table_name
        self.embedding_service = embedding_service or EmbeddingService()
        
        Path(self.db_path).mkdir(parents=True, exist_ok=True)
        
        self.db = lancedb.connect(self.db_path)
        self._ensure_table()
        
        logger.info(
            "vector_store_initialized",
            db_path=self.db_path,
            table_name=self.table_name
        )
    
    def _ensure_table(self) -> None:
        if self.table_name not in self.db.table_names():
            embedding_dim = self.embedding_service.get_embedding_dimension()
            
            schema = pa.schema([
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("embedding", pa.list_(pa.float32(), embedding_dim)),
                pa.field("metadata", pa.string()),
                pa.field("timestamp", pa.string()),
            ])
            
            self.db.create_table(self.table_name, schema=schema)
            
            logger.info("vector_table_created", table=self.table_name)
    
    def add_document(self, doc_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        import json
        
        logger.info("adding_document", doc_id=doc_id, text_length=len(text))
        
        embedding = self.embedding_service.embed_text(text)
        
        table = self.db.open_table(self.table_name)
        
        data = [{
            "id": doc_id,
            "text": text,
            "embedding": embedding,
            "metadata": json.dumps(metadata or {}),
            "timestamp": datetime.utcnow().isoformat()
        }]
        
        table.add(data)
        
        logger.info("document_added", doc_id=doc_id)
    
    def add_documents_batch(self, documents: List[Dict[str, Any]]) -> None:
        import json
        
        logger.info("adding_documents_batch", count=len(documents))
        
        texts = [doc["text"] for doc in documents]
        embeddings = self.embedding_service.embed_batch(texts)
        
        table = self.db.open_table(self.table_name)
        
        data = []
        for doc, embedding in zip(documents, embeddings):
            data.append({
                "id": doc.get("doc_id", str(uuid.uuid4())),
                "text": doc["text"],
                "embedding": embedding,
                "metadata": json.dumps(doc.get("metadata", {})),
                "timestamp": datetime.utcnow().isoformat()
            })
        
        table.add(data)
        
        logger.info("documents_batch_added", count=len(documents))
    
    def search(self, query: str, limit: int = 5, filter_metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        import json
        
        logger.info("searching_documents", query_length=len(query), limit=limit)
        
        query_embedding = self.embedding_service.embed_text(query)
        
        table = self.db.open_table(self.table_name)
        
        results = (
            table.search(query_embedding)
            .limit(limit)
            .to_list()
        )
        
        parsed_results = []
        for result in results:
            parsed_results.append({
                "id": result["id"],
                "text": result["text"],
                "metadata": json.loads(result["metadata"]),
                "timestamp": result["timestamp"],
                "score": float(result.get("_distance", 0))
            })
        
        logger.info("search_completed", results_count=len(parsed_results))
        
        return parsed_results
    
    def delete_document(self, doc_id: str) -> None:
        logger.info("deleting_document", doc_id=doc_id)
        
        table = self.db.open_table(self.table_name)
        table.delete(f'id = "{doc_id}"')
        
        logger.info("document_deleted", doc_id=doc_id)
    
    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        import json
        
        table = self.db.open_table(self.table_name)
        
        results = table.search().where(f'id = "{doc_id}"').limit(1).to_list()
        
        if not results:
            return None
        
        result = results[0]
        return {
            "id": result["id"],
            "text": result["text"],
            "metadata": json.loads(result["metadata"]),
            "timestamp": result["timestamp"]
        }
    
    def get_stats(self) -> Dict[str, Any]:
        table = self.db.open_table(self.table_name)
        
        count = table.count_rows()
        
        stats = {
            "document_count": count,
            "table_name": self.table_name,
            "db_path": self.db_path
        }
        
        logger.debug("vector_store_stats", **stats)
        
        return stats
    
    def clear(self) -> None:
        logger.warning("clearing_vector_store", table=self.table_name)
        
        self.db.drop_table(self.table_name)
        self._ensure_table()
        
        logger.info("vector_store_cleared", table=self.table_name)
