"""Heading-aware chunking: split on markdown headings, then pack paragraphs up to a size."""
import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    text: str
    section: str
    page: int | None = None


def _split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = [("Introduction", [])]
    stack: list[str] = []
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            stack = stack[: level - 1] + [m.group(2).strip()]
            sections.append((" > ".join(stack), []))
        else:
            sections[-1][1].append(line)
    return [(name, "\n".join(lines).strip()) for name, lines in sections if "\n".join(lines).strip()]


def chunk_text(text: str, size: int, overlap: int, page: int | None = None) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, body in _split_sections(text):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        buf = ""
        for para in paragraphs:
            if buf and len(buf) + len(para) + 2 > size:
                chunks.append(Chunk(f"{section}\n{buf}", section, page))
                buf = buf[-overlap:] + "\n\n" + para if overlap else para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
            while len(buf) > size * 2:  # very long paragraph without breaks
                chunks.append(Chunk(f"{section}\n{buf[:size]}", section, page))
                buf = buf[size - overlap :]
        if buf.strip():
            chunks.append(Chunk(f"{section}\n{buf}", section, page))
    return chunks
