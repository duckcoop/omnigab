import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

"""
Benchmark runner for the RSO-2026 self-evolution loop.

This script keeps evaluation logic outside the core verifier. It loads the
existing RAGAgent pipeline, runs each question in evolution_tests.json, and
writes aggregate metrics suitable for comparing sandbox mutations.
"""

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np

from rag_agent import RAGAgent


ROOT = Path(__file__).parent.parent
DEFAULT_SUITE = ROOT / "data" / "evolution" / "evolution_tests.json"
DEFAULT_OUTPUT = ROOT / "data" / "evolution" / "baseline_stats.json"


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("`", "").split())


def count_tokens(agent: RAGAgent, text: str) -> int:
    if agent.generator and hasattr(agent.generator, "tokenizer"):
        return len(agent.generator.tokenizer.encode(text, add_special_tokens=False))
    return max(1, len(text.split()))


def expected_fact_coverage(answer: str, facts: list[str]) -> float:
    normalized_answer = normalize(answer)
    if not facts:
        return 1.0

    hits = 0
    for fact in facts:
        fact_norm = normalize(fact)
        # Full fact matching is intentionally strict; fall back to keyword-ish
        # overlap so paraphrases are not scored as total misses.
        if fact_norm in normalized_answer:
            hits += 1
            continue
        terms = [t.strip(".,:;()[]") for t in fact_norm.split() if len(t.strip(".,:;()[]")) >= 4]
        if terms:
            overlap = sum(1 for term in set(terms) if term in normalized_answer) / len(set(terms))
            if overlap >= 0.65:
                hits += 1

    return hits / len(facts)


def context_precision(sources: list[dict], chunks_by_key: dict, expected: dict) -> float:
    if not sources:
        return 0.0

    expected_files = set(expected.get("source_files", []))
    expected_facts = [normalize(f) for f in expected.get("facts", [])]
    relevant = 0

    for source in sources:
        key = (source["file"], source["chunk"])
        chunk_text = normalize(chunks_by_key.get(key, ""))
        has_fact = any(fact and fact in chunk_text for fact in expected_facts)
        has_source = source["file"] in expected_files
        if has_fact or has_source:
            relevant += 1

    return relevant / len(sources)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
    except Exception:
        pass


def run_benchmark(suite_path: Path, output_path: Path, seed: int) -> dict:
    seed_everything(seed)
    with open(suite_path, "r", encoding="utf-8") as f:
        suite = json.load(f)

    agent = RAGAgent(load_generator=True)
    agent.load_index()
    chunks_by_key = {(c.source_file, c.chunk_index): c.text for c in agent.store.chunks}

    runs = []
    started = time.time()
    for case in suite["tests"]:
        case_start = time.time()
        result = agent.query(case["question"], verbose=False)
        elapsed = time.time() - case_start
        verification = result.get("verification")
        answer = result.get("answer", "")
        output_tokens = count_tokens(agent, answer)
        tps = output_tokens / max(result.get("generate_time", 0.0), 0.001)

        expected = case["expected"]
        runs.append(
            {
                "id": case["id"],
                "question": case["question"],
                "faithfulness_score": verification.faithfulness_score if verification else None,
                "context_precision": round(context_precision(result.get("sources", []), chunks_by_key, expected), 4),
                "expected_fact_coverage": round(expected_fact_coverage(answer, expected.get("facts", [])), 4),
                "tokens_per_second": round(tps, 4),
                "output_tokens": output_tokens,
                "latency_seconds": round(elapsed, 4),
                "correction_rounds": result.get("correction_rounds", 0),
                "sources": result.get("sources", []),
                "answer": answer,
            }
        )

    faithfulness_values = [r["faithfulness_score"] for r in runs if r["faithfulness_score"] is not None]
    avg_faithfulness = sum(faithfulness_values) / len(faithfulness_values) if faithfulness_values else 0.0
    avg_context_precision = sum(r["context_precision"] for r in runs) / len(runs)
    avg_fact_coverage = sum(r["expected_fact_coverage"] for r in runs) / len(runs)
    avg_tps = sum(r["tokens_per_second"] for r in runs) / len(runs)

    stats = {
        "suite": suite.get("suite", suite_path.name),
        "suite_version": suite.get("version"),
        "seed": seed,
        "question_count": len(runs),
        "average_faithfulness_score": round(avg_faithfulness, 4),
        "average_context_precision": round(avg_context_precision, 4),
        "average_expected_fact_coverage": round(avg_fact_coverage, 4),
        "average_tokens_per_second": round(avg_tps, 4),
        "evolution_score": round((avg_faithfulness + avg_context_precision + avg_fact_coverage) / 3, 4),
        "total_runtime_seconds": round(time.time() - started, 4),
        "runs": runs,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    stats = run_benchmark(args.suite, args.output, args.seed)
    print(json.dumps({k: v for k, v in stats.items() if k != "runs"}, indent=2))


if __name__ == "__main__":
    main()
