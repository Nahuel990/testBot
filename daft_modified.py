import json
import os
import time
# Use curl_cffi requests for browser impersonation
from curl_cffi import requests
from bs4 import BeautifulSoup
from typing import Dict, List
from dotenv import load_dotenv

# Load env vars from .env if present
load_dotenv()

# ========= CONFIG =========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("TELEGRAM_TOKEN and CHAT_ID must be set in environment variables or .env file")

POLL_SECONDS = 45
STATE_FILE = "seen_listings_multi.json"

SEARCHES: List[Dict[str, str]] = [
    {
        "name": "Dublin City <= 2200",
        "url": "https://www.daft.ie/property-for-rent/dublin-city?format=rss&sort=publishDateDesc&rentalPrice_to=1300"
    },
    {
        "name": "Dublin 8 <= 2000",
        "url": "https://www.daft.ie/sharing/dublin-8-dublin?rentalPrice_to=800&sort=publishDateDesc"
    },
    {
        "name": "Room South Dublin <= 1100",
        "url": "https://www.daft.ie/sharing/dublin-city?rentalPrice_to=800&sort=publishDateDesc"
    },
]
# ==========================

# UA is handled by impersonate="chrome"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"seen_global": [], "seen_by_search": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen_global": [], "seen_by_search": {}}

def save_state(state: dict) -> None:
    # limita tamaño para que no crezca infinito
    state["seen_global"] = state.get("seen_global", [])[-3000:]
    for k in list(state.get("seen_by_search", {}).keys()):
        state["seen_by_search"][k] = state["seen_by_search"][k][-1500:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def tg_send(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # standard requests or curl_cffi requests both work for API
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, impersonate="chrome")
    r.raise_for_status()

def fetch_new_listing_links(search_url: str) -> List[str]:
    # impersonate="chrome" mimics a real Chrome browser's TLS signature
    r = requests.get(search_url, impersonate="chrome", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    # Selector típico de cards en Daft (si cambia, lo ajustamos)
    links = []
    for a in soup.select("a[data-testid='listing-card-link']"):
        href = a.get("href")
        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.daft.ie" + href
        # href = href.split("?")[0]
        links.append(href)

    # fallback si el selector no devuelve nada: agarra links de daft de la página
    if not links:
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "/for-rent/" in href or "/sharing/" in href:
                if href.startswith("/"):
                    href = "https://www.daft.ie" + href
                # href = href.split("?")[0]
                links.append(href)

    # quita duplicados manteniendo orden
    seen = set()
    out = []
    for x in links:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:40]  # con mirar los primeros 40 alcanza

def main():
    state = load_state()
    seen_global = set(state.get("seen_global", []))
    seen_by_search = state.get("seen_by_search", {})


    while True:
        for s in SEARCHES:
            name = s["name"]
            url = s["url"]
            key = name  # clave por búsqueda

            if key not in seen_by_search:
                seen_by_search[key] = []

            seen_local = set(seen_by_search[key])

            try:
                links = fetch_new_listing_links(url)
            except Exception as e:
                # no spamear: solo avisa error ocasional
                print(f"[WARN] {name}: {e}")
                continue

            new_links = []
            for link in links:
                if link not in seen_global and link not in seen_local:
                    new_links.append(link)

            # Si es la primera vez, no dispares 40 notifs: inicializa “baseline”
            if not seen_global and len(new_links) > 10:
                for link in links:
                    seen_global.add(link)
                    seen_by_search[key].append(link)
                save_state({"seen_global": list(seen_global), "seen_by_search": seen_by_search})
                continue

            for link in new_links:
                msg = f"🏠 NUEVO ({name})\n{link}"
                try:
                    tg_send(msg)
                except Exception as e:
                    print(f"[WARN] Telegram send failed: {e}")

                seen_global.add(link)
                seen_by_search[key].append(link)

            save_state({"seen_global": list(seen_global), "seen_by_search": seen_by_search})

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
