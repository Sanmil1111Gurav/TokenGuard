"""
graph_processor.py — Transforms dependency_graph.json into D3 force-graph format.

Responsibilities:
  - Read and parse dependency_graph.json produced by graph_builder.py
  - Compute imported_by_count for every node (reverse edge count)
  - Compute node size, group (folder), and colour category
  - Compute graph-wide stats block
  - Return a dict ready to be served by the FastAPI /api/graph endpoint
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_folder(file_path: str) -> str:
    """Return the top-level folder name, or 'root' if file is at root level."""
    parts = Path(file_path).parts
    return parts[0] if len(parts) > 1 else "root"


def _node_size(imported_by_count: int) -> float:
    """Scale: hub files that many others depend on appear larger."""
    return max(6, 1 + imported_by_count * 2.5)


def _language(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".js", ".jsx"}:
        return "javascript"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    return "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_graph(graph_path: str, hide_isolated: bool = False) -> dict[str, Any]:
    """
    Read dependency_graph.json and return a D3-compatible graph dict.

    Args:
        graph_path: Absolute path to dependency_graph.json.
        hide_isolated: When True, nodes with zero connections are excluded.

    Returns:
        Dict with keys: nodes, links, stats
    """
    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("graph_processor: failed to read %s — %s", graph_path, exc)
        return {"nodes": [], "links": [], "stats": {}}

    raw_nodes: list[dict] = raw.get("nodes", [])
    raw_edges: list[dict] = raw.get("edges", [])

    # ---- Build imported_by lookup ----------------------------------------
    imported_by: dict[str, list[str]] = {n["id"]: [] for n in raw_nodes}
    for edge in raw_edges:
        target = edge.get("target", "")
        source = edge.get("source", "")
        if target in imported_by:
            imported_by[target].append(source)

    # ---- Build has_any_connection set -------------------------------------
    connected_ids: set[str] = set()
    for edge in raw_edges:
        connected_ids.add(edge.get("source", ""))
        connected_ids.add(edge.get("target", ""))

    # ---- Transform nodes --------------------------------------------------
    d3_nodes: list[dict] = []
    language_counts: dict[str, int] = {}
    most_connected_file = ""
    most_connected_count = -1

    from ledger.manager import LedgerManager
    from sessions.session_manager import SessionManager
    project_root = str(Path(graph_path).parent)
    manager = LedgerManager(project_root)

    # Detect changed files in project from git or session actions
    changed_set: set[str] = set()
    ignored_prefixes = (
        ".git", ".cursor", ".agents", "sessions", "dependency_graph.json",
        ".active_project", ".cursorrules", ".gitignore", "node_modules", ".next", "dist", "build", ".venv"
    )
    try:
        import subprocess
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=2
        )
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                if len(line) < 3:
                    continue
                raw_path = line[3:].strip().strip('"').replace("\\", "/")
                if raw_path.endswith("/"):
                    continue
                if any(raw_path.startswith(p) for p in ignored_prefixes):
                    continue
                if raw_path in ignored_prefixes:
                    continue
                abs_f = Path(project_root) / raw_path
                if abs_f.is_file():
                    changed_set.add(raw_path)
    except Exception:
        pass

    try:
        sm = SessionManager(project_root)
        sess = sm.store.get_active_session(project_root)
        if sess:
            for a in sess.actions:
                if a.file_path:
                    fp = a.file_path.replace("\\", "/").strip().lstrip("./")
                    if not any(fp.startswith(p) for p in ignored_prefixes):
                        changed_set.add(fp)
    except Exception:
        pass

    for raw_node in raw_nodes:
        node_id: str = raw_node.get("id", raw_node.get("file_path", ""))
        ibc = len(imported_by.get(node_id, []))
        is_isolated = node_id not in connected_ids

        if hide_isolated and is_isolated:
            continue

        lang = raw_node.get("language") or _language(node_id)
        language_counts[lang] = language_counts.get(lang, 0) + 1

        fns = raw_node.get("functions", [])
        cls = raw_node.get("classes", [])
        imps = raw_node.get("imports", [])

        node_id_std = node_id.replace("\\", "/").strip()
        if node_id_std.startswith("./"):
            node_id_std = node_id_std[2:]

        lock_status = "unlocked"
        locked_funcs = []
        feat = manager.state.locked_features.get(node_id_std) or manager.state.locked_features.get(node_id)
        if feat:
            lock_status = "frozen" if feat.lock_entire_file else "partially_frozen"
            locked_funcs = feat.locked_functions

        is_changed = (
            node_id_std in changed_set
            or node_id in changed_set
            or any(node_id_std.endswith(c) for c in changed_set)
        )

        node: dict[str, Any] = {
            "id": node_id,
            "label": Path(node_id).name,
            "language": lang,
            "functions": fns,
            "classes": cls,
            "imports": imps,
            "imports_count": len(imps),
            "imported_by": imported_by.get(node_id, []),
            "imported_by_count": ibc,
            "size": _node_size(ibc),
            "group": _first_folder(node_id),
            "summary": raw_node.get("summary", ""),
            "is_isolated": is_isolated,
            "is_changed": is_changed,
            "lock_status": lock_status,
            "locked_functions": locked_funcs,
        }
        d3_nodes.append(node)


        if ibc > most_connected_count:
            most_connected_count = ibc
            most_connected_file = node_id

    # Dynamically inject newly created/untracked files so they appear live in graph
    existing_ids = {n["id"] for n in d3_nodes}
    for cf in changed_set:
        if cf not in existing_ids and not any(n["id"].endswith(cf) for n in d3_nodes):
            d3_nodes.append({
                "id": cf,
                "label": Path(cf).name,
                "language": _language(cf),
                "functions": [],
                "classes": [],
                "imports": [],
                "imports_count": 0,
                "imported_by": [],
                "imported_by_count": 0,
                "size": 8,
                "group": _first_folder(cf),
                "summary": "Newly modified / created file",
                "is_isolated": True,
                "is_changed": True,
                "lock_status": "unlocked",
                "locked_functions": [],
            })
            existing_ids.add(cf)

    # ---- Transform edges --------------------------------------------------
    valid_ids = {n["id"] for n in d3_nodes}
    d3_links: list[dict] = []
    for edge in raw_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in valid_ids and tgt in valid_ids:
            d3_links.append({
                "source": src,
                "target": tgt,
                "type": "imports",
                "raw_import": edge.get("raw_import", ""),
            })

    # ---- Stats ------------------------------------------------------------
    isolated_count = sum(1 for n in d3_nodes if n["is_isolated"])
    frozen_count = sum(1 for n in d3_nodes if n.get("lock_status") in ("frozen", "partially_frozen"))
    stats: dict[str, Any] = {
        "total_files": len(d3_nodes),
        "total_connections": len(d3_links),
        "most_connected_file": most_connected_file,
        "isolated_files": isolated_count,
        "languages": language_counts,
        "changed_files": list(changed_set),
        "changed_files_count": len(changed_set),
        "frozen_count": frozen_count,
    }


    logger.info(
        "graph_processor: %d nodes, %d links, most connected: %s",
        len(d3_nodes), len(d3_links), most_connected_file,
    )

    return {"nodes": d3_nodes, "links": d3_links, "stats": stats}
