import re
from typing import Any
from src.core.logging_setup import get_logger

logger = get_logger(__name__)

class OutputSanitizer:
    def __init__(self):
        self.patterns = {
            "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE),
            "aws_secret_key": re.compile(r"aws_secret_access_key['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9/+=]{40})", re.IGNORECASE),
            "api_key": re.compile(r"(api[_-]?key|apikey)['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{20,})", re.IGNORECASE),
            "secret": re.compile(r"(secret|password|passwd)['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_@#$%^&*\-!]{8,})", re.IGNORECASE),
            "private_key": re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
            "jwt": re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"),
            "bearer_token": re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
            "basic_auth": re.compile(r"Basic\s+[a-zA-Z0-9+/=]+", re.IGNORECASE),
            "github_token": re.compile(r"gh[pousr]_[a-zA-Z0-9]{36,}"),
            "slack_token": re.compile(r"xox[baprs]-[a-zA-Z0-9\-]+"),
            "stripe_key": re.compile(r"sk_live_[a-zA-Z0-9]{24,}"),
            "google_api": re.compile(r"AIza[a-zA-Z0-9_\-]{35}"),
            "ssh_key": re.compile(r"ssh-rsa\s+[a-zA-Z0-9+/=]+"),
            "connection_string": re.compile(r"(mongodb|postgresql|mysql):\/\/[^\s]+", re.IGNORECASE),
            "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
            "ipv4": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
        }
        
        self.replacement_map = {
            "aws_access_key": "[REDACTED_AWS_ACCESS_KEY]",
            "aws_secret_key": "[REDACTED_AWS_SECRET_KEY]",
            "api_key": "[REDACTED_API_KEY]",
            "secret": "[REDACTED_SECRET]",
            "private_key": "[REDACTED_PRIVATE_KEY]",
            "jwt": "[REDACTED_JWT_TOKEN]",
            "bearer_token": "[REDACTED_BEARER_TOKEN]",
            "basic_auth": "[REDACTED_BASIC_AUTH]",
            "github_token": "[REDACTED_GITHUB_TOKEN]",
            "slack_token": "[REDACTED_SLACK_TOKEN]",
            "stripe_key": "[REDACTED_STRIPE_KEY]",
            "google_api": "[REDACTED_GOOGLE_API_KEY]",
            "ssh_key": "[REDACTED_SSH_KEY]",
            "connection_string": "[REDACTED_CONNECTION_STRING]",
            "email": "[REDACTED_EMAIL]",
            "ipv4": "[REDACTED_IP]",
        }
    
    def sanitize(self, output: str, redact_email: bool = False, redact_ip: bool = False) -> tuple[str, list[str]]:
        logger.info("sanitizing_output", output_length=len(output))
        
        sanitized = output
        redacted_items = []
        
        for pattern_name, pattern in self.patterns.items():
            if pattern_name == "email" and not redact_email:
                continue
            if pattern_name == "ipv4" and not redact_ip:
                continue
            
            matches = pattern.findall(sanitized)
            if matches:
                redacted_items.append(f"{pattern_name}: {len(matches)} instance(s)")
                logger.warning("sensitive_data_redacted", pattern=pattern_name, count=len(matches))
                
                replacement = self.replacement_map.get(pattern_name, "[REDACTED]")
                sanitized = pattern.sub(replacement, sanitized)
        
        logger.info("sanitization_complete", redacted_count=len(redacted_items))
        return sanitized, redacted_items
    
    def sanitize_dict(self, data: dict[str, Any], redact_email: bool = False, redact_ip: bool = False) -> tuple[dict[str, Any], list[str]]:
        logger.info("sanitizing_dict", key_count=len(data))
        
        sanitized_data = {}
        all_redactions = []
        
        for key, value in data.items():
            if isinstance(value, str):
                sanitized_value, redactions = self.sanitize(value, redact_email, redact_ip)
                sanitized_data[key] = sanitized_value
                all_redactions.extend(redactions)
            elif isinstance(value, dict):
                sanitized_value, redactions = self.sanitize_dict(value, redact_email, redact_ip)
                sanitized_data[key] = sanitized_value
                all_redactions.extend(redactions)
            elif isinstance(value, list):
                sanitized_list = []
                for item in value:
                    if isinstance(item, str):
                        sanitized_item, redactions = self.sanitize(item, redact_email, redact_ip)
                        sanitized_list.append(sanitized_item)
                        all_redactions.extend(redactions)
                    else:
                        sanitized_list.append(item)
                sanitized_data[key] = sanitized_list
            else:
                sanitized_data[key] = value
        
        return sanitized_data, all_redactions
    
    def check_for_secrets(self, output: str) -> tuple[bool, list[str]]:
        logger.info("checking_for_secrets", output_length=len(output))
        
        found_secrets = []
        
        for pattern_name, pattern in self.patterns.items():
            if pattern_name in ["email", "ipv4"]:
                continue
            
            matches = pattern.findall(output)
            if matches:
                found_secrets.append(pattern_name)
                logger.warning("secret_detected", pattern=pattern_name, count=len(matches))
        
        has_secrets = len(found_secrets) > 0
        
        logger.info("secret_check_complete", has_secrets=has_secrets, secret_types=found_secrets)
        return has_secrets, found_secrets
    
    def sanitize_execution_output(self, output: dict[str, Any]) -> dict[str, Any]:
        logger.info("sanitizing_execution_output")
        
        sanitized_output = output.copy()
        
        if "stdout" in sanitized_output:
            sanitized_stdout, stdout_redactions = self.sanitize(sanitized_output["stdout"])
            sanitized_output["stdout"] = sanitized_stdout
            if stdout_redactions:
                sanitized_output["stdout_redactions"] = stdout_redactions
        
        if "stderr" in sanitized_output:
            sanitized_stderr, stderr_redactions = self.sanitize(sanitized_output["stderr"])
            sanitized_output["stderr"] = sanitized_stderr
            if stderr_redactions:
                sanitized_output["stderr_redactions"] = stderr_redactions
        
        if "command" in sanitized_output:
            sanitized_command, command_redactions = self.sanitize(sanitized_output["command"])
            sanitized_output["command"] = sanitized_command
            if command_redactions:
                sanitized_output["command_redactions"] = command_redactions
        
        logger.info("execution_output_sanitized")
        return sanitized_output
    
    def add_custom_pattern(self, name: str, pattern: str, replacement: str) -> None:
        logger.info("adding_custom_pattern", name=name)
        
        self.patterns[name] = re.compile(pattern, re.IGNORECASE)
        self.replacement_map[name] = replacement
        
        logger.info("custom_pattern_added", name=name)
