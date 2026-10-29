"""AnswerGenerator implementations plus the registry that maps config ModelSpecs to them."""
import re
from dataclasses import dataclass
from typing import Callable

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


def content_text(content) -> str:
    """Chat models return a string, or (Gemini) a list of content parts; keep only the text."""
    if isinstance(content, str):
        return content.strip()
    parts = []
    for part in content or []:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and part.get("type", "text") == "text":
            parts.append(part.get("text", ""))
    return "".join(parts).strip()


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
        return content_text(msg.content)


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


@dataclass(frozen=True)
class ProviderInfo:
    """What the UI and catalog need to know about a provider, beyond how to build it."""

    local: bool  # False means retrieved text leaves this machine
    check: Callable[[Settings], str | None] | None = None  # returns a reason when the provider cannot be used


PROVIDERS: dict[str, ProviderInfo] = {}


class ModelUnavailable(RuntimeError):
    """The model is configured but cannot be used right now (for example a missing API key)."""


@GENERATORS.register("ollama")
def _ollama(spec: ModelSpec, settings: Settings):
    from langchain_ollama import ChatOllama

    return LangChainGenerator(
        ChatOllama(model=spec.name, base_url=settings.ollama_base_url, temperature=spec.temperature)
    )


@GENERATORS.register("gemini")
def _gemini(spec: ModelSpec, settings: Settings):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return LangChainGenerator(
        ChatGoogleGenerativeAI(model=spec.name, google_api_key=settings.gemini_key, temperature=spec.temperature)
    )


@GENERATORS.register("extractive")
def _extractive(spec: ModelSpec, settings: Settings):
    return ExtractiveGenerator()


PROVIDERS["ollama"] = ProviderInfo(local=True)
PROVIDERS["extractive"] = ProviderInfo(local=True)
PROVIDERS["gemini"] = ProviderInfo(
    local=False, check=lambda s: None if s.gemini_key else "GOOGLE_API_KEY is not set on the server"
)


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

    def describe(self, spec: ModelSpec) -> dict:
        """Selection metadata for the UI: whether the model runs locally and whether it can be used now."""
        info = PROVIDERS.get(spec.provider, ProviderInfo(local=True))
        reason = info.check(self._settings) if info.check else None
        return {
            "id": spec.id,
            "label": spec.label,
            "provider": spec.provider,
            "local": info.local,
            "available": reason is None,
            "unavailable_reason": reason,
        }

    def get(self, model_id: str | None):
        model_id = model_id or self.default_id
        if model_id not in self._specs:
            raise KeyError(model_id)
        reason = self.describe(self._specs[model_id])["unavailable_reason"]
        if reason:
            raise ModelUnavailable(reason)
        if model_id not in self._cache:
            self._cache[model_id] = GENERATORS.create(
                self._specs[model_id].provider, spec=self._specs[model_id], settings=self._settings
            )
        return self._cache[model_id]
