"""
Tier Manager: Classifies codebase files into priority tiers (High, Medium, Low, Frozen).
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from prompt_compression.models import PriorityLevel, CodeContextItem
from prompt_compression.nlp_compressor import estimate_tokens, compress_code_to_outline
from ledger.manager import LedgerManager


class TierManager:
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self.ledger_manager = LedgerManager(str(self.project_root))

    def _read_file_content(self, file_path: str) -> str:
        """Read content of a file relative to project root."""
        full_path = self.project_root / file_path
        if full_path.exists() and full_path.is_file():
            try:
                return full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ""
        return ""

    def classify_and_package(
        self,
        task: str,
        query_result: Dict[str, Any],
        max_input_tokens: int = 4000
    ) -> Dict[str, Any]:
        """
        Classify files into High, Medium, Low, and Frozen priority tiers.
        """
        # Locked files from Ledger
        ledger_state = self.ledger_manager.state
        locked_files = list(ledger_state.locked_features.keys()) if ledger_state else []

        # High priority: direct semantic hits
        relevant_files = query_result.get("relevant_files", [])
        high_paths = set()
        for item in relevant_files:
            if isinstance(item, dict) and "file" in item:
                high_paths.add(item["file"].replace("\\", "/").lstrip("./"))
            elif isinstance(item, str):
                high_paths.add(item.replace("\\", "/").lstrip("./"))

        # Medium priority: 1-hop dependencies from files_to_read
        files_to_read = query_result.get("files_to_read", [])
        medium_paths = set()
        for f in files_to_read:
            norm_f = f.replace("\\", "/").lstrip("./")
            if norm_f not in high_paths:
                medium_paths.add(norm_f)

        high_items: List[CodeContextItem] = []
        medium_items: List[CodeContextItem] = []
        low_items: List[CodeContextItem] = []
        frozen_items: List[CodeContextItem] = []

        # Package High priority (Full code)
        for fpath in high_paths:
            content = self._read_file_content(fpath)
            tokens = estimate_tokens(content)
            high_items.append(
                CodeContextItem(
                    file_path=fpath,
                    content=content,
                    priority=PriorityLevel.HIGH,
                    tokens=tokens,
                    is_outline=False,
                    reason="Direct semantic match for task",
                )
            )

        # Package Medium priority (Outline if large)
        for fpath in medium_paths:
            content = self._read_file_content(fpath)
            outline = compress_code_to_outline(content, file_path=fpath)
            tokens = estimate_tokens(outline)
            medium_items.append(
                CodeContextItem(
                    file_path=fpath,
                    content=outline,
                    priority=PriorityLevel.MEDIUM,
                    tokens=tokens,
                    is_outline=True,
                    reason="Dependency of target file",
                )
            )

        # Package Frozen files
        for fpath in locked_files:
            content = self._read_file_content(fpath)
            outline = compress_code_to_outline(content, file_path=fpath)
            tokens = estimate_tokens(outline)
            frozen_items.append(
                CodeContextItem(
                    file_path=fpath,
                    content=outline,
                    priority=PriorityLevel.FROZEN,
                    tokens=tokens,
                    is_outline=True,
                    reason=f"Protected in Ledger: {ledger_state.locked_features[fpath].reason if ledger_state and fpath in ledger_state.locked_features else 'Locked'}",
                )
            )

        return {
            "high_priority_items": high_items,
            "medium_priority_items": medium_items,
            "low_priority_items": low_items,
            "frozen_items": frozen_items,
            "locked_files": locked_files,
        }
