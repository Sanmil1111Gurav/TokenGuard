import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from rich.console import Console
from rich.panel import Panel

from ledger.manager import LedgerManager
from ledger.models import GuardResult
from utils.logger import get_logger

logger = get_logger()
console = Console()

def get_manager(project_root: str = ".") -> LedgerManager:
    return LedgerManager(project_root)

def before_edit(file_path: str, proposed_changes: Dict[str, Any], project_root: str = ".") -> GuardResult:
    """
    Call this BEFORE any agent attempts to edit a file.
    
    proposed_changes format:
    {
      "functions_to_modify": ["login", "validate_token"],
      "lines_to_modify": [45, 46, 47],
      "edit_type": "modify" | "delete" | "rename"
    }
    """
    manager = get_manager(project_root)
    funcs = proposed_changes.get("functions_to_modify", [])
    
    result = manager.check_file(file_path, funcs)
    
    if not result.allowed:
        feature = manager.state.locked_features.get(file_path)
        reason = feature.reason if feature else "Locked"
        funcs_str = ", ".join(result.blocked_functions) if result.blocked_functions else "Entire file"
        
        warning_msg = (
            f"[bold white]🔒 TOKENGUARD BLOCKED THIS EDIT[/bold white]\n"
            f"[white]File:[/white] {file_path}\n"
            f"[white]Blocked functions:[/white] {funcs_str}\n"
            f"[white]Reason:[/white] {reason}\n"
            f"[dim]To unlock: python main.py --unlock {file_path}[/dim]"
        )
        console.print(Panel(warning_msg, border_style="red", expand=False))
        
        manager._add_history(
            event="edit_blocked",
            file_path=file_path,
            reason="Function is frozen" if result.blocked_functions else "Entire file is frozen",
            attempted_functions=funcs,
            blocked_by="TokenGuard",
            session_id=str(uuid.uuid4())
        )
        return result
        
    if result.warning:
        console.print(f"[bold yellow]{result.warning}[/bold yellow]")
        
    return result

def after_edit(file_path: str, changes_made: Dict[str, Any], project_root: str = ".") -> None:
    """
    Call this AFTER a successful edit.
    Logs what changed, updates change_history in ledger.
    """
    manager = get_manager(project_root)
    funcs = changes_made.get("functions_modified", [])
    manager._add_history(
        event="edit_allowed",
        file_path=file_path,
        reason="Successful edit",
        modified_functions=funcs,
        session_id=str(uuid.uuid4())
    )
