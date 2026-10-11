"""
Code & Token Compression Utilities.
Extracts code outlines (signatures, docstrings, classes) while omitting function bodies.
"""

import ast
import re
from typing import Optional

try:
    import tiktoken
    _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:
    _TIKTOKEN_ENCODER = None


def estimate_tokens(text: str) -> int:
    """Estimate token count using tiktoken (fallback: char/word heuristics)."""
    if not text:
        return 0
    if _TIKTOKEN_ENCODER is not None:
        try:
            return len(_TIKTOKEN_ENCODER.encode(text))
        except Exception:
            pass
    # Fallback heuristic: ~4 characters per token
    return max(1, len(text) // 4)


def compress_code_to_outline(code: str, file_path: str = "") -> str:
    """
    Compress source code into a structural outline.
    Preserves classes, method signatures, and docstrings while stripping function bodies.
    """
    if not code:
        return ""

    if file_path.endswith(".py") or not file_path:
        try:
            return _compress_python_outline(code)
        except Exception:
            pass

    # Generic regex fallback for JS/TS and unparseable Python
    return _compress_generic_outline(code)


def _compress_python_outline(code: str) -> str:
    """Use Python AST to generate a skeleton outline."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return _compress_generic_outline(code)

    lines = code.splitlines()
    outline_lines = []

    def get_docstring(node):
        return ast.get_docstring(node, clean=True)

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Retain imports
            start = node.lineno - 1
            end = getattr(node, "end_lineno", node.lineno)
            outline_lines.extend(lines[start:end])
        elif isinstance(node, ast.ClassDef):
            # Class signature
            start = node.lineno - 1
            # Find the line containing class header
            class_header = lines[start]
            outline_lines.append(class_header)
            
            doc = get_docstring(node)
            if doc:
                outline_lines.append(f'    """{doc}"""')
            
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig_start = item.lineno - 1
                    # Extract def line
                    def_line = lines[sig_start]
                    indent = " " * (len(def_line) - len(def_line.lstrip()))
                    outline_lines.append(def_line)
                    fn_doc = get_docstring(item)
                    if fn_doc:
                        outline_lines.append(f'{indent}    """{fn_doc}"""')
                    outline_lines.append(f"{indent}    ...")
                elif isinstance(item, ast.Pass):
                    outline_lines.append("    pass")
            outline_lines.append("")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno - 1
            def_line = lines[start]
            indent = " " * (len(def_line) - len(def_line.lstrip()))
            outline_lines.append(def_line)
            fn_doc = get_docstring(node)
            if fn_doc:
                outline_lines.append(f'{indent}    """{fn_doc}"""')
            outline_lines.append(f"{indent}    ...")
            outline_lines.append("")

    result = "\n".join(outline_lines).strip()
    return result if result else code


def _compress_generic_outline(code: str) -> str:
    """Regex fallback to extract functions, classes, and comments."""
    outline_lines = []
    in_block_comment = False
    for line in code.splitlines():
        trimmed = line.strip()
        if "/*" in trimmed:
            in_block_comment = True
        if in_block_comment:
            outline_lines.append(line)
            if "*/" in trimmed:
                in_block_comment = False
            continue
        if trimmed.startswith(("//", "#", "/*", "*")):
            outline_lines.append(line)
            continue
        if re.search(r"^(export\s+)?(default\s+)?(class|function|interface|type|const\s+\w+\s*=)\b", trimmed):
            outline_lines.append(line)
            if trimmed.endswith("{"):
                outline_lines.append("  ...")
                outline_lines.append("}")
        elif re.search(r"^(def|class)\s+", trimmed):
            outline_lines.append(line)
            outline_lines.append("    ...")
    return "\n".join(outline_lines)
