import uuid
from datetime import datetime
import anthropic
from typing import Any
from src.core.config import Config
from src.core.logging_setup import get_logger, set_correlation_id
from src.agent.state import AgentState, Message, Task, TaskStatus
from src.agent.planner import Planner
from src.agent.executor import Executor
from src.sentinel.guardrails import Guardrails
from src.sentinel.auditor import Auditor

logger = get_logger(__name__)

class AgentOrchestrator:
    def __init__(self, config: Config | None = None, session_id: str | None = None):
        self.config = config or Config()
        self.session_id = session_id or str(uuid.uuid4())
        self.correlation_id = str(uuid.uuid4())
        set_correlation_id(self.correlation_id)
        
        self.planner = Planner(config=self.config)
        self.executor = Executor(config=self.config)
        
        # Initialize guardrails with error handling (NeMo has compatibility issues with Pydantic v2)
        self.guardrails = None
        if self.config.ENABLE_GUARDRAILS:
            try:
                self.guardrails = Guardrails(config=self.config)
            except Exception as e:
                logger.warning("guardrails_init_failed", error=str(e))
                logger.info("continuing_without_guardrails")
        
        self.auditor = Auditor(config=self.config)
        self.client = anthropic.Anthropic(api_key=self.config.ANTHROPIC_API_KEY)
        
        self.state = AgentState(
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            max_iterations=self.config.MAX_ITERATIONS
        )
        
        logger.info("orchestrator_initialized", session_id=self.session_id, correlation_id=self.correlation_id)

    def process_user_message(self, user_input: str) -> str:
        logger.info("processing_user_message", input_length=len(user_input))
        
        self.state.add_message("user", user_input)
        
        if self.config.ENABLE_GUARDRAILS and self.guardrails:
            is_safe, violation_reason = self.guardrails.validate_input(user_input)
            if not is_safe:
                logger.warning("input_blocked_by_guardrails", reason=violation_reason)
                self.state.add_guardrail_violation("input_validation", {"reason": violation_reason})
                return f"Request blocked by security guardrails: {violation_reason}"
        
        try:
            plan = self.planner.create_plan(self.state)
            self.state.current_plan = plan
            
            logger.info("plan_created", task_count=len(plan))
            
            high_risk_tasks = [t for t in plan if self.auditor.requires_approval(t)]
            if high_risk_tasks and self.config.ENABLE_HUMAN_APPROVAL:
                logger.info("high_risk_tasks_detected", count=len(high_risk_tasks))
                return self._handle_approval_workflow(high_risk_tasks)
            
            execution_summary = self.executor.execute_plan(self.state)
            
            response = self._generate_response(execution_summary)
            
            if self.config.ENABLE_GUARDRAILS and self.guardrails:
                is_safe, violation_reason = self.guardrails.validate_output(response)
                if not is_safe:
                    logger.warning("output_blocked_by_guardrails", reason=violation_reason)
                    self.state.add_guardrail_violation("output_validation", {"reason": violation_reason})
                    return "Response blocked by security guardrails due to sensitive content."
            
            self.state.add_message("assistant", response)
            return response
            
        except Exception as e:
            logger.error("message_processing_failed", error=str(e))
            error_msg = f"Error processing request: {str(e)}"
            self.state.error = error_msg
            return error_msg

    def _handle_approval_workflow(self, high_risk_tasks: list[Task]) -> str:
        approval_requests = []
        
        for task in high_risk_tasks:
            audit_log = self.auditor.request_approval(task, user_id=self.state.user_id)
            approval_requests.append(self.auditor.format_approval_request(audit_log))
        
        approval_text = "\n".join(approval_requests)
        
        return f"""HIGH RISK OPERATIONS DETECTED

The following operations require your approval:

{approval_text}

Use these commands to approve/deny:
  approve <task_id> - Approve specific task
  deny <task_id> <reason> - Deny specific task
  approve_all - Approve all pending tasks
  deny_all - Deny all pending tasks
"""

    def approve_task(self, task_id: str, reason: str = "") -> str:
        logger.info("approving_task_via_orchestrator", task_id=task_id)
        
        if self.auditor.approve_task(task_id, reason):
            for task in self.state.current_plan:
                if task.id == task_id:
                    task.approved = True
                    break
            
            return f"Task {task_id} approved. Continue execution with 'continue' command."
        else:
            return f"Task {task_id} not found in pending approvals."

    def deny_task(self, task_id: str, reason: str = "") -> str:
        logger.info("denying_task_via_orchestrator", task_id=task_id)
        
        if self.auditor.deny_task(task_id, reason):
            self.state.current_plan = [t for t in self.state.current_plan if t.id != task_id]
            return f"Task {task_id} denied and removed from plan."
        else:
            return f"Task {task_id} not found in pending approvals."

    def continue_execution(self) -> str:
        logger.info("continuing_execution")
        
        approved_tasks = [t for t in self.state.current_plan if t.approved or not t.requires_approval]
        
        if not approved_tasks:
            return "No approved tasks to execute."
        
        execution_summary = self.executor.execute_plan(self.state)
        response = self._generate_response(execution_summary)
        self.state.add_message("assistant", response)
        
        return response

    def _generate_response(self, execution_summary: dict[str, Any]) -> str:
        logger.info("generating_response", completed=execution_summary["completed"], failed=execution_summary["failed"])
        
        context_docs = "\n\n".join([f"Document {i+1}:\n{doc.get('text', '')[:500]}" for i, doc in enumerate(self.state.context_documents[:3])])
        
        tool_results = "\n\n".join([f"Tool: {task_id}\nResult: {str(result)[:500]}" for task_id, result in execution_summary["results"].items()])
        
        conversation_history = self.state.get_conversation_context()
        
        synthesis_prompt = f"""Synthesize the following information into a helpful response for the user.

Conversation History:
{conversation_history}

Execution Results:
Completed: {execution_summary["completed"]}
Failed: {execution_summary["failed"]}

Tool Outputs:
{tool_results}

Context Documents:
{context_docs}

Provide a clear, concise response that answers the user's question using the execution results and context."""

        try:
            response = self.client.messages.create(
                model=self.config.ANTHROPIC_MODEL,
                max_tokens=self.config.MAX_TOKENS,
                temperature=self.config.TEMPERATURE,
                messages=[{"role": "user", "content": synthesis_prompt}]
            )
            
            return response.content[0].text
            
        except anthropic.APIError as e:
            logger.error("response_generation_failed", error=str(e))
            return f"Execution completed but response generation failed: {str(e)}"

    def get_session_stats(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "total_messages": len(self.state.messages),
            "completed_tasks": len(self.state.completed_tasks),
            "pending_tasks": len(self.state.current_plan),
            "iterations": self.state.iteration_count,
            "guardrail_violations": len(self.state.guardrail_violations),
            "pending_approvals": len(self.auditor.get_pending_approvals()),
            "audit_history": self.auditor.get_risk_stats(),
        }

    def reset_session(self) -> None:
        logger.info("resetting_session", old_session_id=self.session_id)
        
        self.session_id = str(uuid.uuid4())
        self.correlation_id = str(uuid.uuid4())
        set_correlation_id(self.correlation_id)
        
        self.state = AgentState(
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            max_iterations=self.config.MAX_ITERATIONS
        )
        
        logger.info("session_reset_complete", new_session_id=self.session_id)
