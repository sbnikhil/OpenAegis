import logging
import sys
import uuid
from typing import Any, Dict, Optional

import structlog
from structlog.types import FilteringBoundLogger
import watchtower

from src.core.config import get_config

SENSITIVE_FIELDS = {
    "key", "secret", "password", "token", "api_key", 
    "apikey", "api-key", "auth", "credential", "private"
}


def mask_sensitive_data(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in event_dict.items():
        if any(sensitive in key.lower() for sensitive in SENSITIVE_FIELDS):
            if isinstance(value, str) and value:
                if len(value) > 4:
                    event_dict[key] = f"***{value[-4:]}"
                else:
                    event_dict[key] = "****"
            else:
                event_dict[key] = "****"
    
    return event_dict


def add_correlation_id(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    if "correlation_id" not in event_dict:
        event_dict["correlation_id"] = str(uuid.uuid4())
    
    return event_dict


def setup_logging(environment: Optional[str] = None,log_level: str = "INFO") -> None:
    
    config = get_config()
    env = environment or config.ENVIRONMENT 
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    logging.basicConfig(
        format="%(message)s",
        level=numeric_level,
        stream=sys.stdout
    )
    
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_id,
        mask_sensitive_data,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    if env.lower() in ("prod", "production"):
        processors = shared_processors + [
            structlog.processors.JSONRenderer()
        ]
        
        try:
            cloudwatch_handler = watchtower.CloudWatchLogHandler(
                log_group=f"/openaegis/{env}/app",
                stream_name=f"{uuid.uuid4().hex}",
                send_interval=5,
                create_log_group=True
            )
            cloudwatch_handler.setLevel(numeric_level)
            
            root_logger = logging.getLogger()
            root_logger.addHandler(cloudwatch_handler)
        except Exception as e:
            logging.warning(f"Failed to setup CloudWatch logging: {e}")
    
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback
            )
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    return structlog.get_logger(name)

def set_correlation_id(correlation_id: str) -> None:
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

def clear_correlation_id() -> None:
    structlog.contextvars.clear_contextvars()

def get_correlation_id() -> Optional[str]:
    context = structlog.contextvars.get_contextvars()
    return context.get("correlation_id")
