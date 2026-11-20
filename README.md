# AI projects

[![tests](https://github.com/At0591/ai-portfolio/actions/workflows/tests.yml/badge.svg)](https://github.com/At0591/ai-portfolio/actions/workflows/tests.yml)

These are things I have built while moving from sales and operations into AI automation. Most of them come from businesses I run. Each one solves a problem I had myself.

| Project | What it does | Status |
|---|---|---|
| [PixelPolish sales agent](01-ai-sales-agent/) | Researches hotels and Airbnb hosts online and scores how well each fits. Drafts outreach emails for me to review | Working |
| [Dum Biryani Rasoi menu assistant](02-dbr-menu-assistant/) | Answers menu questions from my cloud kitchen's real menu with RAG and adds up orders for WhatsApp. Runs behind a webhook in n8n | Working |
| [Writing checks](03-writing-checks/) | Checks my public writing with house rules in Vale, a local LanguageTool server and an AI proofreader that only flags mistakes. A test of 60 sentences measures how well they work | Working |
| Document Q&A bot | Finds answers in a company's own documents and shows the sources, behind a small API | Planned |
| n8n automations | CRM, email and invoice workflows with AI steps that a small business can reuse | Planned |
| [KindRise](https://github.com/At0591/morning-ritual) | My gentle alarm app for Android (React Native, Expo and a native Kotlin alarm module); code in its own repo | Before launch |

## Setup

Python 3.10 or newer.

```bash
py -m venv %USERPROFILE%\.venvs\ai-portfolio
%USERPROFILE%\.venvs\ai-portfolio\Scripts\pip install -r 01-ai-sales-agent\requirements.txt
%USERPROFILE%\.venvs\ai-portfolio\Scripts\pip install -r 02-dbr-menu-assistant\requirements.txt
```

The projects use [OpenRouter](https://openrouter.ai/keys) for the LLM. Set `OPENROUTER_API_KEY` as an environment variable, or put it in a `.env` file inside the project folder. The `.env` file is listed in `.gitignore`, so it will not be committed.
