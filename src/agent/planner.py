import json
import uuid
from typing import Any
import anthropic
from src.core.config import Config
from src.core.logging_setup import get_logger
from src.agent.state import AgentState, Task, TaskStatus, RiskLevel

logger = get_logger(__name__)

class Planner:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.client = anthropic.Anthropic(api_key=self.config.ANTHROPIC_API_KEY)
        self.max_retries = self.config.MAX_RETRIES

    def create_plan(self, state: AgentState) -> list[Task]:
        logger.info("generating_plan", user_query=state.messages[-1].content if state.messages else "")
        
        system_prompt = self._build_system_prompt()
        user_query = state.messages[-1].content if state.messages else ""
        conversation_context = state.get_conversation_context()
        
        planning_prompt = f"""Analyze the user's request and create a detailed execution plan.

User Request: {user_query}

Conversation History:
{conversation_context}

Available Documents: {len(state.context_documents)}

Create a step-by-step plan to fulfill this request. For each step, provide:
1. A clear description
2. The tool to use
3. Tool inputs as JSON
4. Dependencies (list of step IDs that must complete first)
5. Risk level (low, medium, high, critical)

Available Tools: document_search, code_execution, bash_command, web_search, file_read, file_write"""
        
        if self.config.ENABLE_COMPUTER_USE:
            planning_prompt += ", screenshot, mouse_move, mouse_click, keyboard_type, keyboard_press, keyboard_hotkey"
        
        planning_prompt += """

Format your response as a JSON array of tasks:
[
  {{
    "id": "task_1",
    "description": "Search documents for X",
    "tool": "document_search",
    "tool_input": {{"query": "...", "top_k": 5}},
    "dependencies": [],
    "risk_level": "low"
  }},
  ...
]

Risk Assessment Guidelines:
- LOW: Read-only operations (searches, file reads, screenshots)
- MEDIUM: File writes, non-destructive operations, mouse/keyboard control
- HIGH: Code execution, network requests, system commands
- CRITICAL: File deletion, privileged operations, external API calls

Only return the JSON array, no additional text."""

        try:
            response = self.client.messages.create(
                model=self.config.ANTHROPIC_MODEL,
                max_tokens=4096,
                temperature=0.3,
                system=system_prompt,
                messages=[{"role": "user", "content": planning_prompt}]
            )
            
            plan_text = response.content[0].text
            logger.debug("raw_plan_response", plan=plan_text[:500])
            
            tasks = self._parse_plan(plan_text)
            self._validate_plan(tasks)
            
            logger.info("plan_created", task_count=len(tasks), high_risk_tasks=sum(1 for t in tasks if t.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]))
            return tasks
            
        except anthropic.APIError as e:
            logger.error("anthropic_api_error", error=str(e))
            raise
        except json.JSONDecodeError as e:
            logger.error("plan_parsing_failed", error=str(e))
            raise ValueError(f"Failed to parse plan JSON: {e}")
        except Exception as e:
            logger.error("plan_creation_failed", error=str(e))
            raise

    def _parse_plan(self, plan_text: str) -> list[Task]:
        plan_text = plan_text.strip()
        if plan_text.startswith("```json"):
            plan_text = plan_text[7:]
        if plan_text.startswith("```"):
            plan_text = plan_text[3:]
        if plan_text.endswith("```"):
            plan_text = plan_text[:-3]
        plan_text = plan_text.strip()
        
        plan_data = json.loads(plan_text)
        
        tasks = []
        for item in plan_data:
            task = Task(
                id=item.get("id", f"task_{uuid.uuid4().hex[:8]}"),
                description=item["description"],
                tool=item["tool"],
                tool_input=item["tool_input"],
                dependencies=item.get("dependencies", []),
                risk_level=RiskLevel(item.get("risk_level", "low")),
                requires_approval=RiskLevel(item.get("risk_level", "low")) in [RiskLevel.HIGH, RiskLevel.CRITICAL]
            )
            tasks.append(task)
        
        return tasks

    def _validate_plan(self, tasks: list[Task]) -> None:
        task_ids = {t.id for t in tasks}
        
        for task in tasks:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    raise ValueError(f"Task {task.id} has invalid dependency: {dep_id}")
            
            valid_tools = ["document_search", "code_execution", "bash_command", "web_search", "file_read", "file_write"]
            if task.tool not in valid_tools:
                raise ValueError(f"Task {task.id} has invalid tool: {task.tool}")
        
        visited = set()
        def has_cycle(task_id: str, path: set[str]) -> bool:
            if task_id in path:
                return True
            if task_id in visited:
                return False
            
            visited.add(task_id)
            path.add(task_id)
            
            task = next((t for t in tasks if t.id == task_id), None)
            if task:
                for dep_id in task.dependencies:
                    if has_cycle(dep_id, path):
                        return True
            
            path.remove(task_id)
            return False
        
        for task in tasks:
            if has_cycle(task.id, set()):
                raise ValueError(f"Circular dependency detected involving task {task.id}")

    def _build_system_prompt(self) -> str:
        prompt = """You are a task planning expert for an AI agent system. Your role is to break down user requests into concrete, executable steps.

Guidelines:
1. Create granular, single-purpose tasks
2. Identify dependencies between tasks
3. Assess risk levels accurately
4. Prefer read operations before write operations
5. Search documents before executing code
6. Keep plans focused and efficient

Tool Capabilities:
- document_search: Semantic search over ingested documents (query, top_k)
- code_execution: Run Python code in sandbox (code, timeout)
- bash_command: Execute terminal commands (command, timeout, cwd)
- web_search: Search the internet (query, num_results)
- file_read: Read file contents (path)
- file_write: Write to file (path, content)"""

        if self.config.ENABLE_COMPUTER_USE:
            prompt += """
- screenshot: Capture screen or region (region, save_path, return_base64)
- mouse_move: Move mouse cursor (x, y, duration)
- mouse_click: Click mouse button (x, y, button, clicks)
- keyboard_type: Type text (text, interval)
- keyboard_press: Press key (key, presses)
- keyboard_hotkey: Press key combination (keys)"""

        prompt += """

Security:
- Flag HIGH/CRITICAL risk for operations that modify state or execute code
- Always validate inputs before destructive operations
- Never expose secrets or credentials"""

        return prompt

    def refine_plan(self, state: AgentState, feedback: str) -> list[Task]:
        logger.info("refining_plan", feedback=feedback)
        
        current_plan_json = json.dumps([{
            "id": t.id,
            "description": t.description,
            "tool": t.tool,
            "status": t.status.value,
            "risk_level": t.risk_level.value
        } for t in state.current_plan], indent=2)
        
        refinement_prompt = f"""The current plan needs adjustment based on feedback.

Current Plan:
{current_plan_json}

Feedback: {feedback}

Generate an updated plan that addresses this feedback. Return the full plan as JSON array."""

        try:
            response = self.client.messages.create(
                model=self.config.ANTHROPIC_MODEL,
                max_tokens=4096,
                temperature=0.3,
                system=self._build_system_prompt(),
                messages=[{"role": "user", "content": refinement_prompt}]
            )
            
            plan_text = response.content[0].text
            tasks = self._parse_plan(plan_text)
            self._validate_plan(tasks)
            
            logger.info("plan_refined", new_task_count=len(tasks))
            return tasks
            
        except Exception as e:
            logger.error("plan_refinement_failed", error=str(e))
            raise
