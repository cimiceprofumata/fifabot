import os
import re
import time
import threading
import requests
import cloudscraper
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
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

# Canali Telegram pubblici che replicano in tempo reale i tweet di X dei leaker
CANALI_TG_LEAK = [
    "Fut_Scoreboard",
    "futpoliceleaks",
    "fifatradingromania",
    "futtrading"
]

# Handle X ufficiali monitorati
HANDLES_X = [
    "Fut_Scoreboard",
    "FutPoliceLeaks",
    "KillerFutTrade",
    "FutSheriff",
    "AsyFutTrader",
    "DonkTrading"
]

SPAM_WORDS = [
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
    "embed",
    "log in",
    "sign up",
    "cookie",
    "privacy policy",
    "rate limit",
    "navigation",
    "search players"
]

TRIGGERS_LEAK = [
    "evo", "evolution", "max ", "max 8", "max 7", "req", "boost",
    "playstyle", "ps+", "pace", "overall", "rating", "sbc", "potm",
    "leaked", "upcoming", "official stats", "lb", "rb", "cb", "cdm",
    "cm", "cam", "lw", "rw", "st", "fullback"
]

messaggi_gia_visti = set()
ultimo_update_id = 0
modello_scoperto = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache"
}

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)

def invia_telegram(testo, chat_id=None):
    if not TELEGRAM_TOKEN or not testo:
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
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code != 200:
                testo_puro = re.sub(r"<[^>]+>", "", testo)[:4000]
                payload_fb = {
                    "chat_id": target,
                    "text": testo_puro,
                    "disable_web_page_preview": True
                }
                requests.post(url, json=payload_fb, timeout=10)
        except Exception as e:
            print("Err TG:", e)

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
        r = requests.get(f"{base}?key={GEMINI_API_KEY}", timeout=6).json()
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

def scarica_jina(target_url):
    try:
        h = dict(HEADERS)
        h["X-Return-Format"] = "markdown"
        resp = requests.get(f"https://r.jina.ai/{target_url}", headers=h, timeout=10)
        if resp.status_code == 200 and len(resp.text) > 120:
            return resp.text
    except Exception:
        pass
    return ""

def scarica_parallelo(lista_urls):
    if not lista_urls:
        return []
    with ThreadPoolExecutor(max_workers=5) as ex:
        return list(ex.map(scarica_jina, lista_urls))

def leggi_telegram_html_diretto(canale):
    """Legge direttamente i post HTML di Telegram con BeautifulSoup (non consuma quota Jina e legge data/ora esatta)."""
    post_estratti = []
    tz_it = timezone(timedelta(hours=2))
    urls_tentativo = [
        f"https://t.me/s/{canale}",
        f"https://r.jina.ai/https://t.me/s/{canale}"
    ]
    for u in urls_tentativo:
        try:
            resp = scraper.get(u, headers=HEADERS, timeout=8)
            if resp.status_code != 200 or len(resp.text) < 300:
                continue
            if "tgme_widget_message" in resp.text:
                soup = BeautifulSoup(resp.text, "html.parser")
                blocchi = soup.find_all("div", class_="tgme_widget_message")
                for b in blocchi[-6:]:
                    t_box = b.find("div", class_="tgme_widget_message_text")
                    if not t_box:
                        continue
                    txt = t_box.get_text(separator=" ").strip()
                    if len(txt) < 20 or any(sp in txt.lower() for sp in SPAM_WORDS):
                        continue
                    ora_post = datetime.now(tz_it).strftime("%d/%m %H:%M")
                    t_tag = b.find("time")
                    if t_tag and t_tag.get("datetime"):
                        try:
                            dt = datetime.fromisoformat(t_tag["datetime"].replace("Z", "+00:00"))
                            ora_post = dt.astimezone(tz_it).strftime("%d/%m %H:%M")
                        except Exception:
                            pass
                    if any(k in txt.lower() for k in TRIGGERS_LEAK):
                        post_estratti.append(f"[{ora_post} | @{canale}]: {txt[:380]}")
                if post_estratti:
                    break
        except Exception:
            continue
    return post_estratti

def leggi_leak_esclusivi_da_x_e_tg():
    """
    Raccoglie SOLO i leak da Telegram e dai mirror di X.
    NON legge le Evoluzioni già vecchie/attive di FUT.GG!
    """
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_str = datetime.now(tz_it).strftime("%d/%m %H:%M")

    # 1. Estrazione diretta dai canali Telegram dei leaker
    with ThreadPoolExecutor(max_workers=4) as ex:
        risultati_tg = list(ex.map(leggi_telegram_html_diretto, CANALI_TG_LEAK))
    for lista_c in risultati_tg:
        raccolta.extend(lista_c[-3:])

    # 2. Estrazione da X / Syndication Jina per gli handle principali
    urls_x = [f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{h}" for h in HANDLES_X[:4]]
    raws_x = scarica_parallelo(urls_x)
    for idx, raw in enumerate(raws_x):
        if not raw:
            continue
        soup = BeautifulSoup(raw, "html.parser")
        testo_pulito = soup.get_text(separator="\n")
        for linea in testo_pulito.split("\n"):
            lc = linea.strip()
            if len(lc) > 35 and any(k in lc.lower() for k in TRIGGERS_LEAK):
                if not any(sp in lc.lower() for sp in SPAM_WORDS):
                    raccolta.append(f"[{ora_str} | @{HANDLES_X[idx]} X]: {lc[:350]}")

    return raccolta[:10]

def estrai_parametri_da_leak(testo):
    """Estrae Max OVR, Ruolo e Max PlayStyles dal testo del leak."""
    t_low = testo.lower()
    max_ovr = 80

    patterns_ovr = [
        r"overall\s*max\s*(\d{2})",
        r"max\s*(?:ovr|overall|rating)?\s*[:=]?\s*(\d{2})",
        r"(\d{2})\s*max\s*(?:ovr|overall)?",
        r"\b(7[5-9]|8[0-6])\s*ovr\b"
    ]
    for pat in patterns_ovr:
        m = re.search(pat, t_low)
        if m:
            val = int(m.group(1))
            if 70 <= val <= 90:
                max_ovr = val
                break

    ruolo = None
    for r_code in ["lb", "rb", "cb", "cdm", "cm", "cam", "lw", "rw", "st"]:
        if re.search(rf"\b{r_code}\b", t_low):
            ruolo = r_code
            break

    return max_ovr, ruolo

def pulisci_corpo_scheda_futgg(raw_text, nome_giocatore=""):
    """
    SALTA IL MENU DI NAVIGAZIONE DI FUT.GG!
    Inizia a leggere solo da dove compare il nome del giocatore nella scheda,
    convertendo le icone ![Club] e ![PlayStyle] in testo chiaro.
    """
    if not raw_text:
        return ""

    # Converte ![Testo Icona](url) in Testo Icona e rimuove gli URL dei link
    testo = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r" [\1] ", raw_text)
    testo = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", testo)

    righe = []
    trovato_inizio_carta = False
    prima_parte_nome = nome_giocatore.split()[0].lower() if nome_giocatore else ""

    for r in testo.split("\n"):
        rc = r.strip()
        rl = rc.lower()
        if len(rc) < 2:
            continue
        if rc.startswith("http") or rc.startswith("Title:") or rc.startswith("URL Source:"):
            continue
        # Ignora le voci del menu in alto di FUT.GG finché non incontra il nome del calciatore
        if not trovato_inizio_carta:
            if prima_parte_nome and prima_parte_nome in rl:
                trovato_inizio_carta = True
            elif any(m_word in rl for m_word in ["evolutions", "sbc", "packs", "market", "squad builder", "database"]):
                continue
        if any(sp in rl for sp in SPAM_WORDS):
            continue
        righe.append(rc)

    # Prende il cuore della scheda (fino a 2.200 caratteri) dove ci sono OVR, Club, PlayStyles e GG Rating
    corpo = " | ".join(righe[:140])
    return corpo[:2200]

def cerca_carte_nel_db_futgg_per_leak(testo_leak):
    """
    NON USA LE VECCHIE EVO DI FUT.GG!
    Prende i requisiti del leak (es. Max 80 OVR) e interroga direttamente il DATABASE GIOCATORI DI EA FC 27
    su FUT.GG, aprendo le schede singole complete con l'ID carta di quest'anno!
    """
    max_ovr, ruolo = estrai_parametri_da_leak(testo_leak)
    min_ovr = max_ovr - 2

    # Interroga il database giocatori di FUT.GG filtrato matematicamente per l'Overall del leak
    url_db = f"https://www.fut.gg/players/?overall__lte={max_ovr}&overall__gte={min_ovr}"
    raw_db = scarica_jina(url_db)

    # Cattura l'URL completo della carta specifica (incluso /27-xxxxx/ se presente, così legge la versione esatta!)
    matches_p = re.findall(r"(/players/(\d+)-([a-zA-Z0-9-]+)/(?:\d+-\d+/)?)", raw_db)

    giocatori_unici = []
    visti_id = set()
    for full_path, pid, slug_nome in matches_p:
        if pid not in visti_id:
            visti_id.add(pid)
            nome_cognome = slug_nome.replace("-", " ").title()
            link_scheda = f"https://www.fut.gg{full_path}"
            giocatori_unici.append((nome_cognome, link_scheda))

    # Scarica in parallelo le prime 5 schede complete dal database di FUT.GG
    top_5 = giocatori_unici[:5]
    urls_schede = [lk for _, lk in top_5]
    raw_schede = scarica_parallelo(urls_schede)

    schede_testo = []
    links_allegati = []

    for idx, (nome_cognome, link_scheda) in enumerate(top_5):
        raw_s = raw_schede[idx] if idx < len(raw_schede) else ""
        corpo_scheda = pulisci_corpo_scheda_futgg(raw_s, nome_cognome)
        if len(corpo_scheda) > 80:
            schede_testo.append(
                f"=== SCHEDA REALE DB FUT.GG: {nome_cognome} ===\n"
                f"LINK UFFICIALE: {link_scheda}\n"
                f"CONTENUTO INTEGRALE CARTA (OVR, CLUB, PLAYSTYLES, GG RATING):\n{corpo_scheda}"
            )
            links_allegati.append((nome_cognome, link_scheda))

    return "\n\n".join(schede_testo), max_ovr, links_allegati

def analizza_leak_e_schede_con_gemini(prompt_u, max_ovr_f=80):
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY mancante."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")

    sys_l = [
        f"Data: {oggi} (Stagione EA Sports FC 27, PlayStation).",
        "REGOLE FERREE:",
        "1) FOCUS ESCLUSIVO SUI LEAK: Analizza SOLO le nuove Evoluzioni o SBC che emergono dai LEAK (X / Telegram) e NON quelle vecchie già attive su FUT.GG!",
        "2) VIETATO USARE DATABASE VECCHI DELLA TUA MEMORIA: Non usare mai la tua memoria storica per dire l'Overall o il Club di un giocatore! "
        "Leggi l'Overall, il Ruolo, il Club, i PlayStyles e il GG Rating ESCLUSIVAMENTE dal blocco 'CONTENUTO INTEGRALE CARTA' scaricato ora da FUT.GG o verificando con Google Search su site:fut.gg!",
        f"3) RISPETTO DEL LIMITE MAX {max_ovr_f} OVR: Se nelle schede vedi una carta che ha un OVR superiore a {max_ovr_f}, SCARTALA SUBITO e non inserirla nella risposta!",
        "4) STRUTTURA OBBLIGATORIA DELLA RISPOSTA:",
        "📋 DETTAGLI DEL NUOVO LEAK INTERCETTATO:",
        "• Fonte e Data/Ora del Leak: [riporta il post del leaker X/Telegram o il rumor trovato oggi]",
        "• Requisiti previsti dal Leak: [Ruolo, Max OVR, Max PlayStyles, ecc.]",
        "• Boost previsto dal Leak: [Stats e PlayStyles+ aggiunti]",
        "",
        f"🎯 CARTE DEL DATABASE FUT.GG (OVR <= {max_ovr_f}) DA COMPRARE IN ANTICIPO:",
        "Per ogni carta valida scrivi:",
        "• Nome e Cognome Completo | Ruolo | OVR letto dalla scheda FUT.GG | Club letto dalla scheda FUT.GG",
        "• PlayStyles e GG Rating estratti dalla scheda FUT.GG",
        "• Prezzo di acquisto PS pre-hype -> Target di rivendita",
        "• Scheda FUT.GG: [URL completo]",
        "Non usare mai asterischi (*) o cancelletti (#)."
    ]
    full_p = "\n".join(sys_l) + "\n\nDATI LIVE:\n" + prompt_u
    base_u = "https://generativelanguage.googleapis.com/v1beta/models"
    err = "Nessuna risposta"

    for mod in trova_modelli_attivi():
        for t_cfg in [[{"google_search": {}}], []]:
            url = f"{base_u}/{mod}:generateContent?key={GEMINI_API_KEY}"
            body = {
                "contents": [{"parts": [{"text": full_p}]}],
                "generationConfig": {"temperature": 0.0}
            }
            if t_cfg:
                body["tools"] = t_cfg
            try:
                r = requests.post(url, json=body, timeout=28).json()
                if "error" in r:
                    err = r["error"].get("message", "Err")
                    continue
                cands = r.get("candidates", [])
                if not cands:
                    continue
                parts = cands[0].get("content", {}).get("parts", [])
                out = "\n".join([p.get("text", "") for p in parts if "text" in p]).strip()
                if out:
                    modello_scoperto = mod
                    out = out.replace("**", "").replace("*", "•").replace("#", "")
                    out = out.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    return out
            except Exception as e:
                err = str(e)
    return f"⚠️ Errore IA: {err[:120]}"

def formatta_box_link_schede(links_allegati):
    if not links_allegati:
        return ""
    righe = ["\n📎 <b>SCHEDE UFFICIALI FUT.GG ALLEGATE:</b>"]
    for nome_c, url_s in links_allegati:
        nome_safe = nome_c.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        righe.append(f"• <a href='{url_s}'>Apri Scheda di {nome_safe} su FUT.GG</a>")
    return "\n".join(righe)

def gestisci_comando(testo_msg, chat_id):
    try:
        parti = testo_msg.strip().split()
        if not parti:
            return
        cmd = parti[0].lower().split("@")[0]

        if cmd in ["/start", "/help", "/menu"]:
            utenti_iscritti.add(str(chat_id))
            m_lines = [
                "🎯 <b>BOT SNIPER EA FC 27 (SOLO NUOVI LEAK + DB FUT.GG PURO)</b>",
                f"👥 <i>Utenti collegati H24: {len(utenti_iscritti)}</i>\n",
                "🔥 <b>/leak</b> - Ignora le vecchie Evo già uscite: cerca <b>SOLO i nuovi Leak da X/Telegram</b> e apre il corpo completo delle schede su FUT.GG",
                "🔮 <b>/simula [req leak]</b> - Es: <code>/simula Leak Evo LB RB Max 80 OVR Max 6 PlayStyles</code>",
                "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
            ]
            invia_telegram("\n".join(m_lines), chat_id)

        elif cmd in ["/leak", "/evo"]:
            invia_telegram(
                "🕵️‍♂️ <i>Ricerca ESCLUSIVA nuovi Leak da X/Telegram (ignorando le vecchie Evo già su FUT.GG) + Lettura profonda schede giocatori FC 27...</i>",
                chat_id
            )
            leaks = leggi_leak_esclusivi_da_x_e_tg()
            t_leaks = "\n".join(leaks) if leaks else "Leak Evo LB/RB Max 80 OVR e ultime Evo leakate oggi su X da FutSheriff, Fut_Scoreboard, FutPoliceLeaks."

            schede_db, m_ovr, links_schede = cerca_carte_nel_db_futgg_per_leak(t_leaks)

            p_lines = [
                f"ULTIMI POST LEAK INTERCETTATI DA X E TELEGRAM:\n{t_leaks}\n",
                f"SCHEDE COMPLETE DAL DATABASE GIOCATORI FUT.GG (FILTRO OVR <= {m_ovr}):\n{schede_db[:3600]}\n",
                "COMPITO:",
                "1) Non parlare di Evoluzioni già uscite su FUT.GG (come Touchline Magic o Academy): concentrati SOLO sui NUOVI LEAK intercettati qui sopra (o trovati oggi su X tramite Google Search).",
                f"2) Dalle schede complete FUT.GG qui sopra, estrai l'Overall reale di FC 27, il Club reale, i PlayStyles e il GG Rating delle carte che rispettano il limite Max {m_ovr} OVR (scartando qualsiasi carta con OVR > {m_ovr}!)."
            ]
            analisi = analizza_leak_e_schede_con_gemini("\n".join(p_lines), max_ovr_f=m_ovr)
            box_links = formatta_box_link_schede(links_schede)

            msg = f"🚨 <b>REPORT NUOVI LEAK &amp; SCHEDE DB FUT.GG (MAX {m_ovr} OVR):</b>\n\n"
            if leaks:
                for lk in leaks[:2]:
                    pul = lk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    msg += f"📢 <i>{pul[:220]}</i>\n\n"
            msg += f"{analisi}\n{box_links}"
            invia_telegram(msg, chat_id)

        elif cmd == "/simula":
            if len(parti) < 2:
                invia_telegram(
                    "🔮 Scrivi il leak che vuoi simulare! Es:\n"
                    "<code>/simula Leak Evo LB RB Max 80 OVR Max 6 PlayStyles Boost +4 DEF</code>",
                    chat_id
                )
                return
            q_in = " ".join(parti[1:])
            invia_telegram("🔮 <i>Estrazione schede complete dal database FUT.GG per i requisiti del leak...</i>", chat_id)
            schede_db, m_ovr, links_schede = cerca_carte_nel_db_futgg_per_leak(q_in)
            p_sim = (
                f"NUOVO LEAK FORNITO DALL'UTENTE:\n'{q_in}'\n\n"
                f"SCHEDE COMPLETE ESTRATTE DAL DB FUT.GG (FILTRO OVR <= {m_ovr}):\n{schede_db[:3500]}\n\n"
                f"Riporta i dettagli del leak e analizza solo i giocatori delle schede qui sopra che hanno OVR <= {m_ovr}, leggendo OVR, Club, PlayStyles e GG Rating dal testo della scheda!"
            )
            risp = analizza_leak_e_schede_con_gemini(p_sim, max_ovr_f=m_ovr)
            box_links = formatta_box_link_schede(links_schede)
            invia_telegram(f"🎯 <b>SIMULAZIONE NUOVO LEAK (MAX {m_ovr} OVR):</b>\n\n{risp}\n{box_links}", chat_id)

        elif cmd == "/tassa":
            if len(parti) < 2:
                invia_telegram("Usa: <code>/tassa 50000</code>", chat_id)
                return
            buy = int(parti[1].replace(".", "").replace("k", "000"))
            par = int(buy / (1 - EA_TAX)) + 100
            sell = int(parti[2].replace(".", "").replace("k", "000")) if len(parti) >= 3 else int(buy * 1.12)
            net = (sell - int(sell * EA_TAX)) - buy
            qta = max(1, int(250000 // buy))
            invia_telegram(
                f"🧮 <b>TASSA EA (5%)</b>\n🛒 Buy: {buy:,} | ⚖️ Par: {par:,}\n"
                f"🎯 Sell: {sell:,} | ✅ Netto: {net:+,} (Su 250k: {net*qta:+,})",
                chat_id
            )

        elif cmd == "/chiedi":
            if len(parti) < 2:
                invia_telegram("Es: <code>/chiedi leak evo max 80 lb rb</code>", chat_id)
                return
            dom = " ".join(parti[1:])
            invia_telegram("🧠 <i>Ricerca leak e schede DB FUT.GG...</i>", chat_id)
            schede_db, m_ovr, links_schede = cerca_carte_nel_db_futgg_per_leak(dom)
            risp = analizza_leak_e_schede_con_gemini(f"Domanda: {dom}\n\n{schede_db[:3000]}", max_ovr_f=m_ovr)
            box_links = formatta_box_link_schede(links_schede)
            invia_telegram(f"🤖 <b>RISPOSTA DB FUT.GG:</b>\n\n{risp}\n{box_links}", chat_id)

    except Exception as e:
        invia_telegram(f"⚠️ Errore esecuzione comando: {e}", chat_id)

def ascolta_comandi():
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
                    if cid:
                        utenti_iscritti.add(str(cid))
                    if txt.startswith("/") and cid:
                        threading.Thread(target=gestisci_comando, args=(txt, cid), daemon=True).start()
        except Exception:
            time.sleep(3)

def scansiona_h24():
    global messaggi_gia_visti
    for lk in leggi_leak_esclusivi_da_x_e_tg():
        id_lk = hash(lk[:90])
        if id_lk not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_lk)
            if len(messaggi_gia_visti) > 3:
                schede_db, m_ovr, links_schede = cerca_carte_nel_db_futgg_per_leak(lk)
                p_h24 = f"NUOVO LEAK APPENA USCITO:\n{lk}\n\nSCHEDE DB FUT.GG (OVR <= {m_ovr}):\n{schede_db[:3000]}"
                analisi = analizza_leak_e_schede_con_gemini(p_h24, max_ovr_f=m_ovr)
                box_links = formatta_box_link_schede(links_schede)
                pul = lk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(f"🚨 <b>NUOVO LEAK INTERCETTATO!</b>\n📢 <i>{pul}</i>\n\n{analisi}\n{box_links}")

def motore_h24():
    invia_telegram(
        "🔥 <b>BOT AGGIORNATO: ESCLUSE LE VECCHIE EVO DI FUT.GG + LETTURA CORPO CENTRALE SCHEDE!</b>\n\n"
        "• Il bot <b>non legge più le Evoluzioni già uscite</b> su FUT.GG (come Touchline Magic), ma punta <b>solo ai nuovi Leak</b>.\n"
        "• Risolto il problema del menu di FUT.GG che nascondeva Overall, Club e PlayStyles reali della carta!"
    )
    scansiona_h24()
    ult_ora = ""
    while True:
        try:
            scansiona_h24()
            ora_s = datetime.now(timezone(timedelta(hours=2))).strftime("%H:%M")
            if ora_s != ult_ora and ora_s == "18:55":
                invia_telegram("⏰ <b>18:55 - CONTENUTI EA TRA 5 MINUTI!</b>")
                ult_ora = ora_s
            time.sleep(90)
        except Exception:
            time.sleep(60)

@app.route("/")
def home():
    return "FC 27 Exclusive Leak & Deep Card Body Scraper OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
