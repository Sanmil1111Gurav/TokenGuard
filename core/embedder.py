import os
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_openai import OpenAIEmbeddings
from config.settings import settings
from core.parser import ParsedFileMetadata
from utils.logger import get_logger, log_step

logger = get_logger()


def build_text_chunk(meta: ParsedFileMetadata) -> str:
    """
    Construct text representation for embedding generation combining path, metadata, and code.
    """
    imports_str = ", ".join(meta.imports) if meta.imports else "None"
    functions_str = ", ".join(meta.functions) if meta.functions else "None"
    classes_str = ", ".join(meta.classes) if meta.classes else "None"

    chunk = (
        f"File Path: {meta.file_path}\n"
        f"Language: {meta.language}\n"
        f"Summary: {meta.summary}\n"
        f"Imports: {imports_str}\n"
        f"Functions: {functions_str}\n"
        f"Classes: {classes_str}\n"
        f"--- Code Preview (First 100 lines) ---\n"
        f"{meta.code_preview}"
    )
    return chunk


class CodebaseEmbedder:
    """Handles generating embeddings and persisting them in ChromaDB."""

    def __init__(self, persist_dir: Optional[str] = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.collection_name = settings.CHROMA_COLLECTION_NAME
        
        # Initialize OpenAI Embeddings via LangChain wrapper
        self.embeddings_wrapper = None
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_key_here":
            try:
                self.embeddings_wrapper = OpenAIEmbeddings(
                    model=settings.EMBEDDING_MODEL,
                    openai_api_key=settings.OPENAI_API_KEY
                )
            except Exception as e:
                logger.warning(f"Could not initialize OpenAIEmbeddings: {e}")

    def get_or_create_collection(self):
        """Get or recreate the ChromaDB collection."""
        try:
            return self.client.get_or_create_collection(name=self.collection_name)
        except Exception as e:
            logger.error(f"Error accessing ChromaDB collection '{self.collection_name}': {e}")
            raise

    def generate_and_store_embeddings(self, parsed_files: List[ParsedFileMetadata], force_reset: bool = False) -> int:
        """
        Generate embeddings for parsed files and store in ChromaDB.
        
        Args:
            parsed_files: List of ParsedFileMetadata objects.
            force_reset: If True, delete and recreate collection first.
            
        Returns:
            Number of embeddings successfully stored.
        """
        count = 0
        with log_step("Embeddings & ChromaDB Persistence (Step 4)"):
            if force_reset:
                try:
                    self.client.delete_collection(self.collection_name)
                    logger.info(f"Reset existing collection '{self.collection_name}'.")
                except Exception:
                    pass

            collection = self.get_or_create_collection()

            if not parsed_files:
                logger.warning("No files provided for embedding.")
                return 0

            ids: List[str] = []
            documents: List[str] = []
            metadatas: List[Dict[str, Any]] = []

            for meta in parsed_files:
                try:
                    chunk = build_text_chunk(meta)
                    ids.append(meta.file_path)
                    documents.append(chunk)

                    metadatas.append({
                        "file_path": meta.file_path,
                        "language": meta.language,
                        "functions": ", ".join(meta.functions) if meta.functions else "",
                        "classes": ", ".join(meta.classes) if meta.classes else "",
                        "imports": ", ".join(meta.imports) if meta.imports else "",
                        "summary": meta.summary
                    })
                except Exception as e:
                    logger.warning(f"Error preparing metadata for '{meta.file_path}': {e}")
                    continue

            # Generate vectors if OpenAI embedding wrapper is configured
            embeddings: Optional[List[List[float]]] = None
            if self.embeddings_wrapper:
                try:
                    logger.info(f"Generating vectors via OpenAI model '{settings.EMBEDDING_MODEL}'...")
                    embeddings = self.embeddings_wrapper.embed_documents(documents)
                except Exception as e:
                    logger.warning(f"OpenAI embedding generation failed ({e}). Storing documents without custom vectors.")

            try:
                if embeddings:
                    collection.upsert(
                        ids=ids,
                        documents=documents,
                        embeddings=embeddings,
                        metadatas=metadatas
                    )
                else:
                    collection.upsert(
                        ids=ids,
                        documents=documents,
                        metadatas=metadatas
                    )
                count = len(ids)
                logger.info(f"Stored [bold green]{count}[/bold green] file embeddings in ChromaDB.")
            except Exception as e:
                logger.error(f"Failed to save embeddings to ChromaDB: {e}")

        return count


def embed_codebase(parsed_files: List[ParsedFileMetadata], force_reset: bool = False) -> int:
    """Convenience function to embed codebase files."""
    embedder = CodebaseEmbedder()
    return embedder.generate_and_store_embeddings(parsed_files, force_reset=force_reset)
