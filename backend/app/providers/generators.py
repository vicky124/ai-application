"""AnswerGenerator implementations plus the registry that maps config ModelSpecs to them."""
import re

from app.config import ModelSpec, Settings
from app.domain import Source
from app.registry import Registry

INSUFFICIENT = "INSUFFICIENT_CONTEXT"

SYSTEM_PROMPT = f"""You are a company policy assistant. Answer ONLY from the numbered sources.
Rules:
- Cite the supporting source after every sentence, like [1] or [2].
- Do not use outside knowledge. Do not invent numbers, dates or names.
- If the sources do not contain the answer, reply with exactly {INSUFFICIENT}.
- Be concise."""

GENERATORS: Registry = Registry("LLM provider")


def format_sources(sources: list[Source]) -> str:
    return "\n\n".join(f"[{i}] ({s.title} - {s.section})\n{s.text}" for i, s in enumerate(sources, 1))


class LangChainGenerator:
    """Wraps any LangChain chat model; works for every provider that exposes one."""

    def __init__(self, chat_model):
        self._chat = chat_model

    def generate(self, question: str, sources: list[Source]) -> str:
        msg = self._chat.invoke(
            [
                ("system", SYSTEM_PROMPT),
                ("human", f"Sources:\n{format_sources(sources)}\n\nQuestion: {question}"),
            ]
        )
        return str(msg.content).strip()


class ExtractiveGenerator:
    """No-LLM fallback: returns the best-matching sentences from the top sources, with citations."""

    def generate(self, question: str, sources: list[Source]) -> str:
        q_terms = set(re.findall(r"[a-z0-9]+", question.lower())) - {"the", "a", "an", "is", "are", "of", "to", "how", "what", "do", "i", "my", "for", "and", "in"}
        scored = []
        for idx, s in enumerate(sources[:3], 1):
            body = s.text.removeprefix(s.section).lstrip("\n")  # chunk text is prefixed with its heading path
            for sent in re.split(r"(?<=[.!?])\s+|\n+", body):
                sent = sent.strip(" -*#\t")
                if len(sent) < 25:
                    continue
                overlap = len(q_terms & set(re.findall(r"[a-z0-9]+", sent.lower())))
                if overlap:
                    scored.append((overlap, idx, sent))
        if not scored:
            return INSUFFICIENT
        best = sorted(scored, key=lambda t: -t[0])[:2]
        return " ".join(f"{sent.rstrip('.')} [{idx}]." for _, idx, sent in best)


@GENERATORS.register("ollama")
def _ollama(spec: ModelSpec, settings: Settings):
    from langchain_ollama import ChatOllama

    return LangChainGenerator(
        ChatOllama(model=spec.name, base_url=settings.ollama_base_url, temperature=spec.temperature)
    )


@GENERATORS.register("extractive")
def _extractive(spec: ModelSpec, settings: Settings):
    return ExtractiveGenerator()


class ModelCatalog:
    """Resolves a model id (from the request) to a generator; lazily builds and caches them."""

    def __init__(self, specs: list[ModelSpec], settings: Settings):
        self._specs = {s.id: s for s in specs}
        self._settings = settings
        self._cache: dict[str, object] = {}
        defaults = [s.id for s in specs if s.default]
        self.default_id = defaults[0] if defaults else specs[0].id

    def specs(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def get(self, model_id: str | None):
        model_id = model_id or self.default_id
        if model_id not in self._specs:
            raise KeyError(model_id)
        if model_id not in self._cache:
            self._cache[model_id] = GENERATORS.create(
                self._specs[model_id].provider, spec=self._specs[model_id], settings=self._settings
            )
        return self._cache[model_id]
