# Phase 2, part 1: retrieval quality and the evaluation suite

This document records how retrieval was measured, what changed because of the measurements, and what is still open.
The raw results are in [`backend/eval/reports/phase2-ablation.json`](../backend/eval/reports/phase2-ablation.json).

## 1. Why measure first

Phase 1 answered questions correctly in demos, but nothing showed whether a change made answers better or worse, and
two failures had already been seen by hand (an unanswerable question got an answer, and an employee asking about an
HR-only document got an unrelated sentence). Before adding hybrid search and reranking, a **golden set** was built so
that every change gets a before-and-after number.

## 2. The golden set

`backend/eval/golden_set.json` holds **60 cases** over a 15-document corpus (`backend/data/sample_docs` plus
`backend/eval/corpus`; 52 chunks, one superseded document and two role-restricted ones).

| Category | Cases | What it checks |
|---|---|---|
| factual | 12 | Plain lookups |
| paraphrase | 19 | Different wording from the policy text ("vacation" for "annual leave") |
| keyword | 9 | Exact numbers, codes and identifiers (`P1`, `0.58`, `HR-204`, `SEC-9`, cost centre `4410`) |
| multi_doc | 3 | Answer lives in more than one document |
| superseded | 1 | The old (inactive) 18-day policy must never be used |
| rbac_denied | 4 | Restricted documents must not be retrieved or stated; the system must refuse |
| rbac_allowed | 2 | The same questions asked by HR must be answered |
| unanswerable | 7 | Off-topic and plausible-but-absent questions (pet insurance, sabbatical, dress code) must be refused |
| injection | 3 | Prompt-injection attempts must be refused |

Each case lists the documents that hold the answer, facts the answer must contain, and documents or facts that must
never appear. Tests verify the set itself: ids are unique, referenced documents exist, expected documents are active,
and **every expected fact really appears in its expected document**.

## 3. Metrics

- **Retrieval** (raw top 5, before any threshold): hit@k, hit@1, MRR, document recall.
- **Answers:** answered rate, all-facts-correct rate, citation precision (cited sources that belong to the expected documents).
- **Safety:** refused-when-it-should rate, and **leaks** (a forbidden document retrieved or a forbidden fact stated).
- **Threshold calibration:** how well the best passage's relevance score separates "answer" from "refuse" questions, and the cut-off that would score best.
- **Latency:** mean and p95 of the agent run.

Run it with `python -m app.eval --configs dense:none,hybrid:none,dense:fastembed,hybrid:fastembed`.

## 4. Results

Offline extractive generator (so the numbers measure retrieval and the answer/refuse decision, not an LLM), real
`bge-small-en-v1.5` embeddings, top 5, 60 cases.

| | dense | hybrid | **dense + rerank** | hybrid + rerank |
|---|---|---|---|---|
| Overall pass rate | 81.7% | 81.7% | **95.0%** | 95.0% |
| Right document in top 5 (hit@k) | 100% | 100% | 100% | 100% |
| Right document first (hit@1) | 95.7% | 95.7% | 95.7% | 95.7% |
| MRR | 0.973 | 0.969 | 0.978 | 0.978 |
| Answers answerable questions | 100% | 100% | 97.8% | 97.8% |
| All expected facts present | 91.3% | 93.5% | 95.7% | 95.7% |
| Citation precision | 88.0% | 85.9% | 90.0% | 90.0% |
| **Refuses when it should** | **50.0%** | 42.9% | **92.9%** | 92.9% |
| Leaks | 0 | 0 | 0 | 0 |
| Relevance threshold | 0.45 | 0.45 | 0.001 | 0.001 |
| Mean latency (20 candidates) | 12 ms | 35 ms | 462 ms | 464 ms |

With 10 candidates for the reranker instead of 20 the pass rate is the same (95.0%), the mean latency drops to
279 ms, and with 6 candidates to 179 ms.

## 5. What the numbers say

1. **Finding documents was never the problem.** Dense search already put the right document in the top 5 for every
   answerable question. Hybrid search therefore had nothing to fix on this corpus, even with the identifier-style
   questions added to give it a fair chance, and it made citations slightly worse.
2. **Deciding when to refuse was the problem.** Without a reranker, the cosine score of the best passage for an
   unanswerable question (0.58 to 0.79) overlaps the score for answerable ones (0.64 and up), so no threshold works:
   the old 0.45 blocked 18% of refusals, and even the best possible cut-off would be right only 93% of the time.
3. **A cross-encoder reranker separates the two cleanly.** Refusal-worthy questions score at or below 0.0006
   while almost all answerable ones score 0.2 or more, and correct refusals jump from 50% to 93%, role-restricted
   questions from 0 of 4 to 4 of 4. The reranker's score is a probability, so it needs its own threshold (0.001),
   tuned from the calibration output.
4. **Cost:** about 280 ms extra per question on CPU with 10 candidates.

## 6. Decisions

| Setting | Default | Why |
|---|---|---|
| `RERANKER_PROVIDER` | `fastembed` (`Xenova/ms-marco-MiniLM-L-6-v2`, 80 MB, local) | +13 points overall pass rate, refusals 50% to 93% |
| `RERANK_FETCH_K` | 10 | Same accuracy as 20 at roughly 60% of the latency |
| `MIN_RERANK_SCORE` | 0.001 | Best separation point found by the calibration step |
| `RETRIEVAL_MODE` | `dense` | Hybrid showed no gain here; it stays available (`hybrid`) for larger corpora |

Retrieval changes behind these defaults: `Source.relevance` (a comparable 0..1 score the agent uses for the
answer/abstain decision) is now separate from `Source.score` (what the ranking used); hybrid fusion scores are rank
based and not comparable across questions, so hybrid keeps the dense cosine as its relevance.

## 7. Known weak spots (3 of 60 cases still fail)

- `leave-04` "Do I need a doctor's note when I am sick?": the cross-encoder scores the correct passage at 0.0002, below the threshold, so the system refuses a question it could answer.
- `prv-04` "How quickly must we respond when a customer asks us to delete their data?": the right passage is retrieved, but the offline extractive generator picks the wrong sentence. An LLM generator is expected to fix this; the extractive mode is a fallback.
- `none-06` "How many weeks of sabbatical leave do employees get?": the reranker rates the leave policy as relevant to "sabbatical leave" (0.87), so the question is answered instead of refused. This needs the claim-level verifier planned next.

## 8. Limitations of this evaluation

- **Small corpus** (15 documents, 52 chunks). Hybrid search often earns its keep on thousands of chunks; this corpus cannot show that.
- **Thresholds were tuned on the same 60 cases they are scored on**, so the 95% figure is optimistic for unseen questions. Grow the set (the feedback buttons planned for Phase 2 are meant to feed it) and re-run the calibration.
- **The generator is extractive**, not an LLM. Answer-quality numbers (facts, citation precision) will differ with a real model, and the groundedness of free-text answers is not yet measured. A model-based judge is part of the verifier work.
- **Latency** is CPU-only on a development machine.

## 9. Reproducing

```bash
cd backend
.venv/Scripts/python -m app.eval --configs dense:none,hybrid:none,dense:fastembed,hybrid:fastembed --json
RUN_EVAL=1 .venv/Scripts/python -m pytest tests/test_eval.py::test_quality_gate_with_real_models   # CI-style gate
```

The first run downloads the embedding, keyword and reranker models. `--model gemini-3.5-flash-lite` runs the same
cases through a real LLM (it sends the synthetic corpus text to Google and uses quota).
