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
    except Exception as e:
        print(f"  [as24] scrape failed: {e}")
        return []

    listings = []
    for item in raw_listings:
        try:
            item_id = str(item.get("id", ""))
            if not item_id:
                continue

            # tracking has the most reliable numeric data in the new structure
            tracking = item.get("tracking") or {}

            price_val = int(re.sub(r"[^\d]", "", str(tracking.get("price", "") or "")) or 0)
            price_type = "fixed" if price_val > 0 else "ask"

            vehicle = item.get("vehicle") or {}
            vehicle = vehicle if isinstance(vehicle, dict) else {}
            make = vehicle.get("make", "")
            model = vehicle.get("model", "")
            version = vehicle.get("modelVersionInput") or vehicle.get("variant", "")
            title = " ".join(p for p in [make, model, version] if p).strip() or "AutoScout24"

            # Year from tracking.firstRegistration: "02-1998" → 1998
            year = 0
            reg = str(tracking.get("firstRegistration", "") or "")
            if reg:
                try:
                    year = int(re.split(r"[-/]", reg)[-1])
                except (ValueError, IndexError):
                    year = 0

            mileage = int(re.sub(r"[^\d]", "", str(tracking.get("mileage", "") or "")) or 0)

            location_obj = item.get("location") or {}
            location = location_obj.get("city", "") if isinstance(location_obj, dict) else ""

            images = item.get("images") or []
            image_url = images[0] if images and isinstance(images[0], str) else ""

            listings.append({
                "id": f"as24:{item_id}",
                "platform": "autoscout24",
                "title": title,
                "price_eur": price_val,
                "price_type": price_type,
                "year": year,
                "mileage_km": mileage,
                "url": "https://www.autoscout24.com" + item.get("url", ""),
                "location": location,
                "image_url": image_url,
                "scraped_at": _now(),
            })
        except Exception:
            continue

    return listings


# ---------------------------------------------------------------------------
# Kleinanzeigen.de  (curl_cffi — mimics Chrome TLS to bypass DataDome)
# ---------------------------------------------------------------------------

def _cffi_session():
    """curl_cffi session that impersonates Chrome (bypasses DataDome/Cloudflare JA3 checks)."""
    from curl_cffi import requests as cfrequests
    s = cfrequests.Session(impersonate="chrome110")
    s.headers.update({
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
    })
    return s


def _scrape_kleinanzeigen(query: str, max_year: int | None) -> list:
    """
    Kleinanzeigen is a React SPA protected by DataDome.
    Organic listings are not accessible via automation (no API, no SSR data).
    Firefox only returns 2 sponsored PLA ads (irrelevant to Mercedes search).
    """
    print("  [kaz] overgeslagen (DataDome blokkeert organische resultaten)")
    return []


def _scrape_kleinanzeigen_cffi(query: str, max_year: int | None) -> list:
    try:
        session = _cffi_session()
    except ImportError:
        return []

    slug = query.lower().replace(" ", "-").replace("_", "-")
    page_url = (
        f"https://www.kleinanzeigen.de/s-{slug}/c216+autos.ez_i:,{max_year}/k0"
        if max_year
        else f"https://www.kleinanzeigen.de/s-{slug}/c216/k0"
    )

    # Load page first to obtain session cookies, then hit the search API
    try:
        session.get(page_url, timeout=20)
    except Exception:
        return []

    # Internal search API — requires session cookies from page load
    api_params = {
        "categoryId": "216",
        "query": query,
        "pageSize": "50",
        "sortField": "CREATION_DATE",
        "sortDirection": "DESC",
    }
    if max_year:
        api_params["maxConstructionYear"] = str(max_year)

    for api_url in [
        "https://gateway.kleinanzeigen.de/ads/v1/ads",
        "https://www.kleinanzeigen.de/api/v1/ads",
    ]:
        try:
            resp = session.get(
                api_url,
                params=api_params,
                headers={"Accept": "application/json", "Referer": page_url},
                timeout=15,
            )
            if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
                data = resp.json()
                items = data.get("ads", data.get("listings", data.get("items", [])))
                if items:
                    listings = _parse_kleinanzeigen_api_items(items)
                    print(f"  [kaz/api] {len(listings)} aanbiedingen via {api_url.split('/')[2]}")
                    return listings
        except Exception:
            continue

    # Fallback: parse SPA HTML (usually empty, but try)
    try:
        resp = session.get(page_url, timeout=20)
        if resp.status_code == 200 and "DataDome" not in resp.text:
            soup = BeautifulSoup(resp.text, "lxml")
            listings = _parse_kleinanzeigen_html(soup)
            if listings:
                print(f"  [kaz/cffi] {len(listings)} aanbiedingen via HTML")
                return listings
    except Exception:
        pass
    return []


def _parse_kleinanzeigen_api_items(items: list) -> list:
    listings = []
    for item in items[:50]:
        try:
            ad_id = str(item.get("id", item.get("adId", "")))
            if not ad_id:
                continue
            title = item.get("title", "")[:100]
            price_raw = item.get("price", {})
            if isinstance(price_raw, dict):
                price_eur = int(price_raw.get("amount", 0) or 0)
                pt = (price_raw.get("type") or "").upper()
                price_type = "fixed" if pt in ("FIXED", "NEGOTIABLE") or price_eur > 0 else "ask"
            else:
                price_eur, price_type = _parse_price_text(str(price_raw))
            loc = item.get("location", {})
            location = loc.get("city", loc.get("zipCode", "")) if isinstance(loc, dict) else ""
            year = int(item.get("year", item.get("firstRegistrationYear", 0)) or 0)
            if year == 0:
                year = _extract_year_from_text(title)
            mileage_raw = item.get("mileageInKm", item.get("mileage", 0))
            mileage = int(re.sub(r"[^\d]", "", str(mileage_raw or 0)) or 0)
            vip = item.get("url", item.get("link", ""))
            item_url = vip if vip.startswith("http") else f"https://www.kleinanzeigen.de{vip}"
            if not item_url or item_url == "https://www.kleinanzeigen.de":
                item_url = f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}"
            listings.append({
                "id": f"kaz:{ad_id}",
                "platform": "kaz",
                "title": title,
                "price_eur": price_eur,
                "price_type": price_type,
                "year": year,
                "mileage_km": mileage,
                "url": item_url,
                "location": location,
                "image_url": "",
                "scraped_at": _now(),
            })
        except Exception:
            continue
    return listings


def _scrape_kleinanzeigen_pw_firefox(query: str, max_year: int | None) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [kaz] playwright not installed, skipping")
        return []

    slug = query.lower().replace(" ", "-").replace("_", "-")
    url = (
        f"https://www.kleinanzeigen.de/s-{slug}/c216+autos.ez_i:,{max_year}/k0"
        if max_year
        else f"https://www.kleinanzeigen.de/s-{slug}/c216/k0"
    )

    captured_json: list = []

    def on_response(response):
        try:
            if "kleinanzeigen.de" not in response.url or response.status != 200:
                return
            if "json" not in response.headers.get("content-type", ""):
                return
            data = response.json()
            if not isinstance(data, dict):
                return
            for key in ("ads", "listings", "items", "results"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    captured_json.extend(val)
                    return
        except Exception:
            pass

    listings = []
    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(locale="de-DE")
            page = context.new_page()
            page.on("response", on_response)
            page.goto(url, timeout=30000, wait_until="domcontentloaded")

            page.wait_for_timeout(3000)  # let consent banner appear

            # Accept consent — DataDome banner + fallback for all frames
            try:
                page.click("#gdpr-banner-accept", timeout=3000)
            except Exception:
                _accept_consent_all_frames(page)
            page.wait_for_timeout(4000)  # wait for listings after consent

            if captured_json:
                print(f"  [kaz/pw] {len(captured_json)} items via API interceptie")
                for item in captured_json[:40]:
                    try:
                        ad_id = str(item.get("id", item.get("adId", "")))
                        if not ad_id:
                            continue
                        title = item.get("title", "")[:100]
                        price_raw = item.get("price", {})
                        if isinstance(price_raw, dict):
                            price_eur = int(price_raw.get("amount", 0) or 0)
                            pt = (price_raw.get("type") or "").upper()
                            price_type = "fixed" if pt == "FIXED" or price_eur > 0 else "ask"
                        else:
                            price_eur, price_type = _parse_price_text(str(price_raw))
                        loc = item.get("location", {})
                        location = loc.get("city", loc.get("zipCode", "")) if isinstance(loc, dict) else ""
                        year = int(item.get("year", item.get("firstRegistrationYear", 0)) or 0)
                        if year == 0:
                            year = _extract_year_from_text(title)
                        vip = item.get("url", item.get("link", ""))
                        item_url = vip if vip.startswith("http") else f"https://www.kleinanzeigen.de{vip}"
                        listings.append({"id": f"kaz:{ad_id}", "platform": "kaz", "title": title, "price_eur": price_eur, "price_type": price_type, "year": year, "mileage_km": 0, "url": item_url, "location": location, "image_url": "", "scraped_at": _now()})
                    except Exception:
                        continue
            else:
                # DOM fallback: parse the rendered HTML
                content = page.content()
                soup = BeautifulSoup(content, "lxml")
                listings = _parse_kleinanzeigen_html(soup)
                print(f"  [kaz/pw] {len(listings)} DOM listings gevonden")

            browser.close()
    except Exception as e:
        print(f"  [kaz/pw] scrape failed: {e}")
    return listings


def _parse_kleinanzeigen_html(soup: "BeautifulSoup") -> list:
    listings = []
    articles = soup.select("article.aditem, article[data-adid], li.ad-listitem article")
    for article in articles[:40]:
        try:
            ad_id = article.get("data-adid", "")
            if not ad_id:
                link = article.select_one("a[href*='/s-anzeige/']")
                if link:
                    m = re.search(r"/(\d+)$", link.get("href", ""))
                    ad_id = m.group(1) if m else ""
            if not ad_id:
                continue
            title_el = article.select_one(".ellipsis, h2, .aditem-main--top--left")
            title = title_el.get_text(strip=True)[:100] if title_el else ""
            link_el = article.select_one("a[href*='/s-anzeige/']")
            href = link_el.get("href", "") if link_el else ""
            item_url = f"https://www.kleinanzeigen.de{href}" if href and not href.startswith("http") else href
            card_text = article.get_text(" ")
            price_eur, price_type = _parse_price_text(card_text)
            year = _extract_year_from_text(title + " " + card_text)
            m_km = re.search(r"([\d.,]+)\s*km", card_text)
            mileage = int(re.sub(r"[^\d]", "", m_km.group(1)) or 0) if m_km else 0
            location_el = article.select_one(".aditem-main--top--right, .aditem-details")
            location = location_el.get_text(strip=True)[:50] if location_el else ""
            listings.append({"id": f"kaz:{ad_id}", "platform": "kaz", "title": title, "price_eur": price_eur, "price_type": price_type, "year": year, "mileage_km": mileage, "url": item_url, "location": location, "image_url": "", "scraped_at": _now()})
        except Exception:
            continue

    if not listings:
        seen: set = set()
        for link in soup.select("a[href*='/s-anzeige/']")[:40]:
            try:
                href = link.get("href", "")
                if not href or href in seen:
                    continue
                seen.add(href)
                m = re.search(r"/(\d+)$", href)
                ad_id = m.group(1) if m else ""
                if not ad_id:
                    continue
                item_url = f"https://www.kleinanzeigen.de{href}" if not href.startswith("http") else href
                card_text = link.get_text(" ")
                price_eur, price_type = _parse_price_text(card_text)
                year = _extract_year_from_text(card_text)
                listings.append({"id": f"kaz:{ad_id}", "platform": "kaz", "title": card_text.split("\n")[0].strip()[:100], "price_eur": price_eur, "price_type": price_type, "year": year, "mileage_km": 0, "url": item_url, "location": "", "image_url": "", "scraped_at": _now()})
            except Exception:
                continue
    return listings


# ---------------------------------------------------------------------------
# Mobile.de  (Playwright Firefox — bypasses Akamai Bot Manager)
# ---------------------------------------------------------------------------

def _scrape_mobile_de(query: str, max_year: int | None, max_price: int | None) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [mde] playwright not installed, skipping")
        return []

    params = {
        "isSearchRequest": "true",
        "sortOption.sortBy": "creationTime",
        "sortOption.sortOrder": "DESCENDING",
    }
    if query.lower() in ("mercedes", "mercedes-benz"):
        params["makeModelVariant1.makeId"] = "17200"
    else:
        params["q"] = query
    if max_year:
        params["maxFirstRegistrationDate"] = f"{max_year}-12-01"
    if max_price:
        params["maxPrice.EUR"] = str(max_price)

    from urllib.parse import urlencode
    search_url = "https://suchen.mobile.de/fahrzeuge/search.html?" + urlencode(params)

    captured_json: list = []

    def on_response(response):
        try:
            if "mobile.de" not in response.url or response.status != 200:
                return
            if "json" not in response.headers.get("content-type", ""):
                return
            data = response.json()
            if not isinstance(data, dict):
                return
            # Look for search results in common keys
            for key in ("data", "items", "listings", "results", "ads", "searchResults"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    captured_json.extend(val)
                    return
                if isinstance(val, dict):
                    for sub in ("items", "listings", "ads"):
                        sub_val = val.get(sub)
                        if isinstance(sub_val, list) and sub_val:
                            captured_json.extend(sub_val)
                            return
        except Exception:
            pass

    listings = []
    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(locale="de-DE")
            page = context.new_page()
            page.on("response", on_response)
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)  # let consent modal appear
            print(f"  [mde] pagina titel: {page.title()[:80]}")

            # Accept consent — try main frame + all iframes (Sourcepoint CMP uses iframes)
            _accept_consent_all_frames(page)

            # Consent click may trigger page reload — wait for it to settle
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(4000)  # wait for listings to render

            page_title = page.title()
            if "Zugriff" in page_title or "Access denied" in page_title or not page_title:
                print("  [mde] geblokkeerd door Akamai (GitHub Actions IP niet toegestaan)")
                browser.close()
                return []
            links_check = page.query_selector_all("a[href*='/fahrzeuge/details']")
            print(f"  [mde] na consent: {len(links_check)} detail-links")

            if captured_json:
                print(f"  [mde] {len(captured_json)} items via API interceptie")
                for item in captured_json[:40]:
                    try:
                        listing_id = str(item.get("id", item.get("listingId", "")))
                        title = item.get("title", item.get("name", ""))[:100]
                        price_raw = item.get("price", item.get("grossPrice", {}))
                        if isinstance(price_raw, dict):
                            price_eur = int(re.sub(r"[^\d]", "", str(price_raw.get("amount", price_raw.get("value", 0)) or 0)) or 0)
                            price_type = "fixed" if price_eur > 0 else "ask"
                        else:
                            price_eur, price_type = _parse_price_text(str(price_raw))
                        year_raw = item.get("year", item.get("firstRegistrationYear", 0))
                        year = int(year_raw or 0)
                        if year == 0:
                            year = _extract_year_from_text(title)
                        mileage_raw = item.get("mileage", item.get("mileageInKm", 0))
                        mileage = int(re.sub(r"[^\d]", "", str(mileage_raw or 0)) or 0)
                        vip = item.get("url", item.get("link", ""))
                        item_url = vip if vip.startswith("http") else f"https://www.mobile.de{vip}"
                        loc = item.get("location", item.get("seller", {}) or {})
                        location = loc.get("city", loc.get("zip", "")) if isinstance(loc, dict) else ""
                        if listing_id:
                            listings.append({"id": f"mde:{listing_id}", "platform": "mde", "title": title, "price_eur": price_eur, "price_type": price_type, "year": year, "mileage_km": mileage, "url": item_url, "location": location, "image_url": "", "scraped_at": _now()})
                    except Exception:
                        continue
            else:
                # DOM fallback: extract from rendered listing links
                link_els = page.query_selector_all("a[href*='/fahrzeuge/details']")
                print(f"  [mde] geen API data, {len(link_els)} DOM detail-links")
                seen: set = set()
                for link in link_els[:40]:
                    try:
                        href = link.get_attribute("href") or ""
                        if not href or href in seen:
                            continue
                        seen.add(href)
                        item_url = f"https://www.mobile.de{href}" if not href.startswith("http") else href
                        m_id = re.search(r"/(\d+)\.html", href)
                        listing_id = m_id.group(1) if m_id else ""
                        if not listing_id:
                            continue
                        # Walk up to find the containing article/card
                        card_text = page.evaluate(
                            "el => { let p = el; for (let i=0; i<5; i++) { p = p.parentElement; if (!p) break; if (p.tagName === 'ARTICLE' || p.tagName === 'LI') return p.innerText; } return el.innerText; }",
                            link
                        ) or link.inner_text()
                        title = card_text.split("\n")[0].strip()[:100]
                        price_eur, price_type = _parse_price_text(card_text)
                        year = _extract_year_from_text(card_text)
                        m_km = re.search(r"([\d.,]+)\s*km", card_text)
                        mileage = int(re.sub(r"[^\d]", "", m_km.group(1)) or 0) if m_km else 0
                        listings.append({
                            "id": f"mde:{listing_id}",
                            "platform": "mde",
                            "title": title,
                            "price_eur": price_eur,
                            "price_type": price_type,
                            "year": year,
                            "mileage_km": mileage,
                            "url": item_url,
                            "location": "",
                            "image_url": "",
                            "scraped_at": _now(),
                        })
                    except Exception:
                        continue
            browser.close()
    except Exception as e:
        print(f"  [mde] scrape failed: {e}")
    print(f"  [mde] {len(listings)} aanbiedingen gevonden")
    return listings


# ---------------------------------------------------------------------------
# Facebook Marketplace  (Playwright, optional)
# ---------------------------------------------------------------------------

def _scrape_facebook(auth_state_path: str = "fb_auth_state.json") -> list:
    import base64
    import os
    import tempfile

    # Decode base64 auth state from environment variable (set as GitHub Secret)
    # Supports both plain base64 and gzip+base64 (for large auth states > 64KB limit)
    tmp_path = None
    fb_auth_env = os.environ.get("FB_AUTH_STATE", "")
    if fb_auth_env:
        try:
            import gzip
            raw = base64.b64decode(fb_auth_env)
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass  # not gzipped, use as-is
            tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False)
            tmp.write(raw)
            tmp.close()
            tmp_path = tmp.name
            auth_state_path = tmp_path
        except Exception as e:
            print(f"  [fb] failed to decode FB_AUTH_STATE: {e}")

    has_auth = os.path.exists(auth_state_path)

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
            context = browser.new_context(storage_state=auth_state_path) if has_auth else browser.new_context(user_agent=HEADERS["User-Agent"])
            page = context.new_page()
            page.goto(
                "https://www.facebook.com/marketplace/amsterdam/search/"
                "?query=mercedes+oldtimer&sortBy=creation_time_descend&radiusKm=200",
                timeout=30000,
                wait_until="domcontentloaded",
            )
            page.wait_for_timeout(5000)

            # Dismiss cookie/login dialogs
            for sel in [
                "[aria-label='Close']",
                "[data-testid='cookie-policy-manage-dialog-accept-button']",
                "button:has-text('Alle accepteren')",
                "button:has-text('Accept all')",
                "button:has-text('Only allow essential')",
            ]:
                try:
                    page.click(sel, timeout=1500)
                    page.wait_for_timeout(500)
                except Exception:
                    continue

            page_title = page.title()
            current_url = page.url
            print(f"  [fb] pagina titel: {page_title[:80]}")
            print(f"  [fb] url na laden: {current_url[:100]}")

            # Detect expired session (redirect to login page)
            if "/login" in current_url or page_title.strip() == "Facebook":
                print("  [fb] sessie verlopen — vernieuw FB_AUTH_STATE in GitHub Secrets")
                browser.close()
                return []

            # Scroll to trigger lazy loading of marketplace items
            for _ in range(3):
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(1500)

            # Wait for marketplace items to appear
            try:
                page.wait_for_selector("a[href*='/marketplace/item/']", timeout=10000)
            except Exception:
                pass

            auth_label = "ingelogd" if has_auth else "zonder login"

            # Debug: log all unique href patterns to find correct selector
            all_hrefs = page.evaluate("""
                () => [...new Set(
                    [...document.querySelectorAll('a[href]')]
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && h.includes('marketplace'))
                    .slice(0, 20)
                )]
            """)
            print(f"  [fb] marketplace hrefs gevonden: {all_hrefs[:10]}")

            # Try all known selector patterns
            cards = page.query_selector_all("div[data-pagelet='MarketplaceSearchResults'] a[href*='/marketplace/item/']")
            if not cards:
                cards = page.query_selector_all("a[href*='/marketplace/item/']")
            if not cards:
                cards = page.query_selector_all("[href*='/marketplace/item/']")
            if not cards:
                # Try any link containing numeric item IDs typical for FB marketplace
                cards = page.query_selector_all("a[href*='marketplace']")
            print(f"  [fb] {len(cards)} item-links gevonden na scrollen")
            print(f"  [fb] {len(cards)} listings gevonden ({auth_label})")
            seen_fb: set = set()
            for card in cards[:60]:
                try:
                    href = card.get_attribute("href") or ""
                    item_id = re.search(r"/item/(\d+)/", href)
                    if not item_id or item_id.group(1) in seen_fb:
                        continue
                    seen_fb.add(item_id.group(1))
                    # Strip query params from URL to get clean item link
                    item_url = f"https://www.facebook.com/marketplace/item/{item_id.group(1)}/"
                    text = card.inner_text()
                    title = text.split("\n")[0].strip()[:100]
                    price_eur, price_type = _parse_price_text(text)
                    year = _extract_year_from_text(text)
                    # Skip obvious non-car listings (price < €200 fixed, or title too short)
                    if price_type == "fixed" and 0 < price_eur < 200:
                        continue
                    if len(title) < 5:
                        continue
                    listings.append({
                        "id": f"fb:{item_id.group(1)}",
                        "platform": "fb",
                        "title": title,
                        "price_eur": price_eur,
                        "price_type": price_type,
                        "year": year,
                        "mileage_km": 0,
                        "url": item_url,
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

def _accept_consent_all_frames(page) -> None:
    """Click 'accept all' consent buttons in the main page and all iframes."""
    js = """
        () => {
            const pattern = /alle akzept|accept all|zustimmen|alle cookies|akzeptieren/i;
            document.querySelectorAll('button, [role="button"]').forEach(b => {
                if (pattern.test(b.textContent)) b.click();
            });
        }
    """
    try:
        page.evaluate(js)
    except Exception:
        pass
    for frame in page.frames:
        try:
            frame.evaluate(js)
        except Exception:
            pass


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

    print("  [profiel 3] NL belastingvrij (alle merken ≤ 1987, max €7.000)")
    for scraper, name in [
        (lambda: scrape_marktplaats_profile("mercedes", max_year=1987, max_price=7000), "marktplaats mercedes"),
        (lambda: scrape_marktplaats_profile("volkswagen", max_year=1987, max_price=7000), "marktplaats vw"),
        (lambda: scrape_marktplaats_profile("bmw", max_year=1987, max_price=7000), "marktplaats bmw"),
        (lambda: scrape_2dehands_profile("mercedes", max_year=1987, max_price=7000), "2dehands mercedes"),
        (lambda: scrape_2dehands_profile("volkswagen", max_year=1987, max_price=7000), "2dehands vw"),
        (lambda: _scrape_autoscout24("", max_year=1987, max_price=7000), "autoscout24"),
    ]:
        results = scraper()
        filtered = [
            r for r in results
            if r["year"] > 0 and r["year"] <= 1987
            and (r["price_eur"] <= 7000 or r["price_type"] != "fixed")
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
