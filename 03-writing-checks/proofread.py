"""Flag-only proofreading with a second model. It never rewrites text.

    python proofread.py path/to/file.md
    python proofread.py --text "One sentence to check."

A model from a different company to the one that drafts the text (so it does not
share the writer's blind spots) reads the text 3 times
and returns grammar and spelling problems as JSON. Only problems that at least 2 of the 3
runs agree on are reported. Style is left to Vale; this pass is for real mistakes only.
Costs about $0.0001 a sentence with the default model. Key: OPENROUTER_API_KEY.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import httpx

MODEL = 'openai/gpt-6-luna'
RUNS = 3
AGREE = 2

PROMPT = """You are a strict proofreader for British English professional writing.
Find only real grammar and spelling mistakes: subject-verb agreement, wrong word
(their/there, its/it's, affect/effect), missing plural, wrong verb form, missing or extra
word, misspelling. Do NOT flag style, tone, word choice, sentence length, the Oxford
comma, sentence-case headings, numbers written as digits, or product and place names.
If the text is correct, return no issues. Do not rewrite the text.

Return JSON only, in this shape:
{"issues": [{"quote": "exact words from the text, 1 to 4 words", "problem": "short reason"}]}

Text:
<<<
%s
>>>"""


def ask(text: str, client: httpx.Client) -> list[dict]:
    r = client.post('https://openrouter.ai/api/v1/chat/completions', json={
        'model': MODEL,
        'messages': [{'role': 'user', 'content': PROMPT % text}],
        'temperature': 0.3,
        'max_tokens': 800,
        'reasoning': {'effort': 'low'},
        'response_format': {'type': 'json_object'},
    })
    r.raise_for_status()
    content = r.json()['choices'][0]['message'].get('content') or '{}'
    m = re.search(r'\{.*\}', content, re.S)
    try:
        issues = json.loads(m.group(0) if m else '{}').get('issues', [])
    except json.JSONDecodeError:
        return []
    # Keep only quotes that really appear in the text, so an invented problem cannot pass.
    return [i for i in issues if isinstance(i, dict) and i.get('quote') and i['quote'].lower() in text.lower()]


def proofread(text: str, client: httpx.Client | None = None) -> list[dict]:
    """Issues that at least AGREE of RUNS runs report, matched by the quoted words."""
    own = client is None
    client = client or httpx.Client(timeout=60, headers={'Authorization': f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    try:
        runs = [ask(text, client) for _ in range(RUNS)]
    finally:
        if own:
            client.close()
    votes, first = Counter(), {}
    for issues in runs:
        seen = set()
        for i in issues:
            key = i['quote'].lower().strip()
            if key not in seen:
                seen.add(key)
                votes[key] += 1
                first.setdefault(key, i)
    return [first[k] for k, n in votes.items() if n >= AGREE]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('file', nargs='?')
    ap.add_argument('--text')
    a = ap.parse_args()
    text = a.text if a.text else Path(a.file).read_text(encoding='utf-8')
    issues = proofread(text)
    for i in issues:
        print(f"- \"{i['quote']}\": {i.get('problem', '')}")
    print(f"{len(issues)} issue(s) agreed by {AGREE} of {RUNS} runs ({MODEL}).")
    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
