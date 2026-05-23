"""
Visual Terminal Demo
====================
A Rich-powered wrapper around the RAG pipeline that color-codes every
stage of the retrieval-generation-verification loop:

    Blue    →  Retrieved context chunks
    Yellow  →  Raw generated answer (before verification)
    Green   →  Final verified answer (after hallucination removal)

Run:
    pip install rich
    python demo_ui.py              # interactive mode
    python demo_ui.py --demo       # run preset demo queries
"""

import sys
import time
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.prompt import Prompt
    from rich.rule import Rule
    from rich.columns import Columns
    from rich.live import Live
    from rich import box
except ImportError:
    print("This script requires the 'rich' library.")
    print("Install it with: pip install rich")
    sys.exit(1)

from config import (
    EMBEDDING_MODEL, FAITHFULNESS_THRESHOLD, CLAIM_SUPPORT_THRESHOLD,
    TOP_K, USE_GGUF, GGUF_MODEL_PATH, N_THREADS,
)
from rag_agent import RAGAgent

console = Console()


def print_header():
    """Print the startup banner."""
    console.print()
    console.print(
        Panel(
            "[bold white]🛡️  OmniAgent[/bold white]\n"
            "[dim]Local AI agent with tool-calling, RAG, and verification[/dim]",
            border_style="bright_cyan",
            padding=(1, 4),
        )
    )


def print_system_info(agent: RAGAgent):
    """Print system configuration in a compact table."""
    table = Table(
        show_header=False, box=box.SIMPLE, padding=(0, 2),
        border_style="dim",
    )
    table.add_column("Key", style="dim")
    table.add_column("Value", style="bold")

    backend = "GGUF/llama-cpp" if USE_GGUF else "HuggingFace"
    model_name = Path(GGUF_MODEL_PATH).stem if USE_GGUF else "SmolLM2-360M"

    table.add_row("Embedding", EMBEDDING_MODEL.split("/")[-1])
    table.add_row("Generator", f"{backend} ({model_name})")
    table.add_row("Threads", str(N_THREADS))
    table.add_row("Index Size", f"{agent.store.size} vectors")
    table.add_row("Verification", f"threshold={FAITHFULNESS_THRESHOLD}")

    console.print(Panel(table, title="[bold]System", border_style="dim"))


def display_retrieved_context(sources: list):
    """Show retrieved chunks in blue panels."""
    console.print(Rule("[bold bright_blue]📄 Retrieved Context[/bold bright_blue]"))

    for i, src in enumerate(sources, 1):
        score_pct = f"{src['score']:.0%}"
        title = f"Chunk {i} — {src['file']} (relevance: {score_pct})"

        console.print(
            Panel(
                Text(src["preview"], style="bright_blue"),
                title=f"[dim]{title}[/dim]",
                border_style="blue",
                padding=(0, 1),
            )
        )


def display_raw_answer(answer: str):
    """Show the raw generated answer in yellow."""
    console.print(Rule("[bold yellow]💬 Raw Generated Answer[/bold yellow]"))
    console.print(
        Panel(
            Text(answer, style="yellow"),
            border_style="yellow",
            padding=(1, 2),
        )
    )


def display_verification(verification):
    """Show the verification report with per-claim verdicts."""
    console.print(Rule("[bold bright_cyan]🔍 Verification Report[/bold bright_cyan]"))

    # Summary stats
    supported = sum(1 for c in verification.claims if c.supported)
    total = len(verification.claims)
    unsupported = total - supported

    score_style = "bold green" if verification.passed else "bold red"
    status = "[bold green]PASSED[/bold green]" if verification.passed else "[bold red]FAILED[/bold red] [yellow](correction triggered)[/yellow]"

    summary = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    summary.add_column("Metric", style="dim")
    summary.add_column("Value")

    summary.add_row("Claims Analyzed", str(total))
    summary.add_row("Supported", f"[green]{supported}[/green]")
    summary.add_row("Unsupported", f"[red]{unsupported}[/red]")
    summary.add_row("Faithfulness", f"[{score_style}]{verification.faithfulness_score:.0%}[/{score_style}]")
    summary.add_row("Status", status)

    console.print(summary)

    # Per-claim breakdown
    if verification.claims:
        console.print()
        claims_table = Table(
            title="Per-Claim Breakdown",
            box=box.ROUNDED,
            border_style="cyan",
            show_lines=True,
        )
        claims_table.add_column("Verdict", justify="center", width=10)
        claims_table.add_column("Score", justify="center", width=8)
        claims_table.add_column("Claim", ratio=1)

        for v in verification.claims:
            if v.supported:
                verdict = "[bold green]ACCEPT[/bold green]"
                claim_style = "green"
            else:
                verdict = "[bold red]REJECT[/bold red]"
                claim_style = "red"

            claims_table.add_row(
                verdict,
                f"{v.best_score:.2f}",
                Text(v.text, style=claim_style),
            )

        console.print(claims_table)

    # Removed claims callout
    if verification.removed_claims:
        console.print()
        for claim in verification.removed_claims:
            console.print(f"  [red]✗[/red] [dim strikethrough]{claim}[/dim strikethrough]")


def display_final_answer(answer: str, result: dict):
    """Show the final verified answer in green."""
    console.print(Rule("[bold green]✅ Verified Answer[/bold green]"))
    console.print(
        Panel(
            Text(answer, style="bold green"),
            border_style="green",
            padding=(1, 2),
        )
    )

    # Performance footer
    v = result.get("verification")
    tokens = result.get("tokens", 0)
    tps = result.get("tps", 0)
    rounds = result.get("correction_rounds", 0)
    r_time = result.get("retrieve_time", 0)
    g_time = result.get("generate_time", 0)

    perf_parts = []
    if v:
        perf_parts.append(f"faithfulness={v.faithfulness_score:.0%}")
    perf_parts.append(f"rounds={rounds}")
    perf_parts.append(f"{tokens} tokens @ {tps} tok/s")
    perf_parts.append(f"retrieve={r_time}s")
    perf_parts.append(f"generate={g_time}s")

    console.print(f"  [dim]{' │ '.join(perf_parts)}[/dim]")
    console.print()


def run_query(agent: RAGAgent, question: str):
    """Execute a full query and display all stages with Rich formatting."""
    console.print()
    console.print(f"[bold white]❓ {question}[/bold white]")
    console.print()

    with console.status("[bold cyan]Searching documentation...[/bold cyan]"):
        # Step 1: Retrieve
        results = agent.retrieve(question)
        sources = []
        for chunk, score in results:
            sources.append({
                "file": chunk.source_file,
                "chunk": chunk.chunk_index,
                "score": round(score, 4),
                "preview": chunk.text[:200] + ("..." if len(chunk.text) > 200 else ""),
            })

    # Display retrieved context (blue)
    display_retrieved_context(sources)

    with console.status("[bold yellow]Generating answer...[/bold yellow]"):
        # Step 2: Generate + Verify (uses the full pipeline)
        result = agent.query(question, verbose=False)

    # Display raw answer (yellow)
    original = result.get("original_answer", result["answer"])
    display_raw_answer(original)

    # Display verification details (cyan)
    v = result.get("verification")
    if v:
        display_verification(v)

    # Display final verified answer (green)
    display_final_answer(result["answer"], result)


def interactive_mode(agent: RAGAgent):
    """Run an interactive query loop."""
    print_header()
    print_system_info(agent)

    console.print("[dim]Type your question and press Enter. Type 'quit' to exit.[/dim]\n")

    while True:
        try:
            question = Prompt.ask("[bold white]Your question[/bold white]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not question.strip() or question.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        run_query(agent, question.strip())


def demo_mode(agent: RAGAgent):
    """Run preset demo queries."""
    print_header()
    print_system_info(agent)

    demo_queries = [
        "How do I reset a user password?",
        "What is the VPN configuration process?",
        "How do I set up a new workstation?",
    ]

    console.print(
        Panel(
            f"[bold]Running {len(demo_queries)} demo queries[/bold]",
            border_style="bright_magenta",
        )
    )

    for i, q in enumerate(demo_queries, 1):
        console.print(Rule(f"[bold magenta]Demo {i}/{len(demo_queries)}[/bold magenta]"))
        run_query(agent, q)

    console.print(Rule("[bold green]Demo Complete[/bold green]"))


def main():
    # Suppress the default RAGAgent banner since we have our own
    import io
    import contextlib

    with contextlib.redirect_stdout(io.StringIO()):
        agent = RAGAgent(load_gen=True)
        agent.load_index()

    if "--demo" in sys.argv:
        demo_mode(agent)
    else:
        interactive_mode(agent)


if __name__ == "__main__":
    main()
