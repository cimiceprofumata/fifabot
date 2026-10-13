import os
import re
import time
import threading
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
from bs4 import BeautifulSoup
from flask import Flask
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
EA_TAX = 0.05

CANALI_LEAK = [
    "Fut_Scoreboard",
    "FutSheriff_Official",
    "fifatradingromania"
]

PAROLE_CALDE = [
    "evo", "evolution", "sbc", "potm", "leak",
    "max ", "req", "upgrade", "playstyle", "fodder", "promo"
]

messaggi_gia_visti = set()
ultimo_update_id = 0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8"
}

def invia_telegram(testo, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_TOKEN or not target:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
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

def chiedi_a_gemini_live(prompt_utente, usa_ricerca_web=True):
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata nelle Environment Variables di Render."

    oggi = datetime.now().strftime("%d/%m/%Y")
    sistema = (
        f"Data di oggi: {oggi}. Sei un top trader di EA Sports FC Ultimate Team "
        "(mercato PlayStation, budget utente: 800.000 crediti). "
        "Analizza le notizie e i leak forniti e indica cosa comprare, a quale fascia di prezzo "
        "e quando rivendere considerando la tassa EA del 5%. "
        "Rispondi in italiano in modo diretto, pratico e schematico (massimo 10-12 righe). "
        "Non usare simboli Markdown come asterischi (*) o cancelletti (#). Usa solo elenchi con il pallino •."
    )
    testo_completo = f"{sistema}\n\nRichiesta: {prompt_utente}"

    # 4 tentativi in cascata per evitare errori 'candidates' o blocchi modello/tool
    tentativi = [
        ("gemini-2.5-flash", True),
        ("gemini-2.5-flash", False),
        ("gemini-2.0-flash", True),
        ("gemini-2.0-flash", False),
    ]
    if not usa_ricerca_web:
        tentativi = [("gemini-2.5-flash", False), ("gemini-2.0-flash", False)]

    ultimo_errore = "Nessuna risposta ricevuta"
    for modello, con_search in tentativi:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent?key={GEMINI_API_KEY}"
        body = {"contents": [{"parts": [{"text": testo_completo}]}]}
        if con_search:
            body["tools"] = [{"google_search": {}}]
        try:
            r = requests.post(url, json=body, timeout=25)
            risposta = r.json()

            if "error" in risposta:
                ultimo_errore = risposta["error"].get("message", str(risposta["error"]))
                continue

            candidati = risposta.get("candidates", [])
            if not candidati:
                ultimo_errore = f"Risposta bloccata o vuota ({risposta.get('promptFeedback', 'No candidates')})"
                continue

            parti = candidati[0].get("content", {}).get("parts", [])
            testi = [p.get("text", "") for p in parti if "text" in p]
            out = "\n".join(testi).strip()
            if out:
                out = out.replace("**", "").replace("*", "•").replace("#", "")
                return out.replace("<", "&lt;").replace(">", "&gt;")
        except Exception as e:
            ultimo_errore = str(e)
            continue

    return f"⚠️ Impossibile completare l'analisi IA ({ultimo_errore[:120]}). Controlla che la GEMINI_API_KEY su Render sia attiva e senza spazi."

def estrai_messaggi_html_telegram(html_text, nome_canale):
    risultati = []
    if not html_text or "tgme_widget_message_text" not in html_text:
        return risultati
    soup = BeautifulSoup(html_text, "html.parser")
    blocchi = soup.find_all("div", class_="tgme_widget_message_text")
    for b in blocchi[-3:]:
        txt = b.get_text(separator=" ").strip()
        # Scarta scritte di sistema di Telegram
        if len(txt) > 20 and "Download" not in txt and "Send Message" not in txt:
            risultati.append((nome_canale, txt[:280]))
    return risultati

def leggi_leak_con_bypass():
    raccolta = []

    # 1. Lettura HTML pulita dei canali Telegram tramite codetabs proxy (o connessione diretta)
    for canale in CANALI_LEAK:
        target_url = f"https://t.me/s/{canale}"
        urls_da_provare = [
            target_url,
            f"https://api.codetabs.com/v1/proxy?quest={quote(target_url, safe='')}",
            f"https://api.allorigins.win/raw?url={quote(target_url, safe='')}"
        ]
        for u in urls_da_provare:
            try:
                resp = requests.get(u, headers=HEADERS, timeout=10)
                if resp.status_code == 200 and "tgme_widget_message_text" in resp.text:
                    estratti = estrai_messaggi_html_telegram(resp.text, canale)
                    if estratti:
                        raccolta.extend(estratti[-2:])
                        break
            except Exception:
                continue

    # 2. Integrazione sempre attiva da Google News RSS (non bloccabile da nessun server)
    try:
        rss_url = "https://news.google.com/rss/search?q=%22Ultimate+Team%22+(Leak+OR+Evolution+OR+SBC+OR+FUT)+when:3d&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(rss_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:4]:
                titolo = item.find("title").text
                if titolo:
                    raccolta.append(("Web Leak Radar", titolo))
    except Exception as e:
        print("Errore RSS:", e)

    return raccolta

def leggi_evo_con_bypass():
    lista_evo = []
    target = "https://www.fut.gg/evolutions/"
    tentativi_url = [
        f"https://api.codetabs.com/v1/proxy?quest={quote(target, safe='')}",
        "https://r.jina.ai/https://www.fut.gg/evolutions/"
    ]
    for u in tentativi_url:
        try:
            resp = requests.get(u, headers=HEADERS, timeout=12)
            if resp.status_code == 200:
                links = re.findall(r"/evolutions/\d+-[a-zA-Z0-9-]+/", resp.text)
                visti = []
                for l in links:
                    if l not in visti:
                        visti.append(l)
                for link in visti[:6]:
                    pezzo = link.split("-", 1)[-1].replace("/", "")
                    nome = pezzo.replace("-", " ").title()
                    lista_evo.append((nome, f"https://www.fut.gg{link}"))
                if lista_evo:
                    break
        except Exception:
            continue
    return lista_evo

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    if not parti:
        return
    comando = parti[0].lower().split("@")[0]

    if comando in ["/start", "/help", "/menu"]:
        menu = (
            "🎮 <b>PANNELLO COMANDI BOT ULTIMATE TEAM (H24)</b>\n"
            "💰 Budget: 800.000 crediti (PS)\n\n"
            "🔥 <b>/leak</b> - Scansiona leak e notizie live e ti dice chi comprare\n"
            "🧬 <b>/evo</b> - Analizza le ultime Evoluzioni su FUT.GG e le carte Meta\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto\n"
            "🧠 <b>/chiedi [domanda]</b> - Chiedi strategia e prezzi a Gemini"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram("📡 Scansione Live dei canali Leak e analisi Gemini in corso...", chat_id)
        leaks = leggi_leak_con_bypass()
        if leaks:
            testo_extra = "\n".join([f"[{c}]: {t}" for c, t in leaks])
        else:
            testo_extra = "Usa la ricerca Google per trovare gli ultimi leak di oggi."

        prompt = (
            f"Ecco le ultime notizie e leak intercettati:\n{testo_extra}\n\n"
            "Cerca anche gli ultimissimi leak di oggi su Ultimate Team (Fut Sheriff, Fut Scoreboard, nuove SBC, Promo o Evoluzioni). "
            "Riassumi le uscite più calde e dimmi quali carte o filtri comprare ADESSO su PlayStation con 800k crediti."
        )
        analisi = chiedi_a_gemini_live(prompt, usa_ricerca_web=True)

        msg = "🚨 <b>REPORT LEAK & INVESTIMENTI IN TEMPO REALE:</b>\n\n"
        if leaks:
            for c, t in leaks[:4]:
                pulito = t.replace("<", "&lt;").replace(">", "&gt;")
                msg += f"📢 <b>{c}:</b> <i>{pulito[:160]}</i>\n\n"
        msg += f"🧠 <b>ANALISI LIVE GEMINI:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 Lettura Evoluzioni FUT.GG e analisi carte Meta in corso...", chat_id)
        evos = leggi_evo_con_bypass()
        nomi = ", ".join([n for n, _ in evos]) if evos else "Ultime Evoluzioni attive su Ultimate Team"

        msg = "🔥 <b>RADAR EVOLUZIONI FUT.GG:</b>\n\n"
        if evos:
            for n, link in evos:
                msg += f"• <b>{n}</b> 👉 <a href='{link}'>Apri su FUT.GG</a>\n"
            msg += "\n"

        prompt = (
            f"Evoluzioni rilevate: {nomi}. "
            "Indica quali sono le caratteristiche e le carte Meta migliori da comprare e rivendere "
            "per le Evoluzioni attuali su PlayStation (budget 800k) e quando rivenderle."
        )
        consiglio = chiedi_a_gemini_live(prompt, usa_ricerca_web=True)
        msg += (
            f"🧠 <b>CONSIGLI DI COMPRAVENDITA EVO:</b>\n{consiglio}\n\n"
            f"🔗 <a href='https://www.fut.gg/evolutions/trending/'>Apri Giocatori Trending su FUT.GG</a>"
        )
        invia_telegram(msg, chat_id)

    elif comando == "/tassa":
        if len(parti) < 2:
            invia_telegram("Usa: <code>/tassa 50000</code> o <code>/tassa 50000 60000</code>", chat_id)
            return
        try:
            buy = int(parti[1].replace(".", "").replace("k", "000"))
            pareggio = int(buy / (1 - EA_TAX)) + 100
            consigliato = int(buy * 1.12)
            if len(parti) >= 3:
                sell = int(parti[2].replace(".", "").replace("k", "000"))
            else:
                sell = consigliato
            tassa = int(sell * EA_TAX)
            netto = (sell - tassa) - buy
            qta = max(1, int(250000 // buy))
            msg = (
                f"🧮 <b>CALCOLATORE TASSA EA (5%)</b>\n\n"
                f"🛒 Acquisto: <b>{buy:,}</b>\n"
                f"⚖️ Pareggio (Break-Even): <b>{pareggio:,}</b>\n"
                f"🎯 Vendita: <b>{sell:,}</b> (Tassa: -{tassa:,})\n"
                f"✅ <b>Utile netto a carta: {netto:+,}</b>\n"
                f"📦 Su 250k ({qta} carte): <b>{netto * qta:+,} crediti</b>"
            )
            invia_telegram(msg, chat_id)
        except Exception:
            invia_telegram("⚠️ Inserisci solo numeri! Es: <code>/tassa 40000</code>", chat_id)

    elif comando == "/chiedi":
        if len(parti) < 2:
            invia_telegram("Scrivi una domanda! Es: <code>/chiedi chi compro oggi con 200k?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 Analisi di mercato con Gemini in corso...", chat_id)
        risp = chiedi_a_gemini_live(domanda, usa_ricerca_web=True)
        invia_telegram(f"🤖 <b>ANALISTA MERCATO LIVE:</b>\n\n{risp}", chat_id)

def ascolta_comandi_telegram():
    global ultimo_update_id
    base_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        r = requests.get(f"{base_tg}/getUpdates?timeout=1", timeout=5).json()
        if r.get("ok") and r.get("result"):
            ultimo_update_id = r["result"][-1]["update_id"] + 1
    except Exception:
        pass

    while True:
        try:
            url = f"{base_tg}/getUpdates?offset={ultimo_update_id}&timeout=20"
            resp = requests.get(url, timeout=25).json()
            if resp.get("ok"):
                for item in resp.get("result", []):
                    ultimo_update_id = item["update_id"] + 1
                    msg = item.get("message", {})
                    txt = msg.get("text", "")
                    cid = msg.get("chat", {}).get("id")
                    if txt.startswith("/") and cid:
                        t = threading.Thread(
                            target=gestisci_comando,
                            args=(txt, cid),
                            daemon=True
                        )
                        t.start()
        except Exception:
            time.sleep(3)

def scansiona_leak_automatico():
    global messaggi_gia_visti
    leaks = leggi_leak_con_bypass()
    for fonte, txt in leaks:
        id_msg = hash(txt[:70])
        if id_msg not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_msg)
            if any(k in txt.lower() for k in PAROLE_CALDE):
                if len(messaggi_gia_visti) > 6:
                    analisi = chiedi_a_gemini_live(
                        f"Nuovo leak Ultimate Team appena uscito: {txt}. "
                        "Dimmi in 3 punti chi comprare subito su PlayStation.",
                        usa_ricerca_web=True
                    )
                    pulito = txt[:280].replace("<", "&lt;").replace(">", "&gt;")
                    avviso = (
                        f"🚨 <b>NUOVO LEAK RILEVATO ({fonte})!</b>\n\n"
                        f"📝 <i>{pulito}</i>\n\n"
                        f"🧠 <b>COSA COMPRARE ORA:</b>\n{analisi}"
                    )
                    invia_telegram(avviso)

def motore_h24():
    avvio = (
        "✅ <b>BOT AGGIORNATO (FIX CANDIDATES + PARSER PULITO)!</b>\n\n"
        "Prova subito <b>/leak</b>, <b>/evo</b> oppure <b>/chiedi chi compro oggi?</b>"
    )
    invia_telegram(avvio)
    scansiona_leak_automatico()
    ultimo_orario = ""

    while True:
        try:
            scansiona_leak_automatico()
            tz_it = timezone(timedelta(hours=2))
            now = datetime.now(tz_it)
            ora_str = now.strftime("%H:%M")

            if ora_str != ultimo_orario:
                if ora_str == "18:55":
                    invia_telegram("⏰ <b>18:55 - CONTENUTI EA TRA 5 MINUTI!</b>")
                    ultimo_orario = ora_str
                elif ora_str == "08:55" and now.weekday() == 3:
                    invia_telegram("📉 <b>08:55 - PREMI RIVALS TRA 5 MINUTI!</b>")
                    ultimo_orario = ora_str

            time.sleep(180)
        except Exception:
            time.sleep(60)

@app.route("/")
def home():
    return "FC Bot H24 Running OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
