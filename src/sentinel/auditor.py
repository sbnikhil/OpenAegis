import uuid
from datetime import datetime
from typing import Any
from enum import Enum
from src.core.config import Config
from src.core.logging_setup import get_logger
from src.core.aws_client import CloudWatchClient
from src.agent.state import Task, RiskLevel

logger = get_logger(__name__)

class AuditAction(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    REQUEST_INFO = "request_info"

class AuditLog:
    def __init__(self, task_id: str, task_description: str, tool: str, risk_level: RiskLevel, user_id: str):
        self.id = str(uuid.uuid4())
        self.task_id = task_id
        self.task_description = task_description
        self.tool = tool
        self.risk_level = risk_level
        self.user_id = user_id
        self.timestamp = datetime.utcnow()
        self.decision: AuditAction | None = None
        self.decision_timestamp: datetime | None = None
        self.decision_reason: str | None = None

class Auditor:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.cloudwatch = CloudWatchClient()
        self.pending_approvals: dict[str, AuditLog] = {}
        self.audit_history: list[AuditLog] = []
        
        # Map approval threshold string to RiskLevel
        threshold_map = {
            "LOW": RiskLevel.LOW,
            "MEDIUM": RiskLevel.MEDIUM,
            "HIGH": RiskLevel.HIGH,
            "CRITICAL": RiskLevel.CRITICAL
        }
        self.approval_threshold = threshold_map.get(
            self.config.APPROVAL_THRESHOLD.upper(), 
            RiskLevel.HIGH
        )
        
        logger.info(
            "auditor_initialized",
            approval_threshold=self.approval_threshold.value,
            human_approval_enabled=self.config.ENABLE_HUMAN_APPROVAL
        )

    def assess_task_risk(self, task: Task) -> tuple[RiskLevel, str]:
        logger.info("assessing_task_risk", task_id=task.id, tool=task.tool)
        
        risk_level = task.risk_level
        risk_factors = []
        
        if task.tool == "code_execution":
            risk_level = max(risk_level, RiskLevel.HIGH)
            risk_factors.append("code_execution_enabled")
            
            code = task.tool_input.get("code", "")
            if any(keyword in code.lower() for keyword in ["subprocess", "os.system", "eval", "exec"]):
                risk_level = RiskLevel.CRITICAL
                risk_factors.append("dangerous_code_patterns")
        
        if task.tool == "file_write":
            risk_level = max(risk_level, RiskLevel.MEDIUM)
            risk_factors.append("filesystem_modification")
            
            path = task.tool_input.get("path", "")
            if any(sensitive in path.lower() for sensitive in [".env", "config", "secret", "key"]):
                risk_level = RiskLevel.HIGH
                risk_factors.append("sensitive_file_modification")
        
        if task.tool == "web_search":
            risk_level = max(risk_level, RiskLevel.MEDIUM)
            risk_factors.append("external_network_access")
        
        if task.tool == "bash_command":
            command = task.tool_input.get("command", "")
            
            # CRITICAL: Destructive operations that delete/overwrite data
            destructive_patterns = [
                r'\brm\s+', r'\bunlink\s+', r'\bdd\s+', r'\bshred\s+',
                r'\b>\s*/', r'\btruncate\s+', r'\bmkfs\.',
                r'\bformat\b', r'\bwipefs\b'
            ]
            if any(__import__('re').search(pattern, command) for pattern in destructive_patterns):
                risk_level = RiskLevel.CRITICAL
                risk_factors.append("destructive_operation")
            
            # HIGH: System-level modifications
            elif any(keyword in command for keyword in ['sudo', 'chmod 777', 'chown root', 'systemctl', '/etc/', '/System/']):
                risk_level = RiskLevel.HIGH
                risk_factors.append("system_modification")
            
            # HIGH: Execute downloaded files or scripts
            elif any(keyword in command for keyword in ['curl', 'wget']) and ('|' in command or 'bash' in command or 'sh' in command):
                risk_level = RiskLevel.HIGH
                risk_factors.append("download_and_execute")
            
            # MEDIUM: File modification operations (move, copy, create)
            elif any(keyword in command.split()[0] if command.split() else '' for keyword in ['mv', 'cp', 'mkdir', 'touch', 'echo']):
                risk_level = RiskLevel.MEDIUM
                risk_factors.append("file_modification")
            
            # LOW: Read-only operations
            elif any(keyword in command.split()[0] if command.split() else '' for keyword in ['ls', 'find', 'cat', 'grep', 'head', 'tail', 'wc', 'file', 'stat']):
                risk_level = RiskLevel.LOW
                risk_factors.append("read_only_operation")
            
            # MEDIUM: Everything else (unknown commands)
            else:
                risk_level = RiskLevel.MEDIUM
                risk_factors.append("shell_command_execution")
        
        if task.tool == "screenshot":
            risk_level = max(risk_level, RiskLevel.LOW)
            risk_factors.append("screen_capture")
        
        if task.tool in ["mouse_move", "mouse_click"]:
            risk_level = max(risk_level, RiskLevel.MEDIUM)
            risk_factors.append("mouse_control")
        
        if task.tool in ["keyboard_type", "keyboard_press", "keyboard_hotkey"]:
            risk_level = max(risk_level, RiskLevel.MEDIUM)
            risk_factors.append("keyboard_control")
            
            text = task.tool_input.get("text", "")
            keys = task.tool_input.get("keys", [])
            if any(sensitive in str(text).lower() + str(keys).lower() for sensitive in ["password", "token", "key", "secret"]):
                risk_level = RiskLevel.HIGH
                risk_factors.append("sensitive_input_detected")
        
        risk_explanation = f"Risk level: {risk_level.value}. Factors: {', '.join(risk_factors) if risk_factors else 'none'}"
        
        logger.info("risk_assessment_complete", task_id=task.id, risk_level=risk_level.value, factors=risk_factors)
        return risk_level, risk_explanation

    def requires_approval(self, task: Task) -> bool:
        risk_level, _ = self.assess_task_risk(task)
        
        # Compare task risk level with configured threshold
        # Risk levels: LOW < MEDIUM < HIGH < CRITICAL
        risk_order = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3
        }
        
        return risk_order[risk_level] >= risk_order[self.approval_threshold]

    def request_approval(self, task: Task, user_id: str = "default") -> AuditLog:
        logger.info("requesting_approval", task_id=task.id, tool=task.tool)
        
        risk_level, risk_explanation = self.assess_task_risk(task)
        
        audit_log = AuditLog(
            task_id=task.id,
            task_description=task.description,
            tool=task.tool,
            risk_level=risk_level,
            user_id=user_id
        )
        
        self.pending_approvals[task.id] = audit_log
        
        self._log_to_cloudwatch(audit_log, "approval_requested")
        
        logger.info("approval_requested", audit_id=audit_log.id, task_id=task.id, risk_level=risk_level.value)
        return audit_log

    def approve_task(self, task_id: str, reason: str = "") -> bool:
        logger.info("approving_task", task_id=task_id, reason=reason)
        
        if task_id not in self.pending_approvals:
            logger.error("approval_not_found", task_id=task_id)
            return False
        
        audit_log = self.pending_approvals.pop(task_id)
        audit_log.decision = AuditAction.APPROVE
        audit_log.decision_timestamp = datetime.utcnow()
        audit_log.decision_reason = reason or "Approved by user"
        
        self.audit_history.append(audit_log)
        self._log_to_cloudwatch(audit_log, "task_approved")
        
        logger.info("task_approved", audit_id=audit_log.id, task_id=task_id)
        return True

    def deny_task(self, task_id: str, reason: str = "") -> bool:
        logger.info("denying_task", task_id=task_id, reason=reason)
        
        if task_id not in self.pending_approvals:
            logger.error("approval_not_found", task_id=task_id)
            return False
        
        audit_log = self.pending_approvals.pop(task_id)
        audit_log.decision = AuditAction.DENY
        audit_log.decision_timestamp = datetime.utcnow()
        audit_log.decision_reason = reason or "Denied by user"
        
        self.audit_history.append(audit_log)
        self._log_to_cloudwatch(audit_log, "task_denied")
        
        logger.info("task_denied", audit_id=audit_log.id, task_id=task_id)
        return True

    def get_pending_approvals(self) -> list[AuditLog]:
        return list(self.pending_approvals.values())

    def get_audit_history(self, limit: int = 100) -> list[dict[str, Any]]:
        history = sorted(self.audit_history, key=lambda x: x.timestamp, reverse=True)[:limit]
        
        return [{
            "audit_id": log.id,
            "task_id": log.task_id,
            "description": log.task_description,
            "tool": log.tool,
            "risk_level": log.risk_level.value,
            "user_id": log.user_id,
            "timestamp": log.timestamp.isoformat(),
            "decision": log.decision.value if log.decision else None,
            "decision_timestamp": log.decision_timestamp.isoformat() if log.decision_timestamp else None,
            "decision_reason": log.decision_reason,
        } for log in history]

    def _log_to_cloudwatch(self, audit_log: AuditLog, event_type: str) -> None:
        try:
            log_event = {
                "event_type": event_type,
                "audit_id": audit_log.id,
                "task_id": audit_log.task_id,
                "tool": audit_log.tool,
                "risk_level": audit_log.risk_level.value,
                "user_id": audit_log.user_id,
                "timestamp": audit_log.timestamp.isoformat(),
            }
            
            if audit_log.decision:
                log_event["decision"] = audit_log.decision.value
                log_event["decision_reason"] = audit_log.decision_reason
            
            self.cloudwatch.put_log_event(
                log_group_name="/openaegis/audit",
                log_stream_name="task-approvals",
                message=str(log_event)
            )
            
        except Exception as e:
            logger.warning("cloudwatch_log_failed", error=str(e))

    def get_risk_stats(self) -> dict[str, Any]:
        total = len(self.audit_history)
        if total == 0:
            return {"total": 0, "approved": 0, "denied": 0, "pending": len(self.pending_approvals)}
        
        approved = sum(1 for log in self.audit_history if log.decision == AuditAction.APPROVE)
        denied = sum(1 for log in self.audit_history if log.decision == AuditAction.DENY)
        
        risk_breakdown = {}
        for risk_level in RiskLevel:
            count = sum(1 for log in self.audit_history if log.risk_level == risk_level)
            risk_breakdown[risk_level.value] = count
        
        return {
            "total": total,
            "approved": approved,
            "denied": denied,
            "approval_rate": approved / total if total > 0 else 0,
            "pending": len(self.pending_approvals),
            "risk_breakdown": risk_breakdown,
        }

    def format_approval_request(self, audit_log: AuditLog) -> str:
        return f"""
╔══════════════════════════════════════════════════════════════╗
║                    APPROVAL REQUIRED                         ║
╠══════════════════════════════════════════════════════════════╣
║ Task ID:      {audit_log.task_id[:30]:30}                    ║
║ Tool:         {audit_log.tool:30}                            ║
║ Risk Level:   {audit_log.risk_level.value.upper():30}        ║
║ Timestamp:    {audit_log.timestamp.strftime("%Y-%m-%d %H:%M:%S"):30}  ║
╠══════════════════════════════════════════════════════════════╣
║ Description:                                                 ║
║ {audit_log.task_description[:60]:60} ║
╠══════════════════════════════════════════════════════════════╣
║ Actions: [A]pprove | [D]eny | [I]nfo                        ║
╚══════════════════════════════════════════════════════════════╝
"""
