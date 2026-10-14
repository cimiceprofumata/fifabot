
import os
import re
import time
import threading
import requests
import cloudscraper
from urllib.parse import quote
from bs4 import BeautifulSoup
from flask import Flask
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
EA_TAX = 0.05

CANALI_X_LEAKERS = [
    "Fut_Scoreboard",
    "FutSheriff_Official",
    "AsyFutTrader",
    "DonkTrading",
    "FutPoliceLeaks",
    "fifatradingromania"
]

PAROLE_TRIGGER = [
    "evo", "evolution", "max ", "req", "boost", "playstyle",
    "pace", "overall", "rating", "sbc", "potm", "leaked", "upcoming", "stats"
]

messaggi_gia_visti = set()
evo_gia_viste = set()
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

def anticipa_mercato_con_gemini(prompt_specifico):
    """Motore Pre-Hype: proibisce di copiare i Trending e calcola in anticipo le carte migliori dai requisiti del leak."""
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    sistema = (
        f"Data e ora attuale italiana: {oggi}. Sei un algoritmo predittivo di compravendita per EA Sports FC 27 Ultimate Team (PlayStation). "
        "IL TUO UNICO OBIETTIVO È FAR COMPRARE LE CARTE ALL'UTENTE PRIMA CHE FINISCANO IN TRENDING SU FUT.GG:\n"
        "1) NON COPIARE I TRENDING PLAYERS: Se una carta è già prima in Trending, è già tardi. Tu devi guardare i REQUISITI e i BOOST del nuovo Leak (o della nuova Evo appena uscita) "
        "e trovare nel database di EA FC 27 le 6 CARTE PERFETTE (Nome, Cognome, OVR, Club) che la massa non ha ancora comprato!\n"
        "2) COME INDIVIDUARE LE CARTE PRE-HYPE (METODO META RATING FUT.GG):\n"
        "   - Cerca carte 'AL LIMITE DEL REQUISITO' (es. se il leak dice Max 82 OVR, Max 85 PAC, cerca carte 81-82 OVR con 83-85 PAC).\n"
        "   - Devono avere PlayStyles base in meta (Quick Step, Anticipate, Finesse Shot, Incisive Pass, Rapid, Technical, Intercept, Jockey) "
        "che sommati al PlayStyle+ regalato dal leak creano una combo da 92+ Meta Rating su FUT.GG.\n"
        "   - Devono avere link molto ricercati (Premier League, LaLiga, Serie A, Francia, Brasile) o possibilità di Catena Evo (Evo Chain).\n"
        "3) FORMATO OBBLIGATORIO DELLA RISPOSTA:\n"
        "   • SCHEDA DEL LEAK / NUOVA EVO: Indica Fonte, Data/Ora, Requisiti esatti di ingresso e quali Stats + PlayStyles aggiunge.\n"
        "   • 6 CARTE PRE-TRENDING DA COMPRARE ORA: Per ogni giocatore scrivi Nome e Cognome, OVR e versione, PlayStyles attuali + come diventa col boost, "
        "Prezzo attuale pre-hype su PS (650-1.500 cr per gli Oro scarto, 11k-20k per TOTW/Speciali) e Target di vendita quando andrà in Trending su FUT.GG (3.500-9.500 cr per gli Oro, 25k-45k per Speciali).\n"
        "4) VIETATO INVENTARE PREZZI ASSURDI (gli Oro <83 hanno tetto massimo a 10.000 crediti!). Non usare asterischi (*) o cancelletti (#), usa solo •."
    )
    testo_completo = f"{sistema}\n\nDATI LIVE INTERCETTATI:\n{prompt_specifico}"

    modelli_da_provare = trova_modelli_attivi()
    ultimo_errore = "Nessuna risposta"

    for modello in modelli_da_provare:
        for tool_config in [[{"google_search": {}}], []]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent?key={GEMINI_API_KEY}"
            body = {
                "contents": [{"parts": [{"text": testo_completo}]}],
                "generationConfig": {"temperature": 0.15}
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

def scarica_testo_jina(target_url):
    """Buca Cloudflare e i blocchi IP di Render sia per Telegram che per FUT.GG."""
    try:
        h = dict(HEADERS)
        h["X-No-Cache"] = "true"
        resp = requests.get(f"https://r.jina.ai/{target_url}", headers=h, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text
    except Exception:
        pass
    return ""

def leggi_leak_telegram_tramite_jina():
    """Legge i canali Telegram dei leaker passando da Jina (che non viene schermato da Render) + fallback HTML."""
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_oggi = datetime.now(tz_it).strftime("%d/%m/%Y")

    for canale in CANALI_X_LEAKERS[:4]:
        url_tg = f"https://t.me/s/{canale}"
        testo_raw = scarica_testo_jina(url_tg)
        if not testo_raw:
            continue

        # Divide la pagina in blocchi di messaggi e scarta le scritte di interfaccia di Telegram
        righe = testo_raw.split("\n")
        messaggi_canale = []
        buffer_msg = []

        for r in righe:
            r_clean = r.strip()
            if not r_clean:
                continue
            # Scarta righe inutili di intestazione/footer Telegram
            if any(skip in r_clean for skip in [
                "Title:", "URL Source:", "Markdown Content:", "Warning:",
                "Download Telegram", "View in Telegram", "Send Message", "subscribers", "photos", "videos"
            ]):
                continue
            if r_clean.startswith("![Image"):
                continue

            # Cerca se nella riga c'è l'orario del post (es. 18:45 o 07:30)
            match_ora = re.search(r"\b([01]\d|2[0-3]):([0-5]\d)\b", r_clean)
            if match_ora and buffer_msg:
                testo_unito = " ".join(buffer_msg).strip()
                if len(testo_unito) > 25:
                    messaggi_canale.append((f"{ora_oggi} {match_ora.group(0)}", testo_unito[:420]))
                buffer_msg = []
            else:
                if len(r_clean) > 15 and not r_clean.startswith("http"):
                    buffer_msg.append(r_clean)

        # Se non ha trovato orari separati, prende comunque gli ultimi paragrafi di testo del canale
        if not messaggi_canale and buffer_msg:
            for pezzo in buffer_msg[-3:]:
                if len(pezzo) > 30:
                    messaggi_canale.append((f"{ora_oggi} (Live)", pezzo[:420]))

        for data_ora, txt in messaggi_canale[-2:]:
            raccolta.append({
                "canale": f"@{canale}",
                "data_ora": data_ora,
                "testo": txt
            })

    return raccolta

def leggi_requisiti_e_boost_ultima_evo_futgg():
    """Entra nella pagina Evoluzioni di FUT.GG e apre ANCHE la prima Evoluzione in alto per estrarre Requisiti e Boost veri!"""
    testo_main = scarica_testo_jina("https://www.fut.gg/evolutions/")
    evoluzioni = []
    primo_link_evo = ""

    matches = re.findall(r"(/evolutions/\d+-([a-zA-Z0-9-]+)/)", testo_main)
    for full_path, slug in matches:
        nome_e = slug.replace("-", " ").title()
        if nome_e not in evoluzioni:
            evoluzioni.append(nome_e)
            if not primo_link_evo:
                primo_link_evo = f"https://www.fut.gg{full_path}"

    dettaglio_prima_evo = ""
    if primo_link_evo:
        testo_singola_evo = scarica_testo_jina(primo_link_evo)
        righe_valide = []
        for r in testo_singola_evo.split("\n"):
            rc = r.strip()
            if len(rc) > 10 and not rc.startswith("![") and "http" not in rc:
                righe_valide.append(rc)
        dettaglio_prima_evo = "\n".join(righe_valide[:35])

    return evoluzioni[:6], primo_link_evo, dettaglio_prima_evo[:1800]

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    if not parti:
        return
    comando = parti[0].lower().split("@")[0]

    if comando in ["/start", "/help", "/menu"]:
        menu = (
            "🎯 <b>BOT PRE-TRENDING LEAK & EVO SNIPER (FC 27)</b>\n"
            "💰 Budget: 800.000 crediti (PlayStation)\n\n"
            "🔥 <b>/leak</b> - Intercetta gli ultimi leak di X (@Fut_Scoreboard, @FutSheriff, @AsyFutTrader) ed estrae i <b>6 giocatori Pre-Hype</b> PRIMA che finiscano in Trending su FUT.GG!\n\n"
            "🧬 <b>/evo</b> - Entra nell'ultima Evoluzione di FUT.GG, legge Requisiti + Boost e trova le gemme nascoste ancora a scarto\n\n"
            "🔮 <b>/simula [requisiti e boost]</b> - Incolla un leak appena uscito su X per avere subito i 6 nomi da comprare prima di tutti\n\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram("⚡ <i>Lettura diretta canali Leak (Bypass Jina) + Calcolo carte PRE-TRENDING prima della massa...</i>", chat_id)
        leaks = leggi_leak_telegram_tramite_jina()
        evoluzioni_attive, link_ultima_evo, dettaglio_ultima_evo = leggi_requisiti_e_boost_ultima_evo_futgg()

        if leaks:
            blocco_leaks = "\n".join([f"- [{x['data_ora']}] {x['canale']}: {x['testo']}" for x in leaks[-6:]])
        else:
            blocco_leaks = "Cerca tramite Google Search gli ultimissimi tweet di @Fut_Scoreboard, @FutSheriff e @AsyFutTrader delle ultime ore."

        str_evo = ", ".join(evoluzioni_attive)

        prompt = (
            f"ULTIMI MESSAGGI INTERCETTATI DAI CANALI LEAK:\n{blocco_leaks}\n\n"
            f"ULTIME EVOLUZIONI SU FUT.GG: {str_evo}\n"
            f"DETTAGLIO REQUISITI E BOOST DELL'ULTIMA EVO ({link_ultima_evo}):\n{dettaglio_ultima_evo}\n\n"
            "COMPITO CRITICO (ANTICIPARE IL TRENDING):\n"
            "1) Riporta chiaramente l'ultimo leak di Evoluzione/SBC dai dati qui sopra (o dalla ricerca web delle ultime ore) con Data/Ora, Requisiti esatti, Stats e PlayStyles aggiunti.\n"
            "2) NON DARE I GIOCATORI GIÀ IN TRENDING SU FUT.GG! Analizza tu i REQUISITI e i BOOST e trova nel database di EA FC 27 "
            "6 CARTE SPECIFICHE (Nome, Cognome, OVR, Club) che non sono ancora esplose di prezzo ma che diventeranno le più desiderate "
            "perché toccano il limite massimo dei requisiti, hanno già PlayStyles meta (Quick Step, Anticipate, Finesse Shot, Incisive Pass, Rapid, Technical) e ottimi link.\n"
            "3) Indica il prezzo attuale pre-hype su PlayStation (es. 700-1.200 cr per Oro rari, 11k-18k per Inform/Speciali) e a quanto rivenderle quando finiranno in Trending."
        )
        analisi = anticipa_mercato_con_gemini(prompt)

        msg = "🚨 <b>INTERCETTAZIONE LEAK & CARTE PRE-TRENDING (PRIMA DELLA MASSA):</b>\n\n"
        if leaks:
            for item in leaks[-3:]:
                pulito = item["testo"].replace("<", "&lt;").replace(">", "&gt;")
                msg += f"🕒 <b>{item['data_ora']} | {item['canale']}:</b>\n<i>{pulito[:220]}</i>\n\n"
        if evoluzioni_attive:
            str_evo4 = ", ".join(evoluzioni_attive[:4])
            msg += f"🧬 <b>Ultime Evo rilevate:</b> <code>{str_evo4}</code>\n\n"

        msg += f"🔮 <b>CARTE DA COMPRARE PRIMA CHE VADANO IN TRENDING:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 <i>Apertura ultima Evoluzione su FUT.GG: estrazione Requisiti, Boost e calcolo carte Pre-Hype...</i>", chat_id)
        evoluzioni_attive, link_ultima_evo, dettaglio_ultima_evo = leggi_requisiti_e_boost_ultima_evo_futgg()
        str_evo = ", ".join(evoluzioni_attive)

        prompt = (
            f"EVOLUZIONI ATTIVE SU FUT.GG: {str_evo}\n"
            f"TESTO INTERNO DELL'ULTIMA EVOLUZIONE ({link_ultima_evo}):\n{dettaglio_ultima_evo}\n\n"
            "1) Estrai i Requisiti esatti e i Boost (Stats + PlayStyles) dell'ultima Evoluzione.\n"
            "2) Invece dei soliti giocatori già noti, trova 6 GIOCATORI SPECIFICI (Nome, Cognome, OVR, versione, Club) nel database di EA FC 27 "
            "che entrano perfettamente nei requisiti, creano una combo devastante di PlayStyles Meta e alto Meta Rating su FUT.GG, "
            "e sono ancora acquistabili a basso prezzo su PS per fare compravendita."
        )
        consiglio = anticipa_mercato_con_gemini(prompt)
        msg = (
            f"🔥 <b>ANALISI PROFONDA ULTIMA EVO & GEMME PRE-HYPE:</b>\n\n"
            f"🧬 <b>Ultime Evo:</b> <code>{str_evo}</code>\n\n"
            f"🎯 <b>REQUISITI, BOOST & CARTE DA ANTICIPARE:</b>\n{consiglio}\n\n"
            f"🔗 <a href='{link_ultima_evo or 'https://www.fut.gg/evolutions/'}'>Apri Ultima Evoluzione su FUT.GG</a>"
        )
        invia_telegram(msg, chat_id)

    elif comando == "/simula":
        if len(parti) < 2:
            invia_telegram(
                "🔮 <b>ANTICIPATORE MANUALE LEAK X</b>\n"
                "Appena vedi un requisito leakato su X, scrivilo qui per avere i 6 nomi PRIMA che escano su FUT.GG:\n"
                "<code>/simula Evo CC Max 82 OVR Max 84 PAC Boost +8 PAC +10 PAS PlayStyle+ Incisive Pass</code>",
                chat_id
            )
            return
        leak_input = " ".join(parti[1:])
        invia_telegram("🔮 <i>Calcolo combinazioni PlayStyles + Meta Rating per anticipare il Trending di FUT.GG...</i>", chat_id)
        prompt = (
            f"NUOVO LEAK APPENA INSERITO: '{leak_input}'\n"
            "Trova nel database di EA FC 27 i 6 GIOCATORI ESATTI (Nome, Cognome, OVR, versione e Club) che:\n"
            "• Toccano il limite massimo dei requisiti indicati nel leak.\n"
            "• Hanno già PlayStyles in meta che combinati con questo boost li porteranno in cima al Meta Rating di FUT.GG.\n"
            "• Indica prezzo di acquisto immediato pre-hype su PlayStation e target di rivendita quando la community li scoprirà."
        )
        risp = anticipa_mercato_con_gemini(prompt)
        invia_telegram(f"🎯 <b>CARTE DA COMPRARE SUBITO (PRE-TRENDING):</b>\n\n{risp}", chat_id)

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
            invia_telegram("Scrivi una domanda! Es: <code>/chiedi migliori DC 81-82 OVR con Anticipo da comprare a scarto per future Evo?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 <i>Ricerca gemme nascoste nel database FC 27...</i>", chat_id)
        risp = anticipa_mercato_con_gemini(domanda)
        invia_telegram(f"🤖 <b>ANALISTA PRE-HYPE:</b>\n\n{risp}", chat_id)

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

# ================= MONITORAGGIO H24 PER ANTICIPARE IL MERCATO =================
def scansiona_e_anticipa_h24():
    """Controlla ogni 60 secondi sia i nuovi Leak su Telegram (via Jina) sia l'uscita di una nuova Evo su FUT.GG."""
    global messaggi_gia_visti, evo_gia_viste

    # 1. Controlla se è uscito un nuovo post sui canali Leak
    leaks = leggi_leak_telegram_tramite_jina()
    for item in leaks:
        txt = item["testo"]
        id_msg = hash(txt[:80])
        if id_msg not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_msg)
            if any(k in txt.lower() for k in PAROLE_TRIGGER):
                if len(messaggi_gia_visti) > 5:
                    analisi = anticipa_mercato_con_gemini(
                        f"NUOVO LEAK APPENA USCITO DA {item['canale']} ({item['data_ora']}):\n'{txt}'\n\n"
                        "NON GUARDARE I TRENDING ATTUALI. Analizza subito i requisiti e i boost di questo leak e trova "
                        "nel database di EA FC 27 le 6 CARTE SPECIFICHE (Nome, Cognome, OVR, Club) con i migliori PlayStyles Meta "
                        "da comprare ADESSO a prezzo basso PRIMA che vadano in Trending su FUT.GG!"
                    )
                    pulito = txt[:340].replace("<", "&lt;").replace(">", "&gt;")
                    notifica = (
                        f"🚨 <b>NUOVO LEAK INTERCETTATO AL SECONDO ZERO!</b>\n"
                        f"🕒 <b>{item['data_ora']} | {item['canale']}</b>\n\n"
                        f"📝 <i>{pulito}</i>\n\n"
                        f"🔮 <b>CARTE DA COMPRARE PRIMA CHE VADANO IN TRENDING:</b>\n{analisi}"
                    )
                    invia_telegram(notifica)

    # 2. Controlla se è appena apparsa una nuova Evoluzione su FUT.GG (es. alle 19:00)
    evoluzioni_attive, link_prima, dettaglio_prima = leggi_requisiti_e_boost_ultima_evo_futgg()
    for nome_evo in evoluzioni_attive:
        if nome_evo not in evo_gia_viste:
            evo_gia_viste.add(nome_evo)
            if len(evo_gia_viste) > 6:
                analisi_evo = anticipa_mercato_con_gemini(
                    f"È APPENA USCITA UNA NUOVA EVOLUZIONE SU FUT.GG: {nome_evo}\n"
                    f"Dettagli estratti dalla pagina:\n{dettaglio_prima}\n\n"
                    "Individua subito 6 CARTE SPECIFICHE (Nome, Cognome, OVR, Club) che entrano in questi requisiti "
                    "PRIMA che la community le faccia salire in Trending!"
                )
                invia_telegram(
                    f"🔥 <b>NUOVA EVOLUZIONE APPENA CARICATA SU FUT.GG: {nome_evo}!</b>\n\n"
                    f"🎯 <b>CARTE DA COMPRARE SUBITO (PRE-TRENDING):</b>\n{analisi_evo}\n\n"
                    f"🔗 <a href='{link_prima}'>Apri {nome_evo} su FUT.GG</a>"
                )

def motore_h24():
    avvio = (
        "⚡ <b>BOT AGGIORNATO: MODALITÀ 'ANTICIPA IL TRENDING (PRE-HYPE)'!</b>\n\n"
        "• Rimossa la copia dei giocatori già in Trending.\n"
        "• Attivato lettore Jina anche sui canali Telegram dei Leaker per non essere mai schermati da Render.\n"
        "• Estrazione profonda dei Requisiti dell'ultima Evo e ricerca delle <b>carte dormienti (a prezzo di scarto)</b> prima che la massa le compri.\n\n"
        "Prova subito <b>/leak</b> oppure <b>/evo</b>!"
    )
    invia_telegram(avvio)
    scansiona_e_anticipa_h24()
    ultimo_orario = ""

    while True:
        try:
            scansiona_e_anticipa_h24()
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
    return "FC 27 Pre-Trending Leak Interceptor Running!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
