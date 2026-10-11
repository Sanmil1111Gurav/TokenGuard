---
description: TokenGuard ledger integrity and context querying guidelines for AI coding agents.
globs: ["*"]
always_on: true
---

# TokenGuard AI Agent Guidelines

TokenGuard is active in this workspace to minimize token consumption and protect critical files.

## 1. Context Minimization
- Before reading entire directories or pasting full codebases into your context, use `mcp_tokenguard_query_context` or `mcp_tokenguard_compress_context` with your task description.
- TokenGuard uses dependency graph traversal and semantic embeddings to return only the relevant 3–5 files, saving up to 90% context tokens.

## 2. Pre-Edit Guard (Ledger Check)
- **CRITICAL**: Before modifying or overwriting any file in this project, call `mcp_tokenguard_check_file(file_path=...)`.
- If the file or any of its functions are marked as locked (frozen), **DO NOT edit them**. Explain to the user that the file/function is protected by the TokenGuard Ledger.
- If editing is strictly required, ask the user to unlock it via `mcp_tokenguard_unlock_file(file_path=...)`.

## 3. Dependency Path Verification
- When refactoring cross-file logic, use `mcp_tokenguard_find_dependency_path(source_file=..., target_file=...)` to trace import relationships and avoid accidental breaking changes.
