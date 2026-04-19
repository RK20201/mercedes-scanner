import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from tools.scrape_listings import scrape_all_platforms
from tools.track_seen import load_seen, filter_new, mark_seen, prune_old_ids, save_seen
from tools.analyze_deals import analyze_deals
from tools.notify_whatsapp import notify_deals

SEEN_PATH = "data/seen_listings.json"


def main():
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not telegram_token or not telegram_chat_id:
        print("FOUT: TELEGRAM_BOT_TOKEN en TELEGRAM_CHAT_ID zijn verplicht in .env")
        sys.exit(1)

    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}] Mercedes Scanner gestart")

    seen_data = load_seen(SEEN_PATH)
    seen_data = prune_old_ids(seen_data, days=60)
    print(f"  Eerder gezien: {seen_data.get('total_seen', 0)} aanbiedingen")

    print("Scrapen van alle platforms...")
    all_listings = scrape_all_platforms()
    print(f"  {len(all_listings)} totaal gevonden")

    new_listings = filter_new(all_listings, seen_data)
    print(f"  {len(new_listings)} nieuw (nog niet eerder gezien)")

    # Mark all as seen before analysis to avoid re-notifying on next run if something fails
    seen_data = mark_seen(all_listings, seen_data)
    save_seen(seen_data, SEEN_PATH)

    if not new_listings:
        print("Geen nieuwe aanbiedingen. Klaar.")
        return

    print("Analyseren op deals...")
    deals = analyze_deals(new_listings, all_listings)
    print(f"  {len(deals)} potentiële deals gevonden")

    if deals:
        notify_deals(deals, telegram_token, telegram_chat_id)
    else:
        print("  Geen deals deze run, geen berichten verstuurd.")

    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}] Klaar")


if __name__ == "__main__":
    main()
