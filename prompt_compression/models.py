"""
Data models for Prompt Compression and Token Management.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any, Optional
import datetime


class PriorityLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    FROZEN = "frozen"


@dataclass
class CodeContextItem:
    file_path: str
    content: str
    priority: PriorityLevel = PriorityLevel.MEDIUM
    tokens: int = 0
    is_outline: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "content": self.content,
            "priority": self.priority.value if isinstance(self.priority, PriorityLevel) else str(self.priority),
            "tokens": self.tokens,
            "is_outline": self.is_outline,
            "reason": self.reason,
        }


@dataclass
class TokenStats:
    original_input_tokens: int = 0
    compressed_input_tokens: int = 0
    input_tokens_saved: int = 0
    input_reduction_percent: float = 0.0
    output_tokens: int = 0
    total_tokens_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompressedContext:
    task: str = ""
    items: List[CodeContextItem] = field(default_factory=list)
    assembled_prompt: str = ""
    token_stats: TokenStats = field(default_factory=TokenStats)
    locked_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "items": [item.to_dict() for item in self.items],
            "assembled_prompt": self.assembled_prompt,
            "token_stats": self.token_stats.to_dict(),
            "locked_files": self.locked_files,
        }


@dataclass
class SessionAction:
    action_id: str
    timestamp: str
    action_type: str
    file_path: str = ""
    functions_touched: List[str] = field(default_factory=list)
    description: str = ""
    tokens_used: int = 0
    tokens_saved: int = 0
    original_tokens: int = 0
    compressed_tokens: int = 0
    reduction_percent: float = 0.0
    outcome: str = "success"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionAction":
        return cls(
            action_id=data.get("action_id", ""),
            timestamp=data.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            action_type=data.get("action_type", ""),
            file_path=data.get("file_path", ""),
            functions_touched=data.get("functions_touched", []),
            description=data.get("description", ""),
            tokens_used=data.get("tokens_used", 0),
            tokens_saved=data.get("tokens_saved", 0),
            original_tokens=data.get("original_tokens", 0),
            compressed_tokens=data.get("compressed_tokens", 0),
            reduction_percent=data.get("reduction_percent", 0.0),
            outcome=data.get("outcome", "success"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
