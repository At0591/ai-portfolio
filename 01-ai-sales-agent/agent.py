"""AI Sales Agent for PixelPolish, runnable for free.

For each prospect in a CSV, the agent:
  1. Researches the business with free tools: DuckDuckGo search + reading the prospect's website.
  2. Sends the research to an LLM via OpenRouter (free models by default) and gets back a
     fit score and a personalised cold email as JSON, validated with Pydantic.
  3. Writes everything to outputs/ for a human to review. It never sends email itself.

Usage:
    python agent.py prospects.csv
    python agent.py prospects.csv --limit 3
    python agent.py prospects.csv --research-only     # no API key needed
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from dotenv import load_dotenv
from openai import (APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, OpenAI,
                    RateLimitError)
from pydantic import BaseModel, Field, ValidationError

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

# Any OpenAI-compatible provider works: change these in .env.
BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
MODEL = os.getenv("LLM_MODEL", "openrouter/free")  # routes to whichever free model is available
API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY")

OFFER = """\
PixelPolish (pixelpolish.art) edits listing photos for Airbnb / Vrbo / Booking.com hosts,
boutique hotels, coworking spaces and real-estate agents: relighting, clutter and distraction
removal, day-to-twilight conversion, virtual staging, and short video walkthroughs.
Delivery in 24-48 hours, from $49. Prospects can send 3 photos for a free sample, no card needed.
Truth-in-editing policy: room structure and size are never changed."""

USER_AGENT = "Mozilla/5.0 (compatible; PortfolioResearchBot/1.0)"


# ---------------------------------------------------------------- research (free, no LLM)

def web_search(query: str, max_results: int = 5, attempts: int = 3) -> list[dict]:
    # Free search engines throttle bursts and sometimes answer "no results" when they do,
    # so retry with a growing pause. Research should degrade, never crash the run.
    for attempt in range(attempts):
        try:
            return [
                {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
                for r in DDGS().text(query, max_results=max_results)
            ]
        except Exception as e:
            if attempt == attempts - 1:
                print(f"    search failed after {attempts} tries: {e}")
                return []
            time.sleep(3 * (attempt + 1))
    return []


def fetch_page_text(url: str, max_chars: int = 4000) -> str:
    if not url or "example.com" in url:
        return ""
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"    could not read {url}: {e.__class__.__name__}")
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    images = len(soup.find_all("img"))
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return f"[{images} images on page] {text[:max_chars]}"


def gather_research(prospect: dict) -> str:
    name, city = prospect.get("business_name", ""), prospect.get("city", "")
    parts = []
    site = fetch_page_text(prospect.get("website", ""))
    if site:
        parts.append(f"WEBSITE ({prospect['website']}):\n{site}")
    for query in (f"{name} {city}", f"{name} {city} reviews photos airbnb OR booking.com"):
        for r in web_search(query):
            parts.append(f"SEARCH RESULT: {r['title']} | {r['url']}\n{r['snippet']}")
        time.sleep(1.5)  # be polite to the free search engine
    return "\n\n".join(parts) or "No research found."


# ---------------------------------------------------------------- drafting (one LLM call)

class Outreach(BaseModel):
    research_matches_business: bool = Field(
        description="True only if the research clearly describes THIS business (name and place match). "
        "Search engines return unrelated pages for unknown names; if most results are about something else, false."
    )
    research_summary: list[str] = Field(description="3-6 factual bullets drawn only from the research")
    fit_score: int = Field(ge=1, le=10, description="How likely this business benefits from PixelPolish")
    fit_reason: str
    personalization_hooks: list[str] = Field(description="Specific, verifiable facts used in the email")
    subject: str
    email_body: str = Field(description="Under 120 words, plain text, ends with the free-sample offer")
    follow_up: str = Field(description="Short follow-up for 3-4 days later if no reply")


STYLE = """\
How the email should read:
- Like a short note from one small-business owner to another. Plain words, short sentences.
- Open with one specific, true detail from the research, not with who we are.
- Connect that detail to one concrete thing PixelPolish would do for their photos.
- One offer only: send 3 photos for a free sample. No pressure, no fake urgency.
- 60 to 110 words. No exclamation marks, no em dashes, no emojis.
- Never use: elevate, stunning, seamless, leverage, unlock, game-changer, take it to the next level,
  I hope this email finds you well, I wanted to reach out, in today's competitive market.
- Greet the contact by first name if given, otherwise "Hello," with no name.
- Sign off as "Akshay, PixelPolish".

- Pick the ONE PixelPolish service that best matches the stated facts (e.g. many room types: consistent
  look across rooms; a notable exterior: twilight version; empty or new spaces: virtual staging).
  Don't list every service.
- Vary sentence structure between businesses; no fixed template.

Bad example (never write like this):
  Subject: Elevate Your Property's Visual Appeal!
  I hope this email finds you well! In today's competitive market, stunning visuals are key to
  unlocking more bookings. Our cutting-edge editing will take your listing to the next level!"""

SYSTEM = (
    "You are a careful B2B sales researcher and copywriter for PixelPolish, a two-person photo-editing studio. "
    "First decide whether the research is really about this specific business; web search often returns "
    "unrelated pages. If it is not, set research_matches_business to false, fit_score to 1, and keep the other "
    "fields short. Never infer facts from the business category alone. "
    "Use ONLY facts from the research provided; if something is not in it, do not claim it. Never claim you "
    "saw their photos unless the research describes them, and don't guess at problems they 'probably' have "
    "(e.g. 'old buildings often have dark corners'); connect the offer to a stated fact instead. "
    "Score fit honestly: 8-10 only with clear evidence of many rooms or listings and photo-dependent bookings; "
    "if the fit is weak, say so in fit_reason and keep the email modest.\n\n"
    f"Offer:\n{OFFER}\n\n{STYLE}\n\n"
    "Reply with a single JSON object, no markdown, matching this JSON schema:\n"
    + json.dumps(Outreach.model_json_schema())
)

BANNED = ["elevate", "stunning", "seamless", "leverage", "unlock", "game-changer", "next level",
          "hope this email finds you", "wanted to reach out", "competitive market", "cutting-edge"]


def quality_problems(o: Outreach, prospect: dict) -> list[str]:
    """Cheap code checks for the slop patterns the prompt asks the model to avoid."""
    text = f"{o.subject}\n{o.email_body}\n{o.follow_up}"
    words = len(o.email_body.split())
    problems = []
    if not 50 <= words <= 130:
        problems.append(f"email body is {words} words; keep it between 60 and 110")
    if "!" in text:
        problems.append("remove exclamation marks")
    if "—" in text:
        problems.append("replace em dashes with commas or full stops")
    found = [b for b in BANNED if b in text.lower()]
    if found:
        problems.append("remove these phrases: " + ", ".join(found))
    if copied_from_example(o.email_body):
        problems.append("you copied sentences from the instructions; write your own wording for this business")
    if o.research_matches_business and not uses_a_hook(o):
        problems.append("the email must mention at least one specific fact from personalization_hooks")
    return problems


def _ngrams(text: str, n: int = 6) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


# Models copy whatever is in the prompt. Catch emails that reuse the offer or style text verbatim,
# since every email would then share the same sentences (reads as a template, looks like spam).
PROMPT_NGRAMS = _ngrams(OFFER + "\n" + STYLE)


def copied_from_example(body: str) -> bool:
    return len(_ngrams(body) & PROMPT_NGRAMS) >= 2


# Words too generic to prove the email is personalised.
GENERIC = {"hotel", "hotels", "rooms", "photos", "photo", "property", "listing", "listings", "guests",
           "booking", "airbnb", "their", "which", "with", "from", "about", "boutique", "luxury"}


def uses_a_hook(o: Outreach) -> bool:
    """True if a distinctive word or number from the research hooks appears in the email."""
    body = o.email_body.lower()
    hook_words = {w for h in o.personalization_hooks for w in re.findall(r"\b[a-z0-9]{4,}\b", h.lower())}
    return any(w in body for w in hook_words - GENERIC)


def extract_json(text: str) -> str:
    """Free models sometimes wrap JSON in ``` fences or add a sentence; keep the object only."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


TOKENS = {"input": 0, "output": 0, "calls": 0}


def draft(client: OpenAI, prospect: dict, research: str, model: str = MODEL) -> tuple[Outreach, list[str]]:
    """Returns the draft plus any quality problems that survived one rewrite (shown to the reviewer)."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Prospect:\n{json.dumps(prospect, ensure_ascii=False)}\n\nResearch:\n{research}"},
    ]
    result, problems = None, []
    for attempt in range(2):  # at most one rewrite, to keep cost and free-tier usage down
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        if response.usage:
            TOKENS["input"] += response.usage.prompt_tokens or 0
            TOKENS["output"] += response.usage.completion_tokens or 0
        TOKENS["calls"] += 1
        text = response.choices[0].message.content or ""
        try:
            result = Outreach.model_validate_json(extract_json(text))
        except ValidationError as e:
            if attempt == 1:
                raise
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That JSON was invalid: {e}. Reply with corrected JSON only."},
            ]
            continue
        problems = quality_problems(result, prospect)
        if not problems or not result.research_matches_business:
            return result, []
        if attempt == 0:
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "Rewrite the JSON fixing these problems: " + "; ".join(problems)},
            ]
    return result, problems


# ---------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", type=Path, help="CSV with columns: business_name, website, city, segment, contact_name")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N prospects")
    parser.add_argument("--research-only", action="store_true", help="Skip the LLM; just save the research")
    args = parser.parse_args()

    # utf-8-sig: Excel / Windows save CSVs with a BOM that would otherwise corrupt the first column name
    with args.csv_path.open(newline="", encoding="utf-8-sig") as f:
        prospects = [row for row in csv.DictReader(f) if any((v or "").strip() for v in row.values())]
    prospects = prospects[: args.limit] if args.limit else prospects
    if not prospects:
        print("No prospects found in the CSV.")
        return 1
    if not args.research_only and not API_KEY:
        print("No API key: put OPENROUTER_API_KEY in .env (see README), or run with --research-only.")
        return 1

    # Free models can queue for minutes; cap each call so one slow model can't stall the batch.
    client = None if args.research_only else OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=120, max_retries=1)
    out_dir = HERE / "outputs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    rows, report = [], [f"# Outreach drafts — {stamp} (model: {MODEL})\n", "_Review every email before sending._\n"]

    for i, prospect in enumerate(prospects, 1):
        name = prospect.get("business_name") or f"prospect {i}"
        print(f"[{i}/{len(prospects)}] {name}: researching...", flush=True)
        research = gather_research(prospect)
        if research == "No research found." and not args.research_only:
            print("  skipped: nothing found online, so no grounded email is possible (check the website column)")
            continue
        if args.research_only:
            report.append(f"\n## {name}\n\n```\n{research}\n```\n")
            continue

        print(f"[{i}/{len(prospects)}] {name}: drafting...", flush=True)
        try:
            result, flags = draft(client, prospect, research)
        except AuthenticationError:
            print("Authentication failed: check OPENROUTER_API_KEY in .env.")
            return 1
        except RateLimitError:
            print("Rate limit reached at the provider. Saving what's done; re-run later for the rest.")
            break
        except APITimeoutError:  # subclass of APIConnectionError, so it must come first
            print("  skipped: the model took over 2 minutes (busy free model?); re-run this one later")
            continue
        except APIConnectionError:
            print("Network error: check your internet connection.")
            return 1
        except (APIStatusError, ValidationError) as e:
            print(f"  skipped: {str(e)[:200]}")
            continue

        if not result.research_matches_business:
            print("  skipped: research didn't match this business (check the name and website)")
            report.append(f"\n## {name} — skipped\n\nThe search results were about something else. Check the name and website.\n")
            continue
        rows.append({**prospect, **result.model_dump(),
                     "research_summary": " | ".join(result.research_summary),
                     "personalization_hooks": " | ".join(result.personalization_hooks),
                     "quality_flags": " | ".join(flags)})
        if flags:
            print("  check this one: " + "; ".join(flags))
        report += [
            f"\n## {name} — fit {result.fit_score}/10\n",
            *([f"**Check before sending:** {'; '.join(flags)}\n"] if flags else []),
            f"**Why:** {result.fit_reason}\n",
            "**Research:**\n" + "\n".join(f"- {b}" for b in result.research_summary) + "\n",
            f"**Subject:** {result.subject}\n",
            f"```\n{result.email_body}\n```\n",
            f"**Follow-up:** {result.follow_up}\n",
        ]

    if TOKENS["calls"]:
        print(f"\nModel {MODEL}: {TOKENS['calls']} calls, {TOKENS['input']:,} input + {TOKENS['output']:,} output tokens")
        report.append(f"\n---\n{TOKENS['calls']} model calls, {TOKENS['input']:,} input + {TOKENS['output']:,} output tokens.\n")
    md_out = out_dir / f"outreach-{stamp}.md"
    md_out.write_text("\n".join(report), encoding="utf-8")
    print(f"\nSaved: {md_out}")
    if rows:
        rows.sort(key=lambda r: r["fit_score"], reverse=True)
        csv_out = out_dir / f"outreach-{stamp}.csv"
        with csv_out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Saved: {csv_out}  ({len(rows)} drafts, best fit first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
