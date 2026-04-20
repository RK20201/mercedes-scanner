import re
import time

import requests


def _to_int(value) -> int:
    if isinstance(value, int):
        return value
    return int(re.sub(r"[^\d]", "", str(value or 0)) or 0)

TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _format_message(deal: dict) -> str:
    profile = deal.get("profile", "mercedes_oldtimer")
    title = deal.get("title", "")[:60]
    price_eur = _to_int(deal.get("price_eur", 0))
    price_type = deal.get("price_type", "unknown")
    mileage = _to_int(deal.get("mileage_km", 0))
    year = _to_int(deal.get("year", 0))
    location = deal.get("location", "")
    url = deal.get("url", "")
    platform_raw = deal.get("platform", "")
    platform_names = {
        "mp": "Marktplaats",
        "2dh": "2dehands.be",
        "as24": "AutoScout24",
        "kaz": "Kleinanzeigen",
        "mde": "Mobile.de",
        "fb": "Facebook",
    }
    platform = platform_names.get(platform_raw, platform_raw.title())
    score = deal.get("opportunity_score", 0)
    reason = deal.get("reason", "")

    price_str = f"€{price_eur:,}".replace(",", ".") if price_eur > 0 else "Prijs op aanvraag"
    mileage_str = f"{mileage:,} km".replace(",", ".") if mileage > 0 else "km onbekend"
    year_estimated = deal.get("year_estimated", False)
    year_str = (f"~{year}" if year_estimated else str(year)) if year > 0 else "jaar onbekend"

    if profile == "nl_belastingvrij":
        icon = "🏛️"
        label = "OLDTIMER"
        tax_line = f"📅 {reason}\n"
    elif price_type != "fixed":
        icon = "🔨"
        label = "BIEDEN"
        tax_line = ""
    else:
        icon = "🚗"
        label = "DEAL"
        tax_line = ""

    details = (
        f"{price_str} | {year_str} | {location}"
        if profile == "nl_belastingvrij"
        else f"{price_str} | {mileage_str} | {location}"
    )

    return (
        f"{icon} {label}: {title}\n"
        f"💶 {details}\n"
        f"{tax_line}"
        f"⭐ Score {score}/10 | {reason}\n"
        f"🔗 {url}\n"
        f"📍 {platform}"
    )


def send_message(message: str, token: str, chat_id: str) -> bool:
    url = TELEGRAM_URL.format(token=token)
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=15)
        return resp.status_code == 200
    except Exception as e:
        print(f"  [telegram] send failed: {e}")
        return False


def notify_deals(deals: list, token: str, chat_id: str) -> None:
    if not deals:
        return
    print(f"  Versturen van {len(deals)} Telegram-berichten...")
    for deal in deals:
        msg = _format_message(deal)
        ok = send_message(msg, token, chat_id)
        status = "✓" if ok else "✗"
        print(f"    {status} {deal['id']}: {deal.get('title', '')[:40]}")
        time.sleep(1)
