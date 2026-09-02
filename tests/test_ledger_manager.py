import os
import tempfile
import pytest
from ledger.manager import LedgerManager
from config.settings import settings
import json
import networkx as nx

def test_ledger_manager_lock_unlock():
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = LedgerManager(temp_dir)
        
        # Mock dependency graph for lock validation
        graph_path = os.path.join(temp_dir, settings.GRAPH_FILENAME)
        graph = nx.DiGraph()
        graph.add_node("test_file.py", functions=["func1", "func2"])
        with open(graph_path, "w") as f:
            json.dump({"nodes": [{"id": "test_file.py", "functions": ["func1", "func2"]}], "edges": []}, f)
            
        # Create a dummy file for checksum
        with open(os.path.join(temp_dir, "test_file.py"), "w") as f:
            f.write("def func1(): pass")
            
        # Lock whole file
        assert manager.lock_file("test_file.py", "Testing lock")
        assert "test_file.py" in manager.state.locked_features
        assert manager.state.locked_features["test_file.py"].lock_entire_file
        
        # Unlock
        assert manager.unlock_file("test_file.py")
        assert "test_file.py" not in manager.state.locked_features
        
        # Lock specific function
        assert manager.lock_file("test_file.py", "Lock func", functions=["func1"])
        assert "test_file.py" in manager.state.locked_features
        assert "func1" in manager.state.locked_features["test_file.py"].locked_functions
        assert not manager.state.locked_features["test_file.py"].lock_entire_file
