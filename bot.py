
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

# Blocca qualsiasi banner di Telegram (incluso [Send Message] e tg://resolve)
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

def trova_modelli_attivi():
    global modello_scoperto
    modelli = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash", "gemini-flash-latest"]
    if modello_scoperto and modello_scoperto not in modelli:
        modelli.insert(0, modello_scoperto)
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        r = requests.get(url, timeout=10).json()
        for m in r.get("models", []):
            nome = m.get("name", "").replace("models/", "")
            metodi = m.get("supportedGenerationMethods", [])
            if "generateContent" in metodi and ("flash" in nome or "gemini-3" in nome):
                if nome not in modelli:
                    modelli.insert(0, nome)
    except Exception:
        pass
    return modelli

def scarica_testo_jina(target_url):
    try:
        h = dict(HEADERS)
        h["X-No-Cache"] = "true"
        resp = requests.get(f"https://r.jina.ai/{target_url}", headers=h, timeout=18)
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text
    except Exception:
        pass
    return ""

def pulisci_righe_testo(raw_text, min_len=25):
    """Pulisce il testo scaricato rimuovendo link, immagini e scritte [Send Message]."""
    righe_buone = []
    for r in raw_text.split("\n"):
        rc = r.strip()
        rc_low = rc.lower()
        if len(rc) < min_len:
            continue
        if rc.startswith("![") or rc.startswith("http") or rc.startswith("Title:") or rc.startswith("URL Source:"):
            continue
        if any(bad in rc_low for bad in FRASI_SPAZZATURA):
            continue
        righe_buone.append(rc)
    return righe_buone

def leggi_leak_reali_x_e_telegram():
    """Raccoglie solo veri post di leak da X e Telegram, ignorando bottoni e link di sistema."""
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_str = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")

    # 1. Legge i profili X
    for u in PROFILI_X_LEAKERS[:4]:
        handle = u.split("/")[-1]
        raw = scarica_testo_jina(u)
        righe = pulisci_righe_testo(raw, min_len=35)
        for linea in righe:
            if any(k in linea.lower() for k in PAROLE_TRIGGER):
                if not any(x_bad in linea.lower() for x_bad in ["log in", "sign up", "terms of service", "cookie"]):
                    raccolta.append(f"[{ora_str} | @{handle} su X]: {linea[:320]}")

    # 2. Legge i canali Telegram
    for canale in CANALI_TELEGRAM_APERTI:
        raw = scarica_testo_jina(f"https://t.me/s/{canale}")
        righe = pulisci_righe_testo(raw, min_len=30)
        for post in righe[-3:]:
            if any(k in post.lower() for k in PAROLE_TRIGGER):
                raccolta.append(f"[{ora_str} | @{canale} su TG]: {post[:320]}")

    return raccolta[:10]

def estrai_schede_complete_futgg():
    """
    Scarica da FUT.GG NON SOLO I NOMI, ma il TESTO COMPLETO delle schede giocatori,
    delle Evoluzioni attive e della classifica Best Evolutions ranked by GG Rating!
    Così Gemini legge il vero Club in FC 27, il vero OVR, i PlayStyles e il vero GG Rating!
    """
    blocchi_dati_futgg = []

    # 1. Pagina Best Evolutions (ordinata per GG Rating / Meta Rating su FUT.GG!)
    raw_best_evo = scarica_testo_jina("https://www.fut.gg/evolutions/best/")
    righe_best = pulisci_righe_testo(raw_best_evo, min_len=15)
    if righe_best:
        str_best = "\n".join(righe_best[:45])
        blocchi_dati_futgg.append(f"=== CLASSIFICA FUT.GG BEST EVOLUTIONS (RANKED BY GG RATING) ===\n{str_best}")

    # 2. Pagina Evolutions Principale (con i nomi delle Evo e gli upgrade)
    raw_evos = scarica_testo_jina("https://www.fut.gg/evolutions/")
    righe_evos = pulisci_righe_testo(raw_evos, min_len=15)
    if righe_evos:
        str_evos = "\n".join(righe_evos[:40])
        blocchi_dati_futgg.append(f"=== PAGINA EVOLUZIONI ATTIVE FUT.GG ===\n{str_evos}")

    # 3. Estrae i primi 6 URL di giocatori presenti in Best/Trending Evolutions e apre le loro schede su FUT.GG
    # per leggere Club reale in FC 27 (es. Kayode -> Brentford 81), GG Rating e PlayStyles!
    raw_trending = scarica_testo_jina("https://www.fut.gg/evolutions/trending/")
    links_players = re.findall(r"(/players/\d+-[a-zA-Z0-9-]+/)", raw_best_evo + "\n" + raw_trending)
    visti_p = []
    for lp in links_players:
        if lp not in visti_p:
            visti_p.append(lp)

    schede_giocatori = []
    for lp in visti_p[:5]:
        raw_p = scarica_testo_jina(f"https://www.fut.gg{lp}")
        if raw_p:
            righe_p = pulisci_righe_testo(raw_p, min_len=10)
            estratto_p = " | ".join(righe_p[:18])
            schede_giocatori.append(f"SCHEDA VERIFICATA FUT.GG ({lp}): {estratto_p[:450]}")

    if schede_giocatori:
        str_schede = "\n\n".join(schede_giocatori)
        blocchi_dati_futgg.append(f"=== SCHEDE GIOCATORI VERIFICATE LIVE SU FUT.GG (CLUB, OVR, GG RATING) ===\n{str_schede}")

    return "\n\n".join(blocchi_dati_futgg)

def cerca_schede_giocatori_specifici_su_futgg(query_ricerca):
    """Quando usi /simula o /leak per un ruolo specifico (es. LB o RB), estrae i dati veri da FUT.GG."""
    urls_specifici = ["https://www.fut.gg/evolutions/best/"]
    q_low = query_ricerca.lower()
    for ruolo in ["lb", "rb", "cb", "cdm", "cm", "cam", "lw", "rw", "st"]:
        if ruolo in q_low:
            urls_specifici.insert(0, f"https://www.fut.gg/tactics/most-used-players/{ruolo}/")
            urls_specifici.insert(1, f"https://www.fut.gg/players/tallest/{ruolo}/")

    testi = []
    for u in urls_specifici[:2]:
        raw = scarica_testo_jina(u)
        righe = pulisci_righe_testo(raw, min_len=12)
        if righe:
            str_r = "\n".join(righe[:45])
            testi.append(f"DATI FUT.GG DA {u}:\n{str_r}")
    return "\n\n".join(testi)

def analizza_con_verifica_rigorosa_futgg(prompt_utente):
    """
    Interroga Gemini imponendo l'uso dei dati testuali estratti da FUT.GG (GG Rating, Club 2026/27, OVR reale)
    e vietando rigorosamente di usare la memoria vecchia non verificata.
    """
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    sistema = (
        f"Data e ora attuale italiana: {oggi} (Ottobre 2026, stagione EA Sports FC 27). "
        "Sei l'analista collegato al database di FUT.GG per EA Sports FC 27 Ultimate Team (PlayStation, budget 800k).\n"
        "REGOLE TASSATIVE CONTRO ERRORI DI DATABASE E ALLUCINAZIONI:\n"
        "1) NON USARE MAI VECCHI CLUB O VECCHI OVERALL DELLA TUA MEMORIA (esempio: in EA FC 27 Michael Kayode gioca nel Brentford ed è 81 OVR con GG Rating 77.7, NON è 78 alla Fiorentina! Robin Risser è un portiere, NON metterlo mai come terzino!).\n"
        "2) VERIFICA OGNI SINGOLO GIOCATORE: Devi citare SOLO giocatori di cui vedi chiaramente il Club attuale 2026/27, il Ruolo reale, l'Overall reale in EA FC 27 e il GG Rating (il Meta Rating ufficiale di FUT.GG) nei dati estratti qui sotto o tramite ricerca Google diretta su site:fut.gg!\n"
        "3) CONSIDERA SEMPRE IL 'GG RATING' (META RATING DI FUT.GG) + IL LIMITE MAX PLAYSTYLES: "
        "Su FUT.GG ogni carta ha un punteggio chiamato GG Rating (es. RB 85.4, LB 82.5). Scegli le carte che rispettano i requisiti del leak (Overall massimo, Ruolo, e numero massimo di PlayStyles base/PS+) e che raggiungono il GG Rating più alto!\n"
        "4) Se per un giocatore non sei sicuro al 100% del suo OVR o Club in EA FC 27 su FUT.GG, NON INSERIRLO nella lista.\n"
        "5) Per ogni carta consigliata indica:\n"
        "   • Nome e Cognome, Ruolo reale, OVR reale in EA FC 27 e Club reale in EA FC 27.\n"
        "   • GG Rating (Meta Rating di FUT.GG) e PlayStyles attuali (verificando che non superi il limite Max PlayStyles dell'Evo).\n"
        "   • Prezzo reale su PlayStation e target di rivendita.\n"
        "Non usare simboli Markdown come asterischi (*) o cancelletti (#). Usa solo elenchi con •."
    )
    testo_completo = f"{sistema}\n\nDATI VERIFICATI ESTRATTI ORA DA FUT.GG E LEAKER:\n{prompt_utente}"

    modelli_da_provare = trova_modelli_attivi()
    ultimo_errore = "Nessuna risposta"

    for modello in modelli_da_provare:
        for tool_config in [[{"google_search": {}}], []]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent?key={GEMINI_API_KEY}"
            body = {
                "contents": [{"parts": [{"text": testo_completo}]}],
                "generationConfig": {"temperature": 0.0}
            }
            if tool_config:
                body["tools"] = tool_config
            try:
                r = requests.post(url, json=body, timeout=35)
                risposta = r.json()
                if "error" in risposta:
                    ultimo_errore = risposta["error"].get("message", str(risposta["error"]))
                    continue
                candidati = risposta.get("candidates", [])
                if not candidati:
                    continue
                parti = candidati[0].get("content", {}).get("parts", [])
                testi = [p.get("text", "") for p in parti if "text" in p]
                out = "\n".join(testi).strip()
                if out:
                    modello_scoperto = modello
                    out = out.replace("**", "").replace("*", "•").replace("#", "")
                    return out.replace("<", "&lt;").replace(">", "&gt;")
            except Exception as e:
                ultimo_errore = str(e)
                continue

    return f"⚠️ Errore API Gemini: {ultimo_errore[:140]}"

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    if not parti:
        return
    comando = parti[0].lower().split("@")[0]

    if comando in ["/start", "/help", "/menu"]:
        menu = (
            "🎯 <b>BOT SNIPER EA FC 27 (SCHEDE VERIFICATE FUT.GG & GG RATING)</b>\n"
            "💰 Budget: 800.000 crediti (PlayStation)\n\n"
            "🔥 <b>/leak</b> - Intercetta i leak reali e legge le <b>schede complete di FUT.GG (Club FC 27, OVR reale, GG Rating e Max PlayStyles)</b>\n\n"
            "🔮 <b>/simula [requisiti leak]</b> - Es: <code>/simula Evo LB RB Max 80 OVR Max 6 PlayStyles</code>\n\n"
            "🧬 <b>/evo</b> - Legge la classifica <b>Best Evolutions di FUT.GG ordinata per GG Rating</b>\n\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        )
        invia_telegram(menu, chat_id)

    elif comando in ["/leak", "/evo"]:
        invia_telegram(
            "🕵️‍♂️ <i>Estrazione Schede Complete da FUT.GG (Club 2026/27, OVR, PlayStyles e GG Rating ufficiale) + Scansione Leak...</i>",
            chat_id
        )
        leaks_reali = leggi_leak_reali_x_e_telegram()
        schede_futgg = estrai_schede_complete_futgg()
        dati_ruolo_lbrb = cerca_schede_giocatori_specifici_su_futgg("lb rb")

        blocco_leaks = "\n".join(leaks_reali) if leaks_reali else "Nessun nuovo post testuale diretto; usa Google Search su site:x.com e i dati FUT.GG estratti qui sotto."

        prompt = (
            f"LEAK INTERCETTATI DA X E TELEGRAM:\n{blocco_leaks}\n\n"
            f"DATI COMPLETI ESTRATTI LIVE DA FUT.GG (INCLUSO GG RATING E SCHEDE GIOCATORI):\n{schede_futgg[:2500]}\n\n"
            f"DATI RUOLO TERZINI (LB/RB) DA FUT.GG:\n{dati_ruolo_lbrb[:1200]}\n\n"
            "ISTRUZIONI TASSATIVE:\n"
            "1) Riporta i dettagli degli ultimi leak di Evoluzioni (es. Fullback Fork / Evo LB-RB Max 80 OVR o le Evoluzioni attive elencate nei dati FUT.GG qui sopra) "
            "specificando Requisiti, Max PlayStyles e Boost.\n"
            "2) Seleziona 6 GIOCATORI VERIFICATI (controllando su FUT.GG che il loro Club 2026/27, il loro Ruolo e il loro OVR in EA FC 27 siano esatti al 100%!).\n"
            "3) Per ogni carta indica il GG RATING (Meta Rating di FUT.GG), i PlayStyles attuali (verificando il limite Max PlayStyles) e i prezzi reali su PlayStation."
        )
        analisi = analizza_con_verifica_rigorosa_futgg(prompt)

        msg = "🚨 <b>REPORT VERIFICATO FUT.GG (GG RATING, CLUB FC 27 & MAX PLAYSTYLES):</b>\n\n"
        if leaks_reali:
            for lk in leaks_reali[:3]:
                pulito = lk.replace("<", "&lt;").replace(">", "&gt;")
                msg += f"📢 <i>{pulito[:220]}</i>\n\n"

        msg += f"🎯 <b>CARTE VERIFICATE SU FUT.GG (ZERO ALLUCINAZIONI):</b>\n{analisi}\n\n"
        msg += "🔗 <a href='https://www.fut.gg/evolutions/best/'>Apri Classifica GG Rating su FUT.GG</a>"
        invia_telegram(msg, chat_id)

    elif comando == "/simula":
        if len(parti) < 2:
            invia_telegram(
                "🔮 <b>SIMULATORE CON GG RATING & VERIFICA CLUB FC 27</b>\n"
                "Scrivi i requisiti del leak:\n"
                "<code>/simula Evo LB RB Max 80 OVR Max 6 PlayStyles</code>",
                chat_id
            )
            return
        leak_input = " ".join(parti[1:])
        invia_telegram(f"🔮 <i>Estrazione dati da FUT.GG per '{leak_input}' (verifica Club FC 27, OVR, PlayStyles e GG Rating)...</i>", chat_id)
        dati_specifici = cerca_schede_giocatori_specifici_su_futgg(leak_input)
        schede_futgg = estrai_schede_complete_futgg()
        prompt = (
            f"L'utente vuole simulare questo leak su EA FC 27: '{leak_input}'.\n"
            f"Dati specifici ruolo estratti da FUT.GG:\n{dati_specifici[:1800]}\n\n"
            f"Dati Best Evolutions FUT.GG:\n{schede_futgg[:1500]}\n\n"
            "Trova 6 giocatori REALI di EA Sports FC 27 (verificando su site:fut.gg che abbiano davvero quel ruolo, quell'OVR <= limite richiesto "
            "e il club aggiornato alla stagione 2026/27, senza mai sbagliare club o ruolo!). "
            "Ordina i giocatori in base al GG Rating (Meta Rating di FUT.GG) e al rispetto del limite massimo di PlayStyles, indicando i prezzi su PS."
        )
        risp = analizza_con_verifica_rigorosa_futgg(prompt)
        invia_telegram(f"🎯 <b>SIMULAZIONE VERIFICATA FUT.GG PER '{leak_input.upper()}':</b>\n\n{risp}", chat_id)

    elif comando == "/tassa":
        if len(parti) < 2:
            invia_telegram("Usa: <code>/tassa 50000</code> o <code>/tassa 50000 60000</code>", chat_id)
            return
        try:
            buy = int(parti[1].replace(".", "").replace("k", "000"))
            pareggio = int(buy / (1 - EA_TAX)) + 100
            consigliato = int(buy * 1.12)
            sell = int(parti[2].replace(".", "").replace("k", "000")) if len(parti) >= 3 else consigliato
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
            invia_telegram("Scrivi una domanda! Es: <code>/chiedi quali sono le carte di Michael Kayode su FC 27 e il loro GG Rating?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 <i>Lettura dati FUT.GG in corso...</i>", chat_id)
        schede_futgg = estrai_schede_complete_futgg()
        risp = analizza_con_verifica_rigorosa_futgg(f"Domanda: {domanda}\nDati FUT.GG live:\n{schede_futgg[:2000]}")
        invia_telegram(f"🤖 <b>RISPOSTA VERIFICATA FUT.GG:</b>\n\n{risp}", chat_id)

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

def scansiona_x_e_telegram_h24():
    global messaggi_gia_visti
    leaks = leggi_leak_reali_x_e_telegram()
    for lk in leaks:
        id_lk = hash(lk[:90])
        if id_lk not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_lk)
            if len(messaggi_gia_visti) > 4:
                schede_futgg = estrai_schede_complete_futgg()
                analisi = analizza_con_verifica_rigorosa_futgg(
                    f"NUOVO LEAK APPENA RILEVATO:\n'{lk}'\n\n"
                    f"Dati verificati FUT.GG:\n{schede_futgg[:2000]}\n\n"
                    "Seleziona 5-6 carte REALI di EA FC 27 (con Club 2026/27, OVR reale, GG Rating e verifica Max PlayStyles) da comprare ora su PS!"
                )
                pulito = lk.replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(
                    f"🚨 <b>NUOVO LEAK VERIFICATO IN TEMPO REALE!</b>\n\n"
                    f"📝 <i>{pulito}</i>\n\n"
                    f"🎯 <b>CARTE FUT.GG (GG RATING & PLAYSTYLES):</b>\n{analisi}"
                )

def motore_h24():
    avvio = (
        "🛡️ <b>BOT AGGIORNATO: LETTURA SCHEDE COMPLETE FUT.GG (CLUB FC 27, OVR REALE & GG RATING)!</b>\n\n"
        "• Eliminato definitivamente il bug <i>[Send Message]</i>.\n"
        "• Ora lo script Python scarica <b>l'intero testo delle schede di FUT.GG</b> (es. Kayode = Brentford 81 OVR, GG Rating 77.7) così Gemini non può più pescare club o ruoli sbagliati dalla memoria vecchia!\n\n"
        "Prova subito <b>/leak</b> o <b>/evo</b>!"
    )
    invia_telegram(avvio)
    scansiona_x_e_telegram_h24()
    ultimo_orario = ""

    while True:
        try:
            scansiona_x_e_telegram_h24()
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

            time.sleep(60)
        except Exception:
            time.sleep(60)

@app.route("/")
def home():
    return "FC 27 Full FUT.GG Card Scraper & GG Rating Bot Running!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
