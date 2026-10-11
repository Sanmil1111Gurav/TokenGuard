"""
TokenCompressor: End-to-end token budgeting and prompt compression coordinator.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from prompt_compression.models import (
    CompressedContext,
    TokenStats,
    PriorityLevel,
    CodeContextItem
)
from prompt_compression.nlp_compressor import estimate_tokens
from prompt_compression.tier_manager import TierManager
from prompt_compression.context_builder import ContextBuilder
from config.settings import settings
from utils.logger import get_logger

logger = get_logger("compressor")


class TokenCompressor:
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self.tier_manager = TierManager(str(self.project_root))
        self.context_builder = ContextBuilder()

    def compress_input(
        self,
        task: str,
        max_input_tokens: int = settings.MAX_INPUT_TOKENS,
        max_output_tokens: int = settings.MAX_OUTPUT_TOKENS,
        query_result: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> CompressedContext:
        """
        Compress and assemble prompt context for a task.
        """
        if query_result is None:
            from graph.query_engine import QueryEngine
            from core.graph_builder import load_graph
            graph_file = self.project_root / settings.GRAPH_FILENAME
            graph = load_graph(str(graph_file)) if graph_file.exists() else None
            engine = QueryEngine(graph=graph)
            query_result = engine.query(task=task, graph_path=str(graph_file) if graph_file.exists() else None)

        # Classify files into tiers
        classified = self.tier_manager.classify_and_package(
            task=task,
            query_result=query_result,
            max_input_tokens=max_input_tokens,
        )

        # Build prompt
        assembled_prompt = self.context_builder.assemble(task=task, classified=classified)
        compressed_tokens = estimate_tokens(assembled_prompt)

        # Estimate uncompressed baseline tokens (full codebase files or retrieved files uncompressed)
        files_to_read = query_result.get("files_to_read", [])
        if not files_to_read:
            relevant = query_result.get("relevant_files", [])
            files_to_read = [item["file"] if isinstance(item, dict) else item for item in relevant]

        uncompressed_tokens = sum(
            estimate_tokens(self.tier_manager._read_file_content(f))
            for f in files_to_read
        )
        # Factor in task and prompt boilerplate
        original_tokens = max(compressed_tokens, uncompressed_tokens + estimate_tokens(task) + 500)
        saved_tokens = max(0, original_tokens - compressed_tokens)
        reduction_pct = (saved_tokens / original_tokens * 100.0) if original_tokens > 0 else 0.0

        stats = TokenStats(
            original_input_tokens=original_tokens,
            compressed_input_tokens=compressed_tokens,
            input_tokens_saved=saved_tokens,
            input_reduction_percent=round(reduction_pct, 2),
            output_tokens=0,
            total_tokens_used=compressed_tokens,
        )

        all_items = (
            classified.get("high_priority_items", [])
            + classified.get("medium_priority_items", [])
            + classified.get("frozen_items", [])
        )

        return CompressedContext(
            task=task,
            items=all_items,
            assembled_prompt=assembled_prompt,
            token_stats=stats,
            locked_files=classified.get("locked_files", []),
        )

    def record_output(self, context: CompressedContext, response_text: str) -> TokenStats:
        """Record LLM response tokens and calculate total consumption."""
        out_tokens = estimate_tokens(response_text)
        context.token_stats.output_tokens = out_tokens
        context.token_stats.total_tokens_used = (
            context.token_stats.compressed_input_tokens + out_tokens
        )
        return context.token_stats

    def print_compression_report(self, context: CompressedContext):
        """Print rich summary table of token compression metrics."""
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel

        console = Console()
        stats = context.token_stats

        table = Table(title="TokenGuard — Token Compression Report", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="bold green", justify="right")

        table.add_row("Original Context Tokens", f"{stats.original_input_tokens:,}")
        table.add_row("Compressed Input Tokens", f"{stats.compressed_input_tokens:,}")
        table.add_row("Tokens Saved", f"{stats.input_tokens_saved:,}")
        table.add_row("Reduction %", f"{stats.input_reduction_percent:.1f}%")
        if stats.output_tokens > 0:
            table.add_row("Output Tokens", f"{stats.output_tokens:,}")
            table.add_row("Total Tokens", f"{stats.total_tokens_used:,}")

        console.print(table)


def run_compressed_task(
    task: str,
    project_path: str = ".",
    max_input_tokens: int = settings.MAX_INPUT_TOKENS,
    max_output_tokens: int = settings.MAX_OUTPUT_TOKENS,
) -> CompressedContext:
    """Helper function to run compression on a task description."""
    compressor = TokenCompressor(project_path)
    return compressor.compress_input(
        task=task,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )
