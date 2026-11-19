"""Refresh the menu knowledge base from the public restaurant website.

The menu page at dumbiryanirasoi.in carries the full dish list (price, veg or non-veg, spice level,
portion) inside the page data, and the restaurant details (hours, address, delivery areas, app
links) as schema.org JSON-LD. This script reads both and writes clean JSON into knowledge/.
No LLM is involved.

Usage:
    python scrape_menu.py            # fetch the live site and rewrite knowledge/menu.json
    python scrape_menu.py --check    # fetch and report changes without writing
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import httpx

HERE = Path(__file__).parent
KNOWLEDGE = HERE / "knowledge"
MENU_URL = "https://www.dumbiryanirasoi.in/menu"
USER_AGENT = "Mozilla/5.0 (compatible; DBRMenuAssistant/1.0)"

DIET = {"veg": "veg", "nonveg": "non-veg", "egg": "egg"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def extract_items(html: str) -> list[dict]:
    """Pull the dish list out of the Next.js page payload, where quotes are escaped as \\"."""
    text = html.replace('\\"', '"')
    start = text.find('"items":[{"category"')
    if start == -1:
        raise ValueError("menu data not found on the page; the site layout may have changed")
    items, _ = json.JSONDecoder().raw_decode(text[start + len('"items":'):])
    return items


def extract_restaurant(html: str) -> dict:
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        data = json.loads(block)
        if data.get("@type") == "Restaurant":
            return data
    raise ValueError("restaurant details not found on the page")


def clean_item(raw: dict) -> dict:
    serving = (raw.get("serving") or "").replace("•", ",").replace(" ,", ",").strip()
    price = raw.get("price")
    return {
        "id": slug(raw["name"]),
        "name": raw["name"],
        "category": raw["category"],
        "price_inr": price if isinstance(price, (int, float)) else None,
        # A custom quote has no fixed dish, so its diet depends on what the customer asks for.
        "diet": "varies" if price is None else DIET.get(raw.get("veg"), "unknown"),
        "spice": raw.get("spice") if isinstance(raw.get("spice"), int) else None,
        "portion": serving,
        "description": raw.get("description", "").strip(),
        "bestseller": raw.get("bestseller") is True,
        "pre_order_only": "Pre-Order" in raw["category"] or "Pre-order" in serving,
    }


def clean_restaurant(data: dict) -> dict:
    links = {}
    for url in data.get("sameAs", []):
        for name in ("zomato", "swiggy", "magicpin"):
            if name in url:
                links[name] = url
    phone = data.get("telephone", "")
    hours = [f"{h['opens']} to {h['closes']}" for h in data.get("openingHoursSpecification", [])]
    addr = data.get("address", {})
    return {
        "name": data.get("name"),
        "website": data.get("url"),
        "phone": phone,
        "whatsapp": f"https://wa.me/{phone.lstrip('+')}" if phone else None,
        "order_links": links,
        "address": ", ".join(filter(None, [addr.get("streetAddress"), addr.get("addressLocality"),
                                            addr.get("postalCode")])),
        "daily_hours_24h": hours,
        "areas_served": data.get("areaServed", []),
        "cuisine": data.get("servesCuisine", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report changes, don't write files")
    args = parser.parse_args()

    try:
        r = httpx.get(MENU_URL, timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"Could not fetch {MENU_URL}: {e}")
        return 1

    items = [clean_item(i) for i in extract_items(r.text)]
    restaurant = clean_restaurant(extract_restaurant(r.text))
    menu = {"source": MENU_URL, "checked_on": date.today().isoformat(),
            "note": "Direct-order prices. App prices, fees and availability may differ.",
            "restaurant": restaurant, "items": items}

    path = KNOWLEDGE / "menu.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": []}
    old_prices = {i["id"]: i["price_inr"] for i in old["items"]}
    new_prices = {i["id"]: i["price_inr"] for i in items}
    for k in sorted(new_prices.keys() - old_prices.keys()):
        print(f"  new dish: {k}")
    for k in sorted(old_prices.keys() - new_prices.keys()):
        print(f"  removed: {k}")
    for k in sorted(new_prices.keys() & old_prices.keys()):
        if new_prices[k] != old_prices[k]:
            print(f"  price change: {k} {old_prices[k]} -> {new_prices[k]}")
    print(f"{len(items)} dishes found")

    if not args.check:
        KNOWLEDGE.mkdir(exist_ok=True)
        path.write_text(json.dumps(menu, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"Wrote {path.relative_to(HERE)}. Rebuild the index with: python assistant.py --rebuild")
    return 0


if __name__ == "__main__":
    sys.exit(main())
