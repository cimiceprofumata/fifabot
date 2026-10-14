import os
import re
import time
import threading
import requests
import cloudscraper
from flask import Flask
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
EA_TAX = 0.05

utenti_iscritti = set()
if TELEGRAM_CHAT_ID:
    for cid in TELEGRAM_CHAT_ID.split(","):
        if cid.strip():
            utenti_iscritti.add(cid.strip())

CANALI_TELEGRAM_APERTI = [
    "Fut_Scoreboard",
    "futpoliceleaks",
    "fifatradingromania",
    "futtrading"
]

PROFILI_X_LEAKERS = [
    "https://x.com/Fut_Scoreboard",
    "https://x.com/FutPoliceLeaks",
    "https://x.com/KillerFutTrade",
    "https://x.com/FutSheriff",
    "https://x.com/AsyFutTrader",
    "https://x.com/DonkTrading"
]

FRASI_SPAZZATURA = [
    "if you have telegram",
    "you can contact",
    "right away",
    "view in telegram",
    "download telegram",
    "join channel",
    "subscribers",
    "preview channel",
    "send message",
    "tg://resolve",
    "context",
    "embed"
]

PAROLE_TRIGGER = [
    "evo", "evolution", "max ", "max 8", "max 7", "req", "boost",
    "playstyle", "ps+", "pace", "overall", "rating", "sbc", "potm", "leaked",
    "lb", "rb", "cb", "cdm", "cm", "cam", "lw", "rw", "st", "fullback"
]

messaggi_gia_visti = set()
ultimo_update_id = 0
modello_scoperto = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache"
}

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)

def invia_telegram(testo, chat_id=None):
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    destinatari = [str(chat_id)] if chat_id else list(utenti_iscritti)

    for target in destinatari:
        payload = {
            "chat_id": target,
            "text": testo[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print("Errore Telegram:", e)

def trova_modelli_attivi():
    global modello_scoperto
    modelli = [
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-flash-latest"
    ]
    if modello_scoperto and modello_scoperto not in modelli:
        modelli.insert(0, modello_scoperto)
    try:
        base = "https://generativelanguage.googleapis.com/v1beta/models"
        r = requests.get(f"{base}?key={GEMINI_API_KEY}", timeout=10).json()
        for m in r.get("models", []):
            nome = m.get("name", "").replace("models/", "")
            metodi = m.get("supportedGenerationMethods", [])
            if "generateContent" in metodi:
                if "flash" in nome or "gemini-3" in nome:
                    if nome not in modelli:
                        modelli.insert(0, nome)
    except Exception:
        pass
    return modelli

def scarica_testo_jina(target_url):
    try:
        h = dict(HEADERS)
        h["X-No-Cache"] = "true"
        url_j = f"https://r.jina.ai/{target_url}"
        resp = requests.get(url_j, headers=h, timeout=18)
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text
    except Exception:
        pass
    return ""

def pulisci_righe_testo(raw_text, min_len=20):
    righe_buone = []
    for r in raw_text.split("\n"):
        rc = r.strip()
        rc_low = rc.lower()
        if len(rc) < min_len:
            continue
        if rc.startswith("![") or rc.startswith("http"):
            continue
        if rc.startswith("Title:") or rc.startswith("URL Source:"):
            continue
        if any(bad in rc_low for bad in FRASI_SPAZZATURA):
            continue
        righe_buone.append(rc)
    return righe_buone

def leggi_leak_reali_x_e_telegram():
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_str = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")

    for u in PROFILI_X_LEAKERS[:4]:
        handle = u.split("/")[-1]
        raw = scarica_testo_jina(u)
        righe = pulisci_righe_testo(raw, min_len=35)
        for linea in righe:
            l_low = linea.lower()
            if any(k in l_low for k in PAROLE_TRIGGER):
                bad_x = ["log in", "sign up", "terms of service", "cookie"]
                if not any(xb in l_low for xb in bad_x):
                    raccolta.append(f"[{ora_str} | @{handle} X]: {linea[:300]}")

    for canale in CANALI_TELEGRAM_APERTI:
        raw = scarica_testo_jina(f"https://t.me/s/{canale}")
        righe = pulisci_righe_testo(raw, min_len=30)
        for post in righe[-3:]:
