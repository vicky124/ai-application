"""CLI: python -m app.eval [--configs dense:none,hybrid:fastembed] [--model extractive] [--json report.json]"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.eval.cases import EVAL_DIR, load_cases
from app.eval.harness import StackConfig, build_stack
from app.eval.report import render_comparison, render_run, to_dict
from app.eval.runner import run_cases


def parse_configs(text: str, args) -> list[StackConfig]:
    configs = []
    for part in text.split(","):
        retrieval, _, rerank = part.strip().partition(":")
        configs.append(
            StackConfig(
                retrieval=retrieval or "dense",
                rerank=rerank or "none",
                embedding_provider=args.embedding,
                model_id=args.model,
                top_k=args.top_k,
                fetch_k=args.fetch_k,
                min_score=args.min_score,
            )
        )
    return configs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--configs", default="dense:none", help="comma list of retrieval:rerank, e.g. dense:none,hybrid:none,hybrid:fastembed")
    p.add_argument("--model", default="extractive", help="model id from the catalog (extractive needs no LLM)")
    p.add_argument("--embedding", default="fastembed", choices=["fastembed", "hash"])
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--fetch-k", type=int, default=10, help="candidates handed to the reranker")
    p.add_argument("--min-score", type=float, default=None, help="override the relevance threshold for every configuration")
    p.add_argument("--category", action="append", help="only run these categories (repeatable)")
    p.add_argument("--no-failures", action="store_true", help="do not list failing cases")
    p.add_argument("--json", nargs="?", const="auto", help="write a JSON report (default: eval/reports/<timestamp>.json)")
    p.add_argument("--min-pass-rate", type=float, default=None, help="exit with status 1 if any configuration is below this overall pass rate")
    args = p.parse_args()

    cases = load_cases(categories=set(args.category) if args.category else None)
    runs = []
    for cfg in parse_configs(args.configs, args):
        stack = build_stack(cfg)
        try:
            run = run_cases(stack, cases)
        finally:
            stack.close()
        runs.append(run)
        print(render_run(run, show_failures=not args.no_failures), end="\n\n")

    if len(runs) > 1:
        print(render_comparison(runs))

    if args.json:
        path = Path(args.json) if args.json != "auto" else EVAL_DIR / "reports" / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"runs": [to_dict(r) for r in runs]}, indent=2), encoding="utf-8")
        print(f"\nreport written to {path}")

    if args.min_pass_rate is not None and any(r.summary["pass_rate"] < args.min_pass_rate for r in runs):
        print(f"\nFAIL: pass rate below {args.min_pass_rate:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
