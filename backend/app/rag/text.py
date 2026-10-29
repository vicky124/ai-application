"""Small text utilities used by ingestion: front-matter parsing and cleaning."""
import re

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal `---\\nkey: value\\n---` header parser. Returns ({}, text) when there is no complete header."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, parts[2].lstrip("\n")


def clean_text(text: str) -> str:
    """Normalize line endings, drop control characters, trim trailing spaces, collapse blank-line runs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
