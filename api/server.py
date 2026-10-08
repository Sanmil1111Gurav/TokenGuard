"""
server.py — FastAPI server for TokenGuard Visual Dependency Graph.

Endpoints:
  GET /                        → serves index.html
  GET /api/graph               → full D3-formatted graph JSON
  GET /api/path?from=&to=      → shortest dependency path between two files
  GET /api/file?path=          → full metadata + first 50 lines of source code
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path so internal imports work
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from config.settings import settings
from core.graph_builder import load_graph
from visualizer.graph_processor import process_graph
from utils.logger import get_logger

logger = get_logger()

app = FastAPI(title="TokenGuard Visual API", version="1.0.0")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(__file__).parent.parent / "visualizer" / "static"
_GRAPH_PATH = _PROJECT_ROOT / settings.GRAPH_FILENAME

def set_project(project_path: Path) -> None:
    """Set the active project root dynamically."""
    global _PROJECT_ROOT, _GRAPH_PATH
    _PROJECT_ROOT = Path(project_path).resolve()
    _GRAPH_PATH = _PROJECT_ROOT / settings.GRAPH_FILENAME


def _get_graph_path() -> Path:
    """Return the graph file path, raising 503 if it doesn't exist yet."""
    if not _GRAPH_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "dependency_graph.json not found. "
                "Run `python main.py --project <path>` first to build the graph."
            ),
        )
    return _GRAPH_PATH


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_frontend() -> FileResponse:
    """Serve the single-page visualizer HTML."""
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="index.html not found in visualizer/static/")
    return FileResponse(str(index), media_type="text/html")


@app.get("/api/graph")
async def get_graph(hide_isolated: bool = Query(False)) -> JSONResponse:
    """Return the full D3-formatted dependency graph."""
    graph_path = _get_graph_path()
    data = process_graph(str(graph_path), hide_isolated=hide_isolated)
    return JSONResponse(content=data)


@app.get("/api/path")
async def get_path(
    source: str = Query(..., alias="from"),
    target: str = Query(..., alias="to"),
) -> JSONResponse:
    """
    Return the shortest dependency path between two files using NetworkX.
    Query params:  ?from=src/auth/login.py&to=src/db/connection.py
    """
    graph_path = _get_graph_path()

    try:
        import networkx as nx
        G: nx.DiGraph = load_graph(str(graph_path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load graph: {exc}") from exc

    if source not in G.nodes:
        raise HTTPException(status_code=404, detail=f"Source node not found: {source}")
    if target not in G.nodes:
        raise HTTPException(status_code=404, detail=f"Target node not found: {target}")

    try:
        path = nx.shortest_path(G, source=source, target=target)
        return JSONResponse(content={"path": path, "length": len(path)})
    except Exception:
        # Try undirected fallback so the user sees SOME path
        try:
            path = nx.shortest_path(G.to_undirected(), source=source, target=target)
            return JSONResponse(content={"path": path, "length": len(path), "undirected": True})
        except Exception:
            return JSONResponse(content={"path": [], "length": 0, "error": "No path found"})


@app.get("/api/file")
async def get_file_detail(path: str = Query(...)) -> JSONResponse:
    """Return full metadata and first 50 lines of source for a single file."""
    graph_path = _get_graph_path()

    # Load raw graph for metadata
    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Find node
    node_data: dict[str, Any] | None = None
    for node in raw.get("nodes", []):
        if node.get("id") == path or node.get("file_path") == path:
            node_data = node
            break

    if node_data is None:
        raise HTTPException(status_code=404, detail=f"File not found in graph: {path}")

    # Compute imported_by
    imported_by = [
        e["source"] for e in raw.get("edges", [])
        if e.get("target") == path
    ]

    # Read first 50 lines of source
    source_lines: list[str] = []
    abs_path = _PROJECT_ROOT / path
    if abs_path.exists():
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                source_lines = [line.rstrip("\n") for _, line in zip(range(50), f)]
        except Exception as exc:
            logger.warning("Could not read source for %s: %s", path, exc)

    return JSONResponse(content={
        "file_path": path,
        "language": node_data.get("language", "unknown"),
        "functions": node_data.get("functions", []),
        "classes": node_data.get("classes", []),
        "imports": node_data.get("imports", []),
        "imported_by": imported_by,
        "summary": node_data.get("summary", ""),
        "source_preview": source_lines,
    })

# ---------------------------------------------------------------------------
# Ledger API
# ---------------------------------------------------------------------------
from pydantic import BaseModel
from typing import List, Optional
from ledger.manager import LedgerManager

class LockRequest(BaseModel):
    file_path: str
    reason: str = "No reason provided"
    functions: Optional[List[str]] = None
    classes: Optional[List[str]] = None

class UnlockRequest(BaseModel):
    file_path: str
    functions: Optional[List[str]] = None

def _get_ledger_manager() -> LedgerManager:
    return LedgerManager(str(_PROJECT_ROOT))

@app.post("/api/ledger/lock")
async def api_lock_file(req: LockRequest) -> JSONResponse:
    manager = _get_ledger_manager()
    success = manager.lock_file(req.file_path, req.reason, req.functions, req.classes)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to lock file (not found in graph)")
    feature = manager.state.locked_features.get(req.file_path)
    return JSONResponse(content={"success": True, "locked_feature": feature.__dict__ if feature else None})

class BatchLockRequest(BaseModel):
    file_paths: List[str]
    reason: str = "Batch freeze via UI"

class BatchUnlockRequest(BaseModel):
    file_paths: List[str]

@app.post("/api/ledger/lock_batch")
async def api_lock_batch(req: BatchLockRequest) -> JSONResponse:
    manager = _get_ledger_manager()
    success_files = []
    for fp in req.file_paths:
        if manager.lock_file(fp, req.reason):
            success_files.append(fp)
    return JSONResponse(content={"success": True, "locked_files": success_files, "count": len(success_files)})

@app.post("/api/ledger/unlock")
async def api_unlock_file(req: UnlockRequest) -> JSONResponse:
    manager = _get_ledger_manager()
    success = manager.unlock_file(req.file_path, req.functions)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to unlock file (not locked)")
    return JSONResponse(content={"success": True})

@app.post("/api/ledger/unlock_batch")
async def api_unlock_batch(req: BatchUnlockRequest) -> JSONResponse:
    manager = _get_ledger_manager()
    success_files = []
    for fp in req.file_paths:
        if manager.unlock_file(fp):
            success_files.append(fp)
    return JSONResponse(content={"success": True, "unlocked_files": success_files, "count": len(success_files)})

@app.get("/api/ledger")
async def api_get_ledger() -> JSONResponse:
    manager = _get_ledger_manager()
    return JSONResponse(content=manager.get_ledger_summary())

@app.get("/api/ledger/check")
async def api_check_ledger(file: str = Query(...)) -> JSONResponse:
    manager = _get_ledger_manager()
    result = manager.check_file(file)
    return JSONResponse(content={
        "allowed": result.allowed,
        "reason": result.reason,
        "blocked_functions": result.blocked_functions,
        "safe_to_edit": result.safe_to_edit,
        "warning": result.warning
    })

@app.get("/api/ledger/history")
async def api_get_ledger_history() -> JSONResponse:
    manager = _get_ledger_manager()
    return JSONResponse(content=manager.state.change_history)

@app.post("/api/ledger/verify")
async def api_verify_ledger() -> JSONResponse:
    manager = _get_ledger_manager()
    tampered = manager.verify_integrity()
    return JSONResponse(content={"success": True, "tampered_files": tampered})

# ---------------------------------------------------------------------------
# Token Compression & Session Memory API
# ---------------------------------------------------------------------------
from prompt_compression.compressor import TokenCompressor
from ledger.guard import before_edit, after_edit
from sessions.session_manager import SessionManager

def _get_session_manager() -> SessionManager:
    return SessionManager(str(_PROJECT_ROOT))

class CompressRequest(BaseModel):
    task: str
    max_input_tokens: Optional[int] = settings.MAX_INPUT_TOKENS
    max_output_tokens: Optional[int] = settings.MAX_OUTPUT_TOKENS

class TaskExecuteRequest(BaseModel):
    task: str
    target_file: str
    proposed_functions: Optional[List[str]] = None

@app.get("/api/session/active")
async def api_get_active_session() -> JSONResponse:
    """Return active session metrics, token savings history, and recent actions."""
    manager = _get_session_manager()
    session = manager.store.get_active_session(str(_PROJECT_ROOT))
    if not session:
        session = manager.start_session(str(_PROJECT_ROOT), "Interactive coding session")
    
    summary = manager.get_session_summary(session.session_id)
    summary["session"] = session.to_dict()
    return JSONResponse(content=summary)

@app.post("/api/session/build_context")
async def api_build_context(req: CompressRequest) -> JSONResponse:
    """Build compressed context for a task prompt and record action in active session."""
    manager = _get_session_manager()
    session = manager.store.get_active_session(str(_PROJECT_ROOT))
    if not session:
        session = manager.start_session(str(_PROJECT_ROOT), "Interactive coding session")

    compressor = TokenCompressor(str(_PROJECT_ROOT))
    context = compressor.compress_input(
        task=req.task,
        session_id=session.session_id,
        max_input_tokens=req.max_input_tokens or settings.MAX_INPUT_TOKENS,
        max_output_tokens=req.max_output_tokens or settings.MAX_OUTPUT_TOKENS
    )

    stats = context.token_stats
    action = manager.log_action(
        session_id=session.session_id,
        action_type="query",
        file_path="",
        description=f"Context built for task: {req.task}",
        tokens_used=stats.compressed_input_tokens,
        tokens_saved=stats.input_tokens_saved,
        original_tokens=stats.original_input_tokens,
        compressed_tokens=stats.compressed_input_tokens,
        reduction_percent=stats.input_reduction_percent,
        outcome="success"
    )

    summary = manager.get_session_summary(session.session_id)

    return JSONResponse(content={
        "context": context.to_dict(),
        "action": action.to_dict(),
        "session_summary": summary
    })

@app.post("/api/compress")
async def api_compress_prompt(req: CompressRequest) -> JSONResponse:
    """Compress context into High, Medium, Low, and Frozen priority levels and measure token savings."""
    compressor = TokenCompressor(str(_PROJECT_ROOT))
    context = compressor.compress_input(
        task=req.task,
        max_input_tokens=req.max_input_tokens or settings.MAX_INPUT_TOKENS,
        max_output_tokens=req.max_output_tokens or settings.MAX_OUTPUT_TOKENS
    )
    return JSONResponse(content=context.to_dict())

@app.post("/api/task/execute")
async def api_execute_task(req: TaskExecuteRequest) -> JSONResponse:
    """Integrated AI edit task execution with Freeze/Ledger check and Token Compression."""
    manager = _get_ledger_manager()
    guard_res = manager.check_file(req.target_file, req.proposed_functions)

    if not guard_res.allowed:
        return JSONResponse(
            status_code=403,
            content={
                "allowed": False,
                "status": "MODIFICATION BLOCKED",
                "reason": f"File/feature is frozen ({guard_res.reason})",
                "target_file": req.target_file,
                "blocked_functions": guard_res.blocked_functions
            }
        )

    compressor = TokenCompressor(str(_PROJECT_ROOT))
    context = compressor.compress_input(
        task=req.task,
        max_input_tokens=settings.MAX_INPUT_TOKENS,
        max_output_tokens=settings.MAX_OUTPUT_TOKENS
    )

    return JSONResponse(content={
        "allowed": True,
        "status": "MODIFICATION ALLOWED",
        "target_file": req.target_file,
        "warning": guard_res.warning,
        "token_stats": context.token_stats.to_dict(),
        "assembled_prompt_snippet": context.assembled_prompt[:300] + "..."
    })
