from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class Message:
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Task:
    id: str
    description: str
    tool: str
    tool_input: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    result: Any | None = None
    error: str | None = None
    requires_approval: bool = False
    approved: bool = False
    retry_count: int = 0

@dataclass
class AgentState:
    messages: list[Message] = field(default_factory=list)
    current_plan: list[Task] = field(default_factory=list)
    completed_tasks: list[Task] = field(default_factory=list)
    context_documents: list[dict[str, Any]] = field(default_factory=list)
    tool_outputs: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    correlation_id: str = ""
    user_id: str = "default"
    iteration_count: int = 0
    max_iterations: int = 10
    is_complete: bool = False
    error: str | None = None
    guardrail_violations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: Literal["user", "assistant", "system", "tool"], content: str, metadata: dict[str, Any] | None = None) -> None:
        msg = Message(role=role, content=content, metadata=metadata or {})
        self.messages.append(msg)

    def get_pending_tasks(self) -> list[Task]:
        return [t for t in self.current_plan if t.status == TaskStatus.PENDING and not t.dependencies]

    def get_next_task(self) -> Task | None:
        completed_ids = {t.id for t in self.completed_tasks}
        for task in self.current_plan:
            if task.status == TaskStatus.PENDING:
                deps_met = all(dep_id in completed_ids for dep_id in task.dependencies)
                if deps_met:
                    return task
        return None

    def mark_task_complete(self, task_id: str, result: Any) -> None:
        for task in self.current_plan:
            if task.id == task_id:
                task.status = TaskStatus.COMPLETED
                task.result = result
                self.completed_tasks.append(task)
                self.current_plan.remove(task)
                break

    def mark_task_failed(self, task_id: str, error: str) -> None:
        for task in self.current_plan:
            if task.id == task_id:
                task.status = TaskStatus.FAILED
                task.error = error
                break

    def is_planning_complete(self) -> bool:
        return len(self.current_plan) == 0 or all(t.status in [TaskStatus.COMPLETED, TaskStatus.FAILED] for t in self.current_plan)

    def get_conversation_context(self, max_messages: int | None = None) -> str:
        if max_messages is None:
            from src.core.config import Config
            max_messages = Config().MAX_CONVERSATION_MESSAGES
        recent = self.messages[-max_messages:]
        return "\n".join([f"{msg.role}: {msg.content}" for msg in recent])

    def should_continue(self) -> bool:
        return not self.is_complete and self.iteration_count < self.max_iterations and self.error is None

    def add_guardrail_violation(self, violation_type: str, details: dict[str, Any]) -> None:
        self.guardrail_violations.append({"type": violation_type, "details": details, "timestamp": datetime.utcnow().isoformat()})
