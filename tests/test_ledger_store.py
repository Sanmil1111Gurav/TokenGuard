import os
import json
import tempfile
import pytest
from ledger.store import LedgerStore

def test_ledger_store_atomic_save():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = LedgerStore(temp_dir)
        data = {
            "project_root": temp_dir,
            "created_at": "now",
            "last_updated": "now",
            "locked_features": {},
            "change_history": []
        }
        
        store.save(data)
        
        assert store.exists()
        
        loaded = store.load()
        assert loaded["project_root"] == temp_dir
        assert "locked_features" in loaded

def test_ledger_store_corrupt_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = LedgerStore(temp_dir)
        # Write corrupt JSON manually
        os.makedirs(os.path.dirname(store.ledger_path), exist_ok=True)
        with open(store.ledger_path, "w") as f:
            f.write("{ invalid json ")
            
        with pytest.raises(ValueError, match="Corrupt ledger file"):
            store.load()
