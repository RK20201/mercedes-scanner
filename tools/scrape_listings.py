import json
import random
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

OM_ENGINES = ["OM605", "OM606", "OM612", "OM613"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sleep():
    time.sleep(random.uniform(1.5, 3.5))


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ---------------------------------------------------------------------------
# Marktplaats / 2dehands  (shared Adevinta platform)
# ---------------------------------------------------------------------------

def _scrape_adevinta(base_url: str, prefix: str, query: str, max_year: int | None, max_price: int | None) -> list:
    session = _session()
    params = {
        "l1CategoryId": "91",
        "query": query,
        "sortBy": "SORT_INDEX",
        "sortOrder": "DECREASING",
        "limit": "30",
    }
    if max_year:
        params["attributeRanges[]"] = f"constructionYear:::{max_year}"
    if max_price:
        params["priceValueTo"] = str(max_price)

    try:
        resp = session.get(f"{base_url}/lrp/api/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [{prefix}] scrape failed: {e}")
        return []

    listings = []
    for item in data.get("listings", []):
        try:
            price_info = item.get("priceInfo", {})
            price_cents = price_info.get("priceCents", 0) or 0
            price_type_raw = price_info.get("priceType", "UNKNOWN").upper()
            price_type = "fixed" if price_type_raw == "FIXED" else "ask" if price_type_raw in ("FAST_BID", "MIN_BID", "BIDDING") else "unknown"

            attrs = {a["key"]: a.get("value", "") for a in item.get("attributes", [])}
            year_str = attrs.get("constructionYear", "0")
            try:
                year = int(year_str)
            except ValueError:
                year = 0
            mileage_str = attrs.get("mileage", "0").replace(".", "").replace(",", "").split()[0]
            try:
                mileage = int(mileage_str)
            except ValueError:
                mileage = 0

            item_id = str(item.get("itemId", ""))
            vip_url = item.get("vipUrl", "")
            url = vip_url if vip_url.startswith("http") else f"{base_url}{vip_url}"
            images = item.get("imageUrls", [])

            listings.append({
                "id": f"{prefix}:{item_id}",
                "platform": prefix,
                "title": item.get("title", ""),
                "price_eur": price_cents // 100,
                "price_type": price_type,
                "year": year,
                "mileage_km": mileage,
                "url": url,
                "location": item.get("location", {}).get("cityName", ""),
                "image_url": images[0] if images else "",
                "scraped_at": _now(),
            })
        except Exception:
            continue

    return listings


def scrape_marktplaats_profile(query: str, max_year: int | None = None, max_price: int | None = None) -> list:
    return _scrape_adevinta("https://www.marktplaats.nl", "mp", query, max_year, max_price)


def scrape_2dehands_profile(query: str, max_year: int | None = None, max_price: int | None = None) -> list:
    return _scrape_adevinta("https://www.2dehands.be", "2dh", query, max_year, max_price)


# ---------------------------------------------------------------------------
# AutoScout24  (__NEXT_DATA__ extraction)
# ---------------------------------------------------------------------------

def _scrape_autoscout24(query: str, max_year: int | None, max_price: int | None) -> list:
    session = _session()
    params = {
        "sort": "age",
        "desc": "1",
        "ustate": "N,U",
        "size": "20",
        "page": "1",
        "atype": "C",
        "cy": "D,A,B,E,F,I,L,NL",
    }
    if query.lower() == "mercedes":
        url = "https://www.autoscout24.com/lst/mercedes-benz"
    else:
        url = "https://www.autoscout24.com/lst"
        params["q"] = query
    if max_year:
        params["fregto"] = str(max_year)
    if max_price:
        params["priceto"] = str(max_price)

    _sleep()
    try:
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            print("  [as24] __NEXT_DATA__ not found")
            return []
        data = json.loads(script.string)
        raw_listings = (
            data.get("props", {})
            .get("pageProps", {})
            .get("listings", [])
        )
    except Exception as e:
        print(f"  [as24] scrape failed: {e}")
        return []

    listings = []
    for item in raw_listings:
        try:
            vehicle = item.get("vehicle", {})
            price_obj = item.get("price", {})
            price_val = price_obj.get("value", 0) or 0
            price_type = "fixed" if price_val > 0 else "ask"

            reg = vehicle.get("firstRegistration", "01/1900")
            try:
                year = int(reg.split("/")[-1])
            except (ValueError, IndexError):
                year = 0

            listings.append({
                "id": f"as24:{item.get('id', '')}",
                "platform": "autoscout24",
                "title": f"{vehicle.get('make', '')} {vehicle.get('model', '')} {vehicle.get('modelVersion', '')}".strip(),
                "price_eur": int(price_val),
                "price_type": price_type,
                "year": year,
                "mileage_km": vehicle.get("mileageInKm", 0) or 0,
                "url": "https://www.autoscout24.com" + item.get("url", ""),
                "location": item.get("seller", {}).get("city", ""),
                "image_url": (item.get("images") or [{}])[0].get("url", ""),
                "scraped_at": _now(),
            })
        except Exception:
            continue

    return listings


# ---------------------------------------------------------------------------
# Kleinanzeigen.de  (HTML, DataDome — graceful fail)
# ---------------------------------------------------------------------------

def _scrape_kleinanzeigen(query: str, max_year: int | None) -> list:
    session = _session()
    session.headers["Referer"] = "https://www.kleinanzeigen.de/"

    if max_year:
        url = f"https://www.kleinanzeigen.de/s-{query.lower().replace(' ', '-')}/c216l9352+autos.bj_i:,{max_year}/k0"
    else:
        url = f"https://www.kleinanzeigen.de/s-{query.lower().replace(' ', '-')}/c216/k0"

    _sleep()
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code in (403, 429) or "captcha" in resp.text.lower():
            print("  [kaz] blocked by anti-bot, skipping")
            return []
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [kaz] scrape failed: {e}")
        return []

    listings = []
    for article in soup.select("article[data-adid]"):
        try:
            ad_id = article.get("data-adid", "")
            title_el = article.select_one("a.ellipsis")
            title = title_el.get_text(strip=True) if title_el else ""
            price_el = article.select_one("p.aditem-main--middle--price-shipping--price")
            price_text = price_el.get_text(strip=True) if price_el else ""
            price_eur, price_type = _parse_price_text(price_text)
            link_el = article.select_one("a[href*='/s-anzeige/']")
            href = link_el.get("href", "") if link_el else ""
            url = f"https://www.kleinanzeigen.de{href}" if href else ""
            location_el = article.select_one("div.aditem-main--top--left")
            location = location_el.get_text(strip=True) if location_el else ""
            year = _extract_year_from_text(title)

            listings.append({
                "id": f"kaz:{ad_id}",
                "platform": "kleinanzeigen",
                "title": title,
                "price_eur": price_eur,
                "price_type": price_type,
                "year": year,
                "mileage_km": 0,
                "url": url,
                "location": location,
                "image_url": "",
                "scraped_at": _now(),
            })
        except Exception:
            continue

    return listings


# ---------------------------------------------------------------------------
# Mobile.de  (HTML)
# ---------------------------------------------------------------------------

def _scrape_mobile_de(query: str, max_year: int | None, max_price: int | None) -> list:
    session = _session()
    session.headers["Referer"] = "https://www.mobile.de/"

    params = {"isSearchRequest": "true", "sortOption.sortBy": "creationTime", "sortOption.sortOrder": "DESCENDING"}
    if query.lower() in ("mercedes", "mercedes-benz"):
        params["makeModelVariant1.makeId"] = "17200"
    else:
        params["q"] = query
    if max_year:
        params["maxFirstRegistrationDate"] = f"{max_year}-12-01"
    if max_price:
        params["maxPrice.EUR"] = str(max_price)

    _sleep()
    try:
        resp = session.get("https://suchen.mobile.de/fahrzeuge/search.html", params=params, timeout=20)
        if resp.status_code == 403:
            print("  [mobile.de] 403 blocked, skipping")
            return []
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  [mobile.de] scrape failed: {e}")
        return []

    listings = []
    for card in soup.select("div[data-listing-id]"):
        try:
            listing_id = card.get("data-listing-id", "")
            title_el = card.select_one("strong.h3--mobile, h3.u-truncate-text, .h3--mobile")
            title = title_el.get_text(strip=True) if title_el else ""
            price_el = card.select_one("span[data-testid='price'], .price-rating, .u-block.u-margin-bottom-9")
            price_text = price_el.get_text(strip=True) if price_el else ""
            price_eur, price_type = _parse_price_text(price_text)
            link_el = card.select_one("a[href*='/fahrzeuge/']")
            href = link_el.get("href", "") if link_el else ""
            url = f"https://www.mobile.de{href}" if href and not href.startswith("http") else href
            year = _extract_year_from_text(title + " " + card.get_text())

            listings.append({
                "id": f"mde:{listing_id}",
                "platform": "mobile.de",
                "title": title,
                "price_eur": price_eur,
                "price_type": price_type,
                "year": year,
                "mileage_km": 0,
                "url": url,
                "location": "",
                "image_url": "",
                "scraped_at": _now(),
            })
        except Exception:
            continue

    return listings


# ---------------------------------------------------------------------------
# Facebook Marketplace  (Playwright, optional)
# ---------------------------------------------------------------------------

def _scrape_facebook(auth_state_path: str = "fb_auth_state.json") -> list:
    import os
    if not os.path.exists(auth_state_path):
        print("  [fb] auth state not found, skipping")
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [fb] playwright not installed, skipping")
        return []

    listings = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=auth_state_path)
            page = context.new_page()
            page.goto(
                "https://www.facebook.com/marketplace/search/"
                "?query=mercedes%20oldtimer&sortBy=creation_time_descend",
                timeout=30000,
            )
            page.wait_for_timeout(3000)
            cards = page.query_selector_all("div[data-pagelet='MarketplaceSearchResults'] a[href*='/marketplace/item/']")
            for card in cards[:30]:
                try:
                    href = card.get_attribute("href") or ""
                    url = f"https://www.facebook.com{href}" if not href.startswith("http") else href
                    item_id = re.search(r"/item/(\d+)/", href)
                    if not item_id:
                        continue
                    text = card.inner_text()
                    price_eur, price_type = _parse_price_text(text)
                    year = _extract_year_from_text(text)
                    listings.append({
                        "id": f"fb:{item_id.group(1)}",
                        "platform": "facebook",
                        "title": text.split("\n")[0][:100],
                        "price_eur": price_eur,
                        "price_type": price_type,
                        "year": year,
                        "mileage_km": 0,
                        "url": url,
                        "location": "",
                        "image_url": "",
                        "scraped_at": _now(),
                    })
                except Exception:
                    continue
            browser.close()
    except Exception as e:
        print(f"  [fb] scrape failed: {e}")

    return listings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_price_text(text: str) -> tuple[int, str]:
    text = text.strip()
    if any(w in text.lower() for w in ["bieden", "bod", "bieten", "vbo", "negotiable", "offer"]):
        return 0, "ask"
    numbers = re.findall(r"[\d.,]+", text.replace(".", "").replace(",", ""))
    for n in numbers:
        try:
            val = int(n)
            if 100 <= val <= 500000:
                return val, "fixed"
        except ValueError:
            continue
    return 0, "unknown"


def _extract_year_from_text(text: str) -> int:
    matches = re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", text)
    for m in matches:
        y = int(m)
        if 1950 <= y <= 2025:
            return y
    return 0


def _dedup(listings: list) -> list:
    seen = {}
    for l in listings:
        if l["id"] not in seen:
            seen[l["id"]] = l
    return list(seen.values())


# ---------------------------------------------------------------------------
# Public API: three profiles combined
# ---------------------------------------------------------------------------

def scrape_all_platforms() -> list:
    all_listings = []

    print("  [profiel 1] Mercedes oldtimers ≤ 1998")
    for scraper, name in [
        (lambda: scrape_marktplaats_profile("mercedes", max_year=1998), "marktplaats"),
        (lambda: scrape_2dehands_profile("mercedes", max_year=1998), "2dehands"),
        (lambda: _scrape_autoscout24("mercedes", max_year=1998, max_price=None), "autoscout24"),
        (lambda: _scrape_kleinanzeigen("mercedes-benz", max_year=1998), "kleinanzeigen"),
        (lambda: _scrape_mobile_de("mercedes", max_year=1998, max_price=None), "mobile.de"),
    ]:
        results = scraper()
        filtered = [r for r in results if r["year"] <= 1998 or r["year"] == 0]
        for r in filtered:
            r["profile"] = "mercedes_oldtimer"
        print(f"    {name}: {len(filtered)} aanbiedingen")
        all_listings.extend(filtered)
        _sleep()

    print("  [profiel 2] OM-dieselmotoren")
    for engine in OM_ENGINES:
        for scraper, name in [
            (lambda e=engine: scrape_marktplaats_profile(e), "marktplaats"),
            (lambda e=engine: scrape_2dehands_profile(e), "2dehands"),
        ]:
            results = scraper()
            for r in results:
                r["profile"] = "om_diesel"
            print(f"    {name} {engine}: {len(results)} aanbiedingen")
            all_listings.extend(results)
            _sleep()

    print("  [profiel 3] NL belastingvrij (alle merken ≤ 1987, max €10.000)")
    for scraper, name in [
        (lambda: scrape_marktplaats_profile("auto", max_year=1987, max_price=10000), "marktplaats"),
        (lambda: scrape_2dehands_profile("auto", max_year=1987, max_price=10000), "2dehands"),
        (lambda: _scrape_autoscout24("", max_year=1987, max_price=10000), "autoscout24"),
    ]:
        results = scraper()
        filtered = [
            r for r in results
            if (r["year"] <= 1987 or r["year"] == 0)
            and (r["price_eur"] <= 10000 or r["price_type"] != "fixed")
        ]
        for r in filtered:
            r["profile"] = "nl_belastingvrij"
        print(f"    {name}: {len(filtered)} aanbiedingen")
        all_listings.extend(filtered)
        _sleep()

    print("  [facebook] optioneel")
    fb = _scrape_facebook()
    for r in fb:
        r["profile"] = "mercedes_oldtimer"
    all_listings.extend(fb)

    deduped = _dedup(all_listings)
    print(f"  Totaal na deduplicatie: {len(deduped)}")
    return deduped
