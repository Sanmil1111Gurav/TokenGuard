import json
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Set
import networkx as nx
from config.settings import settings
from core.parser import ParsedFileMetadata
from utils.logger import get_logger, log_step

logger = get_logger()

# Common web and backend source file extensions
CANDIDATE_EXTENSIONS = [
    "",
    ".tsx",
    ".ts",
    ".jsx",
    ".js",
    ".py",
    "/index.tsx",
    "/index.ts",
    "/index.jsx",
    "/index.js",
    "/index.py",
    ".json",
    ".css",
    ".scss",
    ".module.css",
    ".module.scss",
    ".d.ts"
]


def _parse_tsconfig_paths(project_root: Optional[str]) -> Dict[str, List[str]]:
    """Parse compilerOptions.paths from tsconfig.json or jsconfig.json if present."""
    if not project_root:
        return {}
    for filename in ["tsconfig.json", "jsconfig.json"]:
        conf_path = Path(project_root) / filename
        if conf_path.exists():
            try:
                with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                # Strip comments for jsonc
                text_clean = re.sub(r'//.*', '', text)
                text_clean = re.sub(r'/\*.*?\*/', '', text_clean, flags=re.DOTALL)
                data = json.loads(text_clean)
                compiler_opts = data.get("compilerOptions", {})
                paths = compiler_opts.get("paths", {})
                if paths:
                    return paths
            except Exception as e:
                logger.debug(f"Could not parse {filename}: {e}")
    return {}


def resolve_import_path(
    current_file: str,
    import_str: str,
    all_files: Set[str],
    project_root: Optional[str] = None,
    tsconfig_paths: Optional[Dict[str, List[str]]] = None,
    all_files_lower: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """
    Resolve an import statement string to an actual file path in the project.
    
    Supports:
      - Relative imports (./foo, ../bar)
      - Path aliases (@/components/..., ~/lib/...)
      - tsconfig.json / jsconfig.json custom path mappings
      - Barrel file indexes (/index.tsx, /index.ts, /index.jsx, /index.js)
      - Non-relative root or src-based imports
      - Python module dot notation (core.parser -> core/parser.py)
      - Case-insensitive Windows path resolution fallback
    
    Args:
        current_file: Relative path of the file containing the import.
        import_str: Raw import string.
        all_files: Set of all valid relative file paths in the project.
        project_root: Optional absolute root directory.
        tsconfig_paths: Optional pre-parsed tsconfig compilerOptions.paths.
        all_files_lower: Optional pre-built lowercased file lookup dictionary.
        
    Returns:
        Resolved relative file path if matched in project, else None.
    """
    if not import_str:
        return None

    current_dir = Path(current_file).parent
    possible_paths: List[Path] = []

    if all_files_lower is None:
        all_files_lower = {f.lower(): f for f in all_files}

    # 1. Relative import starting with . or ..
    if import_str.startswith("."):
        clean_imp = import_str
        if not ("/" in clean_imp or "\\" in clean_imp):
            if clean_imp.startswith(".."):
                clean_imp = "../" + clean_imp[2:].lstrip(".").replace(".", "/")
            elif clean_imp.startswith("."):
                clean_imp = "./" + clean_imp[1:].lstrip(".").replace(".", "/")
        
        target = current_dir / clean_imp
        possible_paths.append(target)
    else:
        # 2. Check custom tsconfig path aliases if configured
        if tsconfig_paths:
            for alias_pattern, target_patterns in tsconfig_paths.items():
                prefix = alias_pattern.replace("*", "")
                if import_str.startswith(prefix):
                    suffix = import_str[len(prefix):]
                    for tgt_pat in target_patterns:
                        resolved_cand = tgt_pat.replace("*", suffix).lstrip("./").lstrip(".\\")
                        possible_paths.append(Path(resolved_cand))

        # 3. Built-in Next.js / Vite / React path aliases (@/* and ~/*)
        if import_str.startswith("@/") or import_str.startswith("~/"):
            stripped = import_str[2:]
            possible_paths.append(Path(stripped))
            possible_paths.append(Path("src") / stripped)
            possible_paths.append(Path("app") / stripped)
        elif import_str.startswith("@") and "/" in import_str:
            # E.g. @components/Navbar or @lib/utils
            parts = import_str.split("/", 1)
            folder_part = parts[0].lstrip("@")
            rest = parts[1]
            possible_paths.append(Path(folder_part) / rest)
            possible_paths.append(Path("src") / folder_part / rest)

        # 4. Root-relative or baseUrl imports (e.g., components/Button or lib/db)
        possible_paths.append(Path(import_str))
        possible_paths.append(Path("src") / import_str)
        possible_paths.append(current_dir / import_str)

        # 5. Python module / package style import (e.g., core.parser or utils.logger)
        if "." in import_str:
            path_from_str = import_str.replace(".", "/")
            possible_paths.append(Path(path_from_str))
            possible_paths.append(current_dir / path_from_str)
            possible_paths.append(Path("src") / path_from_str)

    # Test candidates against known project files with all supported extensions
    for base_target in possible_paths:
        for ext in CANDIDATE_EXTENSIONS:
            candidate = str(base_target) + ext
            candidate_std = os.path.normpath(candidate).replace("\\", "/")
            if candidate_std in all_files:
                return candidate_std
            # Case-insensitive fallback for Windows filesystems
            lower_std = candidate_std.lower()
            if lower_std in all_files_lower:
                return all_files_lower[lower_std]

    return None


def build_dependency_graph(
    parsed_files: List[ParsedFileMetadata],
    project_root: str
) -> nx.DiGraph:
    """
    Build a directed NetworkX graph of codebase dependencies.
    
    Nodes represent files; edges represent "file A imports file B".
    
    Args:
        parsed_files: List of ParsedFileMetadata objects.
        project_root: Absolute project root directory.
        
    Returns:
        NetworkX DiGraph object.
    """
    graph = nx.DiGraph()
    all_files_set: Set[str] = {f.file_path for f in parsed_files}
    all_files_lower: Dict[str, str] = {f.lower(): f for f in all_files_set}
    tsconfig_paths: Dict[str, List[str]] = _parse_tsconfig_paths(project_root)

    with log_step("Dependency Graph Construction (Step 3)"):
        try:
            # Step 1: Add all nodes with metadata
            for meta in parsed_files:
                graph.add_node(
                    meta.file_path,
                    file_path=meta.file_path,
                    language=meta.language,
                    functions=meta.functions,
                    classes=meta.classes,
                    imports=meta.imports,
                    summary=meta.summary
                )

            # Step 2: Add directed edges for imports
            edges_added = 0
            for meta in parsed_files:
                for raw_import in meta.imports:
                    target_file = resolve_import_path(
                        meta.file_path,
                        raw_import,
                        all_files_set,
                        project_root=project_root,
                        tsconfig_paths=tsconfig_paths,
                        all_files_lower=all_files_lower
                    )
                    if target_file and target_file != meta.file_path:
                        graph.add_edge(meta.file_path, target_file, raw_import=raw_import)
                        edges_added += 1

            logger.info(
                f"Graph built with [bold green]{graph.number_of_nodes()}[/bold green] nodes "
                f"and [bold green]{edges_added}[/bold green] dependency edges."
            )
        except Exception as e:
            logger.error(f"Failed to build dependency graph: {e}")

    return graph


def save_graph(graph: nx.DiGraph, output_path: str) -> bool:
    """Save NetworkX graph to a JSON file."""
    try:
        data = nx.node_link_data(graph)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Dependency graph saved to [bold green]{output_path}[/bold green]")
        return True
    except Exception as e:
        logger.error(f"Failed to save dependency graph to '{output_path}': {e}")
        return False


def load_graph(input_path: str) -> Optional[nx.DiGraph]:
    """Load NetworkX graph from a JSON file."""
    if not os.path.exists(input_path):
        return None
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        graph = nx.node_link_graph(data)
        logger.info(f"Loaded existing dependency graph from [bold green]{input_path}[/bold green]")
        return graph
    except Exception as e:
        logger.warning(f"Could not load graph from '{input_path}': {e}")
        return None


def print_graph_summary(graph: nx.DiGraph):
    """Print an ASCII / Rich visual representation of the dependency graph."""
    from rich.tree import Tree
    from rich.console import Console

    # Force utf-8 output encoding for legacy Windows terminals
    console = Console(force_terminal=True, legacy_windows=False)
    tree = Tree("[bold cyan]Project Dependency Graph[/bold cyan]", guide_style="cyan")

    for node in graph.nodes():
        node_tree = tree.add(f"[bold yellow]{node}[/bold yellow] [dim]({graph.nodes[node].get('language', '')})[/dim]")
        neighbors = list(graph.successors(node))
        if neighbors:
            for target in neighbors:
                imp = graph.edges[node, target].get("raw_import", "imports")
                node_tree.add(f"[dim]-> imports[/dim] [green]{target}[/green] [dim]({imp})[/dim]")

    console.print(tree)
