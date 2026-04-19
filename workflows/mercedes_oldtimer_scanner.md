# Workflow: Mercedes Oldtimer Scanner

## Doel
Elk uur nieuwe auto-aanbiedingen scrapen op 6 platforms en via WhatsApp melden als een aanbieding opvallend goedkoop of interessant is.

## Drie zoekprofielen

| Profiel | Wat | Platforms |
|---|---|---|
| `mercedes_oldtimer` | Alle Mercedes t/m bouwjaar 1998 | Alle 6 |
| `om_diesel` | Mercedes met OM605/606/612/613 motor, elk jaar | Marktplaats, 2dehands |
| `nl_belastingvrij` | Alle merken t/m 1987, max €10.000 | Marktplaats, 2dehands, AutoScout24 |

## Benodigde invoer (.env / GitHub Secrets)

| Key | Waarde |
|---|---|
| `CALLMEBOT_API_KEY` | Jouw CallMeBot API-key (zie activering hieronder) |
| `PHONE_NUMBER` | Je WhatsApp-nummer met landcode, bijv. `+31612345678` |

## Tools

| Tool | Bestand | Functie |
|---|---|---|
| Scraper | `tools/scrape_listings.py` | Haalt aanbiedingen op van alle platforms |
| Analyse | `tools/analyze_deals.py` | Beoordeelt statistische prijs + zeldzaamheid |
| Notificatie | `tools/notify_whatsapp.py` | Verstuurt WhatsApp via CallMeBot |
| State | `tools/track_seen.py` | Houdt bij welke aanbiedingen al gezien zijn |
| Orchestrator | `main.py` | Coördineert alle stappen |

## Eenmalige setup

### 1. GitHub repo aanmaken (public)
Maak een public repository op GitHub (public = gratis onbeperkte Actions-minuten).
Push alle bestanden hiernaar toe.

### 2. CallMeBot activeren
1. Open WhatsApp en stuur het bericht `I allow callmebot to send me messages` naar **+34 644 82 94 27**
2. Je ontvangt een API-key terug
3. Sla deze op als GitHub Secret `CALLMEBOT_API_KEY`

### 3. GitHub Secrets instellen
Ga naar je repo → Settings → Secrets and variables → Actions → New repository secret:
- `CALLMEBOT_API_KEY` = jouw CallMeBot key
- `PHONE_NUMBER` = jouw WhatsApp-nummer (bijv. `+31612345678`)

### 4. Facebook Marketplace (optioneel)
Facebook vereist een ingelogde sessie. Om dit in te stellen:
```bash
pip install playwright
playwright install chromium
playwright codegen https://www.facebook.com/marketplace --save-storage=fb_auth_state.json
```
Log handmatig in in het geopende browservenster, sluit daarna de browser.
Commit `fb_auth_state.json` naar de repo.
**Let op:** de sessie verloopt na 30-60 dagen en moet dan opnieuw worden aangemaakt.

## Lokaal testen
```bash
pip install -r requirements.txt
# Maak .env bestand met je keys
python main.py
```

## Handmatig uitvoeren via GitHub
Ga naar repo → Actions → Mercedes Oldtimer Scanner → Run workflow

## Deal-beoordeling

### Score-logica (0-10, deal bij ≥ 6)
- Basisprijs Mercedes/OM profiel: 4 punten
- Basisprijs NL belastingvrij profiel: 6 punten (altijd interessant)
- Prijs 10% onder mediaan: +1 | 25% onder: +2 | 40% onder: +3
- Zeldzaam model (500E, R107, OM606, G-Wagen, etc.): +2
- Bied-aanbieding (potentieel onontdekt): +1

### Zeldzame modellen die altijd worden gemarkeerd
500E, E60 AMG, 2.3-16, 2.5-16 Cosworth, R107 SL, G-Wagen, 230GE, 300GD, Pagode, W111, W113, OM605, OM606

### Drempel aanpassen
Pas de minimale score aan in `tools/analyze_deals.py`, regel `if score >= 6`:
- Score ≥ 5: meer meldingen, ook matige deals
- Score ≥ 7: minder meldingen, alleen sterke deals

## Berichttypen

- 🚗 **DEAL** — vaste prijs, statistisch goedkoop
- 🔨 **BIEDEN** — bied-aanbieding
- 🏛️ **OLDTIMER** — belastingvrij (40+ jaar) profiel

## Bekende beperkingen per platform

| Platform | Beperking |
|---|---|
| Kleinanzeigen.de | DataDome anti-bot — kan blokkeren; systeem slaat dan over en gaat verder |
| Mobile.de | Vereist Referer-header; 403 bij directe verzoeken |
| AutoScout24 | Akamai rate-limiting; bij ≥ 429 response: skip |
| Facebook | Vereist maandelijks vernieuwen van auth-sessie |
| Alle platforms | CSS-selectors kunnen veranderen bij site-updates |

## Onderhoud

- **Maandelijks:** Vernieuw Facebook-sessie als je die gebruikt
- **Kwartaal:** Controleer of scraping nog werkt (logs bekijken in GitHub Actions)
- **Na 60 dagen inactiviteit:** GitHub schakelt scheduled workflows uit — push een commit om te reactiveren

## Probleemoplossing

**Geen WhatsApp-berichten ontvangen:**
1. Controleer of `CALLMEBOT_API_KEY` en `PHONE_NUMBER` correct zijn ingesteld
2. Voer `python main.py` lokaal uit en kijk naar de uitvoer
3. Check de GitHub Actions logs voor foutmeldingen

**Scraping werkt niet:**
- Bekijk de platformspecifieke foutmeldingen in de logs
- Kleinanzeigen en Mobile.de zijn het meest kwetsbaar; de andere platforms zijn stabiel

**Te veel/te weinig meldingen:**
- Pas de score-drempel aan in `tools/analyze_deals.py`
- Voor belastingvrij-profiel: verhoog de baseline van 6 om minder meldingen te krijgen
