# PixelPolish sales agent

PixelPolish is a small photo-editing studio I run with my co-founder. We edit listing photos for Airbnb hosts, boutique hotels and coworking spaces. Finding clients meant hours of looking up each business, checking their photos and writing an email that didn't sound copy-pasted.

This script does that first pass for me. I give it a CSV of businesses. For each one it reads their website, runs two web searches, and asks an LLM to score how well they fit and draft a short email and follow-up. I read every draft before anything gets sent.

## What it does, step by step

1. Reads the business's website and runs two DuckDuckGo searches. Plain Python, no AI here.
2. Sends what it found to an LLM once, and asks for JSON: a short summary of the research, a fit score from 1 to 10 with a reason, the facts it used, a subject line, the email and a follow-up.
3. Checks the JSON against a Pydantic model, then checks the email itself: length, hype words, exclamation marks, whether it mentions a real fact about the business, and whether it copied sentences from the prompt. If anything fails, the model gets one rewrite. Whatever still fails is flagged in the output so I look at it first.
4. Saves a CSV sorted by fit score (I import this into Instantly) and a Markdown file I use for review.

If nothing useful turns up online, it skips the business instead of writing a vague email.

## Example

A real run on Abode Bombay, using a free model. It scored the fit 7 out of 10 and wrote:

> Subject: Photo editing for Abode Bombay's 25 rooms
>
> I came across Abode Bombay while looking at boutique properties in Colaba. The 1910 heritage building and the range of 25 rooms, from suites down to the simpler categories, stood out. That range is exactly where listing photos tend to drift apart in look and mood...

## Why I built it this way

I kept the AI to a single step. Searching and reading pages is ordinary code, so it's cheap, predictable and easy to debug. The model only does the part that needs judgement: deciding whether a business is a good fit and writing to them.

It runs on OpenRouter, so I can switch models by changing one line in `.env`. Free models work, and a cheap paid model gives more consistent writing for about a tenth of a cent per business.

The model is told to use only facts from the research. Each draft lists the facts it relied on, so I can check them quickly before sending.

## Choosing a model

`compare_models.py` researches each business once and gives the same research to several models, so only the model changes. I ran it on three hotels (17 Nov 2026). Bloomrooms Link Road was skipped by every model because the search results didn't match it.

| Model | Emails passing checks | Fit scores | Cost for the run | Time per email |
|---|---|---|---|---|
| openrouter/free | 2 of 2 | 7, 8 | $0 | 85s |
| anthropic/claude-haiku-5.5 | 2 of 2 | 6, 7 | $0.0049 | 10s |
| deepseek/deepseek-v4.1-flash | 2 of 2 | 8, 8 | $0.0053 | 16s |
| openai/gpt-6-luna | 2 of 2 | 9, 8 | $0.0032 | 13s |

All four passed the automatic checks, so I read the emails myself. I went with Claude Haiku 5.5. It picked out the most specific detail (a treehouse room at Ahilya by the Sea that the others ignored), it scored fit more cautiously, and it was the fastest. DeepSeek wrote well too but slipped in a guess about how the photos were taken. Two businesses is a small sample, so I'll rerun this on twenty.

## Running it

```bash
pip install -r requirements.txt
copy .env.example .env
python agent.py prospects.csv --limit 2
python agent.py prospects.csv --research-only
```

Put your OpenRouter key in `.env` (or set `OPENROUTER_API_KEY` as an environment variable). `--research-only` doesn't need a key.

## Tests

`test_agent.py` covers the parts that don't need the network or an API key: the quality checks (length, hype words, exclamation marks, em dashes, copied prompt text, whether the email uses a real fact), JSON extraction from chatty model replies, score bounds, and the "nothing found" path. They run on every push through GitHub Actions.

```bash
pip install pytest
python -m pytest -q
```

## Built with

Python, OpenRouter, ddgs (DuckDuckGo search), httpx, BeautifulSoup, Pydantic

## Still to do

- Run it on 20 real prospects and track how many reply
- Pull prospects from Apify (Google Maps and Airbnb) instead of typing them in
- Send approved drafts straight to Instantly through its API
- Rerun the model comparison on twenty businesses and score the emails blind
