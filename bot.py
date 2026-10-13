import os
import re
import time
import threading
import requests
import cloudscraper
from bs4 import BeautifulSoup
from flask import Flask
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EA_TAX = 0.05

CANALI_LEAK = [
    "https://t.me/s/Fut_Scoreboard",
    "https://t.me/s/FutSheriff_Official",
    "https://t.me/s/fifatradingromania"
]

PAROLE_CHIAVE_CALDE = ["evo", "evolution", "sbc", "potm", "leak", "max ", "req", "upgrade", "playstyle", "pack", "fodder"]

messaggi_gia_visti = set()
evo_gia_viste = set()
ultimo_update_id = 0

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

def invia_telegram(testo, chat_id=None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_TOKEN or not target_chat:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": testo,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def chiedi_a_gemini(prompt_utente):
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    sistema = (
        "Sei il miglior analista e trader di EA Sports FC 27 Ultimate Team (mercato PlayStation, budget utente: 800.000 crediti). "
        "Rispondi in italiano, in modo diretto, schematico e pratico (massimo 10-12 righe). "
        "Non usare formattazione Markdown complessa (niente # o **), usa solo testo semplice ed elenchi puntati con •. "
        "Ricorda sempre di considerare la tassa EA del 5% e la regola d'oro: comprare nel panico/leak e vendere nell'hype prima delle 19:00."
    )
    try:
        r = requests.post(
            url,
            json={"contents": [{"parts": [{"text": f"{sistema}\n\nRichiesta: {prompt_utente}"}]}]},
            timeout=20
        )
        risposta = r.json()
        testo = risposta["candidates"][0]["content"]["parts"][0]["text"]
        return testo.replace("**", "").replace("*", "•").replace("<", "&lt;").replace(">", "&gt;")
    except Exception as e:
        return f"⚡ Errore temporaneo analisi IA: {e}"

def leggi_ultimi_leak_live():
    raccolta = []
    for url in CANALI_LEAK:
        try:
            nome_canale = url.split("/")[-1]
            resp = scraper.get(url, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                blocchi = soup.find_all("div", class_="tgme_widget_message_text")
                for b in blocchi[-2:]:
                    testo = b.get_text(separator=" ").strip()
                    if len(testo) > 15:
                        raccolta.append((nome_canale, testo[:300]))
        except Exception as e:
            print(f"Errore lettura {url}: {e}")
    return raccolta

def leggi_evo_futgg():
    lista_evo = []
    try:
        resp = scraper.get("https://www.fut.gg/evolutions/", timeout=12)
        if resp.status_code == 200:
            links = re.findall(r'/evolutions/\d+-[a-zA-Z0-9-]+/', resp.text)
            visti = []
            for l in links:
                if l not in visti:
                    visti.append(l)
            for link in visti[:6]:
                nome = link.split("-", 1)[-1].replace("/", "").replace("-", " ").title()
                lista_evo.append((nome, f"https://www.fut.gg{link}"))
    except Exception as e:
        print(f"Errore FUT.GG: {e}")
    return lista_evo

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.
