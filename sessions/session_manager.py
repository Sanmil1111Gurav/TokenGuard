"""
Session Manager and Store for TokenGuard.
Tracks interaction actions, token metrics, and active session memory.
"""

import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from prompt_compression.models import SessionAction
from config.settings import settings


class Session:
    def __init__(
        self,
        session_id: str,
        project_root: str,
        task_description: str = "",
        created_at: Optional[str] = None,
        actions: Optional[List[SessionAction]] = None,
    ):
        self.session_id = session_id
        self.project_root = project_root
        self.task_description = task_description
        self.created_at = created_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.actions = actions or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "project_root": self.project_root,
            "task_description": self.task_description,
            "created_at": self.created_at,
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        actions = [SessionAction.from_dict(a) for a in data.get("actions", [])]
        return cls(
            session_id=data.get("session_id", ""),
            project_root=data.get("project_root", ""),
            task_description=data.get("task_description", ""),
            created_at=data.get("created_at"),
            actions=actions,
        )


class SessionStore:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._active_sessions: Dict[str, Session] = {}

    def get_active_session(self, project_root: str) -> Optional[Session]:
        norm_root = str(Path(project_root).resolve()).lower()
        for r, s in self._active_sessions.items():
            if r.lower() == norm_root:
                return s
        
        # Check disk for latest session file
        session_files = sorted(self.storage_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for sf in session_files:
            try:
                data = json.loads(sf.read_text(encoding="utf-8"))
                # Match root or accept session stored in this project's folder
                p = str(Path(data.get("project_root", "")).resolve()).lower()
                if p == norm_root or sf.parent == self.storage_dir:
                    session = Session.from_dict(data)
                    self._active_sessions[norm_root] = session
                    return session
            except Exception:
                pass
        return None


    def save_session(self, session: Session):
        norm_root = str(Path(session.project_root).resolve())
        self._active_sessions[norm_root] = session
        file_path = self.storage_dir / f"{session.session_id}.json"
        file_path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")

    def get_session(self, session_id: str) -> Optional[Session]:
        for session in self._active_sessions.values():
            if session.session_id == session_id:
                return session
        file_path = self.storage_dir / f"{session_id}.json"
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                return Session.from_dict(data)
            except Exception:
                pass
        return None


class SessionManager:
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        storage_dir = self.project_root / settings.SESSION_DIR
        self.store = SessionStore(storage_dir)

    def start_session(self, project_root: str = ".", task_description: str = "") -> Session:
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            project_root=str(Path(project_root).resolve()),
            task_description=task_description,
        )
        self.store.save_session(session)
        return session

    def log_action(
        self,
        session_id: str,
        action_type: str,
        file_path: str = "",
        functions_touched: Optional[List[str]] = None,
        description: str = "",
        tokens_used: int = 0,
        tokens_saved: int = 0,
        original_tokens: int = 0,
        compressed_tokens: int = 0,
        reduction_percent: float = 0.0,
        outcome: str = "success",
    ) -> SessionAction:
        action = SessionAction(
            action_id=str(uuid.uuid4()),
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            action_type=action_type,
            file_path=file_path,
            functions_touched=functions_touched or [],
            description=description,
            tokens_used=tokens_used,
            tokens_saved=tokens_saved,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            reduction_percent=reduction_percent,
            outcome=outcome,
        )

        session = self.store.get_session(session_id)
        if session:
            session.actions.append(action)
            self.store.save_session(session)

        return action

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        session = self.store.get_session(session_id)
        if not session:
            return {
                "session_id": session_id,
                "total_actions": 0,
                "total_tokens_used": 0,
                "total_tokens_saved": 0,
                "compression_ratio": 0.0,
                "reduction_percent": 0.0,
                "changed_files": [],
                "recent_actions": [],
            }

        total_used = sum(a.tokens_used for a in session.actions)
        total_saved = sum(a.tokens_saved for a in session.actions)
        if (total_saved + total_used) > 0:
            compression_ratio = round(total_saved / (total_saved + total_used), 3)
            reduction_percent = round((total_saved / (total_saved + total_used)) * 100.0, 1)
        else:
            compression_ratio = 0.0
            reduction_percent = 0.0

        changed_files = []
        for a in session.actions:
            if a.file_path and a.file_path not in changed_files:
                changed_files.append(a.file_path)

        return {
            "session_id": session.session_id,
            "project_root": session.project_root,
            "task_description": session.task_description,
            "created_at": session.created_at,
            "total_actions": len(session.actions),
            "total_tokens_used": total_used,
            "total_tokens_saved": total_saved,
            "compression_ratio": compression_ratio,
            "reduction_percent": reduction_percent,
            "changed_files": changed_files,
            "recent_actions": [a.to_dict() for a in session.actions[-20:]],
        }

