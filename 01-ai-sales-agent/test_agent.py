"""Tests for the parts of the agent that don't need the network or an API key.

Run: python -m pytest -q
"""

import agent
from agent import Outreach, copied_from_example, extract_json, quality_problems, uses_a_hook


def make(**overrides) -> Outreach:
    fields = dict(
        research_matches_business=True,
        research_summary=["Abode Bombay is a boutique hotel in Colaba."],
        fit_score=7,
        fit_reason="25 rooms across several categories.",
        personalization_hooks=["Housed in a heritage building from 1910 in Colaba"],
        subject="Photo editing for Abode Bombay",
        email_body=(
            "Hello, I read that Abode Bombay sits in a 1910 building in Colaba with 25 rooms. "
            + "Keeping photos of every room type consistent is the kind of editing we do. " * 3
            + "Send three photos and I'll edit them for free. Akshay, PixelPolish"
        ),
        follow_up="Just checking whether you'd like the free sample.",
    )
    fields.update(overrides)
    return Outreach(**fields)


def test_good_email_passes():
    assert quality_problems(make(), {}) == []


def test_hype_and_exclamation_are_flagged():
    o = make(email_body=make().email_body + " Our cutting-edge edits will elevate your stunning rooms!")
    problems = " ".join(quality_problems(o, {}))
    assert "exclamation" in problems
    assert "cutting-edge" in problems and "elevate" in problems and "stunning" in problems


def test_length_limits():
    assert any("words" in p for p in quality_problems(make(email_body="Hello, 1910 Colaba. Short."), {}))
    assert any("words" in p for p in quality_problems(make(email_body="1910 Colaba " + "word " * 200), {}))


def test_em_dash_is_flagged():
    o = make(email_body=make().email_body.replace(" with 25 rooms", " — 25 rooms"))
    assert any("em dash" in p for p in quality_problems(o, {}))


def test_email_must_use_a_specific_fact():
    generic = make(email_body="Hello, your hotel has rooms and photos. " * 8 + "Send three photos for a free sample.")
    assert not uses_a_hook(generic)
    assert any("specific fact" in p for p in quality_problems(generic, {}))


def test_unmatched_research_skips_the_personalisation_check():
    o = make(research_matches_business=False, email_body="Hello, rooms and photos. " * 10)
    assert not any("specific fact" in p for p in quality_problems(o, {}))


def test_copying_prompt_text_is_detected():
    copied = ("Abode Bombay is in Colaba. Relighting, clutter and distraction removal, "
              "day-to-twilight conversion, virtual staging, and short video walkthroughs. "
              "Prospects can send 3 photos for a free sample, no card needed.")
    assert copied_from_example(copied)
    assert not copied_from_example(make().email_body)


def test_extract_json_strips_fences_and_chatter():
    assert extract_json('Sure! ```json\n{"a": 1}\n``` hope that helps') == '{"a": 1}'
    assert extract_json('{"a": {"b": 2}}') == '{"a": {"b": 2}}'


def test_fit_score_is_bounded():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        make(fit_score=11)


def test_gather_research_reports_nothing_found(monkeypatch):
    monkeypatch.setattr(agent, "web_search", lambda q, **k: [])
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    assert agent.gather_research({"business_name": "X", "city": "Y", "website": ""}) == "No research found."
