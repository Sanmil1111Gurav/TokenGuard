import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from config.settings import settings
from core.graph_builder import load_graph
from ledger.models import LockedFeature, LedgerState, GuardResult
from ledger.store import LedgerStore
from utils.logger import get_logger
from rich.table import Table
from rich.console import Console

import sys

logger = get_logger()
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
console = Console()

class LedgerManager:
    def __init__(self, project_root: str):
        self.store = LedgerStore(project_root)
        self.project_root = self.store.get_project_root()
        self.state = self._load_state()

    def _load_state(self) -> LedgerState:
        data = self.store.load()
        if not data:
            now = datetime.now(timezone.utc).isoformat()
            return LedgerState(
                project_root=self.project_root,
                created_at=now,
                last_updated=now,
                locked_features={},
                change_history=[]
            )
        
        features = {}
        for k, v in data.get("locked_features", {}).items():
            features[k] = LockedFeature(**v)
            
        return LedgerState(
            project_root=data.get("project_root", self.project_root),
            created_at=data.get("created_at", ""),
            last_updated=data.get("last_updated", ""),
            locked_features=features,
            change_history=data.get("change_history", [])
        )

    def _save_state(self):
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        
        # Convert state to dict
        data = {
            "project_root": self.state.project_root,
            "created_at": self.state.created_at,
            "last_updated": self.state.last_updated,
            "locked_features": {k: v.__dict__ for k, v in self.state.locked_features.items()},
            "change_history": self.state.change_history
        }
        self.store.save(data)

    def _calculate_checksum(self, file_path: str) -> str:
        abs_path = os.path.join(self.project_root, file_path)
        if not os.path.exists(abs_path):
            return ""
        hasher = hashlib.sha256()
        with open(abs_path, 'rb') as f:
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def _add_history(self, event: str, file_path: str, reason: str, **kwargs):
        history_entry = {
            "event": event,
            "file_path": file_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason
        }
        history_entry.update(kwargs)
        self.state.change_history.append(history_entry)
        self._save_state()

    def lock_file(self, file_path: str, reason: str, functions: Optional[List[str]] = None, classes: Optional[List[str]] = None) -> bool:
        # Standardize path
        file_path = file_path.replace("\\", "/")
        if file_path.startswith("./"):
            file_path = file_path[2:]
            
        # Verify file exists in dependency_graph.json
        graph_path = os.path.join(self.project_root, settings.GRAPH_FILENAME)
        graph = load_graph(graph_path)
        if graph is None or not graph.has_node(file_path):
            logger.error(f"Cannot lock '{file_path}': File not found in dependency graph. Please run TokenGuard pipeline first.")
            return False

        checksum = self._calculate_checksum(file_path)
        
        lock_entire_file = False
        funcs = functions or []
        clss = classes or []
        if not funcs and not clss:
            lock_entire_file = True

        feature = LockedFeature(
            id=str(uuid.uuid4()),
            file_path=file_path,
            locked_functions=funcs,
            locked_classes=clss,
            lock_entire_file=lock_entire_file,
            reason=reason,
            locked_at=datetime.now(timezone.utc).isoformat(),
            locked_by="developer",
            status="frozen",
            checksum=checksum
        )
        
        self.state.locked_features[file_path] = feature
        
        self._add_history(
            event="file_locked",
            file_path=file_path,
            reason=reason,
            locked_functions=funcs,
            locked_classes=clss,
            lock_entire_file=lock_entire_file
        )
        
        funcs_str = ", ".join(funcs) if funcs else ("(entire file)" if lock_entire_file else "")
        console.print(f"[bold green]✅ Locked:[/bold green] {file_path} — {funcs_str} (Reason: {reason})")
        return True

    def unlock_file(self, file_path: str, functions: Optional[List[str]] = None) -> bool:
        file_path = file_path.replace("\\", "/")
        if file_path.startswith("./"):
            file_path = file_path[2:]
            
        if file_path not in self.state.locked_features:
            logger.warning(f"File '{file_path}' is not locked.")
            return False
            
        feature = self.state.locked_features[file_path]
        
        if not functions:
            # Unlock entire file
            del self.state.locked_features[file_path]
            self._add_history(
                event="file_unlocked",
                file_path=file_path,
                reason="Manual unlock",
                functions_unlocked="all"
            )
            console.print(f"🔓 [bold green]Unlocked:[/bold green] {file_path}")
            return True
        else:
            # Unlock specific functions
            current_funcs = set(feature.locked_functions)
            for f in functions:
                current_funcs.discard(f)
                
            feature.locked_functions = list(current_funcs)
            if not feature.locked_functions and not feature.locked_classes and not feature.lock_entire_file:
                del self.state.locked_features[file_path]
            
            self._add_history(
                event="functions_unlocked",
                file_path=file_path,
                reason="Manual unlock",
                functions_unlocked=functions
            )
            console.print(f"🔓 [bold green]Unlocked functions:[/bold green] {', '.join(functions)} in {file_path}")
            self._save_state()
            return True

    def check_file(self, file_path: str, proposed_functions: Optional[List[str]] = None) -> GuardResult:
        file_path = file_path.replace("\\", "/")
        if file_path.startswith("./"):
            file_path = file_path[2:]
            
        if file_path not in self.state.locked_features:
            return GuardResult(allowed=True, reason="Not locked")
            
        feature = self.state.locked_features[file_path]
        
        # Check checksum
        current_checksum = self._calculate_checksum(file_path)
        warning = ""
        if current_checksum and current_checksum != feature.checksum:
            warning = f"⚠️ File content has changed since it was locked — consider re-locking"
            
        if feature.lock_entire_file:
            return GuardResult(
                allowed=False, 
                reason="Entire file is frozen", 
                blocked_functions=feature.locked_functions,
                warning=warning
            )
            
        if proposed_functions:
            blocked = set(feature.locked_functions).intersection(set(proposed_functions))
            if blocked:
                return GuardResult(
                    allowed=False,
                    reason="Attempted to edit frozen functions",
                    blocked_functions=list(blocked),
                    warning=warning
                )
                
        # Get graph for safe_functions
        safe_functions = []
        graph_path = os.path.join(self.project_root, settings.GRAPH_FILENAME)
        graph = load_graph(graph_path)
        if graph and graph.has_node(file_path):
            all_funcs = graph.nodes[file_path].get("functions", [])
            safe_functions = [f for f in all_funcs if f not in feature.locked_functions]
            
        if not warning:
            funcs_str = ", ".join(feature.locked_functions)
            warning = f"⚠️ File has frozen functions: {funcs_str}"
            
        return GuardResult(
            allowed=True,
            reason="Edit allowed, no overlap with frozen functions",
            safe_to_edit=safe_functions,
            warning=warning
        )

    def list_locked(self):
        table = Table(title="Locked Features (TokenGuard Ledger)", header_style="bold magenta")
        table.add_column("File Path", style="cyan")
        table.add_column("Locked Items", style="green")
        table.add_column("Reason")
        table.add_column("Locked Date", style="dim")
        
        # Group by language (simple heuristic by extension)
        sorted_features = sorted(
            self.state.locked_features.values(), 
            key=lambda f: (0 if f.file_path.endswith('.py') else 1, f.file_path)
        )
        
        for feature in sorted_features:
            items = "entire file" if feature.lock_entire_file else ", ".join(feature.locked_functions)
            if feature.locked_classes:
                items += " (classes: " + ", ".join(feature.locked_classes) + ")"
            table.add_row(
                feature.file_path,
                items,
                feature.reason,
                feature.locked_at[:19].replace("T", " ")
            )
            
        console.print(table)

    def get_ledger_summary(self) -> Dict[str, Any]:
        total_files = len(self.state.locked_features)
        total_funcs = sum(len(f.locked_functions) for f in self.state.locked_features.values())
        return {
            "total_locked_files": total_files,
            "total_locked_functions": total_funcs,
            "locked_files": list(self.state.locked_features.keys()),
            "last_updated": self.state.last_updated,
            "locked_features": {k: v.__dict__ for k, v in self.state.locked_features.items()}
        }

    def verify_integrity(self):
        tampered_files = []
        for file_path, feature in self.state.locked_features.items():
            current_checksum = self._calculate_checksum(file_path)
            if current_checksum and current_checksum != feature.checksum:
                console.print(f"[bold red]⚠️ WARNING:[/bold red] {file_path} was modified after locking")
                tampered_files.append(file_path)
        
        if not tampered_files:
            console.print("[bold green]✅ Integrity check passed.[/bold green] No locked files were tampered with.")
            
        return tampered_files
