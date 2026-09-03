import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure project root is in sys.path so modules like config, core, utils can always be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import networkx as nx

try:
    import chromadb
except ImportError:
    chromadb = None

try:
    from langchain_openai import OpenAIEmbeddings
except ImportError:
    OpenAIEmbeddings = None

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config.settings import settings
from core.graph_builder import load_graph
from utils.logger import get_logger, log_step

logger = get_logger()

class QueryRequest(BaseModel):
    task: str
    project_path: Optional[str] = "."

class QueryEngine:
    """Query engine to find relevant files and minimal context using ChromaDB and NetworkX."""

    def __init__(self, graph: Optional[nx.DiGraph] = None, persist_dir: Optional[str] = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.collection_name = settings.CHROMA_COLLECTION_NAME
        self.graph = graph
        
        self.embeddings_wrapper = None
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_key_here":
            try:
                self.embeddings_wrapper = OpenAIEmbeddings(
                    model=settings.EMBEDDING_MODEL,
                    openai_api_key=settings.OPENAI_API_KEY
                )
            except Exception as e:
                logger.warning(f"Could not initialize OpenAI embeddings wrapper for query engine: {e}")

    def query(self, task: str, top_k: int = settings.TOP_K_RELEVANT, graph_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute natural language query to find relevant files and dependency paths.
        
        Args:
            task: Plain English task description.
            top_k: Number of relevant files to retrieve.
            graph_path: Path to dependency_graph.json if self.graph is not loaded.
            
        Returns:
            Structured dictionary matching TokenGuard specifications.
        """
        # Load graph if not already provided
        if self.graph is None:
            g_path = graph_path or settings.GRAPH_FILENAME
            self.graph = load_graph(g_path)

        # Step 1: ChromaDB Query
        relevant_files: List[Dict[str, Any]] = []
        top_file_paths: List[str] = []

        try:
            collection = self.client.get_collection(name=self.collection_name)
            
            query_embeddings = None
            if self.embeddings_wrapper:
                try:
                    query_embeddings = [self.embeddings_wrapper.embed_query(task)]
                except Exception as e:
                    logger.warning(f"Failed to generate query embedding via OpenAI ({e}). Using ChromaDB text search.")

            if query_embeddings:
                results = collection.query(
                    query_embeddings=query_embeddings,
                    n_results=top_k,
                    include=["metadatas", "distances"]
                )
            else:
                results = collection.query(
                    query_texts=[task],
                    n_results=top_k,
                    include=["metadatas", "distances"]
                )

            if results and results.get("metadatas") and len(results["metadatas"]) > 0:
                metas = results["metadatas"][0]
                distances = results.get("distances", [[]])[0]

                for i, meta in enumerate(metas):
                    file_path = meta.get("file_path", "")
                    dist = distances[i] if i < len(distances) else 0.5
                    # Convert distance to similarity score
                    sim_score = max(0.0, round(1.0 - float(dist), 2)) if dist <= 1.0 else round(1.0 / (1.0 + float(dist)), 2)
                    
                    reason_parts = []
                    if meta.get("summary"):
                        reason_parts.append(meta.get("summary"))
                    if meta.get("functions"):
                        reason_parts.append(f"functions: {meta.get('functions')}")
                    if meta.get("imports"):
                        reason_parts.append(f"imports: {meta.get('imports')}")

                    reason = "; ".join(reason_parts) if reason_parts else "matched task semantic similarity"

                    relevant_files.append({
                        "file": file_path,
                        "reason": reason,
                        "similarity_score": sim_score
                    })
                    top_file_paths.append(file_path)
        except Exception as e:
            logger.warning(f"Error querying ChromaDB collection: {e}")

        # Step 2: Calculate graph dependencies & filter unconnected vector hits
        dependency_path: List[str] = []
        file_relationships: List[str] = []
        files_to_read_set: set = set()

        if top_file_paths:
            # Primary target file is the top match
            primary_file = top_file_paths[0]
            files_to_read_set.add(primary_file)

            if self.graph is not None:
                # Find all reachable nodes from or to primary file in the dependency graph
                # Undirected view for full context component
                undirected_graph = self.graph.to_undirected()
                
                reachable_files = set()
                if self.graph.has_node(primary_file):
                    reachable_files = set(nx.node_connected_component(undirected_graph, primary_file))

                # Filter relevant files to those connected to the primary target component
                connected_top_files = [f for f in top_file_paths if f in reachable_files]
                if not connected_top_files:
                    connected_top_files = [primary_file]

                # Extract shortest paths between connected pairs
                for i in range(len(connected_top_files)):
                    source = connected_top_files[i]
                    for j in range(i + 1, len(connected_top_files)):
                        target = connected_top_files[j]
                        try:
                            if nx.has_path(self.graph, source, target):
                                path = nx.shortest_path(self.graph, source, target)
                                for node in path:
                                    if node not in dependency_path:
                                        dependency_path.append(node)
                                    files_to_read_set.add(node)
                            elif nx.has_path(self.graph, target, source):
                                path = nx.shortest_path(self.graph, target, source)
                                for node in path:
                                    if node not in dependency_path:
                                        dependency_path.append(node)
                                    files_to_read_set.add(node)
                        except Exception:
                            pass

                # Add immediate dependencies of primary file
                if self.graph.has_node(primary_file):
                    for succ in self.graph.successors(primary_file):
                        files_to_read_set.add(succ)
                    for pred in self.graph.predecessors(primary_file):
                        files_to_read_set.add(pred)

                # Build readable file relationships
                for src in files_to_read_set:
                    if self.graph.has_node(src):
                        for tgt in self.graph.successors(src):
                            if tgt in files_to_read_set:
                                raw_imp = self.graph.edges[src, tgt].get("raw_import", "imports")
                                file_relationships.append(f"{src} --> imports --> {tgt} ('{raw_imp}')")

                # Filter relevant_files list to exclude un-connected files
                relevant_files = [item for item in relevant_files if item.get("file") in files_to_read_set]
            
            if not dependency_path:
                dependency_path = list(files_to_read_set)

        # Step 3: Compute exact files_to_read, skipped count, and estimated tokens saved
        files_to_read = list(dict.fromkeys(list(files_to_read_set)))
        total_codebase_files = self.graph.number_of_nodes() if self.graph else len(files_to_read) + 10
        files_skipped = max(0, total_codebase_files - len(files_to_read))

        # Estimate tokens saved (~400 tokens per skipped file)
        estimated_tokens_saved = files_skipped * 400

        return {
            "task": task,
            "relevant_files": relevant_files,
            "dependency_path": dependency_path,
            "file_relationships": file_relationships,
            "files_to_read": files_to_read,
            "files_skipped": files_skipped,
            "estimated_tokens_saved": estimated_tokens_saved
        }


# Optional FastAPI app integration
app = FastAPI(title="TokenGuard Query API", version="1.0.0")

@app.post("/query")
def query_endpoint(req: QueryRequest):
    """Expose Query Engine as FastAPI POST /query endpoint."""
    try:
        engine = QueryEngine()
        result = engine.query(task=req.task)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
