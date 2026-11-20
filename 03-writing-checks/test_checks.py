"""Offline tests: no network, no Vale and no LanguageTool needed."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = load('sentence_case')
pr = load('proofread')
VOCAB = sc.vocabulary()


def test_title_case_is_flagged():
    assert sc.problems('Book A Free Call', VOCAB) == ['A', 'Free', 'Call']


def test_sentence_case_passes():
    assert sc.problems('Get free sample', VOCAB) == []


def test_names_acronyms_and_mixed_case_pass():
    assert sc.problems('Built with Next.js, OpenAI and the CRM', VOCAB) == []
    assert sc.problems('Dum Biryani Rasoi menu assistant', VOCAB) == []


def test_capital_allowed_after_colon_and_separator():
    assert sc.problems('KindRise: Gentle alarm | Home', VOCAB) == []


def test_html_finds_buttons_titles_and_options(tmp_path):
    page = tmp_path / 'p.html'
    page.write_text('<title>Akshay | Home Page</title><button>Send Message</button>'
                    '<select><option>Boutique hotel</option></select>', encoding='utf-8')
    assert sc.check_page(page, VOCAB) == 2


def test_majority_vote_and_quote_check(monkeypatch):
    text = 'Owners check there photos.'
    runs = iter([
        [{'quote': 'there photos', 'problem': 'their'}],
        [{'quote': 'There photos', 'problem': 'their'}, {'quote': 'Owners', 'problem': 'odd'}],
        [],
    ])
    monkeypatch.setattr(pr, 'ask', lambda t, c: next(runs))
    issues = pr.proofread(text, client=object())
    assert [i['quote'] for i in issues] == ['there photos']


def test_invented_quote_is_dropped():
    class Fake:
        def post(self, *a, **k):
            class R:
                def raise_for_status(self): pass
                def json(self):
                    return {'choices': [{'message': {'content': '{"issues": [{"quote": "not here", "problem": "x"}]}'}}]}
            return R()
    assert pr.ask('A correct sentence.', Fake()) == []


def test_cases_file_is_balanced():
    import json
    cases = json.loads((HERE / 'eval' / 'cases.json').read_text(encoding='utf-8'))['cases']
    assert sum(c['error'] for c in cases) == 30
    assert sum(not c['error'] for c in cases) == 30
