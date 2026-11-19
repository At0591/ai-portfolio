"""Knowledge base and retrieval for the Dum Biryani Rasoi menu assistant.

Turns knowledge/menu.json (one document per dish) and knowledge/kitchen.md (one document per
section) into short text documents, embeds them with a small local model (BAAI/bge-small-en-v1.5
through fastembed, no API key or cost) and searches them with a FAISS index.

List questions ("anything veg and not spicy", "biryani for a party") need the whole menu rather
than the top few matches, so menu_filter() answers those with plain code and adds the result as
one extra document.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

HERE = Path(__file__).parent
KNOWLEDGE = HERE / "knowledge"
CACHE = HERE / ".cache"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

SPICE = {0: "not spicy", 1: "mild", 2: "medium", 3: "hot"}
# Plain words customers use for a menu section that the dish text doesn't otherwise contain.
SECTION_HINTS = {
    "Bulk Orders (Pre-Order Only)": "For parties, events and large groups.",
    "Desserts": "Dessert, something sweet after the meal.",
    "Beverages": "Cold drink.",
    "Extras": "Side dish.",
}
DIET_LABEL = {"veg": "Vegetarian", "non-veg": "Non-vegetarian", "egg": "Contains egg", "varies": "Depends on the order"}


@dataclass
class Doc:
    id: str
    kind: str  # "dish" or "info"
    title: str
    text: str
    item: dict | None = field(default=None, repr=False)


def load_menu(path: Path = KNOWLEDGE / "menu.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dish_text(item: dict) -> str:
    price = f"₹{item['price_inr']}" if item["price_inr"] is not None else "price on request (custom quote)"
    parts = [
        f"{item['name']}.",
        f"Menu section: {item['category']}.",
        f"Price: {price} (direct order).",
        f"{DIET_LABEL.get(item['diet'], item['diet'])}.",
    ]
    if item["spice"] is not None:
        parts.append(f"Spice level {item['spice']} of 3 ({SPICE[item['spice']]}).")
    if item["portion"]:
        parts.append(f"Portion: {item['portion']}.")
    if item["bestseller"]:
        parts.append("Bestseller.")
    if item["pre_order_only"]:
        parts.append("Pre-order only, arranged in advance on WhatsApp.")
    if item["category"] in SECTION_HINTS:
        parts.append(SECTION_HINTS[item["category"]])
    parts.append(item["description"])
    return " ".join(parts)


def load_documents(menu: dict | None = None, kitchen_path: Path = KNOWLEDGE / "kitchen.md") -> list[Doc]:
    menu = menu or load_menu()
    docs = [Doc(id=i["id"], kind="dish", title=i["name"], text=dish_text(i), item=i) for i in menu["items"]]
    # Split the kitchen notes on "## " headings: one section, one document.
    for block in re.split(r"^## ", kitchen_path.read_text(encoding="utf-8"), flags=re.M)[1:]:
        title, _, body = block.partition("\n")
        body = " ".join(body.split())
        docs.append(Doc(id="info-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
                        kind="info", title=title.strip(), text=f"{title.strip()}. {body}"))
    return docs


# ------------------------------------------------------------------ embeddings

Embedder = Callable[[list[str], bool], np.ndarray]  # (texts, is_query) -> unit vectors, one per row


def fastembed_embedder() -> Embedder:
    """Local embedding model. The first run downloads about 130 MB to the fastembed cache."""
    from fastembed import TextEmbedding  # imported here so tests don't need the model

    cache = os.getenv("FASTEMBED_CACHE_PATH", str(Path.home() / ".cache" / "fastembed"))
    model = TextEmbedding(EMBED_MODEL, cache_dir=cache)

    def embed(texts: list[str], is_query: bool) -> np.ndarray:
        vectors = model.query_embed(texts) if is_query else model.passage_embed(texts)
        return normalise(np.array(list(vectors), dtype="float32"))

    return embed


def normalise(m: np.ndarray) -> np.ndarray:
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-12, None)


# ------------------------------------------------------------------ list questions

def menu_filter(question: str, items: list[dict]) -> Doc | None:
    """Answer list questions ("veg and not spicy", "under ₹150", "for a party") with plain code.

    Top-k search only returns a few dishes, so a question about every veg dish would miss most of
    them. When the question names a diet, spice level, group size or budget, this adds one document
    listing every matching dish.
    """
    q = question.lower()
    rules, label = [], []
    if re.search(r"\bnon[- ]?veg|chicken or mutton|\bmeat\b", q):
        rules.append(lambda i: i["diet"] == "non-veg"); label.append("non-vegetarian")
    elif re.search(r"\b(veg|vegetarian|veggie|pure veg)\b", q):
        rules.append(lambda i: i["diet"] == "veg"); label.append("vegetarian")
    elif re.search(r"\begg (dishes|options|items)|eggetarian|anything with eggs?\b", q):
        rules.append(lambda i: i["diet"] == "egg"); label.append("egg")
    if re.search(r"not (too )?spicy|less spicy|mild|no spice|kids?|children|bland", q):
        rules.append(lambda i: (i["spice"] or 0) <= 1); label.append("spice level 0 or 1")
    elif re.search(r"\b(very spicy|spiciest|hot|extra spicy|most spicy)\b", q):
        rules.append(lambda i: (i["spice"] or 0) >= 3); label.append("spice level 3")
    if re.search(r"\bparty|parties|\bgroup\b|\bbulk\b|\b([5-9]|\d{2,}) (people|persons|guests|pax)|\b\d+ ?kg\b", q):
        rules.append(lambda i: i["pre_order_only"]); label.append("sold by the kilogram for groups (pre-order)")
    budget = re.search(r"(?:under|below|less than|within|upto|up to|max)\s*(?:rs\.?|₹|inr)?\s*(\d{2,4})", q)
    if budget:
        limit = int(budget.group(1))
        rules.append(lambda i: i["price_inr"] is not None and i["price_inr"] <= limit)
        label.append(f"₹{limit} or less")
    if not rules:
        return None
    matches = [i for i in items if all(r(i) for r in rules) and i["category"] != "Beverages"]
    lines = [f"- {i['name']} (₹{i['price_inr']}, {i['category']}, spice {i['spice']})" for i in matches[:30]]
    body = "\n".join(lines) if lines else "No dishes on the menu match."
    return Doc(id="filter", kind="info", title="Menu filter",
               text=f"Every dish on the menu that is {', '.join(label)} ({len(matches)} found):\n{body}")


# ------------------------------------------------------------------ index

@dataclass
class Hit:
    doc: Doc
    score: float


class MenuIndex:
    def __init__(self, docs: list[Doc], embed: Embedder, use_cache: bool = True):
        import faiss

        self.docs = docs
        self.embed = embed
        vectors = self._doc_vectors(use_cache)
        self.index = faiss.IndexFlatIP(vectors.shape[1])  # inner product of unit vectors = cosine
        self.index.add(vectors)

    def _doc_vectors(self, use_cache: bool) -> np.ndarray:
        digest = hashlib.sha256((EMBED_MODEL + "".join(d.text for d in self.docs)).encode()).hexdigest()[:16]
        path = CACHE / f"vectors-{digest}.npy"
        if use_cache and path.exists():
            return np.load(path)
        vectors = self.embed([d.text for d in self.docs], False)
        if use_cache:
            CACHE.mkdir(exist_ok=True)
            np.save(path, vectors)
        return vectors

    def search(self, question: str, k: int = 8, min_info: int = 3) -> list[Hit]:
        """Top k documents, always including the best min_info kitchen sections.

        A question with two parts ("do you deliver to Versova, and what's a good thali?") would
        otherwise fill every slot with dishes and lose the delivery section.
        """
        scores, ids = self.index.search(self.embed([question], True), len(self.docs))  # ~90 docs
        ranked = [Hit(self.docs[i], float(s)) for s, i in zip(scores[0], ids[0])]
        info = [h for h in ranked if h.doc.kind == "info"][:min_info]
        rest = [h for h in ranked if h not in info][:max(k - len(info), 0)]
        return sorted(info + rest, key=lambda h: h.score, reverse=True)


def build_index(use_cache: bool = True) -> MenuIndex:
    return MenuIndex(load_documents(), fastembed_embedder(), use_cache)
