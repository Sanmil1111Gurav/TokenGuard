"""
TokenGuard MCP Server — Model Context Protocol plugin for Antigravity & Cursor.

Exposes TokenGuard's core capabilities (scan, query, compress, lock/unlock,
visualize) as MCP tools that AI coding agents can call directly.

Transport: stdio (JSON-RPC over stdin/stdout)
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# ── Ensure project root is importable ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Logging to stderr only (stdout is reserved for MCP JSON-RPC) ──────────
logging.basicConfig(
    level=logging.INFO,
    format="[TokenGuard MCP] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("tokenguard-mcp")

# ── Load environment ──────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "TokenGuard",
    description=(
        "TokenGuard — Intelligent codebase context middleware. "
        "Scans codebases, builds dependency graphs, generates embeddings, "
        "queries relevant files, compresses prompts, and protects locked code."
    ),
)

# ── Lazy-loaded singletons ────────────────────────────────────────────────
_active_project: Optional[str] = None


def _resolve_project(project_path: Optional[str] = None) -> str:
    """Resolve and cache the active project path."""
    global _active_project
    if project_path and project_path != ".":
        _active_project = str(Path(project_path).resolve())
    elif _active_project is None:
        cwd = Path.cwd()
        if (cwd / "dependency_graph.json").exists():
            _active_project = str(cwd.resolve())
        else:
            _active_project = str(PROJECT_ROOT)
    return _active_project


def _log_session_action(
    project_root: str,
    action_type: str,
    description: str,
    file_path: str = "",
    tokens_used: int = 0,
    tokens_saved: int = 0,
    original_tokens: int = 0,
    compressed_tokens: int = 0,
    reduction_percent: float = 0.0,
    outcome: str = "success"
):
    """Record an action into the project's SessionManager for live UI reporting."""
    try:
        from sessions.session_manager import SessionManager
        sm = SessionManager(project_root)
        session = sm.store.get_active_session(project_root)
        if not session:
            session = sm.start_session(project_root, task_description="AI Agent Session")
        sm.log_action(
            session_id=session.session_id,
            action_type=action_type,
            file_path=file_path,
            description=description,
            tokens_used=tokens_used,
            tokens_saved=tokens_saved,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            reduction_percent=reduction_percent,
            outcome=outcome,
        )
    except Exception as e:
        logger.warning("Session logging error: %s", e)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 1 — Scan & Index Project
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def scan_project(
    project_path: str,
    force: bool = False,
) -> str:
    """
    Scan a codebase and build its dependency graph + vector embeddings.

    This is the first step — run this before querying. It will:
    1. Walk the project and collect all .py/.js/.ts/.jsx/.tsx files
    2. Parse each file with Tree-sitter AST (regex fallback)
    3. Build a directed dependency graph (NetworkX) → saved as dependency_graph.json
    4. Generate embeddings for every file → stored in ChromaDB

    Args:
        project_path: Absolute path to the project directory to analyze.
        force: If True, force a full re-scan even if the graph already exists.

    Returns:
        JSON summary with file count, node count, and edge count.
    """
    from config.settings import settings
    from core.scanner import scan_codebase
    from core.parser import parse_file
    from core.graph_builder import build_dependency_graph, save_graph, load_graph
    from core.embedder import embed_codebase

    project_root = Path(_resolve_project(project_path)).resolve()
    graph_file = project_root / settings.GRAPH_FILENAME

    # Idempotent: skip if graph exists
    if not force and graph_file.exists():
        graph = load_graph(str(graph_file))
        return json.dumps({
            "status": "already_indexed",
            "project": str(project_root),
            "message": "Dependency graph already exists. Use force=True to re-scan.",
            "nodes": graph.number_of_nodes() if graph else 0,
            "edges": graph.number_of_edges() if graph else 0,
        }, indent=2)

    # Step 1 — Scan
    relative_files = scan_codebase(str(project_root))
    if not relative_files:
        return json.dumps({"status": "error", "message": "No supported source files found."})

    # Step 2 — Parse
    parsed = []
    for rel_path in relative_files:
        meta = parse_file(str(project_root), rel_path)
        parsed.append(meta)

    # Step 3 — Build graph
    graph = build_dependency_graph(parsed, str(project_root))
    save_graph(graph, str(graph_file))

    # Step 4 — Embed
    embed_count = embed_codebase(parsed, force_reset=force)

    _log_session_action(
        str(project_root),
        action_type="scan",
        description=f"Indexed {len(relative_files)} files ({graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)",
        outcome="success"
    )

    return json.dumps({
        "status": "success",
        "project": str(project_root),
        "files_scanned": len(relative_files),
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "embeddings_stored": embed_count,
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 2 — Query Relevant Files
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def query_context(
    task: str,
    project_path: Optional[str] = None,
    top_k: int = 5,
) -> str:
    """
    Find the minimal set of relevant files for a coding task using semantic
    search + dependency graph traversal. Returns only what the AI needs to see.

    Args:
        task: Plain English description of the coding task (e.g., "fix the login validation").
        project_path: Project directory (uses last scanned project if omitted).
        top_k: Number of top semantic matches to retrieve (default: 5).

    Returns:
        JSON with relevant_files, dependency_path, files_to_read,
        files_skipped, and estimated_tokens_saved.
    """
    from config.settings import settings
    from core.graph_builder import load_graph
    from graph.query_engine import QueryEngine

    project_root = Path(_resolve_project(project_path)).resolve()
    graph_file = project_root / settings.GRAPH_FILENAME

    if not graph_file.exists():
        return json.dumps({
            "status": "error",
            "message": f"No dependency graph found at {graph_file}. Run scan_project first.",
        })

    graph = load_graph(str(graph_file))
    engine = QueryEngine(graph=graph)
    result = engine.query(task=task, top_k=top_k, graph_path=str(graph_file))

    files_to_read = result.get("files_to_read", [])
    first_file = files_to_read[0] if files_to_read else ""
    saved = result.get("estimated_tokens_saved", 0)
    _log_session_action(
        str(project_root),
        action_type="query",
        description=f"Query context: {task}",
        file_path=first_file,
        tokens_saved=saved,
        original_tokens=saved + 300,
        compressed_tokens=300,
        reduction_percent=round(saved / (saved + 300) * 100.0, 1) if saved else 0.0,
        outcome="success"
    )

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 3 — Compress Prompt Context
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def compress_context(
    task: str,
    project_path: Optional[str] = None,
    max_input_tokens: int = 4000,
    max_output_tokens: int = 1024,
) -> str:
    """
    Build a compressed, token-budgeted prompt for a coding task.

    Combines query_context results with structural code compression
    (outlines instead of full code) and priority tiering (High/Medium/Low/Frozen).

    Args:
        task: Plain English task description.
        project_path: Project directory (uses last scanned project if omitted).
        max_input_tokens: Hard token budget for the assembled prompt (default: 4000).
        max_output_tokens: Expected max output tokens from the LLM (default: 1024).

    Returns:
        JSON with token_stats (original, compressed, saved, reduction%),
        assembled_prompt snippet, and priority breakdown.
    """
    from prompt_compression.compressor import TokenCompressor

    project_root = str(Path(_resolve_project(project_path)).resolve())

    compressor = TokenCompressor(project_root)
    context = compressor.compress_input(
        task=task,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )

    stats = context.token_stats
    first_file = context.items[0].file_path if context.items else ""
    _log_session_action(
        project_root,
        action_type="compress",
        description=f"Compressed prompt: {task}",
        file_path=first_file,
        tokens_used=stats.compressed_input_tokens,
        tokens_saved=stats.input_tokens_saved,
        original_tokens=stats.original_input_tokens,
        compressed_tokens=stats.compressed_input_tokens,
        reduction_percent=stats.input_reduction_percent,
        outcome="success"
    )

    return json.dumps(context.to_dict(), indent=2)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 4 — Lock File / Function (Freeze)
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def lock_file(
    file_path: str,
    reason: str = "Locked via TokenGuard plugin",
    functions: Optional[str] = None,
    classes: Optional[str] = None,
    project_path: Optional[str] = None,
) -> str:
    """
    Lock (freeze) a file or specific functions/classes to prevent AI modification.

    A SHA-256 checksum is recorded at lock time. Any edit attempt on a locked
    file will be blocked. Dependency-connected files will trigger warnings.

    Args:
        file_path: Relative path of the file to lock (e.g., "core/parser.py").
        reason: Human-readable reason for locking.
        functions: Comma-separated function names to lock (locks entire file if omitted).
        classes: Comma-separated class names to lock.
        project_path: Project directory.

    Returns:
        JSON with lock status and details.
    """
    from ledger.manager import LedgerManager

    project_root = _resolve_project(project_path)
    manager = LedgerManager(project_root)

    funcs = [f.strip() for f in functions.split(",")] if functions else None
    clss = [c.strip() for c in classes.split(",")] if classes else None

    success = manager.lock_file(file_path, reason, funcs, clss)

    if success:
        feature = manager.state.locked_features.get(file_path.replace("\\", "/").lstrip("./"))
        _log_session_action(
            project_root,
            action_type="lock",
            description=f"Freeze file {file_path} ({reason})",
            file_path=file_path,
            outcome="locked"
        )
        return json.dumps({
            "status": "locked",
            "file_path": file_path,
            "reason": reason,
            "locked_functions": feature.locked_functions if feature else [],
            "locked_classes": feature.locked_classes if feature else [],
            "lock_entire_file": feature.lock_entire_file if feature else True,
            "checksum": feature.checksum if feature else "",
        }, indent=2)
    else:
        return json.dumps({
            "status": "error",
            "message": f"Failed to lock '{file_path}'. File may not exist in the dependency graph. Run scan_project first.",
        })


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 5 — Unlock File / Function
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def unlock_file(
    file_path: str,
    functions: Optional[str] = None,
    project_path: Optional[str] = None,
) -> str:
    """
    Unlock a previously locked file or specific functions.

    Args:
        file_path: Relative path of the file to unlock.
        functions: Comma-separated function names to unlock (unlocks entire file if omitted).
        project_path: Project directory.

    Returns:
        JSON with unlock status.
    """
    from ledger.manager import LedgerManager

    project_root = _resolve_project(project_path)
    manager = LedgerManager(project_root)

    funcs = [f.strip() for f in functions.split(",")] if functions else None
    success = manager.unlock_file(file_path, funcs)

    if success:
        _log_session_action(
            project_root,
            action_type="unlock",
            description=f"Unfreeze file {file_path}",
            file_path=file_path,
            outcome="unlocked"
        )

    return json.dumps({
        "status": "unlocked" if success else "error",
        "file_path": file_path,
        "message": "File unlocked successfully." if success else "File is not locked.",
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 6 — Check File Safety (Pre-Edit Guard)
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def check_file(
    file_path: str,
    proposed_functions: Optional[str] = None,
    project_path: Optional[str] = None,
) -> str:
    """
    Check if a file is safe to edit BEFORE making changes.

    Call this before editing any file. It checks:
    - Whether the file or any of its functions are locked (frozen)
    - Whether the file is connected to locked files in the dependency graph
    - SHA-256 integrity of locked files

    Args:
        file_path: Relative path of the file to check.
        proposed_functions: Comma-separated function names you plan to modify.
        project_path: Project directory.

    Returns:
        JSON with allowed (bool), reason, blocked_functions, safe_to_edit list, and warnings.
    """
    from ledger.manager import LedgerManager

    project_root = _resolve_project(project_path)
    manager = LedgerManager(project_root)

    funcs = [f.strip() for f in proposed_functions.split(",")] if proposed_functions else None
    result = manager.check_file(file_path, funcs)

    _log_session_action(
        project_root,
        action_type="check_file",
        description=f"Pre-edit check for {file_path}: {'Allowed' if result.allowed else 'Blocked'}",
        file_path=file_path,
        outcome="allowed" if result.allowed else "blocked"
    )

    return json.dumps({
        "allowed": result.allowed,
        "reason": result.reason,
        "blocked_functions": result.blocked_functions,
        "safe_to_edit": result.safe_to_edit,
        "warning": result.warning,
    }, indent=2)



# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 7 — List All Locked Files
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_locked(
    project_path: Optional[str] = None,
) -> str:
    """
    List all currently locked (frozen) files and functions in the Ledger.

    Args:
        project_path: Project directory.

    Returns:
        JSON summary of all locked features with file paths, functions, reasons, and dates.
    """
    from ledger.manager import LedgerManager

    project_root = _resolve_project(project_path)
    manager = LedgerManager(project_root)
    summary = manager.get_ledger_summary()

    return json.dumps(summary, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 8 — Verify Ledger Integrity
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def verify_integrity(
    project_path: Optional[str] = None,
) -> str:
    """
    Verify SHA-256 integrity of all locked files. Detects if any locked file
    was tampered with after being frozen.

    Args:
        project_path: Project directory.

    Returns:
        JSON with list of tampered files (empty list = all clean).
    """
    from ledger.manager import LedgerManager

    project_root = _resolve_project(project_path)
    manager = LedgerManager(project_root)
    tampered = manager.verify_integrity()

    return json.dumps({
        "status": "clean" if not tampered else "tampered",
        "tampered_files": tampered,
        "total_locked": len(manager.state.locked_features),
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 9 — Get Dependency Graph Summary
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_graph_summary(
    project_path: Optional[str] = None,
) -> str:
    """
    Get a summary of the project's dependency graph: total files, edges,
    top connected files, and isolated files.

    Args:
        project_path: Project directory.

    Returns:
        JSON with node count, edge count, top connected nodes, and isolated nodes.
    """
    from config.settings import settings
    from core.graph_builder import load_graph

    project_root = Path(_resolve_project(project_path)).resolve()
    graph_file = project_root / settings.GRAPH_FILENAME

    if not graph_file.exists():
        return json.dumps({
            "status": "error",
            "message": "No dependency graph found. Run scan_project first.",
        })

    graph = load_graph(str(graph_file))
    if graph is None:
        return json.dumps({"status": "error", "message": "Failed to load graph."})

    # Top connected nodes by total degree
    degrees = sorted(graph.degree(), key=lambda x: x[1], reverse=True)
    top_connected = [{"file": n, "connections": d} for n, d in degrees[:10]]
    isolated = [n for n, d in degrees if d == 0]

    return json.dumps({
        "status": "success",
        "project": str(project_root),
        "total_files": graph.number_of_nodes(),
        "total_edges": graph.number_of_edges(),
        "top_connected_files": top_connected,
        "isolated_files": isolated,
        "isolated_count": len(isolated),
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 10 — Find Shortest Dependency Path
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
def find_dependency_path(
    source_file: str,
    target_file: str,
    project_path: Optional[str] = None,
) -> str:
    """
    Find the shortest import/dependency path between two files in the codebase.

    Args:
        source_file: Relative path of the source file (e.g., "core/parser.py").
        target_file: Relative path of the target file (e.g., "utils/logger.py").
        project_path: Project directory.

    Returns:
        JSON with the dependency path (list of files) and path length.
    """
    import networkx as nx
    from config.settings import settings
    from core.graph_builder import load_graph

    project_root = Path(_resolve_project(project_path)).resolve()
    graph_file = project_root / settings.GRAPH_FILENAME

    if not graph_file.exists():
        return json.dumps({"status": "error", "message": "No dependency graph. Run scan_project first."})

    graph = load_graph(str(graph_file))
    if graph is None:
        return json.dumps({"status": "error", "message": "Failed to load graph."})

    def _find_fuzzy(q: str):
        if not q:
            return None
        if q in graph.nodes:
            return q
        std = q.replace("\\", "/").strip().lstrip("/")
        if std in graph.nodes:
            return std
        lower = std.lower()
        for node in graph.nodes:
            ns = str(node).replace("\\", "/")
            if ns.lower() == lower or ns.lower().endswith("/" + lower) or Path(node).name.lower() == lower:
                return str(node)
        return None

    src = _find_fuzzy(source_file)
    tgt = _find_fuzzy(target_file)

    if not src:
        return json.dumps({"status": "error", "message": f"Source file '{source_file}' not found in graph."})
    if not tgt:
        return json.dumps({"status": "error", "message": f"Target file '{target_file}' not found in graph."})

    try:
        path = nx.shortest_path(graph, source=src, target=tgt)
        return json.dumps({"status": "found", "path": path, "length": len(path), "directed": True, "source": src, "target": tgt}, indent=2)
    except nx.NetworkXNoPath:
        pass

    # Try reverse directed
    try:
        path_rev = nx.shortest_path(graph, source=tgt, target=src)
        path = list(reversed(path_rev))
        return json.dumps({"status": "found", "path": path, "length": len(path), "directed": False, "reverse": True, "source": src, "target": tgt}, indent=2)
    except nx.NetworkXNoPath:
        pass

    # Try undirected fallback
    try:
        path = nx.shortest_path(graph.to_undirected(), source=src, target=tgt)
        return json.dumps({"status": "found", "path": path, "length": len(path), "directed": False, "source": src, "target": tgt}, indent=2)
    except nx.NetworkXNoPath:
        return json.dumps({"status": "no_path", "message": f"No dependency path between '{src}' and '{tgt}'."})


# ═══════════════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logger.info("Starting TokenGuard MCP Server (stdio transport)...")
    mcp.run(transport="stdio")
