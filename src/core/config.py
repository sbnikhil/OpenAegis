import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Config(BaseSettings):
    # AWS Configuration
    AWS_REGION: str = Field(default="us-east-1", description="AWS region for all services")
    ENVIRONMENT: str = Field(default="dev", description="Deployment environment (dev/staging/prod)")
    S3_BUCKET_NAME: Optional[str] = Field(default=None, description="S3 bucket name from terraform output")
    SECRETS_MANAGER_SECRET_NAME: str = Field(
        default="openaegis/dev/anthropic_api_key",
        description="Secrets Manager secret name for Anthropic API key"
    )
    
    # Anthropic Configuration
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, description="Anthropic API key (from env or Secrets Manager)")
    ANTHROPIC_MODEL: str = Field(default="claude-sonnet-4-20250514", description="Anthropic Claude model identifier")
    MAX_TOKENS: int = Field(default=4096, description="Maximum tokens for LLM responses")
    TEMPERATURE: float = Field(default=0.7, description="LLM temperature for response generation")
    
    # Local Storage Configuration
    LANCEDB_PATH: str = Field(
        default=str(Path.home() / ".openaegis" / "lancedb"),
        description="Local path for LanceDB vector database"
    )
    WORKSPACE_PATH: str = Field(
        default=str(Path.home() / "workspace"),
        description="Default workspace directory for code execution"
    )
    
    # Document Processing Configuration
    EMBEDDING_MODEL: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Sentence transformers model for embeddings"
    )
    CHUNK_SIZE: int = Field(default=512, description="Text chunk size for embeddings (tokens)")
    CHUNK_OVERLAP: int = Field(default=50, description="Overlap between chunks (tokens)")
    MAX_FILE_SIZE_MB: int = Field(default=10, description="Maximum file size for uploads (MB)")
    ALLOWED_EXTENSIONS: list = Field(
        default=[".pdf", ".txt", ".docx", ".md", ".html"],
        description="Allowed file extensions for upload"
    )
    ALLOWED_MIME_TYPES: list = Field(
        default=[
            "application/pdf",
            "text/plain",
            "text/markdown",
            "text/html",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ],
        description="Allowed MIME types for uploads"
    )
    
    # Security Configuration
    ENABLE_CLAMAV: bool = Field(default=True, description="Enable ClamAV malware scanning")
    CLAMAV_SOCKET: str = Field(default="/tmp/clamd.socket", description="ClamAV socket path")
    
    # Agent Configuration
    MAX_ITERATIONS: int = Field(default=10, description="Maximum agent iterations per session")
    MAX_RETRIES: int = Field(default=3, description="Maximum retry attempts for failed operations")
    RETRY_DELAY_SECONDS: int = Field(default=2, description="Delay between retries in seconds")
    ENABLE_GUARDRAILS: bool = Field(default=True, description="Enable NeMo Guardrails input/output validation")
    ENABLE_HUMAN_APPROVAL: bool = Field(default=True, description="Require human approval for high-risk tasks")
    APPROVAL_THRESHOLD: str = Field(
        default="HIGH",
        description="Minimum risk level requiring approval: LOW, MEDIUM, HIGH, CRITICAL (default: HIGH - only dangerous operations)"
    )
    CODE_EXECUTION_TIMEOUT: int = Field(default=30, description="Code execution timeout in seconds")
    MAX_FILE_READ_SIZE_MB: int = Field(default=10, description="Maximum file size for read operations (MB)")
    MAX_CONVERSATION_MESSAGES: int = Field(default=10, description="Maximum messages to include in conversation context")
    
    # Docker Sandbox Configuration
    ENABLE_DOCKER_SANDBOX: bool = Field(default=True, description="Execute code in Docker sandbox instead of host")
    DOCKER_PYTHON_IMAGE: str = Field(default="python:3.11-slim", description="Docker image for Python execution")
    DOCKER_BASH_IMAGE: str = Field(default="ubuntu:22.04", description="Docker image for bash execution")
    DOCKER_NETWORK_MODE: str = Field(default="none", description="Docker network mode (none=isolated, bridge=network access)")
    DOCKER_MEMORY_LIMIT: str = Field(default="512m", description="Memory limit for Docker containers")
    DOCKER_CPU_QUOTA: int = Field(default=50000, description="CPU quota for Docker containers (50000 = 50% of one core)")
    ENABLE_CODE_ANALYZER: bool = Field(default=True, description="Enable AST code analysis before execution")
    ENABLE_OUTPUT_SANITIZER: bool = Field(default=True, description="Enable output sanitization to redact secrets")
    
    # Computer Use Configuration
    ENABLE_COMPUTER_USE: bool = Field(default=False, description="Enable computer use tools (screen, mouse, keyboard)")
    COMPUTER_USE_ACTION_DELAY: float = Field(default=0.1, description="Delay between computer use actions in seconds")
    COMPUTER_USE_FAILSAFE: bool = Field(default=True, description="Enable pyautogui failsafe (move mouse to corner to abort)")
    COMPUTER_USE_MOUSE_MOVE_DURATION: float = Field(default=0.5, description="Duration for mouse movements in seconds")
    COMPUTER_USE_TYPING_INTERVAL: float = Field(default=0.05, description="Interval between keystrokes in seconds")
    COMPUTER_USE_LOCATE_CONFIDENCE: float = Field(default=0.8, description="Confidence threshold for image recognition")
    
    # Retrieval Configuration
    DEFAULT_TOP_K: int = Field(default=5, description="Default number of documents to retrieve")
    SIMILARITY_THRESHOLD: float = Field(default=0.7, description="Minimum similarity score for document retrieval")
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore"
    }
    
    def ensure_directories(self) -> None:
        Path(self.LANCEDB_PATH).mkdir(parents=True, exist_ok=True)
        Path(self.WORKSPACE_PATH).mkdir(parents=True, exist_ok=True)
    
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in ("prod", "production")
    
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() in ("dev", "development", "local")

_config_instance: Optional[Config] = None

def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
        _config_instance.ensure_directories()
    return _config_instance

def reset_config() -> None:
    global _config_instance
    _config_instance = None
