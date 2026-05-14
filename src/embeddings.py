"""
Embedding Module
================
Generates dense vector embeddings from text chunks using a lightweight
sentence-transformer model optimized for semantic similarity search.
"""

import numpy as np
from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL, EMBEDDING_DIMENSION


class EmbeddingEngine:
    """Manages the embedding model and generates vectors from text."""

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        print(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.dimension = EMBEDDING_DIMENSION
        print(f"Embedding model ready (dim={self.dimension})")

    def embed_texts(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """
        Encode a list of text strings into dense vectors.
        Returns an ndarray of shape (n_texts, embedding_dim).
        """
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 100,
            normalize_embeddings=True,  # L2 normalize for cosine similarity via dot product
        )
        return np.array(embeddings, dtype=np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        """Encode a single query string. Returns shape (1, embedding_dim)."""
        return self.embed_texts([query])


if __name__ == "__main__":
    print("=== Embedding Engine Test ===\n")
    engine = EmbeddingEngine()

    test_texts = [
        "How to reset a user password in Active Directory",
        "Configure DHCP scope on Windows Server 2022",
        "Troubleshooting VPN connection timeout errors",
    ]

    vectors = engine.embed_texts(test_texts)
    print(f"\nEmbedded {len(test_texts)} texts -> shape {vectors.shape}")

    # Test similarity
    from numpy.linalg import norm
    sim = np.dot(vectors[0], vectors[1])
    print(f"Similarity between text 0 and 1: {sim:.4f}")
    sim2 = np.dot(vectors[0], vectors[2])
    print(f"Similarity between text 0 and 2: {sim2:.4f}")
