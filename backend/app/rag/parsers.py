"""Document parsers keyed by file extension. Add a format by registering a parser."""
import io
from pathlib import Path

from app.domain import ParsedPage
from app.interfaces import DocumentParser


class TextParser:
    def parse(self, data: bytes) -> list[ParsedPage]:
        return [ParsedPage(data.decode("utf-8", errors="replace"))]


class PdfParser:
    def parse(self, data: bytes) -> list[ParsedPage]:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [ParsedPage(p.extract_text() or "", i + 1) for i, p in enumerate(reader.pages)]


class ParserRegistry:
    def __init__(self):
        self._by_ext: dict[str, DocumentParser] = {}

    def register(self, extensions: tuple[str, ...], parser: DocumentParser) -> "ParserRegistry":
        for ext in extensions:
            self._by_ext[ext] = parser
        return self

    def for_file(self, filename: str) -> DocumentParser:
        ext = Path(filename).suffix.lower()
        if ext not in self._by_ext:
            raise ValueError(f"Unsupported file type '{ext}'. Supported: {sorted(self._by_ext)}")
        return self._by_ext[ext]


def default_parsers() -> ParserRegistry:
    return ParserRegistry().register((".md", ".txt"), TextParser()).register((".pdf",), PdfParser())
