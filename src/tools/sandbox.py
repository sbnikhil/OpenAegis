import docker
import tempfile
import os
from pathlib import Path
from typing import Any
from src.core.config import Config
from src.core.logging_setup import get_logger

logger = get_logger(__name__)

class DockerSandbox:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        try:
            self.client = docker.from_env()
            logger.info("docker_client_initialized")
        except docker.errors.DockerException as e:
            logger.error("docker_not_available", error=str(e))
            self.client = None
    
    def is_available(self) -> bool:
        if self.client is None:
            return False
        try:
            self.client.ping()
            return True
        except Exception as e:
            logger.warning("docker_ping_failed", error=str(e))
            return False
    
    def execute_code(self, code: str, language: str = "python", timeout: int | None = None) -> dict[str, Any]:
        logger.info("executing_code_in_sandbox", language=language, code_length=len(code))
        
        if not self.is_available():
            raise RuntimeError("Docker is not available. Install Docker Desktop and ensure it's running.")
        
        timeout = timeout or self.config.CODE_EXECUTION_TIMEOUT
        
        with tempfile.TemporaryDirectory() as tmpdir:
            if language == "python":
                return self._execute_python(code, tmpdir, timeout)
            else:
                raise ValueError(f"Unsupported language: {language}")
    
    def _execute_python(self, code: str, tmpdir: str, timeout: int) -> dict[str, Any]:
        code_file = Path(tmpdir) / "script.py"
        code_file.write_text(code)
        
        try:
            container = self.client.containers.run(
                image=self.config.DOCKER_PYTHON_IMAGE,
                command=["python", "/workspace/script.py"],
                volumes={tmpdir: {"bind": "/workspace", "mode": "ro"}},
                working_dir="/workspace",
                network_mode=self.config.DOCKER_NETWORK_MODE,
                mem_limit=self.config.DOCKER_MEMORY_LIMIT,
                cpu_period=100000,
                cpu_quota=self.config.DOCKER_CPU_QUOTA,
                detach=True,
                remove=False,
                security_opt=["no-new-privileges"],
                cap_drop=["ALL"],
                read_only=True,
            )
            
            try:
                result = container.wait(timeout=timeout)
                exit_code = result["StatusCode"]
                
                logs = container.logs(stdout=True, stderr=True).decode("utf-8")
                
                stdout_logs = container.logs(stdout=True, stderr=False).decode("utf-8")
                stderr_logs = container.logs(stdout=False, stderr=True).decode("utf-8")
                
                output = {
                    "stdout": stdout_logs,
                    "stderr": stderr_logs,
                    "exit_code": exit_code,
                    "success": exit_code == 0,
                    "sandboxed": True,
                }
                
                logger.info("sandbox_execution_complete", exit_code=exit_code, output_size=len(stdout_logs))
                return output
                
            finally:
                try:
                    container.remove(force=True)
                except Exception as e:
                    logger.warning("container_cleanup_failed", error=str(e))
                    
        except docker.errors.ContainerError as e:
            logger.error("container_execution_failed", error=str(e))
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": e.exit_status,
                "success": False,
                "sandboxed": True,
            }
        except Exception as e:
            logger.error("sandbox_execution_failed", error=str(e))
            raise
    
    def execute_bash(self, command: str, timeout: int | None = None, cwd: str = "/workspace") -> dict[str, Any]:
        logger.info("executing_bash_in_sandbox", command=command[:100])
        
        if not self.is_available():
            raise RuntimeError("Docker is not available. Install Docker Desktop and ensure it's running.")
        
        timeout = timeout or self.config.CODE_EXECUTION_TIMEOUT
        
        try:
            container = self.client.containers.run(
                image=self.config.DOCKER_BASH_IMAGE,
                command=["/bin/bash", "-c", command],
                working_dir=cwd,
                network_mode=self.config.DOCKER_NETWORK_MODE,
                mem_limit=self.config.DOCKER_MEMORY_LIMIT,
                cpu_period=100000,
                cpu_quota=self.config.DOCKER_CPU_QUOTA,
                detach=True,
                remove=False,
                security_opt=["no-new-privileges"],
                cap_drop=["ALL"],
            )
            
            try:
                result = container.wait(timeout=timeout)
                exit_code = result["StatusCode"]
                
                stdout_logs = container.logs(stdout=True, stderr=False).decode("utf-8")
                stderr_logs = container.logs(stdout=False, stderr=True).decode("utf-8")
                
                output = {
                    "stdout": stdout_logs,
                    "stderr": stderr_logs,
                    "exit_code": exit_code,
                    "success": exit_code == 0,
                    "command": command,
                    "sandboxed": True,
                }
                
                logger.info("bash_sandbox_complete", exit_code=exit_code)
                return output
                
            finally:
                try:
                    container.remove(force=True)
                except Exception as e:
                    logger.warning("container_cleanup_failed", error=str(e))
                    
        except docker.errors.ContainerError as e:
            logger.error("bash_container_failed", error=str(e))
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": e.exit_status,
                "success": False,
                "command": command,
                "sandboxed": True,
            }
        except Exception as e:
            logger.error("bash_sandbox_failed", error=str(e))
            raise
    
    def get_sandbox_stats(self) -> dict[str, Any]:
        if not self.is_available():
            return {"available": False, "message": "Docker not available"}
        
        try:
            info = self.client.info()
            return {
                "available": True,
                "containers_running": info.get("ContainersRunning", 0),
                "images": len(self.client.images.list()),
                "memory_limit": self.config.DOCKER_MEMORY_LIMIT,
                "cpu_quota": self.config.DOCKER_CPU_QUOTA,
                "network_mode": self.config.DOCKER_NETWORK_MODE,
            }
        except Exception as e:
            logger.error("failed_to_get_sandbox_stats", error=str(e))
            return {"available": False, "error": str(e)}
    
    def ensure_images(self) -> None:
        if not self.is_available():
            logger.warning("docker_not_available_skipping_image_pull")
            return
        
        images_to_pull = [
            self.config.DOCKER_PYTHON_IMAGE,
            self.config.DOCKER_BASH_IMAGE,
        ]
        
        for image in images_to_pull:
            try:
                logger.info("checking_docker_image", image=image)
                self.client.images.get(image)
                logger.info("docker_image_exists", image=image)
            except docker.errors.ImageNotFound:
                logger.info("pulling_docker_image", image=image)
                try:
                    self.client.images.pull(image)
                    logger.info("docker_image_pulled", image=image)
                except Exception as e:
                    logger.error("docker_image_pull_failed", image=image, error=str(e))
