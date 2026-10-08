import pytest
from unittest.mock import MagicMock, patch
import networkx as nx
from prompt_compression.models import PriorityLevel, CodeContextItem, TokenStats, CompressedContext
from prompt_compression.nlp_compressor import estimate_tokens, compress_code_to_outline
from prompt_compression.tier_manager import TierManager
from prompt_compression.context_builder import ContextBuilder
from prompt_compression.compressor import TokenCompressor


def test_estimate_tokens_returns_positive_int():
    text = "def hello_world():\n    print('Hello World')"
    token_count = estimate_tokens(text)
    assert isinstance(token_count, int)
    assert token_count > 0


def test_compress_code_to_outline_python():
    sample_code = """
import os
import sys

class UserSession:
    \"\"\"Manages user session state.\"\"\"
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.active = True

    def validate(self) -> bool:
        \"\"\"Validates current session.\"\"\"
        if not self.user_id:
            return False
        return True

def standalone_helper(x: int) -> int:
    return x * 2
"""
    outline = compress_code_to_outline(sample_code, file_path="session.py")

    # Outline must preserve classes, signatures, and docstrings
    assert "class UserSession:" in outline
    assert '"""Manages user session state."""' in outline
    assert "def validate(self) -> bool:" in outline
    assert "def standalone_helper(x: int) -> int:" in outline
    # Implementation logic should be omitted / replaced by ...
    assert "return x * 2" not in outline


def test_priority_classification_and_frozen_preservation():
    mock_query_result = {
        "task": "update authentication flow",
        "relevant_files": [
            {"file": "core/auth.py", "reason": "Target match", "similarity_score": 0.95}
        ],
        "files_to_read": ["core/auth.py", "core/user.py"],
        "dependency_path": ["core/auth.py", "core/user.py"],
        "files_skipped": 5
    }

    mock_ledger_state = MagicMock()
    mock_feature = MagicMock()
    mock_feature.lock_entire_file = True
    mock_feature.reason = "Critical auth security"
    mock_ledger_state.locked_features = {"core/security.py": mock_feature}

    with patch("ledger.manager.LedgerManager._load_state", return_value=mock_ledger_state), \
         patch("prompt_compression.tier_manager.TierManager._read_file_content") as mock_read:

        mock_read.side_effect = lambda fpath: f"# Content of {fpath}\ndef main(): pass"

        tier_mgr = TierManager(project_root=".")
        classified = tier_mgr.classify_and_package(
            task="update authentication flow",
            query_result=mock_query_result,
            max_input_tokens=4000
        )

        assert "core/security.py" in classified["locked_files"]
        high_files = [i.file_path for i in classified["high_priority_items"]]
        medium_files = [i.file_path for i in classified["medium_priority_items"]]

        assert "core/auth.py" in high_files
        assert "core/user.py" in medium_files


def test_token_compressor_input_output_measurement():
    compressor = TokenCompressor(project_root=".")
    
    mock_query_result = {
        "task": "test token measurement",
        "relevant_files": [{"file": "main.py", "reason": "match", "similarity_score": 0.9}],
        "files_to_read": ["main.py"],
        "files_skipped": 10
    }

    context = compressor.compress_input(
        task="test token measurement",
        max_input_tokens=2000,
        max_output_tokens=500,
        query_result=mock_query_result
    )

    assert isinstance(context, CompressedContext)
    assert context.token_stats.compressed_input_tokens > 0
    assert context.token_stats.original_input_tokens >= context.token_stats.compressed_input_tokens
    assert context.token_stats.input_tokens_saved >= 0

    # Test output recording
    mock_response = "```python\n# Small diff response\n```"
    stats = compressor.record_output(context, mock_response)

    assert stats.output_tokens > 0
    assert stats.total_tokens_used == stats.compressed_input_tokens + stats.output_tokens
