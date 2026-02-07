"""
Input sanitizer for validating and securing file uploads.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import magic

from src.core.config import get_config
from src.core.logging_setup import get_logger

logger = get_logger(__name__)

try:
    import clamd
    CLAMAV_AVAILABLE = True
except ImportError:
    CLAMAV_AVAILABLE = False
    logger.warning("clamd not installed - malware scanning disabled. Install: pip install clamd")


@dataclass
class ValidationResult:
    """Result of file validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    
    def __bool__(self) -> bool:
        return self.is_valid


class InputSanitizer:
    
    def __init__(self):
        self.config = get_config()
        self.max_size_bytes = self.config.MAX_FILE_SIZE_MB * 1024 * 1024
        self.allowed_extensions = set(self.config.ALLOWED_EXTENSIONS)
        self.allowed_mime_types = set(self.config.ALLOWED_MIME_TYPES)
        self.clamav_enabled = self.config.ENABLE_CLAMAV and CLAMAV_AVAILABLE
        self.clamav_client = None
        
        if self.clamav_enabled:
            try:
                self.clamav_client = clamd.ClamdUnixSocket(self.config.CLAMAV_SOCKET)
                self.clamav_client.ping()
                logger.info("clamav_connected", socket=self.config.CLAMAV_SOCKET)
            except Exception as e:
                logger.warning("clamav_unavailable", error=str(e), message="Malware scanning disabled")
                self.clamav_enabled = False
        
        logger.info(
            "input_sanitizer_initialized",
            max_size_mb=self.config.MAX_FILE_SIZE_MB,
            allowed_extensions=list(self.allowed_extensions),
            clamav_enabled=self.clamav_enabled
        )
    
    def validate_file(self, file_path: str) -> ValidationResult:
        errors = []
        warnings = []
        
        file_path = Path(file_path)
        
        logger.info("validating_file", file=file_path.name)
        
        if not file_path.exists():
            errors.append(f"File not found: {file_path}")
            return ValidationResult(False, errors, warnings)
        
        if not file_path.is_file():
            errors.append(f"Path is not a file: {file_path}")
            return ValidationResult(False, errors, warnings)
        
        if not self._check_size(file_path):
            errors.append(
                f"File exceeds maximum size of {self.config.MAX_FILE_SIZE_MB}MB"
            )
        
        ext_valid, ext_msg = self._check_extension(file_path)
        if not ext_valid:
            errors.append(ext_msg)
        
        mime_valid, mime_msg = self._check_mime_type(file_path)
        if not mime_valid:
            errors.append(mime_msg)
        elif mime_msg:
            warnings.append(mime_msg)
        
        if self._check_path_traversal(file_path.name):
            errors.append("Filename contains path traversal patterns")
        
        if self.clamav_enabled:
            malware_safe, malware_msg = self._scan_malware(file_path)
            if not malware_safe:
                errors.append(malware_msg)
        else:
            warnings.append("ClamAV malware scanning not available")
        
        is_valid = len(errors) == 0
        
        if is_valid:
            logger.info("file_validation_passed", file=file_path.name)
        else:
            logger.warning(
                "file_validation_failed",
                file=file_path.name,
                errors=errors
            )
        
        return ValidationResult(is_valid, errors, warnings)
    
    def _check_size(self, file_path: Path) -> bool:
        size = file_path.stat().st_size
        
        if size > self.max_size_bytes:
            logger.warning(
                "file_size_exceeded",
                file=file_path.name,
                size_mb=size / (1024 * 1024),
                max_mb=self.config.MAX_FILE_SIZE_MB
            )
            return False
        
        return True
    
    def _check_extension(self, file_path: Path) -> tuple[bool, str]:
        extension = file_path.suffix.lower()
        
        if extension not in self.allowed_extensions:
            return False, f"Extension '{extension}' not allowed"
        
        return True, ""
    
    def _check_mime_type(self, file_path: Path) -> tuple[bool, Optional[str]]:
        try:
            mime = magic.Magic(mime=True)
            mime_type = mime.from_file(str(file_path))
            
            if mime_type not in self.allowed_mime_types:
                logger.warning(
                    "mime_type_not_allowed",
                    file=file_path.name,
                    mime_type=mime_type
                )
                return False, f"MIME type '{mime_type}' not allowed"
            
            expected_mime = self._get_expected_mime(file_path.suffix)
            if expected_mime and mime_type != expected_mime:
                msg = f"Extension/MIME mismatch: {file_path.suffix} vs {mime_type}"
                logger.warning("mime_mismatch", file=file_path.name, message=msg)
                return True, msg
            
            return True, None
            
        except Exception as e:
            logger.error("mime_check_failed", file=file_path.name, error=str(e))
            return False, f"MIME type check failed: {e}"
    
    def _get_expected_mime(self, extension: str) -> Optional[str]:
        mime_map = {
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.html': 'text/html',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
        }
        return mime_map.get(extension.lower())
    
    def _scan_malware(self, file_path: Path) -> tuple[bool, str]:
        try:
            scan_result = self.clamav_client.scan(str(file_path))
            
            if scan_result is None:
                logger.info("malware_scan_clean", file=file_path.name)
                return True, ""
            
            for file, result in scan_result.items():
                status, virus_name = result
                if status == "FOUND":
                    logger.error(
                        "malware_detected",
                        file=file_path.name,
                        virus=virus_name
                    )
                    return False, f"Malware detected: {virus_name}"
            
            return True, ""
            
        except Exception as e:
            logger.error("malware_scan_failed", file=file_path.name, error=str(e))
            return False, f"Malware scan failed: {e}"
    
    def _check_path_traversal(self, filename: str) -> bool:
        traversal_patterns = ['../', '..\\', '%2e%2e', '....']
        
        filename_lower = filename.lower()
        
        for pattern in traversal_patterns:
            if pattern in filename_lower:
                return True
        
        return False
    
    def sanitize_filename(self, filename: str) -> str:
        filename = os.path.basename(filename)
        filename = re.sub(r'[^\w\s\-\.]', '_', filename)
        filename = re.sub(r'\.+', '.', filename)
        filename = filename[:255]
        logger.debug("filename_sanitized", original=filename, sanitized=filename)
        return filename
    
    def check_size_before_upload(self, file_path: str) -> bool:
        return self._check_size(Path(file_path))
