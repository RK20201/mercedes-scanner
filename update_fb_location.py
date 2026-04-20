"""
Wijzigt de Facebook Marketplace locatie naar Enschede en slaat nieuwe auth state op.
Gebruik: python update_fb_location.py
"""
import base64
import gzip
import json
import tempfile
import os
from playwright.sync_api import sync_playwright

AUTH_FILE = "fb_auth_state.json"
B64_FILE = "fb_auth_state_b64.txt"


def main():
    if not os.path.exists(AUTH_FILE):
        print("fb_auth_state.json niet gevonden. Eerst inloggen via playwright codegen.")
        return

    print("Browser openen met huidige auth state...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=AUTH_FILE)
        page = context.new_page()

        print("Naar Facebook Marketplace gaan...")
        page.goto("https://www.facebook.com/marketplace/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        # Dialogen wegklikken
        for sel in ["[aria-label='Close']", "button:has-text('Alle accepteren')", "button:has-text('Accept all')"]:
            try:
                page.click(sel, timeout=2000)
                page.wait_for_timeout(500)
            except Exception:
                pass

        # Locatie input zoeken en aanpassen
        print("Locatie aanpassen naar Enschede...")
        changed = False
        for sel in [
            "input[placeholder*='locatie']",
            "input[placeholder*='location']",
            "input[placeholder*='Locatie']",
            "input[placeholder*='Location']",
            "[aria-label*='locatie'] input",
            "[aria-label*='location'] input",
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    el.triple_click()
                    page.wait_for_timeout(300)
                    el.fill("")
                    el.type("Enschede", delay=100)
                    page.wait_for_timeout(2000)
                    # Eerste suggestie selecteren
                    page.keyboard.press("ArrowDown")
                    page.wait_for_timeout(500)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(3000)
                    changed = True
                    print(f"  Locatie input gevonden en ingevuld ({sel})")
                    break
            except Exception:
                continue

        if not changed:
            print("  Locatie input niet automatisch gevonden.")
            print("  Pas de locatie handmatig aan in de browser naar 'Enschede, Netherlands'")
            print("  Druk daarna op Enter in de terminal om door te gaan...")
            input()

        print("Nieuwe auth state opslaan...")
        context.storage_state(path=AUTH_FILE)
        browser.close()

    # Slim b64 genereren (cookies only, gzip)
    with open(AUTH_FILE) as f:
        data = json.load(f)

    slim = {
        "cookies": data["cookies"],
        "origins": [{"origin": o["origin"], "localStorage": []} for o in data.get("origins", [])],
    }
    b64 = base64.b64encode(gzip.compress(json.dumps(slim).encode(), compresslevel=9)).decode()
    with open(B64_FILE, "w") as f:
        f.write(b64)

    print(f"\nGereed! b64 lengte: {len(b64)} tekens (GitHub max: 65536)")
    print(f"\nKopieer deze waarde naar GitHub Secret 'FB_AUTH_STATE':\n")
    print(b64)


if __name__ == "__main__":
    main()
