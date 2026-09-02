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
    project_root = str(Path(graph_path).parent)
    manager = LedgerManager(project_root)

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
            "lock_status": lock_status,
            "locked_functions": locked_funcs,
        }
        d3_nodes.append(node)

        if ibc > most_connected_count:
            most_connected_count = ibc
            most_connected_file = node_id

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
    stats: dict[str, Any] = {
        "total_files": len(d3_nodes),
        "total_connections": len(d3_links),
        "most_connected_file": most_connected_file,
        "isolated_files": isolated_count,
        "languages": language_counts,
    }

    logger.info(
        "graph_processor: %d nodes, %d links, most connected: %s",
        len(d3_nodes), len(d3_links), most_connected_file,
    )

    return {"nodes": d3_nodes, "links": d3_links, "stats": stats}
