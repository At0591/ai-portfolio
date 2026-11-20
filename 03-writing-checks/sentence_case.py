"""Sentence case for the short text Vale cannot see: page titles, meta titles,
buttons, links, labels and email subject lines.

    python sentence_case.py page.html ...                # titles, buttons and labels on pages
    python sentence_case.py --text "Book A Free Call"    # one line, such as an email subject

A capital is allowed on the first word, after a colon, a full stop, a question mark or a
" | " separator, and on words in the house vocabulary (.vale accept.txt and the Headings
exceptions in styles/), acronyms and mixed-case names such as iQOO or Next.js. Exits 1 on any problem.
"""
import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAGS = {'title', 'button', 'a', 'label', 'summary', 'th', 'figcaption', 'option'}
META = {'og:title', 'twitter:title', 'description:title'}


def vocabulary() -> set[str]:
    words = set()
    accept = HERE / 'styles' / 'config' / 'vocabularies' / 'Akshay' / 'accept.txt'
    for line in accept.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            words.add(line.replace('\\', ''))
    heads = (HERE / 'styles' / 'Akshay' / 'Headings.yml').read_text(encoding='utf-8')
    words.update(re.findall(r'^\s+-\s+(\S+)\s*$', heads.split('exceptions:')[-1], re.M))
    return words


def problems(text: str, vocab: set[str]) -> list[str]:
    """Capitalised words that sentence case does not allow."""
    bad = []
    # Each segment starts afresh: after : . ? ! or a | separator.
    for seg in re.split(r'[:.?!|]\s+|\s+[|·]\s+', text.strip()):
        words = re.findall(r"[A-Za-z][\w.'’-]*", seg)
        for i, w in enumerate(words):
            core = w.rstrip(".'’").split("'")[0].split('’')[0]
            if i == 0 or not core[:1].isupper():
                continue
            if core in vocab or (core.isupper() and len(core) > 1) or any(c.isupper() for c in core[1:]) or any(c.isdigit() for c in core):
                continue
            # Multi-word names in the vocabulary, such as "Dum Biryani Rasoi".
            if any(core in v.split() and v in seg for v in vocab if ' ' in v):
                continue
            bad.append(core)
    return bad


class Short(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.found, self.off = [], [], False

    def handle_comment(self, data):
        if 'vale off' in data:
            self.off = True
        elif 'vale on' in data:
            self.off = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta' and (a.get('property') in META or a.get('name') in META) and a.get('content'):
            self.found.append((tag + ' ' + (a.get('property') or a.get('name')), a['content'], self.getpos()[0]))
        if tag in TAGS:
            self.stack.append([tag, '', self.getpos()[0]])

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            t, text, line = self.stack.pop()
            if not self.off and text.strip():
                self.found.append((t, ' '.join(text.split()), line))

    def handle_data(self, data):
        for item in self.stack:
            item[1] += data


def check_page(path: Path, vocab: set[str]) -> int:
    p = Short()
    p.feed(path.read_text(encoding='utf-8'))
    n = 0
    for tag, text, line in p.found:
        # Links that are only a name or an address (email, phone, a site) are not labels.
        if tag == 'a' and ('@' in text or re.fullmatch(r'[+\d\s()-]+|\S+\.\w{2,}(/\S*)?', text)):
            continue
        bad = problems(text, vocab)
        if bad:
            n += 1
            print(f'  {path.name}:{line} <{tag}> "{text}": {", ".join(bad)}')
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('pages', nargs='*')
    ap.add_argument('--text')
    a = ap.parse_args()
    vocab = vocabulary()
    if a.text:
        bad = problems(a.text, vocab)
        print(f'"{a.text}": ' + (', '.join(bad) if bad else 'sentence case'))
        return 1 if bad else 0
    if not a.pages:
        ap.error('give one or more HTML pages, or --text')
    pages = [Path(x) for x in a.pages]
    total = sum(check_page(p, vocab) for p in pages)
    print(f'Sentence case: {total} problem(s) in titles, buttons, links and labels across {len(pages)} page(s).')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
