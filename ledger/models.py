from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class LockedFeature:
    id: str
    file_path: str
    locked_functions: List[str]
    locked_classes: List[str]
    lock_entire_file: bool
    reason: str
    locked_at: str
    locked_by: str
    status: str
    checksum: str

@dataclass
class LedgerState:
    project_root: str
    created_at: str
    last_updated: str
    locked_features: Dict[str, LockedFeature] = field(default_factory=dict)
    change_history: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class GuardResult:
    allowed: bool
    reason: str
    blocked_functions: List[str] = field(default_factory=list)
    safe_to_edit: List[str] = field(default_factory=list)
    warning: str = ""
