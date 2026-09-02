import argparse
import json
import os
import sys
import webbrowser
import threading
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.json import JSON

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from config.settings import settings
from core.scanner import scan_codebase
from core.parser import parse_file
from core.graph_builder import build_dependency_graph, save_graph, load_graph, print_graph_summary
from core.embedder import embed_codebase
from graph.query_engine import QueryEngine
from ledger.manager import LedgerManager
from utils.logger import get_logger

logger = get_logger()
console = Console()



def run_pipeline(project_path: str, force: bool = False):
    """
    Run full TokenGuard pipeline on project_path: scan, parse, build graph, embed.
    Idempotent: skips re-scan if dependency_graph.json exists unless force=True.
    """
    project_root = Path(project_path).resolve()
    graph_file = project_root / settings.GRAPH_FILENAME

    console.print(Panel(f"[bold cyan]TokenGuard Pipeline[/bold cyan]\nProject: [green]{project_root}[/green]", expand=False))

    # Check idempotency
    if not force and graph_file.exists():
        console.print(f"[yellow]Found existing dependency graph at {graph_file}. Skipping full scan (use --force to re-scan).[/yellow]")
        graph = load_graph(str(graph_file))
        return graph

    # Step 1 — Scan Codebase
    relative_files = scan_codebase(str(project_root))
    if not relative_files:
        console.print("[bold red]No supported source files found to parse.[/bold red]")
        return None

    # Step 2 — Parse Each File
    console.print(f"[bold cyan]Parsing {len(relative_files)} files...[/bold cyan]")
    parsed_metadata_list = []
    success_count = 0

    for rel_path in relative_files:
        meta = parse_file(str(project_root), rel_path)
        parsed_metadata_list.append(meta)
        if meta.summary and not meta.summary.startswith("Failed to read"):
            success_count += 1

    console.print(f"Parsed [bold green]{success_count}/{len(relative_files)}[/bold green] files successfully.")

    # Step 3 — Build Dependency Graph
    graph = build_dependency_graph(parsed_metadata_list, str(project_root))
    save_graph(graph, str(graph_file))

    # Step 4 — Generate Embeddings & Store in ChromaDB
    embed_codebase(parsed_metadata_list, force_reset=force)

    console.print(Panel("[bold green]TokenGuard ready. You can now query this codebase.[/bold green]", expand=False))
    return graph


def run_query_demo(query_text: str, project_path: str):
    """Run natural language task query and display structured results."""
    project_root = Path(project_path).resolve()
    graph_file = project_root / settings.GRAPH_FILENAME

    console.print(f"\n[bold yellow]Executing Query:[/bold yellow] [bold white]\"{query_text}\"[/bold white]\n")

    engine = QueryEngine(graph=load_graph(str(graph_file)) if graph_file.exists() else None)
    result = engine.query(task=query_text, graph_path=str(graph_file) if graph_file.exists() else None)

    # Format output tables and metrics
    table = Table(title="Top Relevant Files", show_header=True, header_style="bold magenta")
    table.add_column("File", style="cyan")
    table.add_column("Similarity", style="green", justify="right")
    table.add_column("Reason / Extracted Context", style="white")

    for item in result.get("relevant_files", []):
        table.add_row(
            item.get("file", ""),
            f"{item.get('similarity_score', 0.0):.2f}",
            item.get("reason", "")
        )

    console.print(table)

    if result.get("file_relationships"):
        console.print("\n[bold cyan]File Relationships (Import Links):[/bold cyan]")
        for rel in result.get("file_relationships", []):
            console.print(f"  [yellow]*[/yellow] [white]{rel}[/white]")

    console.print(f"\n[bold cyan]Dependency Path:[/bold cyan] {result.get('dependency_path', [])}")
    console.print(f"[bold green]Files to Read ({len(result.get('files_to_read', []))}):[/bold green] {result.get('files_to_read', [])}")
    console.print(f"[bold yellow]Files Skipped:[/bold yellow] {result.get('files_skipped', 0)}")
    console.print(f"[bold magenta]Estimated Tokens Saved:[/bold magenta] ~{result.get('estimated_tokens_saved', 0)} tokens\n")

    console.print("[bold dim]Structured JSON Output:[/bold dim]")
    console.print(JSON(json.dumps(result, indent=2)))


def launch_visualizer(graph_file: Path, host: str = "127.0.0.1", port: int = 8000, hide_isolated: bool = False) -> None:
    """
    Start the FastAPI visualizer server and open the browser.
    Blocks until the user presses Ctrl+C.
    """
    if not graph_file.exists():
        console.print(
            "[bold red]dependency_graph.json not found.[/bold red]\n"
            "Run [cyan]python main.py --project <path>[/cyan] first to build the graph."
        )
        sys.exit(1)

    try:
        import uvicorn
        from api.server import app, set_project
        set_project(graph_file.parent)
    except ImportError as exc:
        console.print(f"[bold red]Import error:[/bold red] {exc}\nInstall with: pip install fastapi uvicorn")
        sys.exit(1)

    url = f"http://{host}:{port}"
    console.print(Panel(
        f"[bold cyan]TokenGuard Visual[/bold cyan] ready\n"
        f"Open -> [link={url}]{url}[/link]\n"
        f"Press [bold]Ctrl+C[/bold] to stop.",
        expand=False,
    ))

    # Auto-open browser after a short delay
    def _open():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


def main():
    parser = argparse.ArgumentParser(description="TokenGuard - Codebase Dependency Graph & Embedding System")
    parser.add_argument("--project", type=str, default=".", help="Path to project directory to analyze")
    parser.add_argument("--query", type=str, default=None, help="Task description query string")
    parser.add_argument("--force", action="store_true", help="Force full re-scan and re-embedding")
    parser.add_argument("--tree",  action="store_true", help="Print visual dependency graph tree")
    parser.add_argument("--visualize",     action="store_true", help="Launch interactive D3 visual graph in browser")
    parser.add_argument("--hide-isolated", action="store_true", help="Hide isolated nodes (no imports, not imported) in visual")
    parser.add_argument("--port", type=int, default=8000, help="Port for the visualizer server (default: 8000)")

    # ── Ledger ──
    parser.add_argument("--lock", type=str, help="Lock a file in the ledger")
    parser.add_argument("--unlock", type=str, help="Unlock a file in the ledger")
    parser.add_argument("--functions", type=str, help="Comma-separated functions to lock/unlock")
    parser.add_argument("--classes", type=str, help="Comma-separated classes to lock")
    parser.add_argument("--reason", type=str, default="No reason provided", help="Reason for locking")
    parser.add_argument("--ledger", action="store_true", help="List all locked features")
    parser.add_argument("--check", type=str, help="Check if a file is safe to edit")
    parser.add_argument("--verify", action="store_true", help="Verify integrity of locked files")
    parser.add_argument("--history", action="store_true", help="Show full change history")

    args = parser.parse_args()

    # ── Visualize mode (does not re-scan) ──────────────────────────────────
    if args.visualize:
        project_root = Path(args.project).resolve()
        graph_file   = project_root / settings.GRAPH_FILENAME
        launch_visualizer(graph_file, port=args.port, hide_isolated=args.hide_isolated)
        return  # server is blocking; nothing below runs

    # ── Ledger CLI ─────────────────────────────────────────────────────────
    ledger_manager = LedgerManager(args.project)
    
    if args.lock:
        funcs = args.functions.split(",") if args.functions else None
        clss = args.classes.split(",") if args.classes else None
        ledger_manager.lock_file(args.lock, args.reason, funcs, clss)
        return
        
    if args.unlock:
        funcs = args.functions.split(",") if args.functions else None
        ledger_manager.unlock_file(args.unlock, funcs)
        return
        
    if args.ledger:
        ledger_manager.list_locked()
        return
        
    if args.check:
        result = ledger_manager.check_file(args.check)
        if result.allowed:
            console.print(f"[bold green]✅ Safe to edit:[/bold green] {args.check}")
            if result.warning:
                console.print(f"[bold yellow]{result.warning}[/bold yellow]")
        else:
            funcs_str = ", ".join(result.blocked_functions) if result.blocked_functions else "Entire file"
            console.print(f"[bold red]❌ Blocked:[/bold red] {args.check} ({funcs_str}) - {result.reason}")
        return
        
    if args.verify:
        ledger_manager.verify_integrity()
        return
        
    if args.history:
        history = ledger_manager.state.change_history
        if not history:
            console.print("[dim]No ledger history found.[/dim]")
            return
        
        table = Table(title="Ledger History", header_style="bold magenta")
        table.add_column("Timestamp", style="dim")
        table.add_column("Event", style="cyan")
        table.add_column("File", style="green")
        table.add_column("Details")
        
        for entry in history:
            details = [f"{k}={v}" for k, v in entry.items() if k not in ["timestamp", "event", "file_path"]]
            table.add_row(
                entry.get("timestamp", "")[:19].replace("T", " "),
                entry.get("event", ""),
                entry.get("file_path", ""),
                ", ".join(details)
            )
        console.print(table)
        return

    # ── Step 1–4 Pipeline ──────────────────────────────────────────────────
    graph = run_pipeline(args.project, force=args.force)

    if args.tree and graph:
        print_graph_summary(graph)

    # ── Step 5 Query Demo ──────────────────────────────────────────────────
    if args.query:
        run_query_demo(args.query, args.project)


if __name__ == "__main__":
    main()
