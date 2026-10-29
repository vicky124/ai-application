# Phase 2, part 2: the claim-level groundedness verifier

Before this work the verifier only checked the *form* of an answer: every sentence has a citation, the citations
exist, and the numbers appear somewhere in the sources. It could not tell whether a cited passage actually supports
what the sentence says. This document records what was built, how well it works, and, importantly, how far the
numbers can be trusted.

## 1. What was built

`ClaimVerifier` runs the old rule checks first, then splits the answer into **claims** (one per sentence, each with the
sources it cites) and checks every claim against **only the sources it cites**.

| Mode (`VERIFIER_MODE`) | What it does | Needs |
|---|---|---|
| `rules` | The previous checks only | nothing |
| `claims` (default) | Plus offline claim-by-claim checks (below) | nothing extra; uses the reranker model if enabled |
| `llm` | An LLM judges each claim in one call per answer; falls back to the offline checks if the model is unavailable | an LLM (default `VERIFIER_MODEL_ID=gemini-3.5-flash-lite`) |

**Offline claim checks** (`app/agents/checkers.py`, `app/agents/evidence.py`), in order, per claim:

1. **Numbers:** every number in the claim must appear in the cited text (`1,000` and `1000` match).
2. **Polarity:** the cited passage unit that best matches each clause must not say the opposite (negation parity, so "can be carried forward" against "cannot be carried forward" is a contradiction). Compound claims are compared clause by clause.
3. **Sweeping wording:** words such as *all, always, any, never, immediately, automatically* must be used by the source, otherwise the claim goes beyond it.
4. **Wording coverage:** enough of each clause's content words must be present in the cited text. Clauses are checked separately so an invented extra clause ("... plus a birthday day off") cannot hide behind a true one.
5. **Cross-encoder (optional):** the reranker model scores how well the cited passage states the claim; a very low score vetoes it.

**Verdicts per claim:** `supported`, `unsupported`, `contradicted` or `uncited`, each with a short reason and an evidence
strength. The answer's **confidence** is the strength of its weakest claim (a heuristic shown as High / Medium / Low, not
a probability).

**Feedback loop:** when verification fails, the agent no longer regenerates blindly. The generator receives a hint that
names the unsupported claims ("The claim 'X' cited [1] is not supported: ...") and is told to rewrite using only facts in
the sources or answer `INSUFFICIENT_CONTEXT`. After the last attempt the agent abstains and the reason now says *why*
("answer could not be verified: 1 unsupported claim(s); first: ...").

**API and UI:** `/api/chat` returns `verification.claims` (verdict, cited sources, reason, strength) and
`verification.confidence`. The chat shows a confidence badge and an expandable "Claim checks" list.

## 2. How it was measured

Two labeled sets of model-style answers, each paired with the exact corpus passages they cite
(`backend/eval/verifier_cases.json`, `backend/eval/verifier_holdout.json`). **Faithful** answers are paraphrases that
must pass; **faulty** answers each contain one specific fault that must fail.

| Set | Faithful | Faulty | Purpose |
|---|---|---|---|
| Development (`verifier_cases.json`) | 26 | 29 | Used while building the checks (alternating dev/test halves) |
| **Held-out** (`verifier_holdout.json`) | 20 | 20 | Written **after** the checks were frozen; never used for tuning |

Fault types in the development set: wrong number, fabricated claim, extra unsupported sentence, wrong citation,
contradiction, overgeneralization, no citation, invalid citation index. The held-out set adds subtler ones: **role
swap, flipped condition ("after" becomes "before"), small unit change ("2 working days" becomes "2 hours"), swapped
numbers, entity swap**.

Reported: how many faulty answers are caught (recall), how many faithful answers are wrongly flagged (false alarms),
precision, accuracy. Run: `python -m app.eval.verifier_eval --verifiers rules,lexical,claims [--cases holdout]`.

## 3. Results

### The trap I fell into, and how it was caught
The first version caught 72% of the development set's faulty answers. I then improved the checks by looking at which
cases failed (clause-level coverage, sweeping-wording checks, polarity per clause, a better stemmer) until the
development set scored **100% caught, 0% false alarms**. That number is meaningless as an estimate of real
performance: the checks were shaped by those exact cases. So a fresh held-out set was written afterwards and run once.

### Held-out set (40 answers, the honest numbers)

| Verifier | Catches faulty answers | False alarms on faithful answers | Precision |
|---|---|---|---|
| `rules` (the previous verifier) | **5%** (1 of 20) | 0% | 100% |
| `claims`, offline (new default) | **40%** (8 of 20) | **10%** (2 of 20) | 80% |
| `llm`, Gemini 3.5 Flash-Lite judge | **100%** (20 of 20) | **0%** (0 of 20) | 100% |

By fault type on the held-out set:

| Fault | rules | claims (offline) | llm |
|---|---|---|---|
| fabricated claim / extra clause | 0/5 | 3/5 | 5/5 |
| contradiction | 0/2 | 2/2 | 2/2 |
| wrong citation | 0/1 | 1/1 | 1/1 |
| overgeneralization | 0/1 | 1/1 | 1/1 |
| wrong number | 1/1 | 1/1 | 1/1 |
| **role swap, flipped condition, unit change, number swap, entity swap** | 0/10 | **0/10** | **10/10** |

### What this means
- The old verifier caught almost nothing beyond wrong numbers and missing citations.
- The offline checks reliably catch **invented content, sweeping claims, contradictions with negation and wrong citations**, but **none of the subtle meaning changes** (swapped roles, flipped conditions, unit and number swaps). Wording-based checks cannot see them, and neither can the cross-encoder at its default threshold. That is a limit of the approach, not a tuning problem.
- The **LLM judge caught every fault**, including all ten subtle ones, with no false alarms and no fallbacks.
- Two faithful answers were falsely flagged offline: a paraphrase using different words than the source ("reachable between" for "available during") and a clause-polarity edge case ("are not tolerated, and can lead to ..."). In the application a false alarm costs one retry with feedback, and an abstention if the retry also fails.

### Cost of the LLM judge
About **17 seconds per answer** on Gemini 3.5 Flash-Lite (40 answers took 11.5 minutes), on top of generation time,
plus one API call per answer; and the question, the answer and the cited passages are sent to Google. That is why the
offline mode is the default and `llm` is opt-in.

### End-to-end check (no regression)
On the 60-question retrieval golden set (offline extractive generator) the claim verifier leaves every number unchanged
(95.0% pass rate, the same three known failures) at about 45 ms extra per question. That is expected: the extractive
generator copies source sentences, which are always supported. The verifier matters for LLM-written answers.

## 4. Limits of this evaluation (read before relying on the numbers)

- **Small samples.** 40 held-out answers; 20 faulty. One miss changes the offline recall by 5 points. The 100% for the LLM judge is one run with one model, not a guarantee, and LLM judges can be inconsistent.
- **Synthetic faults.** The faulty answers were written by hand to contain one specific error each. Real LLM mistakes are messier and more varied.
- **Not yet end to end with an LLM generator.** The verifier was measured on labeled answers, not on live answers from Gemini or Llama, because the generators are not installed or quota-limited here.
- **The development set is contaminated** by design (it shaped the checks). Its floors in the test suite guard against regressions; they are not an estimate.
- **The held-out set must stay held out.** If it is used for tuning it stops being evidence. Add new cases to it instead.
- **Confidence is a heuristic**, the evidence strength of the weakest claim, not a calibrated probability.
- **The prompt was written once** before the held-out run and not changed afterwards.

## 5. Not solved yet
- The **sabbatical question** from the retrieval golden set is still answered from the leave policy. Every claim in that answer is *supported* by its source; the problem is that the answer does not address the question. That is answer relevance, a separate check from groundedness.
- Subtle meaning changes are only caught in `llm` mode.
- **Version conflicts** (two documents disagreeing) and conversation-aware follow-ups are still open Phase 2 items.

## 6. Reproducing

```bash
cd backend
.venv/Scripts/python -m app.eval.verifier_eval --verifiers rules,lexical,claims --failures                   # development set
.venv/Scripts/python -m app.eval.verifier_eval --cases holdout --verifiers rules,lexical,claims --failures   # held-out set
.venv/Scripts/python -m app.eval.verifier_eval --cases holdout --verifiers llm --llm gemini-3.5-flash-lite   # judge: 40 live calls
.venv/Scripts/python -m app.eval.verifier_eval --calibrate                                                  # thresholds, dev split only
```

Saved results: `backend/eval/reports/verifier-dev.json`, `verifier-holdout.json`, `verifier-holdout-llm.txt`.
