import statistics

RARE_KEYWORDS = [
    "500e", "e60", "2.3-16", "2.5-16", "cosworth", "evo",
    "r107", "sl280", "sl380", "sl450", "sl500", "sl600",
    "g-wagen", "230ge", "300gd", "500ge",
    "om606", "om605", "om612", "om613",
    "pagode", "w111", "w113", "heckflosse",
]

YEAR_BRACKETS = [
    (1900, 1974),
    (1975, 1985),
    (1986, 1990),
    (1991, 1995),
    (1996, 2000),
    (2001, 2005),
    (2006, 2010),
]


def _bracket(year: int) -> tuple[int, int]:
    for low, high in YEAR_BRACKETS:
        if low <= year <= high:
            return (low, high)
    return (0, 9999)


def _build_median_map(all_listings: list) -> dict:
    """
    Returns {(low, high): median_price} for listings with a known fixed price.
    """
    bracket_prices: dict[tuple, list] = {}
    for l in all_listings:
        if l.get("price_type") == "fixed" and l.get("price_eur", 0) > 0 and l.get("year", 0) > 0:
            b = _bracket(l["year"])
            bracket_prices.setdefault(b, []).append(l["price_eur"])
    return {b: statistics.median(prices) for b, prices in bracket_prices.items() if prices}


def _pct_below_median(price: int, median: float) -> float:
    if median <= 0:
        return 0.0
    return max(0.0, (median - price) / median * 100)


def _has_rare_keyword(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in RARE_KEYWORDS)


def _score_listing(listing: dict, median_map: dict) -> int:
    profile = listing.get("profile", "mercedes_oldtimer")
    price = listing.get("price_eur", 0)
    price_type = listing.get("price_type", "unknown")
    year = listing.get("year", 0)
    title = listing.get("title", "")

    if profile == "nl_belastingvrij":
        score = 6
        if year == 1987:
            score += 1
        if price_type != "fixed":
            score += 1
        if price > 0 and year > 0:
            b = _bracket(year)
            median = median_map.get(b, 0)
            pct = _pct_below_median(price, median)
            if pct >= 25:
                score += 2
        return min(score, 10)

    # mercedes_oldtimer and om_diesel
    score = 4

    if price_type != "fixed":
        score += 1

    rare = _has_rare_keyword(title)
    if rare:
        score += 2

    if price > 0 and year > 0:
        b = _bracket(year)
        median = median_map.get(b, 0)
        if median > 0:
            pct = _pct_below_median(price, median)
            if pct >= 40:
                score += 3
            elif pct >= 25:
                score += 2
            elif pct >= 10:
                score += 1

    return min(score, 10)


def _deal_reason(listing: dict, median_map: dict) -> str:
    profile = listing.get("profile", "mercedes_oldtimer")
    price = listing.get("price_eur", 0)
    year = listing.get("year", 0)
    title = listing.get("title", "")
    price_type = listing.get("price_type", "unknown")

    if profile == "nl_belastingvrij":
        if year == 1987:
            return "Wordt belastingvrij in 2027"
        return "Belastingvrij (40+ jaar)"

    parts = []
    if _has_rare_keyword(title):
        parts.append("Zeldzaam model")
    if price_type != "fixed":
        parts.append("Biedprijs (potentieel onontdekt)")
    if price > 0 and year > 0:
        b = _bracket(year)
        median = median_map.get(b, 0)
        if median > 0:
            pct = _pct_below_median(price, median)
            if pct >= 10:
                parts.append(f"{int(pct)}% onder mediaan")
    return " | ".join(parts) if parts else "Interessante aanbieding"


def analyze_deals(new_listings: list, all_listings: list) -> list:
    """
    new_listings: only unseen listings to evaluate
    all_listings: full batch (for computing medians)
    Returns list of flagged deals with added fields: opportunity_score, reason
    """
    if not new_listings:
        return []

    median_map = _build_median_map(all_listings)
    deals = []

    for listing in new_listings:
        score = _score_listing(listing, median_map)
        if score >= 6:
            deal = dict(listing)
            deal["opportunity_score"] = score
            deal["reason"] = _deal_reason(listing, median_map)
            deals.append(deal)

    deals.sort(key=lambda d: d["opportunity_score"], reverse=True)
    return deals
