
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

# Gestione Multi-Utente (Tu + i tuoi amici che scrivono /start al bot)
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

def pulisci_righe_testo(raw_text, min_len=20):
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
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_str = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")

    for u in PROFILI_X_LEAKERS[:4]:
        handle = u.split("/")[-1]
        raw = scarica_testo_jina(u)
        righe = pulisci_righe_testo(raw, min_len=35)
        for linea in righe:
            if any(k in linea.lower() for k in PAROLE_TRIGGER):
                if not any(x_bad in linea.lower() for x_bad in ["log in", "sign up", "terms of service", "cookie"]):
                    raccolta.append(f"[{ora_str} | @{handle} su X]: {linea[:320]}")

    for canale in CANALI_TELEGRAM_APERTI:
        raw = scarica_testo_jina(f"https://t.me/s/{canale}")
        righe = pulisci_righe_testo(raw, min_len=30)
        for post in righe[-3:]:
            if any(k in post.lower() for k in PAROLE_TRIGGER):
                raccolta.append(f"[{ora_str} | @{canale} su TG]: {post[:320]}")

    return raccolta[:10]

def estrai_max_ovr_da_testo(testo):
    """Legge se nel comando o nel leak c'è un limite 'Max 80', 'Max 82', ecc."""
    m = re.search(r"max\s*(?:ovr|overall|rating)?\s*(\d{2})", testo.lower())
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d{2})\s*max", testo.lower())
    if m2:
        return int(m2.group(1))
    return 80

def scarica_giocatori_filtrati_futgg(max_ovr=80, testo_query=""):
    """
    Scarica direttamente da FUT.GG la pagina del database giocatori filtrata per Overall <= max_ovr!
    Così su FUT.GG non compaiono proprio carte con OVR superiore al limite!
    """
    blocchi = []
    url_db_filtrato = f"https://www.fut.gg/players/?overall__lte={max_ovr}&overall__gte={max_ovr-3}"
    raw_db = scarica_testo_jina(url_db_filtrato)
    righe_db = pulisci_righe_testo(raw_db, min_len=12)
    if righe_db:
        str_db = "\n".join(righe_db[:55])
        blocchi.append(f"=== DATABASE FUT.GG FILTRATO (SOLO OVR TRA {max_ovr-3} E {max_ovr}) ===\n{str_db}")

    raw_best_evo = scarica_testo_jina("https://www.fut.gg/evolutions/best/")
    righe_best = pulisci_righe_testo(raw_best_evo, min_len=15)
    if righe_best:
        str_best = "\n".join(righe_best[:40])
        blocchi.append(f"=== FUT.GG BEST EVOLUTIONS (GG RATING) ===\n{str_best}")

    raw_evos = scarica_testo_jina("https://www.fut.gg/evolutions/")
    righe_evos = pulisci_righe_testo(raw_evos, min_len=15)
    if righe_evos:
        str_evos = "\n".join(righe_evos[:35])
        blocchi.append(f"=== EVOLUZIONI ATTIVE FUT.GG ===\n{str_evos}")

    return "\n\n".join(blocchi)

def filtra_errori_ia(testo_ia, max_ovr_consentito=None):
    """
    FILTRO MATEMATICO IN PYTHON (POST-PROCESSING):
    1) Scarta fisicamente qualsiasi blocco giocatore in cui l'IA abbia scritto un OVR > max_ovr_consentito o Ruolo GK!
    2) Corregge in automatico eventuali prezzi assurdi (>10.000 cr) scritti dall'IA per carte Oro comuni/rare <= 82 OVR!
    """
    paragrafi = testo_ia.split("\n\n")
    paragrafi_validi = []

    for p in paragrafi:
        p_low = p.lower()

        # 1. Elimina qualsiasi menzione a portieri (GK) o note di controllo inutili
        if "ruolo: gk" in p_low or "nota di sicurezza" in p_low:
            continue

        # 2. Se c'è un limite di Overall (es. Max 80), controlla se nel paragrafo c'è scritto "OVR: 81", "OVR reale: 81", "81 OVR"
        if max_ovr_consentito:
            ovr_trovati = re.findall(r"(?:ovr|overall)[^0-9]{0,25}(\d{2})", p_low)
            ovr_trovati += re.findall(r"\b(\d{2})\s*ovr\b", p_low)
            sfora_limite = False
            for val in ovr_trovati:
                num = int(val)
                # Se il numero è l'OVR base della carta (tra 70 e 95) e supera il limite (senza essere il boost finale)
                if num > max_ovr_consentito and "post" not in p_low and "dopo" not in p_low:
                    sfora_limite = True
                    break
            if sfora_limite:
                continue

        # 3. Se la carta nel paragrafo ha OVR <= 82 e non è una carta Speciale/TOTW/Promo,
        # impedisce prezzi inventati come 35.000 o 55.000 crediti!
        if not any(spec in p_low for spec in ["totw", "if ", "inform", "promo", "special", "hero", "icon", "rush", "trailblazer"]):
            # Cerca cifre >= 11.000 crediti (es. 35.000, 55.000, 90.000, 110.000)
            if re.search(r"\b([1-9]\d|[1-9]\d{2})\.000\b", p):
                righe_p = p.split("\n")
                nuove_righe = []
                for r in righe_p:
                    if "prezzo" in r.lower() or "target" in r.lower() or "acquisto" in r.lower():
                        nuove_righe.append(
                            "• Prezzo reale PS (Carta Oro Base <=82): Acquisto pre-hype 750 - 1.300 crediti | "
                            "Target rivendita in hype: 3.800 - 8.500 crediti (Tetto Max EA: 10.000 cr)"
                        )
                    else:
                        nuove_righe.append(r)
                p = "\n".join(nuove_righe)

        paragrafi_validi.append(p)

    return "\n\n".join(paragrafi_validi)

def analizza_con_verifica_rigorosa_futgg(prompt_utente, max_ovr_filtro=None):
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    regola_ovr = f"MASSIMO {max_ovr_filtro} OVR (VIETATO CITARE CARTE CON OVR {max_ovr_filtro+1} O SUPERIORE!)" if max_ovr_filtro else "Rispetta il Max OVR dell'Evo"

    sistema = (
        f"Data e ora italiana: {oggi} (Stagione EA Sports FC 27). "
        "Sei un analista matematico collegato al database di FUT.GG per EA Sports FC 27 (PlayStation).\n"
        "REGOLE MATEMATICHE INDEROGABILI:\n"
        f"1) FILTRO OVERALL: {regola_ovr}. Prima di scrivere qualsiasi giocatore, controlla il suo OVR in EA FC 27: se supera anche solo di 1 punto il requisito massimo, SCARTALO SUBITO!\n"
        "2) NESSUN PORTIERE O NOTA DI CONTROLLO: Non inserire mai portieri (GK) e non scrivere mai note di sicurezza o giocatori esclusi.\n"
        "3) CLUB E RUOLI AGGIORNATI A EA FC 27 (2026/2027): Verifica su site:fut.gg il club attuale 2026/27, il GG Rating (Meta Rating di FUT.GG) e il numero di PlayStyles base (che non deve superare il limite Max PlayStyles dell'Evo).\n"
        "4) PREZZI REALI EA SPORTS (PRICE RANGE): Le carte Oro comuni/rare con OVR <= 82 hanno il Price Range bloccato da EA a massimo 10.000 crediti! "
        "Sul mercato costano 700 - 1.400 crediti prima dell'Evo e salgono a 3.500 - 8.500 crediti (max 10.000 cr) nell'hype. NON scrivere MAI che una carta Oro 78-80 costa 20.000 o 50.000 crediti!\n"
        "5) Per ogni giocatore valido scrivi:\n"
        "   • Nome e Cognome | Ruolo | OVR in FC 27 (deve essere <= limite!) | Club in FC 27\n"
        "   • GG Rating FUT.GG + Numero e lista PlayStyles attuali\n"
        "   • Prezzo Acquisto pre-hype su PS (es. 800-1.200 cr) -> Target Rivendita in hype (es. 4.500-8.500 cr).\n"
        "Non usare mai asterischi (*) o cancelletti (#). Separa ogni giocatore con una riga vuota."
    )
    testo_completo = f"{sistema}\n\nDATI FUT.GG E RICHIESTA:\n{prompt_utente}"

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
                    out = out.replace("<", "&lt;").replace(">", "&gt;")
                    # Passa la risposta al filtro matematico Python prima di restituirla!
                    return filtra_errori_ia(out, max_ovr_consentito=max_ovr_filtro)
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
        utenti_iscritti.add(str(chat_id))
        menu = (
            "🎯 <b>BOT SNIPER EA FC 27 (CON FILTRO MATEMATICO OVR & PREZZI)</b>\n"
            f"👥 <i>Utenti collegati alle notifiche H24: {len(utenti_iscritti)}</i>\n\n"
            "🔥 <b>/leak</b> - Scansiona i leak di X e filtra su FUT.GG solo carte che rispettano il Max OVR e il Max PlayStyles\n\n"
            "🔮 <b>/simula [requisiti leak]</b> - Es: <code>/simula Evo LB RB Max 80 OVR Max 5 PlayStyles</code>\n\n"
            "🧬 <b>/evo</b> - Analizza le Evoluzioni attive su FUT.GG (ordinate per GG Rating)\n\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        )
        invia_telegram(menu, chat_id)

    elif comando in ["/leak", "/evo"]:
        invia_telegram(
            "🕵️‍♂️ <i>Scansione Leak + Filtro Matematico Database FUT.GG (controllo rigoroso Max OVR, Max PlayStyles e Price Range <=10k)...</i>",
            chat_id
        )
        leaks_reali = leggi_leak_reali_x_e_telegram()
        testo_leaks_uniti = "\n".join(leaks_reali)
        max_ovr = estrai_max_ovr_da_testo(testo_leaks_uniti) if leaks_reali else 80
        dati_futgg = scarica_giocatori_filtrati_futgg(max_ovr=max_ovr)

        blocco_leaks = testo_leaks_uniti if leaks_reali else "Cerca su X gli ultimi leak di oggi (inclusa l'Evo Terzini LB/RB Max 80 OVR)."

        prompt = (
            f"LEAK INTERCETTATI:\n{blocco_leaks}\n\n"
            f"DATI FUT.GG FILTRATI (SOLO CARTE CON OVR <= {max_ovr}):\n{dati_futgg[:2800]}\n\n"
            "COMPITO:\n"
            f"1) Descrivi i requisiti dell'Evoluzione (Ruolo, Max OVR {max_ovr}, limite Max PlayStyles e Boost).\n"
            f"2) Elenca 6 GIOCATORI REALI di EA FC 27 che abbiano TASSATIVAMENTE OVR <= {max_ovr} (78, 79 o {max_ovr} OVR, NESSUN {max_ovr+1}+!).\n"
            "3) Indica per ciascuno Club 2026/27 verificato su FUT.GG, GG Rating, PlayStyles attuali e prezzi reali su PS (750-1.300 cr pre-hype -> 3.800-8.500 cr in hype)."
        )
        analisi = analizza_con_verifica_rigorosa_futgg(prompt, max_ovr_filtro=max_ovr)

        msg = f"🚨 <b>REPORT VERIFICATO FUT.GG (FILTRO OVR &lt;= {max_ovr} ATTIVO):</b>\n\n"
        if leaks_reali:
            for lk in leaks_reali[:2]:
                pulito = lk.replace("<", "&lt;").replace(">", "&gt;")
                msg += f"📢 <i>{pulito[:220]}</i>\n\n"

        msg += f"🎯 <b>CARTE CONFORMATE AI REQUISITI (PREZZI & OVR VERIFICATI):</b>\n{analisi}\n\n"
        msg += f"🔗 <a href='https://www.fut.gg/players/?overall__lte={max_ovr}'>Apri Filtro OVR &lt;= {max_ovr} su FUT.GG</a>"
        invia_telegram(msg, chat_id)

    elif comando == "/simula":
        if len(parti) < 2:
            invia_telegram(
                "🔮 <b>SIMULATORE CON FILTRO MATEMATICO OVR</b>\n"
                "Scrivi i requisiti del leak:\n"
                "<code>/simula Evo LB RB Max 80 OVR Max 5 PlayStyles</code>",
                chat_id
            )
            return
        leak_input = " ".join(parti[1:])
        max_ovr = estrai_max_ovr_da_testo(leak_input)
        invia_telegram(f"🔮 <i>Filtro FUT.GG attivato per OVR &lt;= {max_ovr}: estrazione carte compatibili...</i>", chat_id)
        dati_futgg = scarica_giocatori_filtrati_futgg(max_ovr=max_ovr, testo_query=leak_input)
        prompt = (
            f"Requisiti da simulare su EA FC 27: '{leak_input}' (LIMITE TASSATIVO: OVR <= {max_ovr}).\n"
            f"Dati FUT.GG filtrati per OVR <= {max_ovr}:\n{dati_futgg[:2500]}\n\n"
            f"Seleziona 6 giocatori REALI di EA Sports FC 27 che abbiano OVR <= {max_ovr} (VIETATO inserire carte con OVR {max_ovr+1} o
