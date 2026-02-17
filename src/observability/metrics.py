import time
from datetime import datetime
from typing import Any
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest
from src.core.logging_setup import get_logger

logger = get_logger(__name__)

class MetricsCollector:
    def __init__(self):
        self.registry = CollectorRegistry()
        
        self.requests_total = Counter(
            "openaegis_requests_total",
            "Total number of user requests",
            ["status"],
            registry=self.registry
        )
        
        self.request_duration = Histogram(
            "openaegis_request_duration_seconds",
            "Request processing duration in seconds",
            ["operation"],
            registry=self.registry
        )
        
        self.tasks_executed = Counter(
            "openaegis_tasks_executed_total",
            "Total number of tasks executed",
            ["tool", "status"],
            registry=self.registry
        )
        
        self.guardrail_blocks = Counter(
            "openaegis_guardrail_blocks_total",
            "Total number of requests blocked by guardrails",
            ["violation_type"],
            registry=self.registry
        )
        
        self.approval_requests = Counter(
            "openaegis_approval_requests_total",
            "Total number of approval requests",
            ["risk_level", "decision"],
            registry=self.registry
        )
        
        self.sandbox_executions = Counter(
            "openaegis_sandbox_executions_total",
            "Total number of sandboxed executions",
            ["language", "success"],
            registry=self.registry
        )
        
        self.code_analyzer_blocks = Counter(
            "openaegis_code_analyzer_blocks_total",
            "Total number of code blocks by AST analyzer",
            ["violation_type"],
            registry=self.registry
        )
        
        self.output_sanitizations = Counter(
            "openaegis_output_sanitizations_total",
            "Total number of output sanitizations",
            ["secret_type"],
            registry=self.registry
        )
        
        self.active_sessions = Gauge(
            "openaegis_active_sessions",
            "Number of active agent sessions",
            registry=self.registry
        )
        
        self.vector_search_duration = Histogram(
            "openaegis_vector_search_duration_seconds",
            "Vector search duration in seconds",
            registry=self.registry
        )
        
        self.embedding_generation_duration = Histogram(
            "openaegis_embedding_generation_duration_seconds",
            "Embedding generation duration in seconds",
            registry=self.registry
        )
        
        self.api_tokens_used = Counter(
            "openaegis_api_tokens_used_total",
            "Total API tokens consumed",
            ["model"],
            registry=self.registry
        )
        
        logger.info("metrics_collector_initialized")
    
    def record_request(self, status: str):
        self.requests_total.labels(status=status).inc()
    
    def record_request_duration(self, operation: str, duration: float):
        self.request_duration.labels(operation=operation).observe(duration)
    
    def record_task_execution(self, tool: str, status: str):
        self.tasks_executed.labels(tool=tool, status=status).inc()
    
    def record_guardrail_block(self, violation_type: str):
        self.guardrail_blocks.labels(violation_type=violation_type).inc()
    
    def record_approval_request(self, risk_level: str, decision: str):
        self.approval_requests.labels(risk_level=risk_level, decision=decision).inc()
    
    def record_sandbox_execution(self, language: str, success: bool):
        self.sandbox_executions.labels(language=language, success=str(success)).inc()
    
    def record_code_analyzer_block(self, violation_type: str):
        self.code_analyzer_blocks.labels(violation_type=violation_type).inc()
    
    def record_output_sanitization(self, secret_type: str):
        self.output_sanitizations.labels(secret_type=secret_type).inc()
    
    def set_active_sessions(self, count: int):
        self.active_sessions.set(count)
    
    def record_vector_search_duration(self, duration: float):
        self.vector_search_duration.observe(duration)
    
    def record_embedding_generation_duration(self, duration: float):
        self.embedding_generation_duration.observe(duration)
    
    def record_api_tokens(self, model: str, tokens: int):
        self.api_tokens_used.labels(model=model).inc(tokens)
    
    def get_metrics(self) -> bytes:
        return generate_latest(self.registry)
    
    def get_summary(self) -> dict[str, Any]:
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "requests": {
                "total": self.requests_total._value.get() if hasattr(self.requests_total, "_value") else 0,
            },
            "guardrails": {
                "blocks": sum(self.guardrail_blocks._metrics.values()) if hasattr(self.guardrail_blocks, "_metrics") else 0,
            },
            "sandbox": {
                "executions": sum(self.sandbox_executions._metrics.values()) if hasattr(self.sandbox_executions, "_metrics") else 0,
            },
            "active_sessions": self.active_sessions._value.get() if hasattr(self.active_sessions, "_value") else 0,
        }
        
        return summary

_metrics_collector: MetricsCollector | None = None

def get_metrics_collector() -> MetricsCollector:
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector

class MetricsTimer:
    def __init__(self, operation: str, metrics_collector: MetricsCollector | None = None):
        self.operation = operation
        self.metrics_collector = metrics_collector or get_metrics_collector()
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.metrics_collector.record_request_duration(self.operation, duration)
