"""
Document parser for extracting text from various file formats.
"""

import magic
from pathlib import Path
from typing import List, Optional

from unstructured.partition.auto import partition

from src.core.logging_setup import get_logger

logger = get_logger(__name__)


class DocumentParser:
    
    def __init__(self):
        logger.info("document_parser_initialized")
    
    def detect_file_type(self, file_path: str) -> str:
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        mime = magic.Magic(mime=True)
        mime_type = mime.from_file(str(file_path))
        
        logger.debug("file_type_detected", file=file_path.name, mime_type=mime_type)
        
        return mime_type
    
    def parse_file(self, file_path: str) -> str:
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error("file_not_found", file=str(file_path))
            raise FileNotFoundError(f"File not found: {file_path}")
        
        logger.info("parsing_file", file=file_path.name, size_bytes=file_path.stat().st_size)
        
        try:
            elements = partition(filename=str(file_path))
            
            text_parts = []
            for element in elements:
                if hasattr(element, 'text'):
                    text_parts.append(element.text)
            
            full_text = "\n".join(text_parts)
            
            logger.info(
                "file_parsed",
                file=file_path.name,
                extracted_length=len(full_text),
                elements_count=len(elements)
            )
            
            return full_text
            
        except Exception as e:
            logger.error(
                "parsing_failed",
                file=file_path.name,
                error=str(e)
            )
            raise ValueError(f"Failed to parse file: {e}")
    
    def chunk_text(self, text: str, chunk_size: int = 512, chunk_overlap: int = 50) -> List[str]:
        if len(text) <= chunk_size:
            return [text]
        
        logger.debug(
            "chunking_text",
            text_length=len(text),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            
            if end < len(text):
                end = self._find_sentence_boundary(text, end)
            
            chunk = text[start:end].strip()
            
            if chunk:
                chunks.append(chunk)
            
            start = end - chunk_overlap
            
            if start >= len(text):
                break
        
        logger.info("text_chunked", num_chunks=len(chunks))
        
        return chunks
    
    def _find_sentence_boundary(self, text: str, position: int) -> int:
        sentence_endings = ['. ', '.\n', '! ', '!\n', '? ', '?\n']
        
        search_range = 100
        end_search = min(position + search_range, len(text))
        
        best_pos = position
        min_distance = search_range
        
        for ending in sentence_endings:
            pos = text.find(ending, position, end_search)
            if pos != -1:
                distance = pos - position
                if distance < min_distance:
                    min_distance = distance
                    best_pos = pos + len(ending)
        
        return best_pos
    
    def extract_metadata(self, file_path: str) -> dict:
        file_path = Path(file_path)
        
        stat = file_path.stat()
        mime_type = self.detect_file_type(str(file_path))
        
        metadata = {
            "filename": file_path.name,
            "extension": file_path.suffix,
            "size_bytes": stat.st_size,
            "mime_type": mime_type,
            "modified_time": stat.st_mtime
        }
        
        logger.debug("metadata_extracted", file=file_path.name, **metadata)
        
        return metadata
