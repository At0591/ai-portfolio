"""Grammar and spelling check with a local LanguageTool server.

Usage:
    python grammar.py FILE [FILE ...] [--lang en-GB|en-US]

Checks the readable text of .html and .md files (code, scripts and blocks between
"vale off" and "vale on" comments are skipped). Prints each problem with its
context and suggestions, and exits with 1 if it finds any.

Runs against a LanguageTool server on this computer, which it starts if needed
(LT_DIR, default ~/languagetool/LanguageTool-6.6, needs Java 17 or newer).
LanguageTool's free public API does not allow automated requests, so this script
never calls it. Nothing leaves the computer.
"""
import argparse
import os
import shutil
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PORT = os.environ.get('LT_PORT', '8081')
API = f'http://localhost:{PORT}/v2/check'
LT_DIR = Path(os.environ.get('LT_DIR', Path.home() / 'languagetool' / 'LanguageTool-6.6'))
ADOPTIUM = Path('C:/Program Files/Eclipse Adoptium')
JAVA_CANDIDATES = sorted(ADOPTIUM.glob('*/bin/java.exe')) if ADOPTIUM.exists() else []
# House style: British spelling with -ise, no Oxford comma, degree names as written.
# Straight quotes and a plain '...' are house style too (humanizer 21).
DISABLED = 'SERIAL_COMMA_ON,OXFORD_SPELLING_Z_NOT_S,BACHELOR_ABBR,ATD_VERBS_TO_COLLOCATION,EN_QUOTES,EN_REPEATEDWORDS_CHOOSE,EN_ELLIPSIS,ELLIPSIS'
MAX_CHARS = 18000
ROOT = Path(__file__).resolve().parent
VOCAB = ROOT / 'styles' / 'config' / 'vocabularies' / 'Akshay' / 'accept.txt'


def accepted_words() -> set[str]:
    words: set[str] = set()
    if VOCAB.exists():
        for line in VOCAB.read_text(encoding='utf-8').splitlines():
            words.update(w.lower() for w in line.split())
    return words


def readable_text(path: Path) -> str:
    raw = path.read_text(encoding='utf-8')
    raw = re.sub(r'<!--\s*vale off\s*-->.*?<!--\s*vale on\s*-->', ' ', raw, flags=re.S)
    if path.suffix.lower() in ('.html', '.htm'):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, 'html.parser')
        for tag in soup(['script', 'style', 'pre', 'code', 'head']):
            tag.decompose()
        blocks = [' '.join(el.get_text(' ').split()) for el in soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'dt', 'dd', 'a', 'figcaption', 'span'])
                  if el.find(['p', 'li', 'h1', 'h2', 'h3']) is None]
        seen, out = set(), []
        for b in blocks:
            if b and b not in seen:
                seen.add(b)
                out.append(b)
        return '\n\n'.join(out)
    text = re.sub(r'```.*?```', ' ', raw, flags=re.S)
    text = re.sub(r'`[^`]*`', 'code', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text


def chunks(text: str):
    buf = ''
    for para in text.split('\n\n'):
        if len(buf) + len(para) + 2 > MAX_CHARS and buf:
            yield buf
            buf = ''
        buf += para + '\n\n'
    if buf.strip():
        yield buf


def ensure_server() -> None:
    """Start the local LanguageTool server if it is not already running."""
    import subprocess
    def up() -> bool:
        try:
            urllib.request.urlopen(f'http://localhost:{PORT}/v2/languages', timeout=3)
            return True
        except OSError:
            return False
    if up():
        return
    java = os.environ.get('JAVA') or (str(JAVA_CANDIDATES[-1]) if JAVA_CANDIDATES else shutil.which('java') or 'java')
    subprocess.Popen([java, '-Xmx1g', '-cp', str(LT_DIR / 'languagetool-server.jar'),
                      'org.languagetool.server.HTTPServer', '--port', PORT],
                     cwd=LT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _ in range(40):
        time.sleep(1)
        if up():
            return
    sys.exit('Local LanguageTool server did not start. Check Java and ' + str(LT_DIR))


def check(text: str, lang: str, disabled: str = DISABLED) -> list[dict]:
    data = urllib.parse.urlencode({'text': text, 'language': lang, 'level': 'picky', 'disabledRules': disabled}).encode()
    req = urllib.request.Request(API, data=data, headers={'User-Agent': 'grammar-check-script'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)['matches']


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--lang', default='en-GB')
    args = ap.parse_args()
    ensure_server()
    accept = accepted_words()
    total = 0
    for name in args.files:
        path = Path(name)
        problems = []
        for part in chunks(readable_text(path)):
            for m in check(part, args.lang):
                ctx = m['context']
                word = ctx['text'][ctx['offset']:ctx['offset'] + ctx['length']]
                if m['rule']['issueType'] == 'misspelling' and word.lower() in accept:
                    continue
                problems.append((m, word, part))
        print(f'== {path} ({len(problems)} issues)')
        for m, word, part in problems:
            ctx = m['context']['text']
            fixes = ', '.join(r['value'] for r in m['replacements'][:3]) or 'no suggestion'
            print(f"  [{m['rule']['id']}] {m['message']}\n    \"{ctx}\"\n    -> {fixes}")
        total += len(problems)
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
