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
  "tool": "mcp_tokenguard_scan_project",
  "args": {
    "project_path": "."
  }
}
```
This builds `dependency_graph.json` and populates the vector store with embeddings.

### 2. Intelligent Context Retrieval
Instead of reading every file or dumping huge directories into prompt context, retrieve the minimal 3–5 file subgraph for a task:
```json
{
  "tool": "mcp_tokenguard_query_context",
  "args": {
    "task": "describe your coding task here",
    "top_k": 5
  }
}
```
This returns the exact minimal files to read, saving up to 90% tokens.

### 3. Prompt Compression
To build a budget-capped prompt with AST code outline compression:
```json
{
  "tool": "mcp_tokenguard_compress_context",
  "args": {
    "task": "your coding task",
    "max_input_tokens": 4000
  }
}
```

### 4. Edit Protection (Ledger)
- **Check safety before editing:**
  `mcp_tokenguard_check_file(file_path="relative/path/to/file")`
- **Lock a critical file/function:**
  `mcp_tokenguard_lock_file(file_path="relative/path/to/file", reason="Critical stable code")`
- **Unlock when necessary:**
  `mcp_tokenguard_unlock_file(file_path="relative/path/to/file")`
- **Verify SHA-256 integrity:**
  `mcp_tokenguard_verify_integrity()`
