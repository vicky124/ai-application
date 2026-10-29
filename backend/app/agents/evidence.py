"""Evidence features comparing a claim with a cited passage: numbers, wording coverage and polarity.
All functions are pure and offline; they complement (never replace) a semantic model."""
import re

_STOP = set(
    """a an the and or but of to in on for with by at from as is are was were be been being it its this that these those
    you your yours we our they their them he she his her i my me do does did can could may might must should will would shall
    has have had not no nor never cannot without also any all each every more most than then there here so such per via
    get gets got one up out if when while who whom which what how""".split()
)
_NEGATION = re.compile(
    r"\b(not|no|never|cannot|without|neither|nor|prohibited|forbidden|banned|unable|disallowed)\b|n't\b", re.I
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD = re.compile(r"[a-z]+")


def stem(word: str) -> str:
    """Very light stemmer: enough to match plurals, tenses and adverbs ('anonymously' ~ 'anonymous', 'preserved' ~ 'preserve')."""
    if word.endswith("ied") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    for suffix in ("ing", "edly", "ed", "ly", "es", "s"):
        if suffix == "s" and word.endswith(("ss", "us", "is", "ous")):
            continue  # 'anonymous', 'business', 'analysis' are not plurals
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:-1] if word.endswith("e") and len(word) > 4 else word


def content_terms(text: str) -> dict[str, str]:
    """Content words of a text as {stem: original word}, without stop words."""
    terms: dict[str, str] = {}
    for w in _WORD.findall(text.lower()):
        if w not in _STOP and len(w) > 1:
            terms.setdefault(stem(w), w)
    return terms


def numbers(text: str) -> set[str]:
    """Numbers as plain strings ('1,000' -> '1000') so formatting differences do not matter."""
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


def coverage(claim: str, passage: str) -> tuple[float, list[str]]:
    """Share of the claim's content words that appear in the passage, and the words that do not."""
    claim_terms, passage_terms = content_terms(claim), set(content_terms(passage))
    if not claim_terms:
        return 1.0, []
    missing = [orig for st, orig in claim_terms.items() if st not in passage_terms]
    return 1 - len(missing) / len(claim_terms), missing


def is_negative(text: str) -> bool:
    return bool(_NEGATION.search(text))


def sentences(passage: str) -> list[str]:
    """Sentences of a passage, without the 'Document > Section' heading line that chunks start with."""
    parts = []
    for line in passage.splitlines():
        if " > " in line and len(line.split()) < 12 and not line.rstrip().endswith("."):
            continue
        parts.extend(re.split(r"(?<=[.!?])\s+", line))
    return [p.strip() for p in parts if len(p.split()) >= 2]


def best_sentence(claim: str, passage: str) -> tuple[str | None, float]:
    """The passage unit (a sentence or one clause of it) that overlaps most with the claim, and the share of the
    claim's content words it contains. Comparing against clauses keeps 'do X but not Y' from being judged as one block;
    ties go to the shorter unit."""
    claim_terms = set(content_terms(claim))
    if not claim_terms:
        return None, 0.0
    best, best_key = None, (0.0, 0)
    for sentence in sentences(passage):
        for unit in dict.fromkeys([sentence, *clauses(sentence)]):
            overlap = len(claim_terms & set(content_terms(unit))) / len(claim_terms)
            key = (overlap, -len(unit.split()))
            if overlap > 0 and key > best_key:
                best, best_key = unit, key
    return best, best_key[0]


# ---------------- clause-level checks ----------------
_CLAUSE_SPLIT = re.compile(r",\s*(?:and|but|while|plus|including|so that|then)\b|;|\s+(?:and also|as well as|plus|but also|but)\s+|\s[—–-]\s", re.I)


def clauses(text: str, min_terms: int = 2) -> list[str]:
    """Splits a claim into clauses so an invented extra clause cannot hide behind a true one. Plain ' and ' only
    splits when both sides carry at least `min_terms` content words (so 'HR and Legal' stays whole)."""
    out = []
    for part in _CLAUSE_SPLIT.split(text):
        part = part.strip(" ,.;")
        if not part:
            continue
        pieces = [part]
        if " and " in part:
            left, _, right = part.partition(" and ")
            if len(content_terms(left)) >= min_terms and len(content_terms(right)) >= min_terms:
                pieces = [left.strip(), right.strip()]
        out.extend(pieces)
    return out or [text]


def clause_coverage(claim: str, passage: str, min_terms: int = 2) -> tuple[float, list[str]]:
    """Lowest content-word coverage over the claim's clauses (and over the whole claim), with the words missing
    from the weakest clause."""
    worst, missing_words = coverage(claim, passage)
    for clause in clauses(claim):
        if len(content_terms(clause)) < min_terms:
            continue
        cov, missing = coverage(clause, passage)
        if cov < worst:
            worst, missing_words = cov, missing
    return worst, missing_words


# Words that make a claim broader than most policies are. Each maps to the passage words that justify it.
_ABSOLUTES = {
    "all": {"all", "every", "each"},
    "always": {"always", "every", "each", "all"},
    "every": {"every", "each", "all"},
    "never": {"never", "cannot", "prohibited", "forbidden"},
    "any": {"any", "every", "each", "all"},
    "anyone": {"anyone", "everyone", "any", "all"},
    "everyone": {"everyone", "all", "every", "each"},
    "immediately": {"immediately", "immediate", "instantly", "straight"},
    "automatically": {"automatically", "automatic"},
    "unlimited": {"unlimited"},
    "guaranteed": {"guaranteed", "guarantee"},
}


def unsupported_absolutes(claim: str, passage: str) -> list[str]:
    """Absolute or sweeping words in the claim (all, always, any, immediately, automatically, ...) that the passage
    does not use. A claim that goes beyond the source's scope is not supported by it."""
    passage_words = set(_WORD.findall(passage.lower()))
    return [w for w in dict.fromkeys(_WORD.findall(claim.lower())) if w in _ABSOLUTES and not (_ABSOLUTES[w] & passage_words)]
