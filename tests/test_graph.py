import tempfile
import os
import networkx as nx
import pytest
from core.graph_builder import save_graph, load_graph

def test_graph_shortest_path_and_persistence():
    # Build 3-node graph manually
    graph = nx.DiGraph()
    
    graph.add_node("src/routes/user.py", summary="User routes")
    graph.add_node("src/auth/login.py", summary="Login logic")
    graph.add_node("src/db/connection.py", summary="DB Connection")

    graph.add_edge("src/routes/user.py", "src/auth/login.py")
    graph.add_edge("src/auth/login.py", "src/db/connection.py")

    # Verify shortest path
    path = nx.shortest_path(graph, "src/routes/user.py", "src/db/connection.py")
    assert path == ["src/routes/user.py", "src/auth/login.py", "src/db/connection.py"]

    # Test Save and Load
    with tempfile.TemporaryDirectory() as temp_dir:
        json_path = os.path.join(temp_dir, "test_dependency_graph.json")
        saved = save_graph(graph, json_path)
        assert saved is True

        reloaded_graph = load_graph(json_path)
        assert reloaded_graph is not None
        assert reloaded_graph.number_of_nodes() == 3
        assert reloaded_graph.number_of_edges() == 2
        
        reloaded_path = nx.shortest_path(reloaded_graph, "src/routes/user.py", "src/db/connection.py")
        assert reloaded_path == ["src/routes/user.py", "src/auth/login.py", "src/db/connection.py"]


def test_resolve_import_path_aliases():
    from core.graph_builder import resolve_import_path
    all_files = {
        "components/ui/button.tsx",
        "components/Navbar/index.tsx",
        "lib/utils.ts",
        "app/not-found.tsx",
        "app/page.tsx",
    }

    # 1. Alias import @/components/ui/button
    res1 = resolve_import_path("app/page.tsx", "@/components/ui/button", all_files)
    assert res1 == "components/ui/button.tsx"

    # 2. Barrel index import ./Navbar
    res2 = resolve_import_path("components/Layout.tsx", "./Navbar", all_files)
    assert res2 == "components/Navbar/index.tsx"

    # 3. Relative import with extension-less TS file
    res3 = resolve_import_path("app/page.tsx", "../lib/utils", all_files)
    assert res3 == "lib/utils.ts"

    # 4. Case-insensitive fallback
    res4 = resolve_import_path("app/page.tsx", "@/components/UI/Button", all_files)
    assert res4 == "components/ui/button.tsx"


def test_fuzzy_node_matching():
    from api.server import _find_node_fuzzy
    G = nx.DiGraph()
    G.add_node("app/not-found.tsx")
    G.add_node("components/ui/button.tsx")
    G.add_node("lib/utils.ts")

    # Match by base name
    assert _find_node_fuzzy(G, "not-found.tsx") == "app/not-found.tsx"
    # Match with backslashes
    assert _find_node_fuzzy(G, "components\\ui\\button.tsx") == "components/ui/button.tsx"
    # Match by exact path
    assert _find_node_fuzzy(G, "lib/utils.ts") == "lib/utils.ts"
    # Case-insensitive
    assert _find_node_fuzzy(G, "button.tsx") == "components/ui/button.tsx"
    # Non-existent
    assert _find_node_fuzzy(G, "non_existent.py") is None
