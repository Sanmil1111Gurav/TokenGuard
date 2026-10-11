"""
Context Builder: Assembles final prompt within strict token budget.
"""

from typing import Dict, Any, List
from prompt_compression.models import CodeContextItem
from prompt_compression.nlp_compressor import estimate_tokens


class ContextBuilder:
    def __init__(self, max_input_tokens: int = 4000):
        self.max_input_tokens = max_input_tokens

    def assemble(self, task: str, classified: Dict[str, Any]) -> str:
        """
        Assemble structured prompt with task description and tiered code context.
        """
        sections: List[str] = [
            f"=== TASK OBJECTIVE ===\n{task}\n"
        ]

        # Locked / Frozen warning
        locked_files = classified.get("locked_files", [])
        if locked_files:
            sections.append(
                "=== PROTECTED / FROZEN FILES (DO NOT MODIFY) ===\n"
                + "\n".join(f"- {f}" for f in locked_files)
                + "\n"
            )

        # High priority files (Full code)
        high_items: List[CodeContextItem] = classified.get("high_priority_items", [])
        if high_items:
            sections.append("=== PRIMARY RELEVANT FILES (FULL IMPLEMENTATION) ===")
            for item in high_items:
                sections.append(f"\n--- File: {item.file_path} ---\n{item.content}")

        # Medium priority files (Outlines / context)
        medium_items: List[CodeContextItem] = classified.get("medium_priority_items", [])
        if medium_items:
            sections.append("\n=== RELEVANT CONTEXT (CODE OUTLINES) ===")
            for item in medium_items:
                sections.append(f"\n--- Outline: {item.file_path} ---\n{item.content}")

        assembled = "\n".join(sections).strip()
        return assembled
