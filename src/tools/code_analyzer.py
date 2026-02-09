import ast
from typing import Any
from src.core.logging_setup import get_logger

logger = get_logger(__name__)

class CodeAnalyzer:
    def __init__(self):
        self.dangerous_imports = {
            "os", "subprocess", "sys", "socket", "requests", "urllib", 
            "urllib3", "http", "httplib", "ftplib", "telnetlib", "smtplib",
            "shutil", "glob", "pickle", "marshal", "shelve", "dill",
            "__builtin__", "builtins", "importlib", "runpy", "pty", "rlcompleter",
        }
        
        self.dangerous_functions = {
            "eval", "exec", "compile", "__import__", "open", "file",
            "input", "raw_input", "execfile", "reload", "delattr", "setattr",
        }
        
        self.dangerous_attributes = {
            "__code__", "__globals__", "__builtins__", "__class__", "__bases__",
            "__subclasses__", "__init__", "__import__", "func_globals",
        }
    
    def analyze(self, code: str) -> tuple[bool, list[str]]:
        logger.info("analyzing_code", code_length=len(code))
        
        violations = []
        
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            logger.warning("syntax_error_in_code", error=str(e))
            return False, [f"Syntax error: {e}"]
        
        violations.extend(self._check_imports(tree))
        violations.extend(self._check_function_calls(tree))
        violations.extend(self._check_attributes(tree))
        violations.extend(self._check_dangerous_patterns(tree))
        
        is_safe = len(violations) == 0
        
        logger.info("code_analysis_complete", is_safe=is_safe, violation_count=len(violations))
        return is_safe, violations
    
    def _check_imports(self, tree: ast.AST) -> list[str]:
        violations = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0] in self.dangerous_imports:
                        violations.append(f"Dangerous import: {alias.name}")
                        logger.warning("dangerous_import_detected", module=alias.name)
            
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split('.')[0] in self.dangerous_imports:
                    violations.append(f"Dangerous import from: {node.module}")
                    logger.warning("dangerous_import_from_detected", module=node.module)
        
        return violations
    
    def _check_function_calls(self, tree: ast.AST) -> list[str]:
        violations = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                
                if func_name in self.dangerous_functions:
                    violations.append(f"Dangerous function call: {func_name}()")
                    logger.warning("dangerous_function_detected", function=func_name)
        
        return violations
    
    def _check_attributes(self, tree: ast.AST) -> list[str]:
        violations = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in self.dangerous_attributes:
                    violations.append(f"Dangerous attribute access: {node.attr}")
                    logger.warning("dangerous_attribute_detected", attribute=node.attr)
        
        return violations
    
    def _check_dangerous_patterns(self, tree: ast.AST) -> list[str]:
        violations = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    violations.append("Infinite loop detected: while True")
                    logger.warning("infinite_loop_detected")
            
            if isinstance(node, ast.Lambda):
                if self._contains_dangerous_lambda(node):
                    violations.append("Dangerous lambda expression detected")
                    logger.warning("dangerous_lambda_detected")
        
        return violations
    
    def _contains_dangerous_lambda(self, node: ast.Lambda) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    if child.func.id in self.dangerous_functions:
                        return True
        return False
    
    def get_safe_builtins(self) -> dict[str, Any]:
        safe_builtins = {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "int": int,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "range": range,
            "reversed": reversed,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
        }
        return safe_builtins
    
    def analyze_and_report(self, code: str) -> dict[str, Any]:
        is_safe, violations = self.analyze(code)
        
        report = {
            "is_safe": is_safe,
            "violations": violations,
            "violation_count": len(violations),
            "code_length": len(code),
        }
        
        return report
