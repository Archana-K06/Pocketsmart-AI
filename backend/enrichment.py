"""Post-processing applied to every plan (Gemini or offline).

Adds what the SRS expects in each response: per-item ``search_terms`` and
``shopping_links`` for the right Indian platforms, a ``calculation_table``,
``total_budget`` and ``remaining_budget``.  Only platforms from the whitelist
below ever become links, so model output can never inject arbitrary URLs.
"""
import re
from typing import Any
from urllib.parse import quote_plus

PLATFORM_URLS: dict[str, str] = {
    "Amazon": "https://www.amazon.in/s?k={q}",
    "Flipkart": "https://www.flipkart.com/search?q={q}",
    "IKEA": "https://www.ikea.com/in/en/search/?q={q}",
    "Pepperfry": "https://www.pepperfry.com/catalogsearch/result/?q={q}",
    "Myntra": "https://www.myntra.com/{slug}?rawQuery={q}",
    "Ajio": "https://www.ajio.com/search/?text={q}",
    "Meesho": "https://www.meesho.com/search?q={q}",
    "Swiggy": "https://www.swiggy.com/search?query={q}",
    "Zomato": "https://www.zomato.com/search?q={q}",
    "BookMyShow": "https://in.bookmyshow.com/search?q={q}",
    "Google": "https://www.google.com/search?q={q}",
    "Booking": "https://www.booking.com/searchresults.html?ss={q}",
    "MakeMyTrip": "https://www.makemytrip.com/hotels/hotel-listing/?searchText={q}",
    "OYO": "https://www.oyorooms.com/search?location={q}",
    "NoBroker": "https://www.nobroker.in/property/search?searchTerm={q}",
    "Bluestone": "https://www.bluestone.com/search.html?query={q}",
    "Tanishq": "https://www.tanishq.co.in/search?q={q}",
    "CaratLane": "https://www.caratlane.com/search?q={q}",
    "Melorra": "https://www.melorra.com/search?q={q}",
}
_CANONICAL = {name.lower(): name for name in PLATFORM_URLS}

DEFAULT_HOME_PLATFORMS = ["Amazon", "Flipkart", "IKEA"]
DEFAULT_JEWELRY_PLATFORMS = ["Amazon", "Flipkart", "Bluestone", "Tanishq", "CaratLane", "Melorra"]
VENUE_PLATFORMS = ["Google", "Booking", "MakeMyTrip", "OYO", "NoBroker"]

# Party category keyword -> platforms (SRS: "category_platforms" mapping).
_PARTY_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    (("venue",), VENUE_PLATFORMS),
    (("cater", "food", "drink"), ["Swiggy", "Zomato"]),
    (("cake", "sweet"), ["Swiggy", "Zomato", "Amazon"]),
    (("decor",), ["Amazon", "Flipkart", "Meesho", "Myntra"]),
    (("entertain", "music", "game"), ["BookMyShow", "Amazon", "Flipkart"]),
    (("photo",), ["Google", "Amazon", "Flipkart"]),
    (("gift",), ["Amazon", "Flipkart", "Myntra", "Meesho"]),
    (("accessor", "cloth", "outfit"), ["Amazon", "Flipkart", "Myntra", "Meesho"]),
    (("transport",), ["MakeMyTrip", "Google"]),
]
DEFAULT_PARTY_PLATFORMS = ["Amazon", "Flipkart", "Google"]


def _num(value: Any) -> float:
    """Best-effort number: accepts ints, floats and strings like "₹1,200"."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, str):
        value = re.sub(r"[^0-9.\-]", "", value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number and abs(number) != float("inf") else 0.0


def known_platforms(requested: Any) -> list[str]:
    """Keep only whitelisted platform labels, canonically spelled, in order."""
    if not isinstance(requested, (list, tuple)):
        return []
    labels: list[str] = []
    for value in requested:
        canonical = _CANONICAL.get(str(value).strip().lower())
        if canonical and canonical not in labels:
            labels.append(canonical)
    return labels


def build_links(terms: str, platforms: list[str]) -> dict[str, str]:
    terms = (terms or "").strip()[:120]
    if not terms:
        return {}
    encoded = quote_plus(terms)
    slug = re.sub(r"[^a-z0-9]+", "-", terms.lower()).strip("-") or "search"
    return {
        platform: PLATFORM_URLS[platform].format(q=encoded, slug=slug)
        for platform in platforms
        if platform in PLATFORM_URLS
    }


def _party_platforms(category_name: str) -> list[str]:
    lowered = category_name.lower()
    for keywords, platforms in _PARTY_RULES:
        if any(keyword in lowered for keyword in keywords):
            return platforms
    return DEFAULT_PARTY_PLATFORMS


def _prepare_item(item: dict[str, Any], default_terms: str) -> str:
    """Normalise price aliases and return the item's search terms."""
    price = item.get("price", item.get("estimated_price"))
    item["price"] = _num(price)
    item["estimated_price"] = item["price"]
    terms = item.get("search_terms")
    terms = terms.strip() if isinstance(terms, str) and terms.strip() else default_terms
    item["search_terms"] = terms[:120]
    return item["search_terms"]


def enrich(category: str, result: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    budget = _num(data.get("budget"))
    result["total_budget"] = budget

    if category == "jewelry":
        platforms = known_platforms(data.get("platforms")) or DEFAULT_JEWELRY_PLATFORMS
        spent = 0.0
        for item in result.get("jewelry", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("type") or "jewelry")
            terms = _prepare_item(item, f"{name} jewellery")
            item["shopping_links"] = build_links(terms, platforms)
            spent += item["price"]
        result["remaining_budget"] = round(max(budget - spent, 0.0), 2)
        return result

    platforms = known_platforms(data.get("platforms")) or DEFAULT_HOME_PLATFORMS
    table: list[dict[str, Any]] = []
    allocated = 0.0
    for cat in result.get("categories", []):
        if not isinstance(cat, dict):
            continue
        cat_name = str(cat.get("name") or "Misc")
        items = [item for item in cat.get("items", []) if isinstance(item, dict)]
        cat["items"] = items
        cost = 0.0
        for item in items:
            terms = _prepare_item(item, str(item.get("name") or cat_name))
            quantity = _num(item.get("quantity")) or 1
            item["quantity"] = int(quantity) if quantity == int(quantity) else quantity
            cost += item["price"] * quantity
            item_platforms = platforms if category == "home" else _party_platforms(cat_name)
            item["shopping_links"] = build_links(terms, item_platforms)
        allocation = _num(cat.get("allocation"))
        allocated += allocation
        table.append(
            {
                "category": cat_name,
                "items_count": len(items),
                "allocation": allocation,
                "total_cost": round(cost, 2),
                "percentage_of_budget": round(allocation / budget * 100, 1) if budget else 0.0,
            }
        )
    result["calculation_table"] = table
    result["remaining_budget"] = round(max(budget - allocated, 0.0), 2)

    if category == "party":
        for venue in result.get("venues", []):
            if isinstance(venue, dict):
                terms = " ".join(
                    str(part) for part in (venue.get("name"), venue.get("location")) if part
                )
                venue["search_terms"] = terms[:120]
                venue["search_links"] = build_links(terms, VENUE_PLATFORMS)
    return result
