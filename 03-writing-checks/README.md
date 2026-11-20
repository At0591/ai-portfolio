# Writing checks

My website, CV and business websites all pass these checks before I publish them. This folder holds the checks and a test that measures how well they work.

## Results

The test has 30 sentences with 1 planted mistake each and 30 correct sentences taken from my own pages. Test runs on 20 Nov 2026:

| Checks | Mistakes caught | Correct sentences flagged |
|---|---|---|
| Vale and LanguageTool | 27 of 30 | 0 of 30 |
| With the AI proofreader, run 1 | 29 of 30 | 1 of 30 |
| With the AI proofreader, run 2 | 30 of 30 | 1 of 30 |

The rules missed 3 grammar mistakes: "The assistant answer", "there photos" and "60 account". The AI proofreader caught all 3 in run 2 and 2 of them in run 1.

The flagged correct sentence came from my portfolio: "a kitchen with 13,325 orders since October 2025". The point was fair, so I rewrote the line on the site. The test sentence stayed the same, so the score stays honest.

I wrote the 60 test sentences myself. They show that the checks work on my kind of writing, not on all writing.

## How it works

1. **Vale** applies the house rules in `styles/`. They cover British spelling, sentence case in headings and plain words from the GOV.UK guidance. They also ban contractions, dashes, ampersands and the few signs of AI writing a reader notices.
2. **LanguageTool** checks grammar and spelling (`grammar.py`). It runs as a server on my own computer, so no text leaves it.
3. **The AI proofreader** (`proofread.py`) only points out mistakes. It never rewrites anything. A model from a different company to the one that drafts my text reads the text 3 times. A mistake counts when 2 of the 3 readings agree and the quoted words really appear in the text.
4. **The sentence case check** (`sentence_case.py`) covers what Vale does not read: page titles, buttons, links, form labels and email subject lines. On my business site it found 6 title-case slips, which are now fixed.

## Run it

You need Python 3.10 or newer, [Vale](https://vale.sh), and [LanguageTool](https://languagetool.org/download/) 6.6 with Java 17 or newer. The proofreader reads its key from the `OPENROUTER_API_KEY` environment variable.

```bash
pip install -r requirements.txt
vale sync
python -m pytest -q
python eval/run_eval.py
python eval/run_eval.py --llm
python sentence_case.py --text "Book A Free Call"
python proofread.py --text "Owners check there photos."
```

The grammar check starts LanguageTool from the folder in `LT_DIR` (by default `~/languagetool/LanguageTool-6.6`). Set `VALE` or `JAVA` if those programs are not on your path.

## Files

| File | What it does |
|---|---|
| `styles/` | Vale house rules and the list of accepted names |
| `grammar.py` | LanguageTool on a local server, with the house exceptions |
| `proofread.py` | The AI proofreader, which flags and never rewrites |
| `sentence_case.py` | Sentence case for titles, buttons, links and labels |
| `eval/cases.json` | The 60 test sentences |
| `eval/run_eval.py` | Runs every check on the test set and writes `eval/results.md` |
| `test_checks.py` | 8 offline tests for the sentence case rules and the proofreader's vote |

## Limits

* The test set is small, and I wrote it myself.
* The AI proofreader can give a different answer from one run to the next, which is why it votes over 3 readings.
* The sentence case check reads a business name in an email subject line as title case. Add the name to the list of accepted names first.
