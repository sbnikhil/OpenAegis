"""
Document ingestion pipeline orchestrator.
"""

import uuid
from pathlib import Path
from typing import Dict, List, Optional

from src.core.aws_client import S3Client
from src.core.config import get_config
from src.core.logging_setup import get_logger, set_correlation_id
from src.memory.document_parser import DocumentParser
from src.memory.embeddings import EmbeddingService
from src.memory.input_sanitizer import InputSanitizer
from src.memory.vector_store import VectorStore

logger = get_logger(__name__)


class IngestionPipeline:
    
    def __init__(self, s3_client: Optional[S3Client] = None, sanitizer: Optional[InputSanitizer] = None, parser: Optional[DocumentParser] = None, vector_store: Optional[VectorStore] = None, embedding_service: Optional[EmbeddingService] = None):
        self.config = get_config()
        self.s3_client = s3_client or S3Client()
        self.sanitizer = sanitizer or InputSanitizer()
        self.parser = parser or DocumentParser()
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or VectorStore(
            embedding_service=self.embedding_service
        )
        
        logger.info("ingestion_pipeline_initialized")
    
    def ingest_file(self, file_path: str, metadata: Optional[Dict] = None) -> str:
        correlation_id = str(uuid.uuid4())
        set_correlation_id(correlation_id)
        
        file_path = Path(file_path)
        doc_id = str(uuid.uuid4())
        
        logger.info(
            "ingestion_started",
            file=file_path.name,
            doc_id=doc_id
        )
        
        try:
            validation_result = self.sanitizer.validate_file(str(file_path))
            if not validation_result.is_valid:
                error_msg = f"File validation failed: {', '.join(validation_result.errors)}"
                logger.error(
                    "ingestion_validation_failed",
                    file=file_path.name,
                    errors=validation_result.errors
                )
                raise ValueError(error_msg)
            
            if validation_result.warnings:
                logger.warning(
                    "ingestion_validation_warnings",
                    file=file_path.name,
                    warnings=validation_result.warnings
                )
            
            s3_key = f"quarantine/{doc_id}/{file_path.name}"
            s3_uri = self.s3_client.upload_file(
                str(file_path),
                s3_key
            )
            
            logger.info("file_quarantined", s3_uri=s3_uri)
            
            text = self.parser.parse_file(str(file_path))
            
            if not text or len(text.strip()) == 0:
                raise ValueError("No text content extracted from file")
            
            chunks = self.parser.chunk_text(
                text,
                chunk_size=self.config.CHUNK_SIZE,
                chunk_overlap=self.config.CHUNK_OVERLAP
            )
            
            file_metadata = self.parser.extract_metadata(str(file_path))
            
            combined_metadata = {
                "doc_id": doc_id,
                "s3_uri": s3_uri,
                "s3_key": s3_key,
                "correlation_id": correlation_id,
                **file_metadata,
                **(metadata or {})
            }
            
            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_id}_chunk_{i}"
                chunk_metadata = {
                    **combined_metadata,
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }
                
                self.vector_store.add_document(
                    chunk_id,
                    chunk,
                    chunk_metadata
                )
            
            logger.info(
                "ingestion_completed",
                doc_id=doc_id,
                file=file_path.name,
                chunks=len(chunks),
                text_length=len(text)
            )
            
            return doc_id
            
        except Exception as e:
            logger.error(
                "ingestion_failed",
                doc_id=doc_id,
                file=file_path.name,
                error=str(e)
            )
            raise
    
    def ingest_directory(self, dir_path: str, recursive: bool = False, metadata: Optional[Dict] = None) -> List[str]:
        dir_path = Path(dir_path)
        
        if not dir_path.exists() or not dir_path.is_dir():
            raise ValueError(f"Directory not found: {dir_path}")
        
        logger.info(
            "directory_ingestion_started",
            directory=str(dir_path),
            recursive=recursive
        )
        
        pattern = "**/*" if recursive else "*"
        files = [
            f for f in dir_path.glob(pattern)
            if f.is_file() and f.suffix in self.config.ALLOWED_EXTENSIONS
        ]
        
        logger.info("files_found", count=len(files))
        
        doc_ids = []
        errors = []
        
        for file_path in files:
            try:
                doc_id = self.ingest_file(str(file_path), metadata)
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(
                    "file_ingestion_failed",
                    file=file_path.name,
                    error=str(e)
                )
                errors.append({
                    "file": str(file_path),
                    "error": str(e)
                })
        
        logger.info(
            "directory_ingestion_completed",
            total_files=len(files),
            successful=len(doc_ids),
            failed=len(errors)
        )
        
        if errors:
            logger.warning("ingestion_errors", errors=errors)
        
        return doc_ids
    
    def get_ingestion_status(self, doc_id: str) -> Optional[Dict]:
        chunk_id = f"{doc_id}_chunk_0"
        doc = self.vector_store.get_document(chunk_id)
        
        if not doc:
            return None
        
        metadata = doc.get("metadata", {})
        
        status = {
            "doc_id": doc_id,
            "filename": metadata.get("filename"),
            "size_bytes": metadata.get("size_bytes"),
            "mime_type": metadata.get("mime_type"),
            "s3_uri": metadata.get("s3_uri"),
            "total_chunks": metadata.get("total_chunks"),
            "timestamp": doc.get("timestamp")
        }
        
        return status
    
    def delete_document(self, doc_id: str) -> None:
        logger.info("deleting_document", doc_id=doc_id)
        
        status = self.get_ingestion_status(doc_id)
        
        if not status:
            logger.warning("document_not_found", doc_id=doc_id)
            return
        
        total_chunks = status.get("total_chunks", 0)
        
        for i in range(total_chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            try:
                self.vector_store.delete_document(chunk_id)
            except Exception as e:
                logger.error(
                    "chunk_deletion_failed",
                    chunk_id=chunk_id,
                    error=str(e)
                )
        
        if status.get("s3_key"):
            try:
                self.s3_client.delete_file(status["s3_key"])
            except Exception as e:
                logger.error(
                    "s3_deletion_failed",
                    s3_key=status["s3_key"],
                    error=str(e)
                )
        
        logger.info("document_deleted", doc_id=doc_id)
    
    def search_documents(self, query: str, limit: int = 5) -> List[Dict]:
        return self.vector_store.search(query, limit)
    
    def get_stats(self) -> Dict:
        vector_stats = self.vector_store.get_stats()
        
        stats = {
            "total_chunks": vector_stats["document_count"],
            "embedding_model": self.config.EMBEDDING_MODEL,
            "chunk_size": self.config.CHUNK_SIZE,
            "max_file_size_mb": self.config.MAX_FILE_SIZE_MB,
            "allowed_extensions": self.config.ALLOWED_EXTENSIONS
        }
        
        return stats
