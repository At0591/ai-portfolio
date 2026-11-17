# AI projects

[![tests](https://github.com/At0591/ai-portfolio/actions/workflows/tests.yml/badge.svg)](https://github.com/At0591/ai-portfolio/actions/workflows/tests.yml)

These are things I've built while moving from sales and operations into AI automation. Most of them come from businesses I run, so each one solves a problem I actually had.

| Project | What it does | Status |
|---|---|---|
| [PixelPolish sales agent](01-ai-sales-agent/) | Researches hotels and Airbnb hosts online, scores how well each fits, and drafts outreach emails for me to review | Working |
| Dum Biryani Rasoi ordering assistant | Answers menu questions and takes orders over WhatsApp, using the restaurant's real menu | Next |
| Document Q&A bot | Answers questions from a company's own documents, with sources, behind a small API | Planned |
| n8n automations | CRM, email and invoice workflows with AI steps that a small business can reuse | Planned |
| Morning Ritual | My React Native habit app, rebuilt with the source code public | Later |

## Setup

Python 3.10 or newer.

```bash
py -m venv %USERPROFILE%\.venvs\ai-portfolio
%USERPROFILE%\.venvs\ai-portfolio\Scripts\pip install -r 01-ai-sales-agent\requirements.txt
```

The projects use [OpenRouter](https://openrouter.ai/keys) for the LLM. Set `OPENROUTER_API_KEY` as an environment variable, or put it in a `.env` file inside the project folder. `.env` is in `.gitignore`, so it won't be committed.
