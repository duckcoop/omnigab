"""
RAG Agent - Main Pipeline with Verification Layer
==================================================
Orchestrates the full Retrieval-Augmented Generation pipeline with a
post-generation self-correction loop:

  1. Ingest documents from docs/ directory
  2. Chunk and embed them into a FAISS vector store
  3. Accept user queries
  4. Retrieve relevant context via semantic search
  5. Generate answers using a local GGUF model (llama-cpp)
  6. VERIFY: split answer into claims, check each against source chunks
  7. CORRECT: remove unsupported claims, retry if faithfulness is too low

Usage:
    python rag_agent.py ingest    # Process documents and build index
    python rag_agent.py query     # Interactive query mode
    python rag_agent.py demo      # Run a quick demo with sample queries
"""

import sys
import time
from pathlib import Path

from config import (
    DOCS_DIR, INDEX_PATH, METADATA_PATH, TOP_K,
    GENERATION_MODEL, EMBEDDING_MODEL, TEMPERATURE, USE_GGUF,
    FAITHFULNESS_THRESHOLD, MAX_CORRECTION_ROUNDS,
    RETRY_TEMP_BOOST, RETRY_TOPK_BOOST, GGUF_MODEL_PATH,
)
from ingest import load_documents, chunk_documents
from embeddings import EmbeddingEngine
from vectorstore import VectorStore
from verifier import Verifier, print_verification_report


def load_generator():
    """Load the appropriate generator based on config."""
    if USE_GGUF and GGUF_MODEL_PATH.exists():
        from generator import Generator
        return Generator()
    else:
        from generator import GeneratorHF
        return GeneratorHF()


class RAGAgent:
    """Full RAG pipeline combining retrieval, generation, and verification."""

    def __init__(self, load_gen: bool = True):
        print("\n" + "=" * 60)
        print("  RAG Agent - Local IT Documentation Assistant")
        print("=" * 60 + "\n")

        self.embedder = EmbeddingEngine()
        self.store = VectorStore()
        self.verifier = Verifier(self.embedder)

        self.generator = None
        if load_gen:
            self.generator = load_generator()

        print("\nRAG Agent initialized (verification layer active).\n")

    def ingest(self, docs_dir: Path = DOCS_DIR):
        """Process all documents in docs_dir and build the vector index."""
        print("-- Ingesting Documents --\n")

        documents = load_documents(docs_dir)
        if not documents:
            print("\nNo documents found. Add files to the docs/ directory.")
            return False

        chunks = chunk_documents(documents)
        if not chunks:
            print("\nNo chunks created. Check document contents.")
            return False

        print(f"\nEmbedding {len(chunks)} chunks...")
        start = time.time()
        texts = [c.text for c in chunks]
        embeddings = self.embedder.embed_texts(texts)
        elapsed = time.time() - start
        print(f"Embedded in {elapsed:.1f}s ({len(chunks)/elapsed:.0f} chunks/sec)")

        self.store = VectorStore()
        self.store.add(embeddings, chunks)
        self.store.save()

        print(f"\nIngestion complete. {self.store.size} vectors in index.\n")
        return True

    def load_index(self):
        """Load a previously built index."""
        self.store.load()

    def retrieve(self, query: str, top_k: int = TOP_K) -> list:
        """Retrieve relevant chunks for a query."""
        query_vec = self.embedder.embed_query(query)
        return self.store.search(query_vec, top_k=top_k)

    def _build_context(self, results: list) -> tuple:
        """
        Build a context string from retrieval results.
        Returns (joined_context_for_generation, list_of_all_chunk_texts).
        """
        gen_texts = [chunk.text for chunk, _ in results]
        return "\n\n".join(gen_texts), gen_texts

    def query(self, question: str, verbose: bool = True) -> dict:
        """
        Full RAG query with self-correction verification loop.

        After generating an answer the verification layer:
          1. Splits the response into individual claims.
          2. Embeds each claim and checks cosine similarity to source chunks.
          3. Removes any claim that cannot be directly inferred from the chunks.
          4. If the overall Faithfulness Score is below the threshold, retries
             the query with a higher temperature and more retrieved context.
        """
        start = time.time()
        current_top_k = TOP_K
        current_temp = TEMPERATURE
        best_result = None

        for attempt in range(1 + MAX_CORRECTION_ROUNDS):
            # -- Retrieve --
            results = self.retrieve(question, top_k=current_top_k)
            retrieve_time = time.time() - start

            if not results:
                return {
                    "answer": "I could not find any relevant information in the documentation.",
                    "sources": [],
                    "verification": None,
                    "retrieve_time": round(retrieve_time, 3),
                    "generate_time": 0,
                    "correction_rounds": attempt,
                    "tps": 0,
                }

            sources = []
            for chunk, score in results:
                sources.append({
                    "file": chunk.source_file,
                    "chunk": chunk.chunk_index,
                    "score": round(score, 4),
                    "preview": chunk.text[:100] + "...",
                })

            context, chunk_texts = self._build_context(results)

            # -- Generate --
            gen_start = time.time()
            if self.generator:
                answer = self.generator.generate(
                    question, context,
                    temperature_override=current_temp if attempt > 0 else None,
                )
                stats = self.generator.get_last_stats()
            else:
                return {
                    "answer": f"[Generator not loaded.]\n\n{context}",
                    "sources": sources,
                    "verification": None,
                    "retrieve_time": round(retrieve_time, 3),
                    "generate_time": round(time.time() - gen_start, 3),
                    "correction_rounds": 0,
                    "tps": 0,
                }
            generate_time = time.time() - gen_start

            # -- Verify --
            verification = self.verifier.verify(answer, chunk_texts)

            if verbose:
                print_verification_report(verification)

            # Track the best result across attempts
            if (best_result is None
                    or verification.faithfulness_score > best_result["verification"].faithfulness_score):
                best_result = {
                    "answer": verification.corrected_answer,
                    "original_answer": verification.original_answer,
                    "sources": sources,
                    "verification": verification,
                    "retrieve_time": round(retrieve_time, 3),
                    "generate_time": round(generate_time, 3),
                    "correction_rounds": attempt,
                    "tps": stats.get("tps", 0),
                    "tokens": stats.get("tokens", 0),
                }

            # -- Accept or Retry --
            if verification.passed:
                if verbose and attempt > 0:
                    print(f"  Passed on round {attempt}")
                best_result["answer"] = verification.corrected_answer
                break

            if attempt < MAX_CORRECTION_ROUNDS:
                current_temp = TEMPERATURE + RETRY_TEMP_BOOST * (attempt + 1)
                current_top_k = TOP_K + RETRY_TOPK_BOOST * (attempt + 1)
                if verbose:
                    print(f"  Retrying with temp={current_temp:.2f}, top_k={current_top_k}")

        return best_result

    def interactive(self):
        """Run an interactive query loop."""
        backend = "GGUF/llama-cpp" if USE_GGUF else "HuggingFace"
        print("-- Interactive Query Mode --")
        print(f"  Embedding: {EMBEDDING_MODEL}")
        print(f"  Generator: {backend}")
        print(f"  Index size: {self.store.size} vectors")
        print(f"  Verification: active (threshold={FAITHFULNESS_THRESHOLD})")
        print(f"  Type 'quit' to exit\n")

        while True:
            try:
                question = input("\nYour question: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not question or question.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            print("\nSearching documentation...")
            result = self.query(question)

            print(f"\n{'=' * 50}")
            print(f"Answer:\n{result['answer']}")
            print(f"{'=' * 50}")
            v = result.get("verification")
            if v:
                print(f"Faithfulness: {v.faithfulness_score:.0%} | Rounds: {result['correction_rounds']}")
            print(f"Performance: {result.get('tokens', 0)} tokens at {result.get('tps', 0)} tok/sec")
            print(f"Sources ({len(result['sources'])} chunks):")
            for s in result["sources"]:
                print(f"  - {s['file']} (chunk {s['chunk']}, relevance: {s['score']:.2%})")
            print(f"Timing: retrieve={result['retrieve_time']}s, generate={result['generate_time']}s")


def main():
    if len(sys.argv) < 2:
        print("Usage: python rag_agent.py [ingest|query|demo]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "ingest":
        agent = RAGAgent(load_gen=False)
        agent.ingest()

    elif command == "query":
        agent = RAGAgent(load_gen=True)
        agent.load_index()
        agent.interactive()

    elif command == "demo":
        agent = RAGAgent(load_gen=True)
        agent.load_index()

        demo_queries = [
            "How do I reset a user password?",
            "What is the VPN configuration process?",
            "How do I set up a new workstation?",
        ]

        for q in demo_queries:
            print(f"\n{'='*60}")
            print(f"Demo Query: {q}")
            result = agent.query(q)
            v = result.get("verification")
            print(f"\nFinal Answer: {result['answer']}")
            if v:
                print(f"Faithfulness: {v.faithfulness_score:.0%} | Rounds: {result['correction_rounds']}")
                if v.removed_claims:
                    print(f"Removed claims: {v.removed_claims}")
            print(f"Performance: {result.get('tokens', 0)} tokens at {result.get('tps', 0)} tok/sec")
            print(f"Sources: {[s['file'] for s in result['sources']]}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
