import typer
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from src.core.config import Config
from src.core.logging_setup import get_logger
from src.agent.orchestrator import AgentOrchestrator
from src.memory.ingestion_pipeline import IngestionPipeline
from src.tools.sandbox import DockerSandbox

app = typer.Typer(help="OpenAegis - Production-grade secure AI agent")
console = Console()
logger = get_logger(__name__)

@app.command()
def chat(session_id: str | None = None):
    """Start interactive chat session with the agent"""
    
    try:
        config = Config()
        config.ENABLE_GUARDRAILS = False  # Disable guardrails temporarily
        config.ensure_directories()
        
        console.print(Panel.fit(
            "[bold cyan]OpenAegis Secure Agent[/bold cyan]\n"
            "[dim]Type 'help' for commands, 'exit' to quit[/dim]",
            border_style="cyan"
        ))
        
        sandbox = DockerSandbox(config=config)
        if not sandbox.is_available():
            console.print("[yellow]⚠️  Docker not available. Running in degraded mode (no sandboxing)[/yellow]")
        
        try:
            orchestrator = AgentOrchestrator(config=config, session_id=session_id)
        except Exception as e:
            import traceback
            console.print(f"[red]Failed to initialize orchestrator:[/red]")
            console.print(f"[red]{traceback.format_exc()}[/red]")
            raise
        
        console.print(f"[dim]Session ID: {orchestrator.session_id}[/dim]\n")
        
        while True:
            try:
                user_input = Prompt.ask("\n[bold green]You[/bold green]")
                
                if not user_input.strip():
                    continue
                
                if user_input.lower() in ["exit", "quit", "q"]:
                    console.print("\n[cyan]Goodbye! 👋[/cyan]")
                    break
                
                if user_input.lower() == "help":
                    _show_help()
                    continue
                
                if user_input.lower() == "stats":
                    _show_stats(orchestrator)
                    continue
                
                if user_input.lower() == "approve_all":
                    pending = orchestrator.auditor.get_pending_approvals()
                    if not pending:
                        console.print("[yellow]No pending approvals[/yellow]")
                        continue
                    for audit_log in pending:
                        orchestrator.approve_task(audit_log.task_id, reason="User approved all via CLI")
                    console.print(f"[green]✓ Approved {len(pending)} task(s)[/green]")
                    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                        progress.add_task(description="Executing approved tasks...", total=None)
                        response = orchestrator.continue_execution()
                    console.print(f"\n[bold blue]Assistant[/bold blue]: {response}")
                    continue
                
                if user_input.lower() == "deny_all":
                    pending = orchestrator.auditor.get_pending_approvals()
                    if not pending:
                        console.print("[yellow]No pending approvals[/yellow]")
                        continue
                    for audit_log in pending:
                        orchestrator.deny_task(audit_log.task_id, reason="User denied all via CLI")
                    console.print(f"[red]✗ Denied {len(pending)} task(s)[/red]")
                    continue
                
                if user_input.lower().startswith("approve "):
                    task_id = user_input.split()[1]
                    result = orchestrator.approve_task(task_id, reason="User approved via CLI")
                    console.print(result)
                    continue
                
                if user_input.lower().startswith("deny "):
                    parts = user_input.split(maxsplit=2)
                    task_id = parts[1]
                    reason = parts[2] if len(parts) > 2 else "User denied via CLI"
                    result = orchestrator.deny_task(task_id, reason)
                    console.print(result)
                    continue
                
                if user_input.lower() == "continue":
                    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                        progress.add_task(description="Continuing execution...", total=None)
                        response = orchestrator.continue_execution()
                    console.print(f"\n[bold blue]Assistant[/bold blue]: {response}")
                    continue
                
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                    progress.add_task(description="Processing request...", total=None)
                    response = orchestrator.process_user_message(user_input)
                
                if "APPROVAL REQUIRED" in response:
                    console.print(Panel(response, border_style="yellow", title="⚠️  Approval Required"))
                else:
                    console.print(f"\n[bold blue]Assistant[/bold blue]: {response}")
                
            except KeyboardInterrupt:
                console.print("\n[yellow]Use 'exit' to quit[/yellow]")
                continue
            except Exception as e:
                logger.error("chat_error", error=str(e))
                console.print(f"[red]Error: {str(e)}[/red]")
                continue
    
    except Exception as e:
        logger.error("chat_initialization_failed", error=str(e))
        console.print(f"[red]Failed to initialize chat: {str(e)}[/red]")
        sys.exit(1)

@app.command()
def ingest(
    path: str = typer.Argument(..., help="Path to file or directory to ingest"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Recursively ingest directories"),
):
    """Ingest documents into vector store for Q&A"""
    
    try:
        config = Config()
        pipeline = IngestionPipeline(config=config)
        
        path_obj = Path(path)
        
        if not path_obj.exists():
            console.print(f"[red]Path does not exist: {path}[/red]")
            sys.exit(1)
        
        console.print(f"\n[cyan]Starting document ingestion from:[/cyan] {path}")
        
        if path_obj.is_file():
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                progress.add_task(description=f"Ingesting {path_obj.name}...", total=None)
                result = pipeline.ingest_file(str(path_obj))
            
            if result["status"] == "success":
                console.print(f"[green]✓ Successfully ingested {path_obj.name}[/green]")
                console.print(f"  Document ID: {result['document_id']}")
                console.print(f"  Chunks: {result['chunks_created']}")
            else:
                console.print(f"[red]✗ Failed to ingest {path_obj.name}: {result.get('error')}[/red]")
        
        elif path_obj.is_dir():
            console.print(f"[cyan]Scanning directory...[/cyan]")
            result = pipeline.ingest_directory(str(path_obj), recursive=recursive)
            
            console.print(f"\n[green]Ingestion complete:[/green]")
            console.print(f"  Files processed: {result['files_processed']}")
            console.print(f"  Successful: {result['successful']}")
            console.print(f"  Failed: {result['failed']}")
            console.print(f"  Total chunks: {result['total_chunks']}")
    
    except Exception as e:
        logger.error("ingestion_failed", error=str(e))
        console.print(f"[red]Ingestion failed: {str(e)}[/red]")
        sys.exit(1)

@app.command()
def stats():
    """Show system statistics and metrics"""
    
    try:
        config = Config()
        
        table = Table(title="OpenAegis System Statistics", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        sandbox = DockerSandbox(config=config)
        sandbox_stats = sandbox.get_sandbox_stats()
        
        table.add_row("Docker Available", "✓ Yes" if sandbox_stats.get("available") else "✗ No")
        table.add_row("Running Containers", str(sandbox_stats.get("containers_running", "N/A")))
        table.add_row("Memory Limit", config.DOCKER_MEMORY_LIMIT)
        table.add_row("Network Mode", config.DOCKER_NETWORK_MODE)
        table.add_row("Guardrails", "✓ Enabled" if config.ENABLE_GUARDRAILS else "✗ Disabled")
        table.add_row("Human Approval", "✓ Enabled" if config.ENABLE_HUMAN_APPROVAL else "✗ Disabled")
        table.add_row("Code Analyzer", "✓ Enabled" if config.ENABLE_CODE_ANALYZER else "✗ Disabled")
        table.add_row("Output Sanitizer", "✓ Enabled" if config.ENABLE_OUTPUT_SANITIZER else "✗ Disabled")
        table.add_row("ClamAV", "✓ Enabled" if config.ENABLE_CLAMAV else "✗ Disabled")
        table.add_row("Max Iterations", str(config.MAX_ITERATIONS))
        table.add_row("Code Timeout", f"{config.CODE_EXECUTION_TIMEOUT}s")
        
        console.print(table)
        
    except Exception as e:
        logger.error("stats_failed", error=str(e))
        console.print(f"[red]Failed to get stats: {str(e)}[/red]")
        sys.exit(1)

@app.command()
def test():
    """Run security and performance tests"""
    
    console.print("[cyan]Running system tests...[/cyan]\n")
    
    config = Config()
    results = []
    
    console.print("[bold]Security Tests:[/bold]")
    
    sandbox = DockerSandbox(config=config)
    if sandbox.is_available():
        results.append(("Docker Sandbox", "✓ PASS", "green"))
    else:
        results.append(("Docker Sandbox", "✗ FAIL", "red"))
    
    results.append(("Guardrails", "✓ PASS" if config.ENABLE_GUARDRAILS else "✗ FAIL", "green" if config.ENABLE_GUARDRAILS else "red"))
    results.append(("Human Approval", "✓ PASS" if config.ENABLE_HUMAN_APPROVAL else "⚠ WARN", "green" if config.ENABLE_HUMAN_APPROVAL else "yellow"))
    results.append(("Code Analyzer", "✓ PASS" if config.ENABLE_CODE_ANALYZER else "✗ FAIL", "green" if config.ENABLE_CODE_ANALYZER else "red"))
    results.append(("Output Sanitizer", "✓ PASS" if config.ENABLE_OUTPUT_SANITIZER else "✗ FAIL", "green" if config.ENABLE_OUTPUT_SANITIZER else "red"))
    results.append(("ClamAV", "✓ PASS" if config.ENABLE_CLAMAV else "⚠ WARN", "green" if config.ENABLE_CLAMAV else "yellow"))
    
    table = Table(show_header=False)
    table.add_column("Test", style="cyan")
    table.add_column("Result")
    
    for test_name, result, color in results:
        table.add_row(test_name, f"[{color}]{result}[/{color}]")
    
    console.print(table)
    
    passed = sum(1 for _, result, _ in results if "PASS" in result)
    total = len(results)
    
    console.print(f"\n[bold]Results:[/bold] {passed}/{total} tests passed")
    
    if passed == total:
        console.print("[green]✓ System is production-ready[/green]")
    elif passed >= total * 0.8:
        console.print("[yellow]⚠ System has warnings but is operational[/yellow]")
    else:
        console.print("[red]✗ System has critical issues[/red]")

def _show_help():
    help_text = """
[bold cyan]Available Commands:[/bold cyan]

[bold]Chat Commands:[/bold]
  help              Show this help message
  exit, quit, q     Exit the chat
  stats             Show session statistics
  approve <task_id> Approve a pending high-risk task
  deny <task_id>    Deny a pending high-risk task
  continue          Continue execution after approval

[bold]Examples:[/bold]
  "What's in my documents about AWS?"
  "Organize my Downloads folder"
  "Run this Python code: print(2+2)"
  "List all files in my home directory"
"""
    console.print(Panel(help_text, border_style="cyan"))

def _show_stats(orchestrator: AgentOrchestrator):
    stats = orchestrator.get_session_stats()
    
    table = Table(title="Session Statistics", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Session ID", stats["session_id"][:16] + "...")
    table.add_row("Total Messages", str(stats["total_messages"]))
    table.add_row("Completed Tasks", str(stats["completed_tasks"]))
    table.add_row("Pending Tasks", str(stats["pending_tasks"]))
    table.add_row("Iterations", str(stats["iterations"]))
    table.add_row("Guardrail Violations", str(stats["guardrail_violations"]))
    table.add_row("Pending Approvals", str(stats["pending_approvals"]))
    
    console.print(table)

if __name__ == "__main__":
    app()
