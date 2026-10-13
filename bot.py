import os
import re
import time
import threading
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from flask import Flask
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EA_TAX = 0.05

CANALI_LEAK = [
    "Fut_Scoreboard",
    "FutSheriff_Official",
    "fifatradingromania"
]

PAROLE_CALDE = [
    "evo", "evolution", "sbc", "potm", "leak",
    "max ", "req", "upgrade", "playstyle", "fodder"
]

messaggi_gia_visti = set()
ultimo_update_id = 0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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
    """Interroga Gemini attivando Google Search Live per aggirare qualsiasi blocco Cloudflare."""
    if not GEMINI_API_KEY:
        return "Chiave GEMINI_API_KEY non trovata su Render."
    
    base = "https://generativelanguage.googleapis.com/v1beta/models/"
    url = f"{base}gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    oggi = datetime.now().strftime("%d/%m/%Y")
    sistema = (
        f"Data di oggi: {oggi}. Sei un top trader di Ultimate Team (mercato PlayStation, budget 800.000 crediti). "
        "Usa la ricerca web per trovare gli ultimissimi leak, SBC, Evoluzioni di FUT.GG e prezzi attuali. "
        "Rispondi in italiano in modo diretto, pratico e schematico (max 12 righe). "
        "Non usare mai simboli Markdown come asterischi (*) o cancelletti (#). Usa solo elenchi con il pallino •. "
        "Considera sempre la tassa EA del 5%."
    )
    testo_completo = f"{sistema}\n\nRichiesta: {prompt_utente}"
    
    body = {
        "contents": [{"parts": [{"text": testo_completo}]}]
    }
    if usa_ricerca_web:
        body["tools"] = [{"google_search": {}}]

    try:
        r = requests.post(url, json=body, timeout=30)
        risposta = r.json()
        
        # Se l'account API non supporta il tool search, riprova senza tool
        if "error" in risposta and usa_ricerca_web:
            return chiedi_a_gemini_live(prompt_utente, usa_ricerca_web=False)
            
        parti = risposta["candidates"][0]["content"]["parts"]
        out = "".join([p.get("text", "") for p in parti])
        out = out.replace("**", "").replace("*", "•").replace("#", "")
        return out.replace("<", "&lt;").replace(">", "&gt;")
    except Exception as e:
        return f"Errore analisi IA: {e}"

def leggi_leak_con_bypass():
    """Legge i canali Telegram e i feed di notizie passando da proxy e RSS per evitare blocchi IP su Render."""
    raccolta = []
    
    # 1. Tentativo tramite Proxy Reader (aggira il blocco IP di Render su t.me)
    for canale in CANALI_LEAK:
        try:
            url_proxy = f"https://r.jina.ai/https://t.me/s/{canale}"
            resp = requests.get(url_proxy, headers=HEADERS, timeout=12)
            if resp.status_code == 200 and len(resp.text) > 200:
                righe = [line.strip() for line in resp.text.split("\n") if len(line.strip()) > 35]
                ultime = [r for r in righe if not r.startswith("http") and "Telegram" not in r][-2:]
                for u in ultime:
                    raccolta.append((canale, u[:250]))
        except Exception:
            pass

    # 2. Backup sempre attivo tramite Google News RSS su Ultimate Team Leaks & Evolutions
    if not raccolta:
        try:
            rss_url = "https://news.google.com/rss/search?q=Ultimate+Team+Leak+OR+Evolution+OR+SBC+when:2d&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(rss_url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item")[:5]:
                    titolo = item.find("title").text
                    raccolta.append(("Leak Radar", titolo))
        except Exception as e:
            print("Errore RSS:", e)

    return raccolta

def leggi_evo_con_bypass():
    """Legge le Evoluzioni di FUT.GG passando dal proxy reader Jina per superare Cloudflare."""
    lista_evo = []
    try:
        url_proxy = "https://r.jina.ai/https://www.fut.gg/evolutions/"
        resp = requests.get(url_proxy, headers=HEADERS, timeout=15)
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
    except Exception as e:
        print("Errore Proxy FUT.GG:", e)
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
            "🔥 <b>/leak</b> - Scansiona il web e i leaker in tempo reale e ti dice chi comprare\n"
            "🧬 <b>/evo</b> - Analizza le ultime Evoluzioni su FUT.GG e le carte Meta\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto\n"
            "🧠 <b>/chiedi [domanda]</b> - Ricerca live su mercato e prezzi con Gemini"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram("📡 Scansione Live (Bypass + Google Search) sugli ultimi Leak in corso...", chat_id)
        leaks = leggi_leak_con_bypass()
        testo_extra = "\n".join([f"[{c}]: {t}" for c, t in leaks]) if leaks else "Cerca direttamente sul web."
        
        prompt = (
            f"Notizie intercettate: {testo_extra}\n"
            "Cerca sul web gli ultimissimi leak di oggi su Ultimate Team (Fut Sheriff, Fut Scoreboard, nuove SBC, nuove Promo o Evoluzioni). "
            "Elenca i leak più importanti del momento e dimmi esattamente quali carte o filtri comprare ADESSO su PlayStation con 800k crediti."
        )
        analisi = chiedi_a_gemini_live(prompt, usa_ricerca_web=True)
        
        msg = "🚨 <b>REPORT LEAK & INVESTIMENTI IN TEMPO REALE:</b>\n\n"
        if leaks:
            for c, t in leaks[:3]:
                pulito = t.replace("<", "&lt;").replace(">", "&gt;")
                msg += f"📢 <b>{c}:</b> <i>{pulito[:140]}...</i>\n\n"
        msg += f"🧠 <b>ANALISI LIVE GEMINI:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 Lettura Evoluzioni FUT.GG (con Bypass Cloudflare + Ricerca Live)...", chat_id)
        evos = leggi_evo_con_bypass()
        nomi = ", ".join([n for n, _ in evos]) if evos else "Cerca le ultime Evoluzioni attive su FUT.GG"
        
        msg = "🔥 <b>RADAR EVOLUZIONI FUT.GG:</b>\n\n"
        if evos:
            for n, link in evos:
                msg += f"• <b>{n}</b> 👉 <a href='{link}'>Apri su FUT.GG</a>\n"
            msg += "\n"
            
        prompt = (
            f"Evoluzioni rilevate: {nomi}. Cerca su FUT.GG le ultime Evoluzioni uscite su Ultimate Team e i giocatori Trending. "
            "Dimmi quali sono le migliori carte Meta da comprare e rivendere per queste Evoluzioni e i filtri da usare."
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
            invia_telegram("Scrivi una domanda! Es: <code>/chiedi chi compro oggi?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 Ricerca sul web e analisi con Gemini in corso...", chat_id)
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
                if len(messaggi_gia_visti) > 5:
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
        "🛡️ <b>BOT AGGIORNATO CON BYPASS CLOUDFLARE + RICERCA LIVE GOOGLE!</b>\n\n"
        "Adesso <b>/leak</b> ed <b>/evo</b> usano il proxy di lettura e la ricerca web in tempo reale di Gemini!\n"
        "Provali subito qui in chat."
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
    return "FC Bot H24 with Cloudflare Bypass Running OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
