"""Compare LLMs on the same prospects, so the model choice is based on evidence.

Each prospect is researched once and every model gets identical research, so only the model differs.
Records, per model: whether the email passed the quality checks, fit score, tokens, real cost
(from OpenRouter's live price list) and time taken. Writes outputs/compare-<time>.md.

Usage:
    python compare_models.py prospects.csv --models openrouter/free anthropic/claude-haiku-5.5
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

import httpx
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

import agent

DEFAULT_MODELS = ["openrouter/free", "anthropic/claude-haiku-5.5", "deepseek/deepseek-v4.1-flash", "openai/gpt-6-luna"]


def prices(models: list[str]) -> dict[str, tuple[float, float]]:
    """USD per token (input, output) from OpenRouter's public model list."""
    data = httpx.get("https://openrouter.ai/api/v1/models", timeout=30).json()["data"]
    table = {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"])) for m in data}
    return {m: table.get(m, (0.0, 0.0)) for m in models}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args()

    with args.csv_path.open(newline="", encoding="utf-8-sig") as f:
        prospects = [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]
    client = OpenAI(base_url=agent.BASE_URL, api_key=agent.API_KEY, timeout=120, max_retries=1)
    price = prices(args.models)
    stats = {m: {"passed": 0, "flagged": 0, "skipped": 0, "failed": 0, "cost": 0.0, "secs": 0.0, "scores": []}
             for m in args.models}
    emails = []

    for p in prospects:
        name = p.get("business_name", "?")
        print(f"{name}: researching once...", flush=True)
        research = agent.gather_research(p)
        for m in args.models:
            print(f"  {m} ...", flush=True)
            before = dict(agent.TOKENS)
            start = time.monotonic()
            try:
                result, flags = agent.draft(client, p, research, model=m)
            except (OpenAIError, ValidationError) as e:
                stats[m]["failed"] += 1
                emails.append((name, m, f"FAILED: {str(e)[:150]}", ""))
                continue
            finally:
                stats[m]["secs"] += time.monotonic() - start
                tin = agent.TOKENS["input"] - before["input"]
                tout = agent.TOKENS["output"] - before["output"]
                stats[m]["cost"] += tin * price[m][0] + tout * price[m][1]
            if not result.research_matches_business:
                stats[m]["skipped"] += 1
                emails.append((name, m, "skipped: research didn't match", ""))
                continue
            stats[m]["flagged" if flags else "passed"] += 1
            stats[m]["scores"].append(result.fit_score)
            header = f"fit {result.fit_score}/10" + (f", FLAGGED: {'; '.join(flags)}" if flags else ", passed checks")
            emails.append((name, m, header, f"Subject: {result.subject}\n\n{result.email_body}"))

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    lines = [f"# Model comparison, {stamp}\n", f"{len(prospects)} prospects, identical research for every model.\n",
             "| Model | Passed checks | Flagged | Skipped (no match) | Failed | Fit scores | Total cost | Avg time |",
             "|---|---|---|---|---|---|---|---|"]
    for m, s in stats.items():
        n = max(1, len(prospects))
        lines.append(f"| {m} | {s['passed']} | {s['flagged']} | {s['skipped']} | {s['failed']} | "
                     f"{', '.join(map(str, s['scores'])) or '-'} | ${s['cost']:.4f} | {s['secs'] / n:.0f}s |")
    for name, m, header, body in emails:
        lines += [f"\n## {name} · {m}\n", f"_{header}_\n", f"```\n{body}\n```\n" if body else ""]

    out = agent.HERE / "outputs" / f"compare-{stamp}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines[2:3 + len(stats) + 1]))
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
