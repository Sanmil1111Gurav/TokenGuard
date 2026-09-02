import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

class Settings:
    """Central configuration for TokenGuard."""
    
    # Environment Variables
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Core Constants
    SUPPORTED_EXTENSIONS: set = {".py", ".js", ".ts", ".jsx", ".tsx"}
    
    IGNORE_FOLDERS: set = {
        "node_modules",
        ".git",
        "__pycache__",
        "venv",
        ".venv",
        "dist",
        "build",
        ".idea",
        ".vscode",
        ".chroma_db",
        "chroma_db"
    }
    
    IGNORE_FILE_EXTENSIONS: set = {
        ".lock",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".pyc",
        ".bin",
        ".svg"
    }
    
    GRAPH_FILENAME: str = "dependency_graph.json"
    CHROMA_COLLECTION_NAME: str = "token_guard_codebase"
    TOP_K_RELEVANT: int = 5
    
    # ── Ledger ──
    LEDGER_FILENAME: str = "ledger.json"

settings = Settings()
