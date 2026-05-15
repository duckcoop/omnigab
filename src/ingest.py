"""
Document Ingestion Module
=========================
Loads documents from the docs/ directory, splits them into overlapping chunks,
and returns structured chunk objects with metadata for downstream embedding.
"""

import json
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import DOCS_DIR, SUPPORTED_EXTENSIONS, CHUNK_SIZE, CHUNK_OVERLAP


def extract_pdf_text(file_path: Path) -> str:
    """
    Extract text from a PDF file using PyMuPDF (fitz).
    Falls back to raw read if PyMuPDF is not installed.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(f"  Warning: PyMuPDF not installed, reading {file_path.name} as raw text.")
        print(f"  Install with: pip install pymupdf")
        return file_path.read_text(encoding="utf-8", errors="replace")

    doc = fitz.open(str(file_path))
    pages = []
    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            pages.append(text)
    doc.close()

    if not pages:
        return ""

    full_text = "\n\n".join(pages)
    print(f"  PDF: {file_path.name} ({len(pages)} pages, {len(full_text):,} chars)")
    return full_text


@dataclass
class Chunk:
    """A text chunk with source metadata."""
    text: str
    source_file: str
    chunk_index: int
    start_char: int
    end_char: int

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


def load_documents(docs_dir: Optional[Path] = None) -> list[tuple[str, str]]:
    """
    Load all supported documents from the docs directory.
    Returns list of (filename, content) tuples.
    """
    docs_dir = docs_dir or DOCS_DIR
    documents = []

    if not docs_dir.exists():
        docs_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created docs directory at {docs_dir}")
        print("Add your IT documentation files there and run again.")
        return documents

    for file_path in sorted(docs_dir.rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                if file_path.suffix.lower() == ".pdf":
                    content = extract_pdf_text(file_path)
                else:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    rel_path = str(file_path.relative_to(docs_dir))
                    documents.append((rel_path, content))
                    print(f"  Loaded: {rel_path} ({len(content):,} chars)")
            except Exception as e:
                print(f"  Skipped {file_path.name}: {e}")

    print(f"\nTotal documents loaded: {len(documents)}")
    return documents


def chunk_documents(documents: list[tuple[str, str]]) -> list[Chunk]:
    """
    Split documents into overlapping chunks using recursive character splitting.
    This preserves paragraph and sentence boundaries where possible.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )

    all_chunks = []

    for filename, content in documents:
        splits = splitter.split_text(content)
        offset = 0
        for i, split_text in enumerate(splits):
            start = content.find(split_text, offset)
            if start == -1:
                start = offset
            end = start + len(split_text)

            heading_context = get_heading_context(filename, content, start)
            indexed_text = f"{heading_context}\n\n{split_text}" if heading_context else split_text

            chunk = Chunk(
                text=indexed_text,
                source_file=filename,
                chunk_index=i,
                start_char=start,
                end_char=end,
            )
            all_chunks.append(chunk)
            offset = max(offset, start + 1)

    print(f"Total chunks created: {len(all_chunks)}")
    return all_chunks


def get_heading_context(filename: str, content: str, position: int) -> str:
    """
    Return document and markdown heading context for a chunk position.

    Prefixing chunks with their source hierarchy improves semantic retrieval
    for questions that refer to a procedure by name rather than by exact body
    text, while preserving the original chunk body for answer generation.
    """
    headings: dict[int, str] = {}
    cursor = 0

    for line in content.splitlines(keepends=True):
        if cursor > position:
            break

        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.strip())
        if match:
            level = len(match.group(1))
            headings[level] = match.group(2)
            for deeper in list(headings):
                if deeper > level:
                    del headings[deeper]

        cursor += len(line)

    ordered = [headings[level] for level in sorted(headings)]
    if ordered:
        return f"Document: {filename}\nSection: {' > '.join(ordered)}"
    return f"Document: {filename}"


def save_metadata(chunks: list[Chunk], path: Path):
    """Save chunk metadata to JSON for later retrieval."""
    data = [c.to_dict() for c in chunks]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Metadata saved to {path}")
