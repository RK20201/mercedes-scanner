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

# Mercedes model/chassis codes → (min_year, max_year)
MERCEDES_MODEL_YEARS = {
    "w108": (1965, 1972), "w109": (1965, 1972),
    "w111": (1959, 1971), "w112": (1959, 1967),
    "w113": (1963, 1971), "pagode": (1963, 1971),
    "heckflosse": (1959, 1971),
    "w114": (1968, 1976), "w115": (1968, 1976),
    "w116": (1972, 1980),
    "w123": (1975, 1985),
    "w124": (1984, 1997),
    "w126": (1979, 1991),
    "w140": (1991, 1998),
    "w201": (1982, 1993), "190e": (1982, 1993), "190d": (1982, 1993),
    "w202": (1993, 2000),
    "w210": (1995, 2002),
    "w460": (1979, 1991), "w461": (1992, 2015), "w463": (1989, 2018),
    "r107": (1971, 1989),
    "r129": (1989, 2001),
    "om601": (1983, 2000), "om602": (1985, 2000), "om603": (1984, 1994),
    "om604": (1993, 1997), "om605": (1993, 2000), "om606": (1993, 1999),
    "om612": (1999, 2005), "om613": (1999, 2005),
    "200d": (1975, 1993), "200e": (1984, 1992),
    "220d": (1968, 1976), "220e": (1992, 1996),
    "230e": (1980, 1989), "230d": (1975, 1985), "230g": (1979, 1994),
    "240d": (1974, 1985),
    "250d": (1984, 1997),
    "260e": (1984, 1992),
    "280e": (1975, 1985), "280se": (1965, 1972), "280sl": (1967, 1971),
    "300d": (1975, 1985), "300e": (1984, 1993), "300td": (1975, 1986),
    "300sel": (1965, 1973), "300sl": (1989, 2001),
    "320e": (1992, 1997),
    "350se": (1972, 1980), "350sl": (1971, 1980),
    "380se": (1979, 1985), "380sl": (1979, 1986),
    "420se": (1985, 1991),
    "450se": (1972, 1980), "450sl": (1971, 1980),
    "500e": (1991, 1995), "500se": (1979, 1991), "500sl": (1989, 2001),
    "560se": (1985, 1991), "560sel": (1985, 1991),
    "600sel": (1991, 1998),
    "g-klasse": (1979, 2023), "g klasse": (1979, 2023), "gklasse": (1979, 2023),
    "g-class": (1979, 2023), "230ge": (1979, 1994), "300gd": (1979, 1994),
    "500ge": (1993, 1999),
}


def _estimate_year_from_title(title: str) -> int:
    """
    Tries to infer the build year from a Mercedes model name or chassis code
    in the listing title. Returns the midpoint year of the model range, or 0
    if nothing is recognised.
    For models that span across 1998 (e.g. W202 1993-2000) the min_year is
    returned so the listing is not wrongly excluded.
    """
    t = title.lower()
    best = None
    for code, (y_min, y_max) in MERCEDES_MODEL_YEARS.items():
        if re.search(r'\b' + re.escape(code) + r'\b', t):
            if best is None or y_min < best[0]:
                best = (y_min, y_max)
    if best is None:
        return 0
    y_min, y_max = best
    # If the whole range is before 1999, use midpoint
    if y_max <= 1998:
        return (y_min + y_max) // 2
    # Range straddles 1998 — use min_year so it passes the ≤1998 filter
    return y_min


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

def _scrape_adevinta(base_url: str, prefix: str, query: str, max_year: int | None, max_price: int | None, category_id: str | None = None) -> list:
    session = _session()
    params = {
        "query": query,
        "sortBy": "SORT_INDEX",
        "sortOrder": "DECREASING",
        "limit": "30",
    }
    if category_id:
        params["l1CategoryId"] = category_id
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
                "description": item.get("description", "") or item.get("shortDescription", ""),
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
        page_props = data.get("props", {}).get("pageProps", {})
        raw_listings = page_props.get("listings", [])
        if not raw_listings:
            # Try alternate paths AutoScout24 uses after Next.js updates
            raw_listings = (
                page_props.get("searchPageProps", {}).get("listings", [])
                or page_props.get("initialState", {}).get("listings", {}).get("items", [])
            )
        print(f"  [as24] pageProps keys: {list(page_props.keys())[:8]}, listings: {len(raw_listings)}")
    except Exception as e:
        print(f"  [as24] scrape failed: {e}")
        return []

    listings = []
    for item in raw_listings:
        try:
            item_id = str(item.get("id", ""))

            # Price — structure changed: may be dict or numeric
            price_obj = item.get("price", {})
            if isinstance(price_obj, dict):
                price_val = price_obj.get("value", 0) or price_obj.get("amount", 0) or 0
            elif isinstance(price_obj, (int, float)):
                price_val = int(price_obj)
            else:
                price_val = 0
            price_type = "fixed" if price_val > 0 else "ask"

            # Vehicle info — may be under "vehicle" or "identifier"
            vehicle = item.get("vehicle") or {}
            identifier = item.get("identifier") or {}

            make = vehicle.get("make") or identifier.get("make", "")
            model = vehicle.get("model") or identifier.get("model", "")
            version = vehicle.get("modelVersion") or identifier.get("version", "")
            title = " ".join(p for p in [make, model, version] if p).strip() or "AutoScout24"

            # Year from firstRegistration or URL
            year = 0
            reg = vehicle.get("firstRegistration") or identifier.get("firstRegistration", "")
            if reg:
                try:
                    year = int(str(reg).split("/")[-1])
                except (ValueError, IndexError):
                    year = 0
            if year == 0:
                url_path = item.get("url", "")
                m = re.search(r"\b(19[5-9]\d|200\d|201[0-8])\b", url_path)
                if m:
                    year = int(m.group(1))

            mileage = vehicle.get("mileageInKm", 0) or 0
            location = (item.get("seller") or {}).get("city", "")
            images = item.get("images") or []
            image_url = images[0].get("url", "") if images and isinstance(images[0], dict) else ""

            if not item_id:
                continue

            listings.append({
                "id": f"as24:{item_id}",
                "platform": "autoscout24",
                "title": title,
                "price_eur": int(price_val),
                "price_type": price_type,
                "year": year,
                "mileage_km": int(mileage),
                "url": "https://www.autoscout24.com" + item.get("url", ""),
                "location": location,
                "image_url": image_url,
                "scraped_at": _now(),
            })
        except Exception:
            continue

    return listings


# ---------------------------------------------------------------------------
# Kleinanzeigen.de  (Playwright — bypasses DataDome anti-bot)
# ---------------------------------------------------------------------------

def _scrape_kleinanzeigen(query: str, max_year: int | None) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [kaz] playwright not installed, skipping")
        return []

    # No location code — search all of Germany
    if max_year:
        url = f"https://www.kleinanzeigen.de/s-{query.lower().replace(' ', '-')}/c216+autos.ez_i:,{max_year}/k0"
    else:
        url = f"https://www.kleinanzeigen.de/s-{query.lower().replace(' ', '-')}/c216/k0"

    listings = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="de-DE",
            )
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="load")
            page.wait_for_timeout(2000)

            for consent_selector in [
                "#gdpr-banner-accept",
                "button[data-gdpr-action='accept']",
                "[aria-label='Alle akzeptieren']",
                "button.gdpr-consent-accept",
            ]:
                try:
                    page.click(consent_selector, timeout=2000)
                    page.wait_for_timeout(1000)
                    break
                except Exception:
                    continue

            # Wait for listings to appear (JavaScript-rendered content)
            try:
                page.wait_for_selector("a[href*='/s-anzeige/']", timeout=10000)
            except Exception:
                pass

            print(f"  [kaz] page title: {page.title()[:80]}")

            # Find listing links (data-adid no longer in DOM)
            links = page.query_selector_all("a[href*='/s-anzeige/']")
            print(f"  [kaz] {len(links)} advertentielinks gevonden")

            seen_hrefs: set = set()
            for link in links[:40]:
                try:
                    href = link.get_attribute("href") or ""
                    if not href or href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)

                    ad_id = href.strip("/").split("/")[-1]
                    item_url = f"https://www.kleinanzeigen.de{href}" if not href.startswith("http") else href

                    title = link.inner_text().split("\n")[0].strip()[:100]
                    card_text = link.evaluate(
                        "el => (el.closest('article') || el.closest('li') || "
                        "el.parentElement.parentElement || el.parentElement).innerText"
                    ) or title

                    price_eur, price_type = _parse_price_text(card_text)
                    year = _extract_year_from_text(title + " " + card_text)

                    location = ""
                    for line in card_text.split("\n"):
                        stripped = line.strip()
                        if stripped and len(stripped) > 2 and not stripped[0].isdigit():
                            location = stripped[:50]
                            break

                    if ad_id:
                        listings.append({
                            "id": f"kaz:{ad_id}",
                            "platform": "kaz",
                            "title": title,
                            "price_eur": price_eur,
                            "price_type": price_type,
                            "year": year,
                            "mileage_km": 0,
                            "url": item_url,
                            "location": location,
                            "image_url": "",
                            "scraped_at": _now(),
                        })
                except Exception:
                    continue
            browser.close()
    except Exception as e:
        print(f"  [kaz] scrape failed: {e}")

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
    import base64
    import os
    import tempfile

    # Decode base64 auth state from environment variable (set as GitHub Secret)
    tmp_path = None
    fb_auth_env = os.environ.get("FB_AUTH_STATE", "")
    if fb_auth_env:
        try:
            decoded = base64.b64decode(fb_auth_env).decode("utf-8")
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            tmp.write(decoded)
            tmp.close()
            tmp_path = tmp.name
            auth_state_path = tmp_path
        except Exception as e:
            print(f"  [fb] failed to decode FB_AUTH_STATE: {e}")

    if not os.path.exists(auth_state_path):
        print("  [fb] auth state not found, skipping")
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [fb] playwright not installed, skipping")
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
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
                        "platform": "fb",
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
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

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


_PARTS_URL_MARKERS = ("auto-onderdelen", "ersatzteile", "/teile/", "motorteile", "parts")
_PARTS_TITLE_KEYWORDS = [
    "nokkenashuis", "cilinderkop", "cylinderkop", "motorblok",
    "versnellingsbak", "differentieel",
    "injectiepomp", "injector", "injectoren",
    "distributieriem", "distributieketting",
    "koppakking", "pakking",
    "brandstofpomp", "waterpomp", "oliepomp",
    "remschijven", "remschijf", "remblokken",
    "turbocompressor",
    " onderdelen", " onderdeel",
    "wisselstukken",
]


def _is_parts_listing(listing: dict) -> bool:
    url = listing.get("url", "").lower()
    if any(m in url for m in _PARTS_URL_MARKERS):
        return True
    title = listing.get("title", "").lower()
    return any(kw in title for kw in _PARTS_TITLE_KEYWORDS)


# ---------------------------------------------------------------------------
# Enrichment: description fetch + free image captioning (HF BLIP)
# ---------------------------------------------------------------------------

def _fetch_description_adevinta(base_url: str, item_id: str) -> str:
    """Fetch description from listing detail page when API search doesn't return it."""
    session = _session()
    try:
        resp = session.get(f"{base_url}/api/listing/{item_id}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("description", "") or data.get("body", "")
    except Exception:
        pass
    return ""


def _caption_image_hf(image_url: str) -> str:
    """
    Free image captioning via Hugging Face Inference API (BLIP model).
    No API key required. Returns an English caption like 'a red vintage car'.
    """
    if not image_url:
        return ""
    try:
        img_data = requests.get(image_url, timeout=10).content
        resp = requests.post(
            "https://api-inference.huggingface.co/models/Salesforce/blip-image-captioning-base",
            headers={"Content-Type": "application/octet-stream"},
            data=img_data,
            timeout=35,
        )
        if resp.status_code == 200:
            result = resp.json()
            if isinstance(result, list) and result:
                return result[0].get("generated_text", "")
    except Exception:
        pass
    return ""


def _enrich_unknown_year_listings(listings: list) -> int:
    """
    For listings where year is still 0 after model-code lookup,
    fetch the description and analyze the photo via HF BLIP.
    Returns number of listings enriched.
    """
    enriched = 0
    candidates = [
        l for l in listings
        if l["year"] == 0 and l.get("profile") in ("mercedes_oldtimer", "om_diesel")
    ]
    if not candidates:
        return 0

    print(f"  Verrijken van {len(candidates)} listings met onbekend jaar (beschrijving + foto)...")
    for listing in candidates:
        # 1. Try to fetch full description if not already present
        if not listing.get("description"):
            if listing["platform"] == "mp":
                item_id = listing["id"].replace("mp:", "")
                listing["description"] = _fetch_description_adevinta("https://www.marktplaats.nl", item_id)
            elif listing["platform"] == "2dh":
                item_id = listing["id"].replace("2dh:", "")
                listing["description"] = _fetch_description_adevinta("https://www.2dehands.be", item_id)
            _sleep()

        # 2. Free image captioning
        caption = _caption_image_hf(listing.get("image_url", ""))
        if caption:
            listing["image_caption"] = caption

        # 3. Re-try year estimation with description + caption
        combined = f"{listing['title']} {listing.get('description', '')} {caption}"
        estimated = _estimate_year_from_title(combined)
        if estimated > 0:
            listing["year"] = estimated
            listing["year_estimated"] = True
            enriched += 1

    return enriched


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
        filtered = [
            r for r in results
            if (r["year"] <= 1998 or r["year"] == 0) and not _is_parts_listing(r)
        ]
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
            filtered = [r for r in results if not _is_parts_listing(r)]
            for r in filtered:
                r["profile"] = "om_diesel"
            print(f"    {name} {engine}: {len(filtered)} aanbiedingen")
            all_listings.extend(filtered)
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
            if r["year"] > 0 and r["year"] <= 1987
            and (r["price_eur"] <= 10000 or r["price_type"] != "fixed")
            and not _is_parts_listing(r)
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

    # Pass 1: estimate year from model codes in title (free, instant)
    enriched = 0
    for listing in deduped:
        if listing["year"] == 0 and listing.get("profile") in ("mercedes_oldtimer", "om_diesel"):
            estimated = _estimate_year_from_title(listing["title"])
            if estimated > 0:
                listing["year"] = estimated
                listing["year_estimated"] = True
                enriched += 1

    # Pass 2: for still-unknown listings, fetch description + analyze photo (free HF API)
    enriched += _enrich_unknown_year_listings(deduped)

    print(f"  Totaal na deduplicatie: {len(deduped)} ({enriched} jaar geschat uit modelnaam/beschrijving/foto)")
    return deduped
