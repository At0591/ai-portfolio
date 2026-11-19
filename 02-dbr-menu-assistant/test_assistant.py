"""Tests that run without the network, the embedding model or an API key.

A tiny word-hashing embedder stands in for the real model and a fake client stands in for the
LLM, so the tests check the code around the model: knowledge loading, list filters, the price
and dish checks, order totals, the retry and fallback, the API and the evaluation scorer.

Run: python -m pytest -q
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import assistant
import evaluate
import rag
from assistant import Assistant, AssistantError, OrderLine, Reply

HERE = Path(__file__).parent


def fake_embed(texts: list[str], is_query: bool) -> np.ndarray:
    """Bag of words hashed into 256 dimensions: similar wording gives similar vectors."""
    m = np.zeros((len(texts), 256), dtype="float32")
    for row, text in enumerate(texts):
        for w in rag.re.findall(r"[a-z0-9]+", text.lower()):
            m[row, int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
    return rag.normalise(m + 1e-6)


@pytest.fixture(scope="module")
def index():
    return rag.MenuIndex(rag.load_documents(), fake_embed, use_cache=False)


class FakeClient:
    """Returns the queued replies in order, like the OpenAI client would."""

    def __init__(self, *replies: str, finish: str = "stop"):
        self.replies = list(replies)
        self.calls = 0
        self.finish = finish
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        content = self.replies.pop(0)
        usage = SimpleNamespace(cost=0.0003)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                                        finish_reason=self.finish)], usage=usage)


def reply_json(**fields) -> str:
    base = dict(in_scope=True, answer="Mutton Dum Biryani - Half is ₹299.", cited_items=["Mutton Dum Biryani - Half"],
                order_items=[])
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


def make_bot(index, *replies, **kw) -> tuple[Assistant, FakeClient]:
    client = FakeClient(*replies, **kw)
    return Assistant(index=index, client=client), client


# ------------------------------------------------------------------ knowledge base

def test_menu_has_real_dishes_with_prices_and_diet():
    menu = rag.load_menu()
    names = {i["name"]: i for i in menu["items"]}
    assert len(names) >= 70
    assert names["Mutton Dum Biryani - Half"]["price_inr"] == 299
    assert names["Paneer Dum Biryani"]["diet"] == "veg"
    assert names["Egg Dum Biryani"]["diet"] == "egg"
    assert set(menu["restaurant"]["order_links"]) == {"zomato", "swiggy", "magicpin"}


def test_documents_cover_dishes_and_kitchen_sections():
    docs = rag.load_documents()
    titles = {d.title for d in docs}
    assert {"Hours", "Meal plans", "Address and delivery area"} <= titles
    dish = next(d for d in docs if d.title == "Chicken Kosha")
    assert "₹219" in dish.text and "hot" in dish.text and "Non-vegetarian" in dish.text


def test_search_finds_the_named_dish(index):
    titles = [h.doc.title for h in index.search("Shahi Paneer price", 5)]
    assert "Shahi Paneer" in titles


# ------------------------------------------------------------------ list filter

def test_filter_veg_mild_under_budget():
    items = rag.load_menu()["items"]
    doc = rag.menu_filter("anything veg and not spicy under 150?", items)
    assert doc is not None
    assert "Dal Rice" in doc.text and "Deluxe Veg Thali" in doc.text
    assert "Chole Rice" not in doc.text          # spice level 2
    assert "Chicken" not in doc.text
    assert "Shahi Paneer" not in doc.text        # ₹249


def test_filter_party_lists_bulk_biryani():
    doc = rag.menu_filter("biryani for 12 people at a party", rag.load_menu()["items"])
    assert "Mutton Hyderabadi Dum Biryani (1kg)" in doc.text
    assert "Chicken Dum Biryani - Half" not in doc.text


def test_filter_skips_plain_questions():
    assert rag.menu_filter("what time do you open?", rag.load_menu()["items"]) is None


# ------------------------------------------------------------------ checks

def test_rupee_amounts():
    assert assistant.rupee_amounts("₹139, Rs. 2,499 and 80 rupees, not 5 km") == {139, 2499, 80}


def test_invented_dish_and_price_are_flagged(index):
    bot = Assistant(index=index, client=FakeClient())
    hits = bot.retrieve("mutton biryani half")
    bad = Reply(in_scope=True, answer="Butter Chicken is ₹199 and Mutton Dum Biryani - Half is ₹250.",
                cited_items=["Butter Chicken", "Mutton Dum Biryani - Half"])
    problems = " ".join(assistant.check_reply(bad, hits, bot.menu_names))
    assert '"Butter Chicken" is not a dish' in problems
    assert "₹199" in problems and "₹250" in problems


def test_links_in_answer_are_flagged(index):
    bot = Assistant(index=index, client=FakeClient())
    hits = bot.retrieve("mutton biryani half")
    r = Reply(in_scope=True, answer="Order at https://wa.me/123", cited_items=[])
    assert any("links" in p for p in assistant.check_reply(r, hits, bot.menu_names))


# ------------------------------------------------------------------ orders

def test_order_total_is_worked_out_in_code():
    names = {i["name"].lower(): i for i in rag.load_menu()["items"]}
    summary, total, notes = assistant.price_order(
        [OrderLine(name="Chicken Dum Biryani - Half", qty=2), OrderLine(name="raita", qty=1)], names)
    assert total == 288
    assert "2 x Chicken Dum Biryani - Half: ₹278" in summary and "₹288" in summary
    assert notes == []


def test_custom_quote_and_pre_order_notes():
    names = {i["name"].lower(): i for i in rag.load_menu()["items"]}
    summary, total, notes = assistant.price_order(
        [OrderLine(name="Custom Gravies (per Kg)", qty=1), OrderLine(name="Mutton Hyderabadi Dum Biryani (1kg)", qty=1)],
        names)
    assert total is None and "price on quote" in summary and "Food total" not in summary
    assert len(notes) == 2


def test_whatsapp_link_is_encoded():
    link = assistant.whatsapp_link({"whatsapp": "https://wa.me/919137461761"}, "1 x Raita: ₹10")
    assert link.startswith("https://wa.me/919137461761?text=Hello")
    assert " " not in link and "%E2%82%B910" in link


# ------------------------------------------------------------------ the assistant loop

def test_good_reply_gets_ordering_links(index):
    bot, client = make_bot(index, reply_json())
    a = bot.ask("How much is a half mutton biryani?")
    assert not a.fallback and client.calls == 1
    assert "₹299" in a.text and "zomato.com" in a.text and "wa.me" in a.text
    assert a.cost_usd == pytest.approx(0.0003)


def test_order_reply_gets_summary_and_prefilled_whatsapp(index):
    order = reply_json(answer="Noted, two half chicken biryanis.", cited_items=["Chicken Dum Biryani - Half"],
                       order_items=[{"name": "Chicken Dum Biryani - Half", "qty": 2}])
    bot, _ = make_bot(index, order)
    a = bot.ask("2 Chicken Dum Biryani - Half please")
    assert "Food total: ₹278" in a.text and "?text=" in a.whatsapp_link


def test_wrong_price_gets_one_rewrite(index):
    bot, client = make_bot(index, reply_json(answer="Mutton Dum Biryani - Half is ₹250."), reply_json())
    a = bot.ask("half mutton biryani price")
    assert client.calls == 2 and not a.fallback and "₹299" in a.text


def test_repeated_bad_reply_falls_back_to_the_kitchen(index):
    bad = reply_json(answer="Butter Chicken is ₹199.", cited_items=["Butter Chicken"])
    bot, client = make_bot(index, bad, bad)
    a = bot.ask("do you have butter chicken")
    assert client.calls == 2 and a.fallback
    assert a.text.startswith(assistant.FALLBACK) and "₹199" not in a.text


def test_cut_off_json_falls_back(index):
    bot, _ = make_bot(index, '{"in_scope": true, "answer": "We have', '{"answer": "x', finish="length")
    a = bot.ask("what rolls do you have")
    assert a.fallback and "not valid JSON" in a.problems[0]


def test_out_of_scope_reply_has_no_links(index):
    bot, _ = make_bot(index, reply_json(in_scope=False, answer="I can only help with the menu and orders.",
                                        cited_items=[]))
    a = bot.ask("write a poem about cricket")
    assert "zomato" not in a.text


def test_empty_message_needs_no_model_call(index):
    bot, client = make_bot(index)
    assert "Ask me" in bot.ask("   ").text and client.calls == 0


def test_missing_key_is_one_clear_error(index, monkeypatch):
    monkeypatch.setattr(assistant, "API_KEY", None)
    with pytest.raises(AssistantError, match="OPENROUTER_API_KEY"):
        Assistant(index=index).ask("hello")


# ------------------------------------------------------------------ API

def test_api_chat_and_token(index, monkeypatch):
    from fastapi.testclient import TestClient

    import api

    monkeypatch.setattr(api, "_bot", Assistant(index=index, client=FakeClient(reply_json(), reply_json())))
    client = TestClient(api.app)
    assert client.get("/health").json() == {"ok": True}
    r = client.post("/chat", json={"message": "half mutton biryani price", "sender": "test"})
    assert r.status_code == 200 and "₹299" in r.json()["reply"]

    monkeypatch.setattr(api, "API_TOKEN", "secret")
    assert client.post("/chat", json={"message": "hi"}).status_code == 401
    ok = client.post("/chat", json={"message": "half mutton biryani"}, headers={"X-API-Token": "secret"})
    assert ok.status_code == 200


# ------------------------------------------------------------------ evaluation set and workflow

def test_eval_questions_are_well_formed():
    cases = evaluate.load_cases()
    assert 20 <= len(cases) <= 30
    assert len({c["id"] for c in cases}) == len(cases)
    titles = {d.title for d in rag.load_documents()} | {"Menu filter"}
    for c in cases:
        assert c["question"]
        assert set(c.get("sources", [])) <= titles, c["id"]


def test_scorer_handles_alternatives_and_forbidden_phrases():
    a = assistant.Answer("q", "Dal Rice is ₹80. Order on Zomato.", None, ["Dal Rice"])
    assert evaluate.score({"must_include": ["Dal Rice|Rajma Rice", "80"], "sources": ["Dal Rice"]}, a) == []
    fails = evaluate.score({"must_include": ["Chole"], "must_not_include": ["zomato"], "sources": ["Hours"]}, a)
    assert len(fails) == 3


def test_n8n_workflow_calls_the_chat_endpoint():
    wf = json.loads((HERE / "n8n" / "dbr-menu-assistant.workflow.json").read_text(encoding="utf-8"))
    nodes = {n["name"]: n for n in wf["nodes"]}
    assert nodes["Incoming message"]["type"] == "n8n-nodes-base.webhook"
    assert nodes["Ask the assistant"]["parameters"]["url"].endswith("/chat")
    for source, outputs in wf["connections"].items():
        assert source in nodes
        for branch in outputs["main"]:
            assert all(link["node"] in nodes for link in branch)
