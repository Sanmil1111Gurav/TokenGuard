import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any

from config.settings import settings
from utils.logger import get_logger

logger = get_logger()

class LedgerStore:
    def __init__(self, project_root: str):
        self.project_root = str(Path(project_root).resolve())
        self.ledger_path = os.path.join(self.project_root, settings.LEDGER_FILENAME)

    def get_project_root(self) -> str:
        return self.project_root

    def exists(self) -> bool:
        return os.path.exists(self.ledger_path)

    def load(self) -> Dict[str, Any]:
        """Loads and validates the ledger JSON."""
        if not self.exists():
            return {}

        try:
            with open(self.ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Minimal structure validation
            if not isinstance(data, dict):
                raise ValueError("Ledger root must be a dictionary")
            if "locked_features" not in data or "change_history" not in data:
                raise ValueError("Missing required fields 'locked_features' or 'change_history'")
                
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Ledger file is corrupt (JSON Decode Error): {e}. Please delete {self.ledger_path} and restart.")
            raise ValueError(f"Corrupt ledger file: {e}") from e
        except Exception as e:
            logger.error(f"Error reading ledger file: {e}")
            raise

    def save(self, ledger_data: Dict[str, Any]) -> None:
        """Atomically saves the ledger JSON to disk."""
        dir_name = os.path.dirname(self.ledger_path)
        os.makedirs(dir_name, exist_ok=True)
        
        fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="ledger_", suffix=".json")
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(ledger_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Atomic rename (works on POSIX; on Windows os.replace handles existing destinations)
            os.replace(temp_path, self.ledger_path)
        except Exception as e:
            logger.error(f"Failed to save ledger atomically: {e}")
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise
