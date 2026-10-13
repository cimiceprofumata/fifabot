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

PAROLE_CALDE = [
    "evo", "evolution", "sbc", "potm", "leak",
    "max ", "req", "upgrade", "playstyle", "fodder"
]

messaggi_gia_visti = set()
ultimo_update_id = 0

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)

def invia_telegram(testo, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_TOKEN or not target:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": target,
        "text": testo,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Errore Telegram:", e)

def chiedi_a_gemini(prompt_utente):
    if not GEMINI_API_KEY:
        return "Chiave GEMINI_API_KEY non trovata su Render."
    base = "https://generativelanguage.googleapis.com/v1beta/models/"
    url = f"{base}gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    sistema = (
        "Sei un top trader di EA Sports FC 27 Ultimate Team "
        "(mercato PlayStation, budget 800.000 crediti). "
        "Rispondi in italiano in modo diretto e pratico (max 10 righe). "
        "Non usare simboli Markdown come asterischi o cancelletti. "
        "Considera sempre la tassa EA del 5%."
    )
    testo_completo = f"{sistema}\n\nRichiesta: {prompt_utente}"
    body = {"contents": [{"parts": [{"text": testo_completo}]}]}
    try:
        r = requests.post(url, json=body, timeout=20)
        risposta = r.json()
        out = risposta["candidates"][0]["content"]["parts"][0]["text"]
        out = out.replace("**", "").replace("*", "•")
        return out.replace("<", "&lt;").replace(">", "&gt;")
    except Exception as e:
        return f"Errore temporaneo IA: {e}"

def leggi_ultimi_leak_live():
    raccolta = []
    for url in CANALI_LEAK:
        try:
            nome = url.split("/")[-1]
            resp = scraper.get(url, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                blocchi = soup.find_all("div", class_="tgme_widget_message_text")
                for b in blocchi[-2:]:
                    txt = b.get_text(separator=" ").strip()
                    if len(txt) > 15:
                        raccolta.append((nome, txt[:280]))
        except Exception as e:
            print("Errore lettura:", e)
    return raccolta

def leggi_evo_futgg():
    lista_evo = []
    try:
        resp = scraper.get("https://www.fut.gg/evolutions/", timeout=12)
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
        print("Errore FUT.GG:", e)
    return lista_evo

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    if not parti:
        return
    comando = parti[0].lower().split("@")[0]

    if comando in ["/start", "/help", "/menu"]:
        menu = (
            "🎮 <b>PANNELLO COMANDI BOT FC 27 (H24)</b>\n"
            "💰 Budget: 800.000 crediti (PS)\n\n"
            "🔥 <b>/leak</b> - Scansiona gli ultimi leak e consiglia chi comprare\n"
            "🧬 <b>/evo</b> - Mostra le ultime Evoluzioni su FUT.GG\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto\n"
            "🧠 <b>/chiedi [domanda]</b> - Chiedi strategia a Gemini"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram("📡 Scansione canali Leak e analisi IA in corso...", chat_id)
        leaks = leggi_ultimi_leak_live()
        if not leaks:
            invia_telegram("⚠️ Riprova tra 30 secondi!", chat_id)
            return
        righe = [f"[{c}]: {t}" for c, t in leaks]
        testo_ia = "\n".join(righe)
        prompt = (
            f"Ecco gli ultimi post dai canali leak di FC 27:\n{testo_ia}\n\n"
            "Riassumi le novità e dimmi quali carte comprare su PS con 800k."
        )
        analisi = chiedi_a_gemini(prompt)
        msg = "🚨 <b>ULTIMI LEAK LIVE:</b>\n\n"
        for c, t in leaks[-3:]:
            pulito = t.replace("<", "&lt;").replace(">", "&gt;")
            msg += f"📢 <b>{c}:</b> <i>{pulito[:140]}...</i>\n\n"
        msg += f"🧠 <b>CONSIGLIO GEMINI:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 Controllo Evoluzioni su FUT.GG in corso...", chat_id)
        evos = leggi_evo_futgg()
        if not evos:
            fallback = (
                "⚠️ Pagina protetta. Apri direttamente:\n"
                "https://www.fut.gg/evolutions/best/"
            )
            invia_telegram(fallback, chat_id)
            return
        msg = "🔥 <b>EVOLUZIONI ATTIVE SU FUT.GG:</b>\n\n"
        nomi = ", ".join([n for n, _ in evos])
        for n, link in evos:
            msg += f"• <b>{n}</b> 👉 <a href='{link}'>Vedi Carte</a>\n"
        consiglio = chiedi_a_gemini(
            f"Evoluzioni attive su FC 27: {nomi}. "
            "Dammi 3 dritte rapide per fare crediti con queste Evo."
        )
        msg += f"\n🧠 <b>STRATEGIA:</b>\n{consiglio}"
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
        invia_telegram("🧠 Elaborazione risposta in corso...", chat_id)
        risp = chiedi_a_gemini(domanda)
        invia_telegram(f"🤖 <b>ANALISTA FC 27:</b>\n\n{risp}", chat_id)

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
    for url in CANALI_LEAK:
        try:
            resp = scraper.get(url, timeout=12)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            blocchi = soup.find_all("div", class_="tgme_widget_message_text")
            for b in blocchi[-3:]:
                txt = b.get_text(separator="\n").strip()
                id_msg = hash(txt[:80])
                if id_msg not in messaggi_gia_visti and len(txt) > 15:
                    messaggi_gia_visti.add(id_msg)
                    if any(k in txt.lower() for k in PAROLE_CALDE):
                        if len(messaggi_gia_visti) > 6:
                            analisi = chiedi_a_gemini(
                                f"Nuovo leak FC 27: {txt}. "
                                "Dimmi in 3 punti chi comprare ora su PS."
                            )
                            pulito = txt[:300].replace("<", "&lt;").replace(">", "&gt;")
                            avviso = (
                                f"🚨 <b>NUOVO LEAK IN TEMPO REALE!</b>\n\n"
                                f"📝 <i>{pulito}</i>\n\n"
                                f"🧠 <b>COSA COMPRARE:</b>\n{analisi}"
                            )
                            invia_telegram(avviso)
        except Exception as e:
            print("Errore auto:", e)

def motore_h24():
    avvio = (
        "⚡ <b>BOT FC 27 ATTIVO CON COMANDI E IA GEMINI!</b>\n\n"
        "Scrivi qui in chat:\n"
        "• <b>/menu</b> per tutti i comandi\n"
        "• <b>/leak</b> per analizzare gli ultimi leak\n"
        "• <b>/evo</b> per le Evoluzioni di FUT.GG\n"
        "• <b>/tassa 50000</b> per calcolare i margini\n"
        "• <b>/chiedi [domanda]</b> per parlare con Gemini!"
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

            time.sleep(120)
        except Exception:
            time.sleep(60)

@app.route("/")
def home():
    return "FC 27 Bot H24 Running OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
