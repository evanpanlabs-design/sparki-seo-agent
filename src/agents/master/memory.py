"""Memory system (RAG) for Master Agent.

Uses ChromaDB for vector-based semantic search of past cases.
"""

import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB not installed. Memory system disabled.")


class MemoryIndex:
    """ChromaDB-based memory index for semantic case search."""

    def __init__(self, persist_dir: str = "data/memory_index"):
        if not CHROMADB_AVAILABLE:
            raise ImportError("ChromaDB is required for memory system. Install with: pip install chromadb")

        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.Client(Settings(
            persist_directory=str(self.persist_dir),
            anonymized_telemetry=False
        ))
        self.collection = self.client.get_or_create_collection("sparki_cases")

        self._embedding_model = None
        logger.info(f"Memory index initialized at {persist_dir}")

    def _get_embedding_model(self):
        """Lazy-load embedding model."""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            except ImportError:
                logger.error("sentence-transformers not installed")
                raise ImportError("sentence-transformers required. Install with: pip install sentence-transformers")
        return self._embedding_model

    def get_embedding(self, text: str) -> list[float]:
        """Get embedding vector for text."""
        model = self._get_embedding_model()
        embedding = model.encode(text)
        return embedding.tolist()

    def add_case(self, case_id: str, creator_handle: str, article_content: str, video_url: str) -> bool:
        """Add a case to the memory index."""
        try:
            text_to_embed = f"{creator_handle}: {article_content[:2000]}"
            embedding = self.get_embedding(text_to_embed)

            self.collection.add(
                ids=[case_id],
                embeddings=[embedding],
                metadatas=[{
                    "creator": creator_handle,
                    "video_url": video_url,
                }],
                documents=[article_content[:5000]]
            )

            logger.info(f"Added case {case_id} to memory index")
            return True
        except Exception as e:
            logger.error(f"Failed to add case to memory: {e}")
            return False

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Semantic search for similar cases."""
        try:
            query_embedding = self.get_embedding(query)
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )

            matches = []
            if results and results.get("ids") and results["ids"][0]:
                for i, case_id in enumerate(results["ids"][0]):
                    match = {
                        "case_id": case_id,
                        "document": results["documents"][0][i] if results.get("documents") else "",
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                        "distance": results["distances"][0][i] if results.get("distances") else None
                    }
                    matches.append(match)

            logger.info(f"Memory search for '{query}' returned {len(matches)} results")
            return matches
        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return []

    def delete_case(self, case_id: str) -> bool:
        """Delete a case from memory index."""
        try:
            self.collection.delete(ids=[case_id])
            logger.info(f"Deleted case {case_id} from memory")
            return True
        except Exception as e:
            logger.error(f"Failed to delete case from memory: {e}")
            return False

    def get_case_count(self) -> int:
        """Get total number of cases in memory."""
        try:
            return self.collection.count()
        except Exception:
            return 0


class SimpleMemory:
    """Simple fallback memory when ChromaDB is unavailable."""

    def __init__(self):
        self._cases = {}
        logger.info("Using simple in-memory storage (no ChromaDB)")

    def add_case(self, case_id: str, creator_handle: str, article_content: str, video_url: str) -> bool:
        self._cases[case_id] = {
            "creator_handle": creator_handle,
            "article_content": article_content,
            "video_url": video_url
        }
        return True

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        query_lower = query.lower()
        results = []
        for case_id, case in self._cases.items():
            text = f"{case['creator_handle']} {case['article_content']}".lower()
            if query_lower in text:
                results.append({
                    "case_id": case_id,
                    "document": case["article_content"][:500],
                    "metadata": {"creator": case["creator_handle"]},
                    "distance": 0.0
                })
            if len(results) >= top_k:
                break
        return results

    def delete_case(self, case_id: str) -> bool:
        if case_id in self._cases:
            del self._cases[case_id]
            return True
        return False

    def get_case_count(self) -> int:
        return len(self._cases)


def get_memory_index() -> MemoryIndex | SimpleMemory:
    """Get the global memory index instance."""
    if not CHROMADB_AVAILABLE:
        return SimpleMemory()

    global _memory_index
    if _memory_index is None:
        try:
            _memory_index = MemoryIndex()
        except Exception as e:
            logger.warning(f"Failed to init ChromaDB, using simple memory: {e}")
            _memory_index = SimpleMemory()
    return _memory_index


_memory_index: MemoryIndex | SimpleMemory | None = None