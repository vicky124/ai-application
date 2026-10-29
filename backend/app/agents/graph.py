"""LangGraph workflow: guard -> retrieve -> grade -> generate -> verify (bounded retry) -> finalize.

Each node is a small method over injected abstractions; the graph wiring is the only place that knows the order.
"""
from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph

from app.domain import Source, Verification
from app.interfaces import AnswerGenerator, InputGuard, Retriever, Verifier
from app.providers.generators import INSUFFICIENT

ABSTAIN_TEXT = (
    "I couldn't find a reliable answer in the approved policy documents. "
    "Please contact HR or rephrase your question."
)


class AgentState(TypedDict, total=False):
    question: str
    role: str
    model_id: str | None
    sources: list[Source]
    answer: str
    verification: Verification
    attempts: int
    abstained: bool
    abstain_reason: str
    trace: list[str]


class PolicyAgent:
    def __init__(
        self,
        guard: InputGuard,
        retriever: Retriever,
        resolve_generator: Callable[[str | None], AnswerGenerator],
        verifier: Verifier,
        top_k: int,
        min_score: float,
        max_attempts: int,
    ):
        self._guard, self._retriever, self._resolve, self._verifier = guard, retriever, resolve_generator, verifier
        self._top_k, self._min_score, self._max_attempts = top_k, min_score, max_attempts
        self.graph = self._build()

    # ---- nodes ----
    def _guard_node(self, s: AgentState) -> AgentState:
        r = self._guard.check(s["question"])
        if r.allowed:
            return {"trace": s["trace"] + ["guard: ok"]}
        return {"abstained": True, "abstain_reason": r.reason, "trace": s["trace"] + [f"guard: blocked ({r.reason})"]}

    def _retrieve_node(self, s: AgentState) -> AgentState:
        found = self._retriever.search(s["question"], s["role"], self._top_k)
        kept = [x for x in found if x.relevance_or_score >= self._min_score]
        best = max((x.relevance_or_score for x in found), default=0.0)
        note = f"retrieve: {len(found)} found, {len(kept)} above threshold {self._min_score:g} (best relevance {best:.3g})"
        if not kept:
            return {"sources": [], "abstained": True, "abstain_reason": "no relevant sources", "trace": s["trace"] + [note]}
        return {"sources": kept, "trace": s["trace"] + [note]}

    def _generate_node(self, s: AgentState) -> AgentState:
        attempts = s.get("attempts", 0) + 1
        answer = self._resolve(s.get("model_id")).generate(s["question"], s["sources"])
        return {"answer": answer, "attempts": attempts, "trace": s["trace"] + [f"generate: attempt {attempts}"]}

    def _verify_node(self, s: AgentState) -> AgentState:
        v = self._verifier.verify(s["answer"], s["sources"])
        return {"verification": v, "trace": s["trace"] + [f"verify: {'pass' if v.passed else 'fail'} ({v.reason})"]}

    def _abstain_node(self, s: AgentState) -> AgentState:
        reason = s.get("abstain_reason") or "answer could not be verified"
        return {"answer": ABSTAIN_TEXT, "abstained": True, "abstain_reason": reason}

    # ---- routing ----
    @staticmethod
    def _after_guard_or_retrieve(s: AgentState) -> str:
        return "abstain" if s.get("abstained") else "continue"

    def _after_verify(self, s: AgentState) -> str:
        v = s["verification"]
        if s["answer"].strip() == INSUFFICIENT:
            return "abstain"
        if v.passed:
            return "done"
        return "retry" if s["attempts"] < self._max_attempts else "abstain"

    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("guard", self._guard_node)
        g.add_node("retrieve", self._retrieve_node)
        g.add_node("generate", self._generate_node)
        g.add_node("verify", self._verify_node)
        g.add_node("abstain", self._abstain_node)
        g.set_entry_point("guard")
        g.add_conditional_edges("guard", self._after_guard_or_retrieve, {"continue": "retrieve", "abstain": "abstain"})
        g.add_conditional_edges("retrieve", self._after_guard_or_retrieve, {"continue": "generate", "abstain": "abstain"})
        g.add_edge("generate", "verify")
        g.add_conditional_edges("verify", self._after_verify, {"done": END, "retry": "generate", "abstain": "abstain"})
        g.add_edge("abstain", END)
        return g.compile()

    def run(self, question: str, role: str, model_id: str | None = None) -> AgentState:
        return self.graph.invoke(
            {"question": question, "role": role, "model_id": model_id, "attempts": 0, "abstained": False, "trace": []}
        )
