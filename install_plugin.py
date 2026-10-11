"""
TokenGuard 1-Command Installer for Antigravity & Cursor.

Installs TokenGuard as a native Model Context Protocol (MCP) plugin into:
  1. Antigravity IDE (Global ~/.gemini/config and target workspace .agents/)
  2. Cursor IDE (Global ~/.cursor and target workspace .cursor/)

Usage:
  python install_plugin.py                     # Install globally + current workspace
  python install_plugin.py /path/to/project    # Install into a specific project workspace
  python install_plugin.py --global-only       # Install globally for all future projects
"""

import sys
import os
import json
import shutil
import argparse
from pathlib import Path

# Ensure TokenGuard root is discoverable
TOKEN_GUARD_ROOT = Path(__file__).resolve().parent

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Locate preferred Python interpreter (prefer .venv in TokenGuard)
VENV_PYTHON = TOKEN_GUARD_ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = TOKEN_GUARD_ROOT / ".venv" / "bin" / "python"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)

SERVER_SCRIPT = TOKEN_GUARD_ROOT / "mcp_server" / "server.py"


def format_path(p: Path) -> str:
    """Format path with forward slashes for cross-platform JSON configs."""
    return str(p.resolve()).replace("\\", "/")


def get_mcp_server_config() -> dict:
    """Generate the standard TokenGuard MCP server entry."""
    return {
        "command": format_path(VENV_PYTHON),
        "args": [format_path(SERVER_SCRIPT)],
        "env": {
            "PYTHONPATH": format_path(TOKEN_GUARD_ROOT)
        }
    }


def merge_json_config(target_file: Path, server_name: str, server_config: dict) -> bool:
    """Merge or create an mcpServers config file without clobbering other servers."""
    target_file.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if target_file.exists():
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    if not isinstance(data, dict):
        data = {}

    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}

    data["mcpServers"][server_name] = server_config

    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True


SKILL_CONTENT = """---
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
"""

RULE_CONTENT = """---
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
"""

PLUGIN_MANIFEST = """{
  "name": "tokenguard",
  "description": "TokenGuard — Intelligent context reduction middleware and edit protection ledger for AI coding agents."
}
"""


def install_global_antigravity(server_config: dict) -> bool:
    """Install TokenGuard globally in Antigravity ~/.gemini/config/"""
    home = Path.home()
    config_dir = home / ".gemini" / "config"
    mcp_file = config_dir / "mcp_config.json"
    skills_dir = config_dir / "skills" / "tokenguard"
    rules_dir = config_dir / "rules"

    success = merge_json_config(mcp_file, "tokenguard", server_config)

    # Install global skill
    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "SKILL.md").write_text(SKILL_CONTENT, encoding="utf-8")
    except Exception as e:
        print(f"  [Warning] Could not write global skill: {e}")

    # Install global rule
    try:
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "tokenguard_protection.md").write_text(RULE_CONTENT, encoding="utf-8")
    except Exception as e:
        print(f"  [Warning] Could not write global rule: {e}")

    return success


def install_global_cursor(server_config: dict) -> bool:
    """Install TokenGuard globally for Cursor IDE ~/.cursor/mcp.json"""
    home = Path.home()
    mcp_file = home / ".cursor" / "mcp.json"
    return merge_json_config(mcp_file, "tokenguard", server_config)


def install_workspace_antigravity(target_dir: Path, server_config: dict):
    """Install TokenGuard in target workspace for Antigravity."""
    agents_dir = target_dir / ".agents"
    mcp_file = agents_dir / "mcp_config.json"
    merge_json_config(mcp_file, "tokenguard", server_config)

    # Install workspace skill
    skills_dir = agents_dir / "skills" / "tokenguard"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "SKILL.md").write_text(SKILL_CONTENT, encoding="utf-8")

    # Install workspace rule
    rules_dir = agents_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "tokenguard_protection.md").write_text(RULE_CONTENT, encoding="utf-8")

    # Install plugin bundle
    plugin_dir = agents_dir / "plugins" / "tokenguard"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(PLUGIN_MANIFEST, encoding="utf-8")
    merge_json_config(plugin_dir / "mcp_config.json", "tokenguard", server_config)
    (plugin_dir / "skills" / "tokenguard").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "skills" / "tokenguard" / "SKILL.md").write_text(SKILL_CONTENT, encoding="utf-8")
    (plugin_dir / "rules").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "rules" / "tokenguard_protection.md").write_text(RULE_CONTENT, encoding="utf-8")


def install_workspace_cursor(target_dir: Path, server_config: dict):
    """Install TokenGuard in target workspace for Cursor (.cursor/mcp.json)."""
    cursor_dir = target_dir / ".cursor"
    mcp_file = cursor_dir / "mcp.json"
    merge_json_config(mcp_file, "tokenguard", server_config)


def main():
    parser = argparse.ArgumentParser(
        description="1-Command Installer for TokenGuard MCP plugin (Antigravity & Cursor)"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Target project directory to install TokenGuard into (default: current directory)",
    )
    parser.add_argument(
        "--global-only",
        action="store_true",
        help="Only install globally in ~/.gemini and ~/.cursor without modifying target workspace",
    )
    args = parser.parse_args()

    target_path = Path(args.target).resolve()
    server_config = get_mcp_server_config()

    print("=" * 65)
    print("  TokenGuard — 1-Command Plugin Installer")
    print("=" * 65)
    print(f"* TokenGuard Path: {TOKEN_GUARD_ROOT}")
    print(f"* Python Engine:   {VENV_PYTHON}")
    print(f"* MCP Server:      {SERVER_SCRIPT}")
    print("-" * 65)

    # 1. Global Installation
    print("\n[1/3] Installing Global Configurations...")
    try:
        install_global_antigravity(server_config)
        print("  [OK] Antigravity global MCP server & skills installed (~/.gemini/config)")
    except Exception as e:
        print(f"  [ERROR] Failed global Antigravity install: {e}")

    try:
        install_global_cursor(server_config)
        print("  [OK] Cursor global MCP server installed (~/.cursor/mcp.json)")
    except Exception as e:
        print(f"  [ERROR] Failed global Cursor install: {e}")

    # 2. Workspace Installation
    if not args.global_only:
        print(f"\n[2/3] Installing Workspace Configurations into '{target_path}'...")
        try:
            install_workspace_antigravity(target_path, server_config)
            print("  [OK] Antigravity workspace plugin, skills & rules created (.agents/)")
        except Exception as e:
            print(f"  [ERROR] Failed workspace Antigravity install: {e}")

        try:
            install_workspace_cursor(target_path, server_config)
            print("  [OK] Cursor workspace MCP server created (.cursor/mcp.json)")
        except Exception as e:
            print(f"  [ERROR] Failed workspace Cursor install: {e}")
    else:
        print("\n[2/3] Skipping workspace files (--global-only specified)")

    # 3. Environment Check
    print("\n[3/3] Checking TokenGuard Environment...")
    env_file = TOKEN_GUARD_ROOT / ".env"
    if not env_file.exists():
        example_file = TOKEN_GUARD_ROOT / ".env.example"
        if example_file.exists():
            shutil.copy(example_file, env_file)
            print("  [!] Created .env from .env.example - please add your OPENAI_API_KEY")
    else:
        content = env_file.read_text(encoding="utf-8")
        if "your_openai_api_key_here" in content or "OPENAI_API_KEY=" not in content:
            print("  [!] Notice: Add your OPENAI_API_KEY in TokenGuard/.env for semantic search embeddings.")
        else:
            print("  [OK] .env file configured.")

    print("\n" + "=" * 65)
    print("  TokenGuard MCP Plugin is successfully installed!")
    print("=" * 65)
    print("How to use with AI Agents:")
    print("  • In Antigravity: TokenGuard tools and skills are now automatically active.")
    print("  • In Cursor: TokenGuard tools appear in Composer / Agent MCP tool list.")
    print("\nAvailable Tools:")
    print("  - scan_project: Index codebase, dependency graph, and embeddings")
    print("  - query_context: Find minimal 3–5 files for task (saves up to 90% tokens)")
    print("  - compress_context: Compress context into token-capped prompt")
    print("  - check_file / lock_file / unlock_file: Prevent regression edits on frozen code")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
