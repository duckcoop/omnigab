"""
Vector Store Module
===================
FAISS-based vector store for fast approximate nearest-neighbor search.
Handles index creation, persistence, and similarity queries.
"""

import numpy as np
import faiss
from pathlib import Path

from config import EMBEDDING_DIMENSION, INDEX_PATH, METADATA_PATH, TOP_K, SIMILARITY_THRESHOLD
from ingest import Chunk, save_metadata, load_metadata


class VectorStore:
    """FAISS vector store with metadata tracking."""

    def __init__(self, dimension: int = EMBEDDING_DIMENSION):
        self.dimension = dimension
        # Use IndexFlatIP (inner product) since embeddings are L2-normalized,
        # making dot product equivalent to cosine similarity
        self.index = faiss.IndexFlatIP(dimension)
        self.chunks: list[Chunk] = []

    def add(self, embeddings: np.ndarray, chunks: list[Chunk]):
        """Add embeddings and their corresponding chunks to the store."""
        assert len(embeddings) == len(chunks), "Embedding count must match chunk count"
        assert embeddings.shape[1] == self.dimension, f"Expected dim {self.dimension}, got {embeddings.shape[1]}"

        self.index.add(embeddings)
        self.chunks.extend(chunks)
        print(f"Added {len(chunks)} vectors to index (total: {self.index.ntotal})")

    def search(self, query_embedding: np.ndarray, top_k: int = TOP_K) -> list[tuple[Chunk, float]]:
        """
        Search for the top_k most similar chunks to the query embedding.
        Returns list of (chunk, similarity_score) tuples, filtered by threshold.
        """
        if self.index.ntotal == 0:
            return []

        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_embedding, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and score >= SIMILARITY_THRESHOLD:
                results.append((self.chunks[idx], float(score)))

        return results

    def save(self, index_path: Path = INDEX_PATH, metadata_path: Path = METADATA_PATH):
        """Persist the FAISS index and chunk metadata to disk."""
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(index_path))
        save_metadata(self.chunks, metadata_path)
        print(f"Index saved ({self.index.ntotal} vectors)")

    def load(self, index_path: Path = INDEX_PATH, metadata_path: Path = METADATA_PATH):
        """Load a previously saved FAISS index and metadata."""
        if not index_path.exists() or not metadata_path.exists():
            raise FileNotFoundError("No saved index found. Run ingestion first.")

        self.index = faiss.read_index(str(index_path))
        self.chunks = load_metadata(metadata_path)
        print(f"Index loaded ({self.index.ntotal} vectors, {len(self.chunks)} chunks)")

    @property
    def size(self) -> int:
        return self.index.ntotal


if __name__ == "__main__":
    print("=== Vector Store Test ===\n")

    # Create a small test
    store = VectorStore(dimension=4)
    test_embeddings = np.random.randn(5, 4).astype(np.float32)
    # Normalize
    norms = np.linalg.norm(test_embeddings, axis=1, keepdims=True)
    test_embeddings = test_embeddings / norms

    test_chunks = [Chunk(f"Test chunk {i}", "test.txt", i, 0, 10) for i in range(5)]
    store.add(test_embeddings, test_chunks)

    query = test_embeddings[0:1]
    results = store.search(query, top_k=3)
    print(f"\nQuery returned {len(results)} results:")
    for chunk, score in results:
        print(f"  {chunk.text} (score: {score:.4f})")
