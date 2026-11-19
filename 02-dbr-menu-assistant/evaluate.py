"""Score the assistant on the questions in evals/questions.jsonl.

Each question lists the facts a correct reply must contain (must_include, where "a|b" means
either is fine), phrases it must not contain, the documents search should find, and for orders
the expected food total. Scoring is plain string matching, so a run is repeatable and costs
nothing beyond the answers themselves.

Usage:
    python evaluate.py                       # full run, about $0.015 with Claude Haiku 5.5
    python evaluate.py --retrieval-only      # search quality only, no API key needed
    python evaluate.py --only price-mutton-half dessert
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from assistant import IST, Answer, Assistant, AssistantError

HERE = Path(__file__).parent
QUESTIONS = HERE / "evals" / "questions.jsonl"
# A fixed lunchtime, so questions about opening hours score the same on every run.
EVAL_TIME = datetime(2026, 11, 19, 13, 0, tzinfo=IST)


def load_cases(path: Path = QUESTIONS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def retrieval_misses(case: dict, sources: list[str]) -> list[str]:
    return [f"search missed {s!r}" for s in case.get("sources", []) if s not in sources]


def score(case: dict, answer: Answer) -> list[str]:
    """Return the reasons this answer fails the case; an empty list is a pass."""
    text = answer.text.lower()
    failures = retrieval_misses(case, answer.sources)
    if answer.fallback:
        failures.append("fell back to the kitchen: " + "; ".join(answer.problems))
    for fact in case.get("must_include", []):
        if not any(option.lower() in text for option in fact.split("|")):
            failures.append(f"missing {fact!r}")
    for phrase in case.get("must_not_include", []):
        if phrase.lower() in text:
            failures.append(f"should not say {phrase!r}")
    if "in_scope" in case and answer.reply and answer.reply.in_scope != case["in_scope"]:
        failures.append(f"in_scope should be {case['in_scope']}")
    if "order_total" in case and f"₹{case['order_total']:,}" not in answer.order_summary:
        failures.append(f"order total should be ₹{case['order_total']:,}")
    return failures


def run_retrieval(cases: list[dict]) -> int:
    bot = Assistant()
    found = 0
    for case in cases:
        sources = [h.doc.title for h in bot.retrieve(case["question"])]
        misses = retrieval_misses(case, sources)
        found += not misses
        print(f"{'ok  ' if not misses else 'MISS'} {case['id']}" + (f"  ({'; '.join(misses)})" if misses else ""))
    print(f"\nSearch found every expected document for {found} of {len(cases)} questions.")
    return 0


def run_full(cases: list[dict]) -> int:
    bot = Assistant()
    rows, passed, cost, secs = [], 0, 0.0, 0.0
    for case in cases:
        try:
            answer = bot.ask(case["question"], now=EVAL_TIME)
        except AssistantError as e:
            print(e)
            return 1
        failures = score(case, answer)
        passed += not failures
        cost += answer.cost_usd
        secs += answer.seconds
        print(f"{'PASS' if not failures else 'FAIL'} {case['id']}  ${answer.cost_usd:.5f}"
              + (f"\n     {'; '.join(failures)}" if failures else ""))
        rows.append((case, answer, failures))

    n = len(cases)
    summary = (f"{passed} of {n} passed. Total cost ${cost:.4f}, ${cost / n:.5f} per answer, "
               f"{secs / n:.1f}s per answer on average.")
    print("\n" + summary)

    out = HERE / "outputs"
    out.mkdir(exist_ok=True)
    path = out / f"eval-{datetime.now():%Y%m%d-%H%M}.md"
    lines = [f"# Evaluation run {datetime.now():%Y-%m-%d %H:%M}", "", summary, ""]
    for case, answer, failures in rows:
        lines += [f"## {case['id']}: {'pass' if not failures else 'FAIL'}", "",
                  f"**Question:** {case['question']}", "", "```", answer.text, "```", ""]
        if failures:
            lines += ["Failures: " + "; ".join(failures), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved {path.relative_to(HERE)}")
    return 0 if passed == n else 2


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--retrieval-only", action="store_true", help="score search only, no LLM calls")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run only these question ids")
    args = parser.parse_args()

    cases = load_cases()
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]
    if args.retrieval_only:
        return run_retrieval(cases)
    return run_full(cases)


if __name__ == "__main__":
    sys.exit(main())
