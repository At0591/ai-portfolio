"""Score the writing checks on planted errors and clean sentences.

    python eval/run_eval.py          # Vale and LanguageTool
    python eval/run_eval.py --llm    # plus the AI flag-only proofreader

For every case it runs Vale (house rules) and the local LanguageTool server, then reports
how many planted errors were caught and how many clean sentences were wrongly flagged.
Each case is written as a small HTML page, so the heading rules apply to headings.
"""
import html
import importlib.util
import json
import os
import shutil
import sys
import subprocess
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VALE = os.environ.get('VALE') or shutil.which('vale') or str(Path.home() / 'vale' / 'vale.exe')

spec = importlib.util.spec_from_file_location('gc', ROOT / 'grammar.py')
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)
spec = importlib.util.spec_from_file_location('lp', ROOT / 'proofread.py')
lp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)


def vale_findings(case: dict, folder: Path) -> list[str]:
    tag = 'h2' if case['heading'] else 'p'
    page = folder / f"{case['id']}.html"
    page.write_text(f"<!doctype html><html><body><{tag}>{html.escape(case['text'], quote=False)}</{tag}></body></html>", encoding='utf-8')
    r = subprocess.run([str(VALE), '--config', str(ROOT / '.vale.ini'), '--output', 'JSON',
                        str(page.relative_to(ROOT))],
                       capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
    data = json.loads(r.stdout or '{}')
    return [a['Check'] for alerts in data.values() for a in alerts]


def lt_findings(case: dict, accept: set[str]) -> list[str]:
    out = []
    for m in gc.check(case['text'], 'en-GB'):
        word = case['text'][m['offset']:m['offset'] + m['length']]
        if m['rule']['id'].startswith('MORFOLOGIK') and word.lower() in accept:
            continue  # same word list the house checks use
        out.append(m['rule']['id'])
    return out


def llm_findings(case: dict, client) -> list[str]:
    if client is None or case['heading']:
        return []  # headings are a sentence-case job for Vale, not grammar
    return ['LLM: ' + i['quote'] for i in lp.proofread(case['text'], client)]


def main() -> int:
    use_llm = '--llm' in sys.argv
    client = None
    if use_llm:
        import httpx
        client = httpx.Client(timeout=60, headers={'Authorization': f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    gc.ensure_server()
    accept = gc.accepted_words()
    cases = json.loads((HERE / 'cases.json').read_text(encoding='utf-8'))['cases']
    rows = []
    with tempfile.TemporaryDirectory(dir=HERE) as tmp:
        for c in cases:
            v, l, m = vale_findings(c, Path(tmp)), lt_findings(c, accept), llm_findings(c, client)
            rows.append({**c, 'vale': v, 'lt': l, 'llm': m, 'flagged': bool(v or l or m)})

    errors = [r for r in rows if r['error']]
    clean = [r for r in rows if not r['error']]
    caught = [r for r in errors if r['flagged']]
    false_flags = [r for r in clean if r['flagged']]
    lines = [f"# Writing check results, {date.today():%d %b %Y}", "",
             f"Planted errors caught: {len(caught)} of {len(errors)} "
             f"(Vale alone {sum(bool(r['vale']) for r in errors)}, LanguageTool alone {sum(bool(r['lt']) for r in errors)}"
             + (f", AI proofreader alone {sum(bool(r['llm']) for r in errors)}" if use_llm else '') + ").",
             f"Clean sentences wrongly flagged: {len(false_flags)} of {len(clean)}.", "",
             "| Case | Kind | Caught by |", "|---|---|---|"]
    for r in rows:
        by = ', '.join(sorted(set(r['vale'] + r['lt'] + r['llm']))) or ('missed' if r['error'] else 'none')
        lines.append(f"| {r['id']} | {r['kind']} | {by} |")
    (HERE / 'results.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[:4]))
    for r in errors:
        if not r['flagged']:
            print('MISSED', r['id'], r['kind'], '|', r['text'])
    for r in false_flags:
        print('FALSE FLAG', r['id'], '|', r['vale'] + r['lt'] + r['llm'], '|', r['text'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
