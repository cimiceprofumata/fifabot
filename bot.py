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
    """Interroga Gemini 2.5 Flash per analisi di mercato e leak in tempo reale."""
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
        # Rimuove eventuali asterischi residui per non rompere l'HTML di Telegram
        return testo.replace("**", "").replace("*", "•").replace("<", "&lt;").replace(">", "&gt;")
    except Exception as e:
        return f"⚡ Errore temporaneo analisi IA: {e}"

def leggi_ultimi_leak_live():
    """Raccoglie gli ultimi post reali dai canali di leak per il comando /leak e per il monitor H24."""
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
    """Legge le ultime Evoluzioni presenti sulla pagina di FUT.GG."""
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

# ================= GESTIONE COMANDI INTERATTIVI TELEGRAM =================
def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    comando = parti[0].lower().split("@")[0]

    if comando in ["/start", "/help", "/menu"]:
        menu = (
            "🎮 <b>PANNELLO COMANDI BOT FC 27 (H24)</b>\n"
            "💰 <i>Budget tarato: 800.000 crediti (PS)</i>\n\n"
            "Ecco i comandi che puoi inviarmi in qualsiasi momento:\n\n"
            "🔥 <b>/leak</b>\n"
            "Scansiona all'istante gli ultimi post dei leaker (Fut_Scoreboard, Sheriff) e ti dice su cosa investire ADESSO.\n\n"
            "🧬 <b>/evo</b>\n"
            "Mostra le ultime Evoluzioni attive su FUT.GG con link diretti alle carte Meta.\n\n"
            "🧮 <b>/tassa [prezzo_acquisto] [prezzo_vendita]</b>\n"
            "Esempio: <code>/tassa 45000 54000</code> (oppure solo <code>/tassa 45000</code>). Calcola punto di pareggio col 5% EA e profitto totale.\n\n"
            "🧠 <b>/chiedi [la tua domanda]</b>\n"
            "Esempio: <code>/chiedi conviene comprare gli 85 adesso?</code> — L'IA analizza e ti risponde subito!"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram("📡 <i>Scansione canali Leak in tempo reale e analisi con Gemini in corso...</i>", chat_id)
        leaks = leggi_ultimi_leak_live()
        if not leaks:
            invia_telegram("⚠️ Impossibile leggere i canali in questo istante. Riprova tra 30 secondi!", chat_id)
            return
        
        testo_per_ia = "\n".join([f"[{canale}]: {txt}" for canale, txt in leaks])
        analisi = chiedi_a_gemini(
            f"Ecco gli ultimi post appena letti dai canali di leak di FC 27:\n{testo_per_ia}\n\n"
            f"Riassumi cosa c'è di nuovo e dimmi esattamente quali carte o filtri comprare su PlayStation con i miei 800k per fare profitto."
        )
        msg = "🚨 <b>ULTIMI LEAK LIVE & PIANO D'AZIONE:</b>\n\n"
        for canale, txt in leaks[-4:]:
             txt_pulito = txt.replace("<", "&lt;").replace(">", "&gt;")
            msg += f"📢 <b>{canale}:</b> <i>{txt_pulito[:160]}...</i>\n\n"
        msg += f"🧠 <b>CONSIGLIO DI GEMINI:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 <i>Controllo ultime Evoluzioni su FUT.GG in corso...</i>", chat_id)
        evos = leggi_evo_futgg()
        if not evos:
            invia_telegram(
                "⚠️ FUT.GG sta proteggendo la pagina o non ci sono nuove Evo.\n"
                "👉 <a href='https://www.fut.gg/evolutions/best/'>Apri direttamente Best Evolutions qui</a>",
                chat_id
            )
            return
        msg = "🔥 <b>EVOLUZIONI RILEVATE SU FUT.GG:</b>\n\n"
        nomi_evo = ", ".join([n for n, _ in evos])
        for nome, link in evos:
            msg += f"• <b>{nome}</b> 👉 <a href='{link}'>Vedi Carte</a>\n"
        
        consiglio = chiedi_a_gemini(
            f"Le evoluzioni attuali su FUT.GG sono: {nomi_evo}. "
            f"Dammi 3 dritte rapide su come fare crediti con le carte che entrano nelle Evoluzioni (quando comprare, fascia prezzo e quando vendere)."
        )
        msg += f"\n🧠 <b>STRATEGIA EVO:</b>\n{consiglio}\n\n🔗 <a href='https://www.fut.gg/evolutions/trending/'>Vedi Carte Evo Trending Ora</a>"
        invia_telegram(msg, chat_id)

    elif comando == "/tassa":
        if len(parti) < 2:
            invia_telegram("⚠️ Scrivi il prezzo! Esempio:\n<code>/tassa 50000</code> oppure <code>/tassa 50000 60000</code>", chat_id)
            return
        try:
            buy = int(parti[1].replace(".", "").replace("k", "000"))
            pareggio = int(buy / (1 - EA_TAX)) + 100
            target_consigliato = int(buy * 1.12) # +12% (circa +7% netto)
            sell = int(parti[2].replace(".", "").replace("k", "000")) if len(parti) >= 3 else target_consigliato
            
            tassa = int(sell * EA_TAX)
            netto_carta = (sell - tassa) - buy
            qta_250k = max(1, int(250000 // buy))
            qta_800k = max(1, int(800000 // buy))

            msg = (
                f"🧮 <b>CALCOLATORE TRADING (Tassa EA 5%)</b>\n\n"
                f"🛒 Prezzo Acquisto: <b>{buy:,} crediti</b>\n"
                f"⚖️ Punto di Pareggio (Break-Even): <b>{pareggio:,} crediti</b>\n"
                f"🎯 Prezzo Vendita calcolato: <b>{sell:,} crediti</b>\n"
                f"💸 Tassa EA (5%): -{tassa:,} crediti\n\n"
                f"✅ <b>Utile Netto per carta: {netto_carta:+,} crediti</b>\n"
                f"📦 Con 250k ({qta_250k} carte): <b>{netto_carta * qta_250k:+,} crediti netti</b>\n"
                f"💰 Con 800k ({qta_800k} carte): <b>{netto_carta * qta_800k:+,} crediti netti</b>"
            )
            invia_telegram(msg, chat_id)
        except Exception:
            invia_telegram("⚠️ Inserisci solo numeri validi! Esempio: <code>/tassa 35000 42000</code>", chat_id)

    elif comando == "/chiedi":
        if len(parti) < 2:
            invia_telegram("⚠️ Scrivi una domanda dopo /chiedi! Esempio:\n<code>/chiedi su cosa investo stasera con 300k?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 <i>Gemini sta elaborando la strategia...</i>", chat_id)
        risposta = chiedi_a_gemini(domanda)
        invia_telegram(f"🤖 <b>RISPOSTA ANALISTA FC 27:</b>\n\n{risposta}", chat_id)

def ascolta_comandi_telegram():
    """Controlla ogni 2 secondi se hai scritto un comando in chat su Telegram."""
    global ultimo_update_id
    # All'avvio ignora i vecchi messaggi in coda
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?timeout=1", timeout=5).json()
        if r.get("ok") and r.get("result"):
            ultimo_update_id = r["result"][-1]["update_id"] + 1
    except Exception:
        pass

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={ultimo_update_id}&timeout=20"
            resp = requests.get(url, timeout=25).json()
            if resp.get("ok"):
                for item in resp.get("result", []):
                    ultimo_update_id = item["update_id"] + 1
                    msg = item.get("message", {})
                    testo = msg.get("text", "")
                    chat_id = msg.get("chat", {}).get("id")
                    if testo.startswith("/") and chat_id:
                        threading.Thread(target=gestisci_comando, args=(testo, chat_id), daemon=True).start()
        except Exception as e:
            time.sleep(3)

# ================= MONITORAGGIO AUTOMATICO H24 =================
def scansiona_leak_automatico():
    global messaggi_gia_visti
    for url in CANALI_LEAK:
        try:
            resp = scraper.get(url, timeout=12)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            blocchi = soup.find_all("div", class_="tgme_widget_message_text")
            for blocco in blocchi[-3:]:
                testo = blocco.get_text(separator="\n").strip()
                id_msg = hash(testo[:80])
                if id_msg not in messaggi_gia_visti and len(testo) > 15:
                    messaggi_gia_visti.add(id_msg)
                    if any(k in testo.lower() for k in PAROLE_CHIAVE_CALDE):
                        if len(messaggi_gia_visti) > 6:
                            analisi = chiedi_a_gemini(
                                f"È appena uscito questo leak in tempo reale su FC 27:\n'{testo}'\n"
                                f"Dimmi in 3 punti rapidi quali carte comprare ADESSO su PS, a che prezzo e quando rivenderle."
                            )
                            testo_pulito = testo[:350].replace("<", "&lt;").replace(">", "&gt;")
                            invia_telegram(
                                f"🚨 <b>NUOVO LEAK IN TEMPO REALE!</b>\n\n"
                                f"📝 <i>{testo_pulito}</i>\n\n"
                                f"🧠 <b>COSA COMPRARE ORA:</b>\n{analisi}\n\n"
                                f"🔗 <a href='https://www.fut.gg/evolutions/best/'>Apri FUT.GG Evo Lab</a>"
                            )
        except Exception as e:
            print(f"Errore leak auto: {e}")

def motore_h24():
    invia_telegram(
        "⚡ <b>BOT AGGIORNATO CON COMANDI INTERATTIVI E IA GEMINI!</b>\n\n"
        "Scrivi qui in chat:\n"
        "• <b>/menu</b> per vedere tutti i comandi\n"
        "• <b>/leak</b> per analizzare subito gli ultimi leak usciti\n"
        "• <b>/evo</b> per le Evoluzioni di FUT.GG\n"
        "• <b>/tassa 50000</b> per calcolare i margini\n"
        "• <b>/chiedi [domanda]</b> per parlare con l'IA!"
    )
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
                    invia_telegram(
                        "⏰ <b>18:55 - CONTENUTI EA TRA 5 MINUTI!</b>\n"
                        "• Vendi ORA le carte comprate sui leak.\n"
                        "• Scrivi <b>/evo</b> o <b>/leak</b> dopo le 19:00 per vedere cosa è uscito!"
                    )
                    ultimo_orario = ora_str
                elif ora_str == "08:55" and now.weekday() == 3:
                    invia_telegram("📉 <b>08:55 - PREMI RIVALS TRA 5 MINUTI!</b>\nPrepara gli 800k per comprare nel panic selling!")
                    ultimo_orario = ora_str

            time.sleep(120)
        except Exception:
            time.sleep(60)

@app.route('/')
def home():
    return "FC 27 Bot H24 + Interactive Commands Running!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
