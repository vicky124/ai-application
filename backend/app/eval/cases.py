"""Golden-set cases: a question, who asks it, and what a correct outcome looks like."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.config import BASE_DIR

EVAL_DIR = BASE_DIR / "eval"
GOLDEN_PATH = EVAL_DIR / "golden_set.json"
CORPUS_DIRS = [BASE_DIR / "data" / "sample_docs", EVAL_DIR / "corpus"]


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    question: str
    role: str = "employee"
    expected_docs: tuple[str, ...] = ()
    expected_facts: tuple[str, ...] = ()
    forbidden_docs: tuple[str, ...] = ()
    forbidden_facts: tuple[str, ...] = ()
    should_abstain: bool = False

    @property
    def answerable(self) -> bool:
        return not self.should_abstain


def load_cases(path: Path = GOLDEN_PATH, categories: set[str] | None = None) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))["cases"]
    cases = []
    for c in raw:
        case = Case(
            id=c["id"],
            category=c["category"],
            question=c["question"],
            role=c.get("role", "employee"),
            expected_docs=tuple(c.get("expected_docs", ())),
            expected_facts=tuple(c.get("expected_facts", ())),
            forbidden_docs=tuple(c.get("forbidden_docs", ())),
            forbidden_facts=tuple(c.get("forbidden_facts", ())),
            should_abstain=bool(c.get("should_abstain", False)),
        )
        if case.answerable and not case.expected_docs:
            raise ValueError(f"{case.id}: an answerable case needs expected_docs")
        if categories is None or case.category in categories:
            cases.append(case)
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids in the golden set")
    return cases
