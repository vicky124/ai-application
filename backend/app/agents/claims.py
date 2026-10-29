"""Splits an answer into claims: one per sentence, each with the sources it cites."""
import re

from app.domain import Claim

CITE = re.compile(r"\[(\d+)\]")
# "... year. [1]" -> "... year [1]." so a citation placed after the full stop stays with its sentence.
_TRAILING_CITES = re.compile(r"([.!?])\s*((?:\[\d+\]\s*)+)")
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_claims(answer: str, min_words: int = 3) -> list[Claim]:
    text = _TRAILING_CITES.sub(lambda m: f" {m.group(2).strip()}{m.group(1)} ", answer.strip())
    claims = []
    for sentence in _SPLIT.split(text):
        cited = tuple(sorted({int(n) for n in CITE.findall(sentence)}))
        plain = re.sub(r"\s+([.!?,;:])", r"\1", re.sub(r"\s+", " ", CITE.sub("", sentence))).strip(" -*\t")
        if len(plain.split()) >= min_words:
            claims.append(Claim(plain.rstrip(), cited))
    return claims
