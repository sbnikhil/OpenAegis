import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
import requests
from src.core.config import Config
from src.core.logging_setup import get_logger
from src.memory.vector_store import VectorStore
from src.memory.embeddings import EmbeddingService
from src.tools.sandbox import DockerSandbox
from src.tools.code_analyzer import CodeAnalyzer
from src.tools.output_sanitizer import OutputSanitizer
from src.tools.computer_use import ComputerUseTools

logger = get_logger(__name__)

class AgentTools:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.vector_store = VectorStore()
        self.embedding_service = EmbeddingService()
        self.code_timeout = self.config.CODE_EXECUTION_TIMEOUT
        self.sandbox = DockerSandbox(config=self.config) if self.config.ENABLE_DOCKER_SANDBOX else None
        self.code_analyzer = CodeAnalyzer() if self.config.ENABLE_CODE_ANALYZER else None
        self.output_sanitizer = OutputSanitizer() if self.config.ENABLE_OUTPUT_SANITIZER else None
        self.computer_use = ComputerUseTools(config=self.config) if self.config.ENABLE_COMPUTER_USE else None

    def document_search(self, query: str, top_k: int = 5, filter_metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        logger.info("document_search", query=query[:100], top_k=top_k)
        
        try:
            query_embedding = self.embedding_service.embed_text(query)
            results = self.vector_store.search(query_embedding=query_embedding, top_k=top_k, filter_metadata=filter_metadata)
            
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "id": result.get("id"),
                    "text": result.get("text"),
                    "score": result.get("score"),
                    "metadata": result.get("metadata", {}),
                })
            
            logger.info("document_search_complete", result_count=len(formatted_results))
            return formatted_results
            
        except Exception as e:
            logger.error("document_search_failed", error=str(e))
            raise

    def code_execution(self, code: str, timeout: int | None = None) -> dict[str, Any]:
        logger.info("code_execution", code_length=len(code), timeout=timeout or self.code_timeout)
        
        if self.code_analyzer:
            is_safe, violations = self.code_analyzer.analyze(code)
            if not is_safe:
                logger.error("code_analysis_failed", violations=violations)
                raise ValueError(f"Code contains dangerous patterns: {', '.join(violations[:3])}")
        
        timeout = timeout or self.code_timeout
        
        if self.sandbox and self.sandbox.is_available():
            logger.info("executing_code_in_sandbox")
            try:
                output = self.sandbox.execute_code(code, language="python", timeout=timeout)
            except Exception as e:
                logger.error("sandbox_execution_failed", error=str(e))
                raise
        else:
            logger.warning("sandbox_not_available_using_subprocess")
            output = self._execute_code_subprocess(code, timeout)
        
        if self.output_sanitizer:
            output = self.output_sanitizer.sanitize_execution_output(output)
        
        logger.info("code_execution_complete", exit_code=output.get("exit_code"), sandboxed=output.get("sandboxed", False))
        return output
    
    def _execute_code_subprocess(self, code: str, timeout: int) -> dict[str, Any]:
        if not self._is_code_safe(code):
            logger.error("unsafe_code_detected", code=code[:200])
            raise ValueError("Code contains potentially dangerous operations")
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            try:
                result = subprocess.run(
                    ['python', temp_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env={**os.environ, 'PYTHONPATH': os.getcwd()}
                )
                
                output = {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                    "success": result.returncode == 0,
                    "sandboxed": False,
                }
                
                return output
                
            finally:
                os.unlink(temp_file)
                
        except subprocess.TimeoutExpired:
            logger.error("code_execution_timeout", timeout=timeout)
            raise TimeoutError(f"Code execution timed out after {timeout} seconds")
        except Exception as e:
            logger.error("code_execution_failed", error=str(e))
            raise

    def _is_code_safe(self, code: str) -> bool:
        dangerous_patterns = [
            "os.system",
            "subprocess.call",
            "subprocess.Popen",
            "eval(",
            "exec(",
            "__import__",
            "compile(",
            "open(",
            "file(",
        ]
        
        code_lower = code.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in code_lower:
                logger.warning("dangerous_pattern_detected", pattern=pattern)
                return False
        
        return True

    def web_search(self, query: str, num_results: int = 5) -> list[dict[str, Any]]:
        logger.info("web_search", query=query[:100], num_results=num_results)
        
        logger.warning("web_search_not_implemented", message="Web search requires external API integration")
        return [{
            "title": "Web Search Not Configured",
            "url": "",
            "snippet": "Web search functionality requires API key configuration (e.g., Google Custom Search, Bing API)",
        }]

    def bash_command(self, command: str, timeout: int | None = None, cwd: str | None = None) -> dict[str, Any]:
        logger.info("bash_command", command=command[:100], timeout=timeout, cwd=cwd)
        
        if not self._is_command_safe(command):
            logger.error("unsafe_command_detected", command=command[:200])
            raise ValueError("Command contains potentially dangerous operations")
        
        timeout = timeout or self.config.CODE_EXECUTION_TIMEOUT
        working_dir = cwd or "/workspace"
        
        if self.sandbox and self.sandbox.is_available():
            logger.info("executing_bash_in_sandbox")
            try:
                output = self.sandbox.execute_bash(command, timeout=timeout, cwd=working_dir)
            except Exception as e:
                logger.error("sandbox_bash_failed", error=str(e))
                raise
        else:
            logger.warning("sandbox_not_available_using_subprocess")
            output = self._execute_bash_subprocess(command, timeout, cwd)
        
        if self.output_sanitizer:
            output = self.output_sanitizer.sanitize_execution_output(output)
        
        logger.info("bash_command_complete", exit_code=output.get("exit_code"), sandboxed=output.get("sandboxed", False))
        return output
    
    def _execute_bash_subprocess(self, command: str, timeout: int, cwd: str | None) -> dict[str, Any]:
        working_dir = cwd or os.getcwd()
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
                env={**os.environ}
            )
            
            output = {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
                "success": result.returncode == 0,
                "command": command,
                "sandboxed": False,
            }
            
            return output
            
        except subprocess.TimeoutExpired:
            logger.error("bash_command_timeout", timeout=timeout)
            raise TimeoutError(f"Command timed out after {timeout} seconds")
        except Exception as e:
            logger.error("bash_command_failed", error=str(e))
            raise

    def _is_command_safe(self, command: str) -> bool:
        dangerous_commands = [
            "rm -rf /",
            "rm -rf ~",
            "dd if=",
            "mkfs",
            "format",
            "> /dev/sda",
            "fork bomb",
            ":(){ :|:& };:",
            "chmod -R 777 /",
            "curl", 
            "wget",
        ]
        
        command_lower = command.lower()
        for danger in dangerous_commands:
            if danger.lower() in command_lower:
                logger.warning("dangerous_command_detected", pattern=danger)
                return False
        
        return True

    def file_read(self, path: str, encoding: str = "utf-8") -> dict[str, Any]:
        logger.info("file_read", path=path)
        
        safe_path = self._sanitize_path(path)
        
        try:
            file_path = Path(safe_path)
            
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {safe_path}")
            
            if not file_path.is_file():
                raise ValueError(f"Path is not a file: {safe_path}")
            
            max_size_bytes = self.config.MAX_FILE_READ_SIZE_MB * 1024 * 1024
            if file_path.stat().st_size > max_size_bytes:
                raise ValueError(f"File too large (>{self.config.MAX_FILE_READ_SIZE_MB}MB): {safe_path}")
            
            content = file_path.read_text(encoding=encoding)
            
            result = {
                "path": str(file_path),
                "content": content,
                "size": len(content),
                "encoding": encoding,
            }
            
            logger.info("file_read_complete", path=safe_path, size=len(content))
            return result
            
        except Exception as e:
            logger.error("file_read_failed", path=safe_path, error=str(e))
            raise

    def file_write(self, path: str, content: str, encoding: str = "utf-8", create_dirs: bool = True) -> dict[str, Any]:
        logger.info("file_write", path=path, content_length=len(content))
        
        safe_path = self._sanitize_path(path)
        
        try:
            file_path = Path(safe_path)
            
            if create_dirs:
                file_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_path.write_text(content, encoding=encoding)
            
            result = {
                "path": str(file_path),
                "size": len(content),
                "encoding": encoding,
                "success": True,
            }
            
            logger.info("file_write_complete", path=safe_path, size=len(content))
            return result
            
        except Exception as e:
            logger.error("file_write_failed", path=safe_path, error=str(e))
            raise

    def _sanitize_path(self, path: str) -> str:
        path = path.strip()
        
        if ".." in path:
            raise ValueError("Path traversal detected")
        
        if path.startswith("/"):
            raise ValueError("Absolute paths not allowed")
        
        workspace_root = os.getcwd()
        safe_path = os.path.join(workspace_root, path)
        safe_path = os.path.normpath(safe_path)
        
        if not safe_path.startswith(workspace_root):
            raise ValueError("Path outside workspace")
        
        return safe_path

    def screenshot(self, region: dict | None = None, save_path: str | None = None, return_base64: bool = False) -> dict[str, Any]:
        if not self.computer_use:
            raise RuntimeError("Computer use tools not enabled. Set ENABLE_COMPUTER_USE=true in config.")
        
        logger.info("screenshot", region=region, save_path=save_path, return_base64=return_base64)
        try:
            result = self.computer_use.screenshot(region=region, save_path=save_path, return_base64=return_base64)
            logger.info("screenshot_complete", success=result["success"])
            return result
        except Exception as e:
            logger.error("screenshot_failed", error=str(e))
            raise

    def mouse_move(self, x: int, y: int, duration: float | None = None) -> dict[str, Any]:
        if not self.computer_use:
            raise RuntimeError("Computer use tools not enabled. Set ENABLE_COMPUTER_USE=true in config.")
        
        logger.info("mouse_move", x=x, y=y, duration=duration)
        try:
            result = self.computer_use.mouse_move(x, y, duration=duration)
            logger.info("mouse_move_complete", success=result["success"])
            return result
        except Exception as e:
            logger.error("mouse_move_failed", error=str(e))
            raise

    def mouse_click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        if not self.computer_use:
            raise RuntimeError("Computer use tools not enabled. Set ENABLE_COMPUTER_USE=true in config.")
        
        logger.info("mouse_click", x=x, y=y, button=button, clicks=clicks)
        try:
            result = self.computer_use.mouse_click(x, y, button=button, clicks=clicks)
            logger.info("mouse_click_complete", success=result["success"])
            return result
        except Exception as e:
            logger.error("mouse_click_failed", error=str(e))
            raise

    def keyboard_type(self, text: str, interval: float | None = None) -> dict[str, Any]:
        if not self.computer_use:
            raise RuntimeError("Computer use tools not enabled. Set ENABLE_COMPUTER_USE=true in config.")
        
        logger.info("keyboard_type", text_length=len(text), interval=interval)
        try:
            result = self.computer_use.keyboard_type(text, interval=interval)
            logger.info("keyboard_type_complete", success=result["success"])
            return result
        except Exception as e:
            logger.error("keyboard_type_failed", error=str(e))
            raise

    def keyboard_press(self, key: str, presses: int = 1) -> dict[str, Any]:
        if not self.computer_use:
            raise RuntimeError("Computer use tools not enabled. Set ENABLE_COMPUTER_USE=true in config.")
        
        logger.info("keyboard_press", key=key, presses=presses)
        try:
            result = self.computer_use.keyboard_press(key, presses=presses)
            logger.info("keyboard_press_complete", success=result["success"])
            return result
        except Exception as e:
            logger.error("keyboard_press_failed", error=str(e))
            raise

    def keyboard_hotkey(self, keys: list[str]) -> dict[str, Any]:
        if not self.computer_use:
            raise RuntimeError("Computer use tools not enabled. Set ENABLE_COMPUTER_USE=true in config.")
        
        logger.info("keyboard_hotkey", keys=keys)
        try:
            result = self.computer_use.keyboard_hotkey(*keys)
            logger.info("keyboard_hotkey_complete", success=result["success"])
            return result
        except Exception as e:
            logger.error("keyboard_hotkey_failed", error=str(e))
            raise

    def get_available_tools(self) -> list[dict[str, Any]]:
        tools = [
            {
                "name": "document_search",
                "description": "Semantic search over ingested documents",
                "parameters": {
                    "query": {"type": "string", "required": True, "description": "Search query"},
                    "top_k": {"type": "integer", "required": False, "default": 5, "description": "Number of results"},
                    "filter_metadata": {"type": "object", "required": False, "description": "Metadata filters"},
                }
            },
            {
                "name": "code_execution",
                "description": "Execute Python code in sandboxed environment",
                "parameters": {
                    "code": {"type": "string", "required": True, "description": "Python code to execute"},
                    "timeout": {"type": "integer", "required": False, "default": 30, "description": "Timeout in seconds"},
                }
            },
            {
                "name": "bash_command",
                "description": "Execute bash/shell commands in terminal",
                "parameters": {
                    "command": {"type": "string", "required": True, "description": "Bash command to execute"},
                    "timeout": {"type": "integer", "required": False, "default": 30, "description": "Timeout in seconds"},
                    "cwd": {"type": "string", "required": False, "description": "Working directory"},
                }
            },
            {
                "name": "web_search",
                "description": "Search the internet for information",
                "parameters": {
                    "query": {"type": "string", "required": True, "description": "Search query"},
                    "num_results": {"type": "integer", "required": False, "default": 5, "description": "Number of results"},
                }
            },
            {
                "name": "file_read",
                "description": "Read contents of a file",
                "parameters": {
                    "path": {"type": "string", "required": True, "description": "Relative file path"},
                    "encoding": {"type": "string", "required": False, "default": "utf-8", "description": "File encoding"},
                }
            },
            {
                "name": "file_write",
                "description": "Write content to a file",
                "parameters": {
                    "path": {"type": "string", "required": True, "description": "Relative file path"},
                    "content": {"type": "string", "required": True, "description": "Content to write"},
                    "encoding": {"type": "string", "required": False, "default": "utf-8", "description": "File encoding"},
                    "create_dirs": {"type": "boolean", "required": False, "default": True, "description": "Create parent directories"},
                }
            },
        ]
        
        if self.computer_use:
            tools.extend([
                {
                    "name": "screenshot",
                    "description": "Capture screenshot of entire screen or specific region",
                    "parameters": {
                        "region": {"type": "object", "required": False, "description": "Region to capture (x, y, width, height)"},
                        "save_path": {"type": "string", "required": False, "description": "Path to save screenshot"},
                        "return_base64": {"type": "boolean", "required": False, "default": False, "description": "Return base64 encoded image"},
                    }
                },
                {
                    "name": "mouse_move",
                    "description": "Move mouse cursor to specific coordinates",
                    "parameters": {
                        "x": {"type": "integer", "required": True, "description": "X coordinate"},
                        "y": {"type": "integer", "required": True, "description": "Y coordinate"},
                        "duration": {"type": "number", "required": False, "description": "Movement duration in seconds"},
                    }
                },
                {
                    "name": "mouse_click",
                    "description": "Click mouse at specific coordinates",
                    "parameters": {
                        "x": {"type": "integer", "required": False, "description": "X coordinate (current position if not specified)"},
                        "y": {"type": "integer", "required": False, "description": "Y coordinate (current position if not specified)"},
                        "button": {"type": "string", "required": False, "default": "left", "description": "Mouse button: left, right, middle"},
                        "clicks": {"type": "integer", "required": False, "default": 1, "description": "Number of clicks"},
                    }
                },
                {
                    "name": "keyboard_type",
                    "description": "Type text using keyboard",
                    "parameters": {
                        "text": {"type": "string", "required": True, "description": "Text to type"},
                        "interval": {"type": "number", "required": False, "description": "Interval between keystrokes in seconds"},
                    }
                },
                {
                    "name": "keyboard_press",
                    "description": "Press a specific keyboard key",
                    "parameters": {
                        "key": {"type": "string", "required": True, "description": "Key to press (e.g., 'enter', 'tab', 'esc')"},
                        "presses": {"type": "integer", "required": False, "default": 1, "description": "Number of times to press"},
                    }
                },
                {
                    "name": "keyboard_hotkey",
                    "description": "Press keyboard hotkey combination",
                    "parameters": {
                        "keys": {"type": "array", "required": True, "description": "Keys to press together (e.g., ['ctrl', 'c'])"},
                    }
                },
            ])
        
        return tools
