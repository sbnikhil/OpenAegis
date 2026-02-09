from typing import Any
import time
from src.core.config import Config
from src.core.logging_setup import get_logger
from src.agent.state import AgentState, Task, TaskStatus
from src.agent.tools import AgentTools

logger = get_logger(__name__)

class Executor:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.tools = AgentTools(config=self.config)
        self.max_retries = self.config.MAX_RETRIES
        self.retry_delay = self.config.RETRY_DELAY_SECONDS

    def execute_task(self, task: Task, state: AgentState) -> Any:
        logger.info("executing_task", task_id=task.id, tool=task.tool, description=task.description)
        
        if task.requires_approval and not task.approved:
            logger.warning("task_requires_approval", task_id=task.id, risk_level=task.risk_level.value)
            raise PermissionError(f"Task {task.id} requires approval before execution")
        
        task.status = TaskStatus.IN_PROGRESS
        
        try:
            result = self._execute_tool(task, state)
            
            logger.info("task_completed", task_id=task.id, result_size=len(str(result)))
            return result
            
        except Exception as e:
            task.retry_count += 1
            logger.error("task_execution_failed", task_id=task.id, error=str(e), retry_count=task.retry_count)
            
            if task.retry_count < self.max_retries:
                logger.info("retrying_task", task_id=task.id, retry_count=task.retry_count)
                time.sleep(self.retry_delay * task.retry_count)
                return self.execute_task(task, state)
            else:
                raise

    def _execute_tool(self, task: Task, state: AgentState) -> Any:
        tool_map = {
            "document_search": self.tools.document_search,
            "code_execution": self.tools.code_execution,
            "bash_command": self.tools.bash_command,
            "web_search": self.tools.web_search,
            "file_read": self.tools.file_read,
            "file_write": self.tools.file_write,
        }
        
        if self.tools.computer_use:
            tool_map.update({
                "screenshot": self.tools.screenshot,
                "mouse_move": self.tools.mouse_move,
                "mouse_click": self.tools.mouse_click,
                "keyboard_type": self.tools.keyboard_type,
                "keyboard_press": self.tools.keyboard_press,
                "keyboard_hotkey": self.tools.keyboard_hotkey,
            })
        
        tool_func = tool_map.get(task.tool)
        if not tool_func:
            raise ValueError(f"Unknown tool: {task.tool}")
        
        try:
            result = tool_func(**task.tool_input)
            return result
        except TypeError as e:
            logger.error("invalid_tool_input", task_id=task.id, tool=task.tool, error=str(e))
            raise ValueError(f"Invalid tool input for {task.tool}: {e}")

    def execute_plan(self, state: AgentState) -> dict[str, Any]:
        logger.info("executing_plan", task_count=len(state.current_plan))
        
        results = {}
        failed_tasks = []
        
        while state.current_plan and state.should_continue():
            next_task = state.get_next_task()
            
            if not next_task:
                blocked_tasks = [t for t in state.current_plan if t.status == TaskStatus.PENDING]
                if blocked_tasks:
                    logger.error("tasks_blocked", blocked_count=len(blocked_tasks))
                    for task in blocked_tasks:
                        task.status = TaskStatus.BLOCKED
                break
            
            try:
                result = self.execute_task(next_task, state)
                state.mark_task_complete(next_task.id, result)
                results[next_task.id] = result
                state.tool_outputs[next_task.id] = result
                
            except PermissionError as e:
                logger.warning("task_awaiting_approval", task_id=next_task.id)
                break
                
            except Exception as e:
                logger.error("task_failed", task_id=next_task.id, error=str(e))
                state.mark_task_failed(next_task.id, str(e))
                failed_tasks.append(next_task)
                
                if next_task.risk_level.value in ["high", "critical"]:
                    logger.error("critical_task_failed", task_id=next_task.id)
                    state.error = f"Critical task {next_task.id} failed: {e}"
                    break
            
            state.iteration_count += 1
        
        execution_summary = {
            "completed": len(state.completed_tasks),
            "failed": len(failed_tasks),
            "remaining": len(state.current_plan),
            "results": results,
            "failed_tasks": [{"id": t.id, "error": t.error} for t in failed_tasks]
        }
        
        logger.info("plan_execution_complete", summary=execution_summary)
        return execution_summary

    def execute_single_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        logger.info("executing_single_tool", tool=tool_name, input=tool_input)
        
        tool_map = {
            "document_search": self.tools.document_search,
            "code_execution": self.tools.code_execution,
            "bash_command": self.tools.bash_command,
            "web_search": self.tools.web_search,
            "file_read": self.tools.file_read,
            "file_write": self.tools.file_write,
        }
        
        tool_func = tool_map.get(tool_name)
        if not tool_func:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        try:
            result = tool_func(**tool_input)
            logger.info("tool_executed", tool=tool_name, result_size=len(str(result)))
            return result
        except Exception as e:
            logger.error("tool_execution_failed", tool=tool_name, error=str(e))
            raise

    def validate_task_inputs(self, task: Task) -> tuple[bool, str | None]:
        required_inputs = {
            "document_search": ["query"],
            "code_execution": ["code"],
            "bash_command": ["command"],
            "web_search": ["query"],
            "file_read": ["path"],
            "file_write": ["path", "content"],
        }
        
        required = required_inputs.get(task.tool, [])
        missing = [field for field in required if field not in task.tool_input]
        
        if missing:
            error_msg = f"Missing required inputs for {task.tool}: {missing}"
            return False, error_msg
        
        return True, None
