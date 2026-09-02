import os
import tempfile
import pytest
from ledger.guard import before_edit, after_edit
from ledger.manager import LedgerManager
from config.settings import settings
import json
import networkx as nx

def test_guard_before_edit():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Mock dependency graph
        graph_path = os.path.join(temp_dir, settings.GRAPH_FILENAME)
        with open(graph_path, "w") as f:
            json.dump({"nodes": [{"id": "main.py", "functions": ["run", "stop"]}], "edges": []}, f)
            
        # Create dummy file
        with open(os.path.join(temp_dir, "main.py"), "w") as f:
            f.write("def run(): pass")

        manager = LedgerManager(temp_dir)
        manager.lock_file("main.py", "Freeze run func", functions=["run"])
        
        # Check allowed
        res1 = before_edit("main.py", {"functions_to_modify": ["stop"]}, project_root=temp_dir)
        assert res1.allowed
        assert "stop" in res1.safe_to_edit
        
        # Check blocked
        res2 = before_edit("main.py", {"functions_to_modify": ["run"]}, project_root=temp_dir)
        assert not res2.allowed
        assert "run" in res2.blocked_functions
        
        # After edit
        after_edit("main.py", {"functions_modified": ["stop"]}, project_root=temp_dir)
        manager = LedgerManager(temp_dir) # reload
        assert len(manager.state.change_history) > 0
        assert manager.state.change_history[-1]["event"] == "edit_allowed"
