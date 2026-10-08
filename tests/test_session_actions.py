import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import unittest
from prompt_compression.models import SessionAction
from sessions.session_manager import SessionManager

class TestSessionActions(unittest.TestCase):
    def test_session_action_token_metrics(self):
        action_data = {
            "action_id": "test-123",
            "timestamp": "2026-09-06T20:51:49.315016+00:00",
            "action_type": "query",
            "file_path": "",
            "functions_touched": [],
            "description": "Context built for task: add log level in logger.py",
            "tokens_used": 3181,
            "tokens_saved": 29303,
            "original_tokens": 32484,
            "compressed_tokens": 3181,
            "reduction_percent": 90.2,
            "outcome": "success"
        }
        action = SessionAction.from_dict(action_data)
        d = action.to_dict()

        self.assertEqual(d["original_tokens"], 32484)
        self.assertEqual(d["compressed_tokens"], 3181)
        self.assertEqual(d["tokens_saved"], 29303)
        self.assertEqual(round(d["reduction_percent"]), 90)

    def test_session_manager_log_action(self):
        manager = SessionManager(project_root=".")
        session = manager.start_session(project_root=".", task_description="Test task")
        action = manager.log_action(
            session_id=session.session_id,
            action_type="query",
            file_path="utils/logger.py",
            description="Context built for task: add log level in logger.py",
            tokens_used=3181,
            tokens_saved=29303,
            original_tokens=32484,
            compressed_tokens=3181,
            reduction_percent=90.2,
            outcome="success"
        )
        d = action.to_dict()
        self.assertEqual(d["original_tokens"], 32484)
        self.assertEqual(d["compressed_tokens"], 3181)
        self.assertEqual(d["tokens_saved"], 29303)

if __name__ == "__main__":
    unittest.main()
