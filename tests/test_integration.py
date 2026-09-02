import os
import tempfile
import pytest
from ledger.guard import before_edit, after_edit
from ledger.manager import LedgerManager
from config.settings import settings
import json

def test_full_ledger_workflow():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Mock dependency graph
        graph_path = os.path.join(temp_dir, settings.GRAPH_FILENAME)
        with open(graph_path, "w") as f:
            json.dump({
                "nodes": [
                    {"id": "core/auth.py", "functions": ["login", "logout"]},
                    {"id": "api/routes.py", "functions": ["handle_req"]}
                ], 
                "edges": []
            }, f)
            
        os.makedirs(os.path.join(temp_dir, "core"), exist_ok=True)
        with open(os.path.join(temp_dir, "core/auth.py"), "w") as f:
            f.write("def login(): pass\ndef logout(): pass")
            
        manager = LedgerManager(temp_dir)
        
        # 1. Lock auth.py entirely
        assert manager.lock_file("core/auth.py", "Critical core auth")
        
        # 2. Agent tries to edit login
        res = before_edit("core/auth.py", {"functions_to_modify": ["login"]}, project_root=temp_dir)
        assert not res.allowed
        
        # 3. Unlock login function
        # Wait, if we lock entirely, can we unlock specific functions?
        # Unlock entire file
        assert manager.unlock_file("core/auth.py")
        
        # 4. Lock just login function
        assert manager.lock_file("core/auth.py", "Freeze login", functions=["login"])
        
        # 5. Agent tries to edit logout
        res2 = before_edit("core/auth.py", {"functions_to_modify": ["logout"]}, project_root=temp_dir)
        assert res2.allowed
        assert "logout" in res2.safe_to_edit
        
        # 6. Verify ledger history contains all events
        manager = LedgerManager(temp_dir)
        events = [e["event"] for e in manager.state.change_history]
        assert "file_locked" in events
        assert "file_unlocked" in events
