---
name: tokenguard
description: Intelligent context window reduction, prompt compression, dependency graph analysis, and code edit protection ledger. Use whenever you need to find relevant files, minimize prompt tokens, trace imports, or verify file edit safety.
---

# TokenGuard Skill

This skill allows the agent to interact with TokenGuard's MCP tools to drastically cut token consumption and prevent accidental regression bugs.

## Core Workflows

### 1. Codebase Indexing
If the project hasn't been indexed yet (or if files have changed significantly), call:
```json
{
  "tool": "scan_project",
  "args": {
    "project_path": "."
  }
}
```
This builds `dependency_graph.json` and populates the vector store with embeddings.

### 2. Intelligent Context Retrieval
Instead of inspecting every directory or guessing files, retrieve the exact minimal subgraph for a task:
```json
{
  "tool": "query_context",
  "args": {
    "task": "fix authentication token expiration error",
    "top_k": 5
  }
}
```
This returns the exact files to read, saving up to 90% in token costs.

### 3. Prompt Compression
To build a budget-capped prompt with AST code outline compression:
```json
{
  "tool": "compress_context",
  "args": {
    "task": "refactor database migration",
    "max_input_tokens": 4000
  }
}
```

### 4. Edit Protection (Ledger)
- **Lock a file/function:**
  `lock_file(file_path="core/parser.py", reason="Stable AST parser", functions="parse_file")`
- **Check safety before editing:**
  `check_file(file_path="core/parser.py")`
- **Unlock when necessary:**
  `unlock_file(file_path="core/parser.py")`
- **Verify SHA-256 integrity:**
  `verify_integrity()`
