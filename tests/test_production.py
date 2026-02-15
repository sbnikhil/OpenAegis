"""
Comprehensive test suite for OpenAegis production deployment.
Tests all components end-to-end with pytest.
"""

import pytest
import os
import tempfile
from pathlib import Path
from src.core.config import Config, get_config
from src.agent.tools import AgentTools
from src.agent.orchestrator import AgentOrchestrator
from src.memory.embeddings import EmbeddingService
from src.memory.vector_store import VectorStore
from src.tools.sandbox import DockerSandbox
from src.tools.code_analyzer import CodeAnalyzer
from src.tools.output_sanitizer import OutputSanitizer
from src.tools.computer_use import ComputerUseTools
from src.sentinel.auditor import Auditor

# Fixtures

@pytest.fixture
def test_config():
    """Create test configuration."""
    config = Config()
    config.ENABLE_GUARDRAILS = False  # Disable for testing
    config.AUTO_APPROVE_LOW_RISK = True
    config.ENABLE_DOCKER_SANDBOX = True
    config.ENABLE_CODE_ANALYZER = True
    config.ENABLE_OUTPUT_SANITIZER = True
    config.ENABLE_COMPUTER_USE = False  # Disabled by default for safety
    return config

@pytest.fixture
def temp_workspace():
    """Create temporary workspace for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

# Component Tests

class TestConfig:
    """Test configuration management."""
    
    def test_config_singleton(self):
        """Test that config uses singleton pattern."""
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2
    
    def test_config_defaults(self, test_config):
        """Test that all required config values have defaults."""
        assert test_config.AWS_REGION
        assert test_config.ANTHROPIC_MODEL
        assert test_config.MAX_TOKENS > 0
        assert test_config.CODE_EXECUTION_TIMEOUT > 0
    
    def test_directory_creation(self, test_config):
        """Test that config creates required directories."""
        test_config.ensure_directories()
        assert Path(test_config.LANCEDB_PATH).exists()
        assert Path(test_config.WORKSPACE_PATH).exists()

class TestEmbeddings:
    """Test embedding service."""
    
    def test_embed_single_text(self):
        """Test embedding single text."""
        service = EmbeddingService()
        embedding = service.embed_text("Hello world")
        assert len(embedding) == 384  # all-MiniLM-L6-v2 dimension
        assert all(isinstance(x, float) for x in embedding)
    
    def test_embed_batch(self):
        """Test batch embedding."""
        service = EmbeddingService()
        texts = ["Hello world", "Test text", "Another document"]
        embeddings = service.embed_batch(texts)
        assert len(embeddings) == 3
        assert all(len(emb) == 384 for emb in embeddings)
    
    def test_embed_empty_text(self):
        """Test embedding empty text."""
        service = EmbeddingService()
        embedding = service.embed_text("")
        assert len(embedding) == 384

class TestVectorStore:
    """Test vector store operations."""
    
    def test_vector_store_init(self, temp_workspace):
        """Test vector store initialization."""
        db_path = str(temp_workspace / "lancedb")
        store = VectorStore(db_path=db_path)
        assert Path(db_path).exists()
    
    def test_add_and_search(self, temp_workspace):
        """Test adding documents and searching."""
        db_path = str(temp_workspace / "lancedb")
        store = VectorStore(db_path=db_path)
        service = EmbeddingService()
        
        # Add test document
        text = "OpenAegis is a secure AI agent system"
        embedding = service.embed_text(text)
        doc_id = store.add_document(
            content=text,
            embedding=embedding,
            metadata={"source": "test"}
        )
        
        assert doc_id is not None
        
        # Search for document
        query_embedding = service.embed_text("secure AI agent")
        results = store.search(query_embedding=query_embedding, top_k=1)
        
        assert len(results) > 0
        assert "OpenAegis" in results[0]["content"]

class TestDockerSandbox:
    """Test Docker sandbox execution."""
    
    def test_sandbox_available(self, test_config):
        """Test that Docker sandbox is available."""
        sandbox = DockerSandbox(config=test_config)
        assert sandbox.is_available()
    
    def test_execute_safe_code(self, test_config):
        """Test executing safe Python code."""
        sandbox = DockerSandbox(config=test_config)
        code = "print('Hello from sandbox'); result = 2 + 2"
        result = sandbox.execute_code(code, timeout=5)
        
        assert result["success"]
        assert "Hello from sandbox" in result["stdout"]
        assert result["sandboxed"]
    
    def test_execute_with_timeout(self, test_config):
        """Test that timeout works."""
        sandbox = DockerSandbox(config=test_config)
        code = "import time; time.sleep(10)"
        
        with pytest.raises(TimeoutError):
            sandbox.execute_code(code, timeout=2)
    
    def test_network_isolation(self, test_config):
        """Test that network is isolated."""
        sandbox = DockerSandbox(config=test_config)
        code = "import urllib.request; urllib.request.urlopen('http://google.com')"
        result = sandbox.execute_code(code, timeout=5)
        
        assert not result["success"]
        assert result["sandboxed"]

class TestCodeAnalyzer:
    """Test code analysis and validation."""
    
    def test_safe_code_passes(self):
        """Test that safe code passes validation."""
        analyzer = CodeAnalyzer()
        code = "x = 1 + 2\nprint(x)"
        is_safe, message = analyzer.analyze(code)
        assert is_safe
    
    def test_dangerous_imports_blocked(self):
        """Test that dangerous imports are blocked."""
        analyzer = CodeAnalyzer()
        dangerous_codes = [
            "import os; os.system('rm -rf /')",
            "import subprocess; subprocess.run(['ls'])",
            "from socket import *",
        ]
        
        for code in dangerous_codes:
            is_safe, message = analyzer.analyze(code)
            assert not is_safe
            assert message is not None
    
    def test_dangerous_functions_blocked(self):
        """Test that dangerous functions are blocked."""
        analyzer = CodeAnalyzer()
        dangerous_codes = [
            "eval('malicious code')",
            "exec('print(1)')",
            "open('/etc/passwd', 'r')",
        ]
        
        for code in dangerous_codes:
            is_safe, message = analyzer.analyze(code)
            assert not is_safe

class TestOutputSanitizer:
    """Test output sanitization."""
    
    def test_sanitize_aws_keys(self):
        """Test AWS key redaction."""
        sanitizer = OutputSanitizer()
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        sanitized = sanitizer.sanitize(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in sanitized
        assert "[REDACTED_AWS_KEY]" in sanitized
    
    def test_sanitize_api_keys(self):
        """Test API key redaction."""
        sanitizer = OutputSanitizer()
        text = "api_key=sk-1234567890abcdef"
        sanitized = sanitizer.sanitize(text)
        assert "sk-1234567890abcdef" not in sanitized
        assert "[REDACTED_API_KEY]" in sanitized
    
    def test_sanitize_execution_output(self):
        """Test execution output sanitization."""
        sanitizer = OutputSanitizer()
        output = {
            "stdout": "token=ghp_1234567890abcdef",
            "stderr": "",
            "success": True
        }
        sanitized = sanitizer.sanitize_execution_output(output)
        assert "ghp_1234567890abcdef" not in sanitized["stdout"]
        assert "[REDACTED" in sanitized["stdout"]

class TestComputerUse:
    """Test computer use tools."""
    
    def test_computer_use_disabled_by_default(self, test_config):
        """Test that computer use is disabled by default."""
        assert not test_config.ENABLE_COMPUTER_USE
    
    def test_computer_use_init(self, test_config):
        """Test computer use tools initialization."""
        test_config.ENABLE_COMPUTER_USE = True
        tools = ComputerUseTools(config=test_config)
        assert tools is not None
    
    def test_get_screen_size(self, test_config):
        """Test getting screen size."""
        test_config.ENABLE_COMPUTER_USE = True
        tools = ComputerUseTools(config=test_config)
        result = tools.get_screen_size()
        
        assert result["success"]
        assert result["width"] > 0
        assert result["height"] > 0
    
    def test_get_mouse_position(self, test_config):
        """Test getting mouse position."""
        test_config.ENABLE_COMPUTER_USE = True
        tools = ComputerUseTools(config=test_config)
        result = tools.get_mouse_position()
        
        assert result["success"]
        assert "x" in result
        assert "y" in result

class TestAuditor:
    """Test audit and approval workflows."""
    
    def test_risk_assessment_low(self, test_config):
        """Test low risk assessment."""
        from src.agent.state import Task, RiskLevel
        auditor = Auditor(config=test_config)
        
        task = Task(
            id="test_1",
            description="Search documents",
            tool="document_search",
            tool_input={"query": "test"},
            risk_level=RiskLevel.LOW
        )
        
        risk, explanation = auditor.assess_task_risk(task)
        assert risk == RiskLevel.LOW
    
    def test_risk_assessment_high(self, test_config):
        """Test high risk assessment for code execution."""
        from src.agent.state import Task, RiskLevel
        auditor = Auditor(config=test_config)
        
        task = Task(
            id="test_2",
            description="Execute code",
            tool="code_execution",
            tool_input={"code": "print('hello')"},
            risk_level=RiskLevel.MEDIUM
        )
        
        risk, explanation = auditor.assess_task_risk(task)
        assert risk in [RiskLevel.HIGH, RiskLevel.CRITICAL]

class TestAgentTools:
    """Test agent tool integration."""
    
    def test_tools_init(self, test_config):
        """Test tools initialization."""
        tools = AgentTools(config=test_config)
        assert tools.vector_store is not None
        assert tools.embedding_service is not None
        assert tools.sandbox is not None
        assert tools.code_analyzer is not None
        assert tools.output_sanitizer is not None
    
    def test_get_available_tools(self, test_config):
        """Test getting available tools list."""
        tools = AgentTools(config=test_config)
        available = tools.get_available_tools()
        
        tool_names = [t["name"] for t in available]
        assert "document_search" in tool_names
        assert "code_execution" in tool_names
        assert "bash_command" in tool_names
        assert "file_read" in tool_names
        assert "file_write" in tool_names
    
    def test_computer_use_tools_conditional(self, test_config):
        """Test that computer use tools are conditional."""
        # Disabled
        test_config.ENABLE_COMPUTER_USE = False
        tools1 = AgentTools(config=test_config)
        available1 = tools1.get_available_tools()
        tool_names1 = [t["name"] for t in available1]
        assert "screenshot" not in tool_names1
        
        # Enabled
        test_config.ENABLE_COMPUTER_USE = True
        tools2 = AgentTools(config=test_config)
        available2 = tools2.get_available_tools()
        tool_names2 = [t["name"] for t in available2]
        assert "screenshot" in tool_names2
        assert "mouse_move" in tool_names2
        assert "keyboard_type" in tool_names2

# Integration Tests

class TestEndToEnd:
    """End-to-end integration tests."""
    
    def test_file_read_operation(self, test_config, temp_workspace):
        """Test end-to-end file read operation."""
        test_config.WORKSPACE_BASE_DIR = str(temp_workspace)
        tools = AgentTools(config=test_config)
        
        # Create test file
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello OpenAegis")
        
        # Read file
        result = tools.file_read("test.txt")
        assert result["success"]
        assert "Hello OpenAegis" in result["content"]
    
    def test_code_execution_workflow(self, test_config):
        """Test complete code execution workflow."""
        tools = AgentTools(config=test_config)
        
        code = "result = sum([1, 2, 3, 4, 5])\nprint(f'Sum: {result}')"
        
        # Analyze code
        is_safe, message = tools.code_analyzer.analyze(code)
        assert is_safe
        
        # Execute code
        result = tools.code_execution(code=code, timeout=5)
        assert result["success"]
        assert "Sum: 15" in result["stdout"]
        
        # Sanitize output
        sanitized = tools.output_sanitizer.sanitize_execution_output(result)
        assert sanitized["success"]

# Performance Tests

class TestPerformance:
    """Performance and scalability tests."""
    
    def test_embedding_batch_performance(self):
        """Test embedding generation performance."""
        import time
        service = EmbeddingService()
        
        texts = [f"Test document {i}" for i in range(100)]
        
        start = time.time()
        embeddings = service.embed_batch(texts)
        duration = time.time() - start
        
        assert len(embeddings) == 100
        assert duration < 10.0  # Should complete within 10 seconds
    
    def test_vector_search_performance(self, temp_workspace):
        """Test vector search performance."""
        import time
        db_path = str(temp_workspace / "lancedb")
        store = VectorStore(db_path=db_path)
        service = EmbeddingService()
        
        # Add 100 documents
        for i in range(100):
            text = f"Test document number {i} with some content"
            embedding = service.embed_text(text)
            store.add_document(content=text, embedding=embedding)
        
        # Search
        query_embedding = service.embed_text("test document")
        
        start = time.time()
        results = store.search(query_embedding=query_embedding, top_k=10)
        duration = time.time() - start
        
        assert len(results) == 10
        assert duration < 1.0  # Should complete within 1 second

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
