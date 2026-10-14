import os
import re
import time
import threading
import requests
import cloudscraper
from urllib.parse import quote
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

CANALI_TG_LEAK = [
    "Fut_Scoreboard",
    "futpoliceleaks",
    "fifatradingromania",
    "futtrading"
]

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
    "privacy policy"
]

TRIGGERS_LEAK = [
    "evo", "evolution", "max ", "max 8", "max 7", "req", "boost",
    "playstyle", "ps+", "pace", "overall", "rating", "sbc", "potm",
    "leaked", "upcoming", "official stats", "lb", "rb", "cb", "cdm",
    "cm", "cam", "lw", "rw", "st", "fullback"
]

# Mappa dei codici posizione interni usati da FUT.GG nei filtri URL
MAPPA_POSIZIONI_FUTGG = {
    "gk": "1",
    "rb": "2",
    "cb": "3",
    "lb": "4",
    "cdm": "5",
    "rm": "6",
    "cm": "7",
    "lm": "8",
    "cam": "9",
    "rw": "10",
    "lw": "11",
    "st": "12"
}

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
        h["X-No-Cache"] = "true"
        resp = requests.get(f"https://r.jina.ai/{target_url}", headers=h, timeout=10)
        if resp.status_code == 200 and len(resp.text) > 120:
            return resp.text
    except Exception:
        pass
    return ""

def scarica_parallelo(lista_urls):
    if not lista_urls:
        return []
    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(scarica_jina, lista_urls))

def leggi_telegram_html_diretto(canale):
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
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_str = datetime.now(tz_it).strftime("%d/%m %H:%M")

    with ThreadPoolExecutor(max_workers=4) as ex:
        risultati_tg = list(ex.map(leggi_telegram_html_diretto, CANALI_TG_LEAK))
    for lista_c in risultati_tg:
        raccolta.extend(lista_c[-3:])

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
    """Estrae Max OVR e la lista dei Ruoli (es. ['lb', 'rb']) dal testo del leak."""
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

    ruoli_trovati = []
    if "fullback" in t_low or "terzin" in t_low:
        ruoli_trovati = ["lb", "rb"]
    else:
        for r_code in ["lb", "rb", "cb", "cdm", "cm", "cam", "lw", "rw", "rm", "lm", "st"]:
            if re.search(rf"\b{r_code}\b", t_low):
                ruoli_trovati.append(r_code)

    return max_ovr, ruoli_trovati

def pulisci_scheda_singola_futgg(raw_text):
    """
    Estrae TUTTI i dati della carta dalla pagina singola di FUT.GG:
    - Converte le immagini ![Testo](url) in [Testo] (così legge Club, Nazione, PlayStyles e Ruoli!)
    - Taglia solo le prime 25 righe di menu, conservando per intero Overall, Ruolo, Prezzo, PlayStyles e GG Rating!
    """
    if not raw_text:
        return ""

    testo = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r" [\1] ", raw_text)
    testo = re.sub(r"\[([^\]]+)\]\([^)]+\)", r" \1 ", testo)

    righe_utili = []
    for r in testo.split("\n"):
        rc = " ".join(r.split()).strip()
        if not rc:
            continue
        rl = rc.lower()
        if rc.startswith("http") or rc.startswith("URL Source:"):
            continue
        if any(sp in rl for sp in SPAM_WORDS):
            continue
        righe_utili.append(rc)

    # Salta solo le prime 18 righe di barra di navigazione superiore e prende tutto il blocco centrale della carta
    corpo = " | ".join(righe_utili[18:160]) if len(righe_utili) > 20 else " | ".join(righe_utili)
    return corpo[:2600]

def cerca_carte_con_id_completo_futgg(testo_leak):
    """
    RISOLVE IL BUG DI OPENDA/STOICA E DELLE SCHEDE VUOTE:
    1) Costruisce gli URL del database di FUT.GG filtrati sia per Overall (overall__lte) sia per RUOLO (positions=2,4 per RB/LB!).
    2) Scarta i primi 5 link del widget laterale 'Trending Players' (Openda, Stoica, Ludmila) che non c'entrano col filtro!
    3) Cattura SOLO gli URL COMPLETI con l'ID carta (/players/123-nome/27-45678/) che contengono Overall, PlayStyles e GG Rating!
    """
    max_ovr, ruoli = estrai_parametri_da_leak(testo_leak)
    min_ovr = max_ovr - 2

    urls_ricerca_db = []
    if ruoli:
        codici_pos = [MAPPA_POSIZIONI_FUTGG[r] for r in ruoli if r in MAPPA_POSIZIONI_FUTGG]
        if codici_pos:
            pos_str = ",".join(codici_pos)
            urls_ricerca_db.append(
                f"https://www.fut.gg/players/?overall__lte={max_ovr}&overall__gte={min_ovr}&positions={pos_str}"
            )
        for r in ruoli[:2]:
            urls_ricerca_db.append(f"https://www.fut.gg/tactics/most-used-players/{r}/")

    urls_ricerca_db.append(f"https://www.fut.gg/players/?overall__lte={max_ovr}&overall__gte={min_ovr}")

    raws_db = scarica_parallelo(urls_ricerca_db[:3])
    testo_db_unito = "\n".join([r for r in raws_db if r])

    # REGEX CHIAVE: esige OBBLIGATORIAMENTE il suffisso /\d+-\d+/ (es. /27-50585395/)!
    # In questo modo ignora gli URL corti vuoti del widget laterale Trending (come /players/231747-lois-openda/)
    # e prende SOLO le vere carte della griglia risultati di FUT.GG!
    matches_completi = re.findall(r"(/players/(\d+)-([a-zA-Z0-9-]+)/(\d+-\d+)/)", testo_db_unito)

    giocatori_unici = []
    visti_id = set()

    for full_path, pid, slug_nome, card_id in matches_completi:
        if pid not in visti_id:
            visti_id.add(pid)
            nome_cognome = slug_nome.replace("-", " ").title()
            link_scheda = f"https://www.fut.gg{full_path}"
            giocatori_unici.append((nome_cognome, link_scheda))

    # Fallback: se per caso FUT.GG mostra link senza card_id, salta i primi 5 (che sono il box Trending laterale!)
    if not giocatori_unici:
        matches_base = re.findall(r"(/players/(\d+)-([a-zA-Z0-9-]+)/)", testo_db_unito)
        for full_path, pid, slug_nome in matches_base[5:]:
            if pid not in visti_id:
                visti_id.add(pid)
                nome_cognome = slug_nome.replace("-", " ").title()
                link_scheda = f"https://www.fut.gg{full_path}"
                giocatori_unici.append((nome_cognome, link_scheda))

    # Scarica in parallelo le prime 6 schede complete dal database di FUT.GG
    top_6 = giocatori_unici[:6]
    urls_schede = [lk for _, lk in top_6]
    raw_schede = scarica_parallelo(urls_schede)

    schede_testo = []
    links_allegati = []

    for idx, (nome_cognome, link_scheda) in enumerate(top_6):
        raw_s = raw_schede[idx] if idx < len(raw_schede) else ""
        corpo_scheda = pulisci_scheda_singola_futgg(raw_s)
        if len(corpo_scheda) > 60:
            schede_testo.append(
                f"=== SCHEDA CARTA VERIFICATA FUT.GG: {nome_cognome} ===\n"
                f"URL CARTA: {link_scheda}\n"
                f"TESTO ESTRATTO DALLA PAGINA CARTA:\n{corpo_scheda}"
            )
            links_allegati.append((nome_cognome, link_scheda))

    return "\n\n".join(schede_testo), max_ovr, ruoli, links_allegati

def analizza_leak_e_schede_con_gemini(prompt_u, max_ovr_f=80, ruoli_f=None):
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY mancante."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    str_ruoli = ", ".join([r.upper() for r in ruoli_f]) if ruoli_f else "Tutti i ruoli compatibili"

    sys_l = [
        f"Data: {oggi} (Stagione EA Sports FC 27, PlayStation).",
        "SEI COLLEGATO ALLE SCHEDE COMPLETE DELLE CARTE DI FUT.GG (/players/.../27-.../).",
        "REGOLE DI ESTRAZIONE E ANALISI:",
        f"1) FILTRO RUOLO E OVR: Il leak richiede Ruolo [{str_ruoli}] e Overall Massimo [{max_ovr_f}].",
        "2) LEGGI I DATI DAL 'TESTO ESTRATTO DALLA PAGINA CARTA' E CON GOOGLE SEARCH SU SITE:FUT.GG: "
        "Dentro il testo estratto di ogni carta trovi il titolo della pagina (es. 'Nome Cognome - 80 - ...'), il Club, i PlayStyles (tra parentesi quadre, es. [Rapid], [Jockey], [Anticipate]) e il GG Rating.",
        "3) Se nel testo estratto vedi il Nome, il Ruolo, l'OVR e i PlayStyles, compilali chiaramente per ogni giocatore!",
        "4) STRUTTURA OBBLIGATORIA DELLA RISPOSTA:",
        "📋 DETTAGLI DEL NUOVO LEAK INTERCETTATO:",
        "• Fonte e Data/Ora: ...",
        f"• Requisiti previsti dal Leak: Ruolo {str_ruoli}, Max {max_ovr_f} OVR, limiti PlayStyles...",
        "• Boost previsto dal Leak: ...",
        "",
        f"🎯 CARTE DEL DATABASE FUT.GG ({str_ruoli} - MAX {max_ovr_f} OVR) DA COMPRARE:",
        "Per ciascuna delle carte estratte qui sotto scrivi:",
        "• Nome e Cognome Completo | Ruolo | OVR | Club",
        "• PlayStyles e GG Rating rilevati sulla scheda FUT.GG",
        "• Prezzo di acquisto PS pre-hype (700-1.300 cr per gli Oro <=82) -> Target rivendita nell'hype (3.500-8.500 cr)",
        "• Scheda FUT.GG: [URL completo della carta]",
        "Non usare mai asterischi (*) o cancelletti (#)."
    ]
    full_p = "\n".join(sys_l) + "\n\nDATI SCHEDE CARTE FUT.GG:\n" + prompt_u
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
    righe = ["\n📎 <b>SCHEDE CARTE UFFICIALI FUT.GG ALLEGATE:</b>"]
    for nome_c, url_s in links_allegati:
        nome_safe = nome_c.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        righe.append(f"• <a href='{url_s}'>Apri Carta di {nome_safe} su FUT.GG</a>")
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
                "🎯 <b>BOT SNIPER EA FC 27 (FILTRO RUOLO + ID CARTA COMPLETO FUT.GG)</b>",
                f"👥 <i>Utenti collegati H24: {len(utenti_iscritti)}</i>\n",
                "🔥 <b>/leak</b> - Intercetta l'ultimo leak e cerca su FUT.GG <b>solo le carte del Ruolo e Overall del leak</b> (con ID carta completo!)",
                "🔮 <b>/simula [req leak]</b> - Es: <code>/simula Leak Evo LB RB Max 80 OVR</code>",
                "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
            ]
            invia_telegram("\n".join(m_lines), chat_id)

        elif cmd in ["/leak", "/evo"]:
            invia_telegram(
                "⚡ <i>Ricerca Leak + Estrazione carte con ID Completo e Filtro Ruolo/Overall su FUT.GG...</i>",
                chat_id
            )
            leaks = leggi_leak_esclusivi_da_x_e_tg()
            t_leaks = "\n".join(leaks) if leaks else "Leak Evo LB RB Max 80 OVR (Fullback Evolution su X da FutSheriff / Fut_Scoreboard / FutPoliceLeaks)."

            schede_db, m_ovr, ruoli_lk, links_schede = cerca_carte_con_id_completo_futgg(t_leaks)
            str_r = "/".join([r.upper() for r in ruoli_lk]) if ruoli_lk else "TUTTI"

            p_lines = [
                f"ULTIMI LEAK INTERCETTATI:\n{t_leaks}\n",
                f"SCHEDE CARTE COMPLETE ESTRATTE DA FUT.GG (RUOLO: {str_r} | OVR <= {m_ovr}):\n{schede_db[:3600]}\n",
                "Analizza il leak e compila i dati completi (Nome, Cognome, Ruolo, OVR, Club, PlayStyles, GG Rating, Prezzo e Link) per ciascuna delle carte estratte qui sopra!"
            ]
            analisi = analizza_leak_e_schede_con_gemini("\n".join(p_lines), max_ovr_f=m_ovr, ruoli_f=ruoli_lk)
            box_links = formatta_box_link_schede(links_schede)

            msg = f"🚨 <b>REPORT NUOVI LEAK &amp; CARTE FUT.GG ({str_r} MAX {m_ovr} OVR):</b>\n\n"
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
                    "<code>/simula Leak Evo LB RB Max 80 OVR Max 6 PlayStyles</code>",
                    chat_id
                )
                return
            q_in = " ".join(parti[1:])
            invia_telegram("🔮 <i>Filtro FUT.GG per Ruolo + Overall con apertura ID carta completo...</i>", chat_id)
            schede_db, m_ovr, ruoli_lk, links_schede = cerca_carte_con_id_completo_futgg(q_in)
            str_r = "/".join([r.upper() for r in ruoli_lk]) if ruoli_lk else "TUTTI"
            p_sim = (
                f"NUOVO LEAK FORNITO DALL'UTENTE:\n'{q_in}'\n\n"
                f"SCHEDE CARTE COMPLETE ESTRATTE DA FUT.GG (RUOLO: {str_r} | OVR <= {m_ovr}):\n{schede_db[:3600]}\n\n"
                "Compila il blocco dettagli del leak e tutte le schede delle carte estratte qui sopra!"
            )
            risp = analizza_leak_e_schede_con_gemini(p_sim, max_ovr_f=m_ovr, ruoli_f=ruoli_lk)
            box_links = formatta_box_link_schede(links_schede)
            invia_telegram(f"🎯 <b>SIMULAZIONE LEAK ({str_r} MAX {m_ovr} OVR):</b>\n\n{risp}\n{box_links}", chat_id)

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
            invia_telegram("🧠 <i>Ricerca carte con ID completo su FUT.GG...</i>", chat_id)
            schede_db, m_ovr, ruoli_lk, links_schede = cerca_carte_con_id_completo_futgg(dom)
            risp = analizza_leak_e_schede_con_gemini(f"Domanda: {dom}\n\n{schede_db[:3200]}", max_ovr_f=m_ovr, ruoli_f=ruoli_lk)
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
                schede_db, m_ovr, ruoli_lk, links_schede = cerca_carte_con_id_completo_futgg(lk)
                p_h24 = f"NUOVO LEAK APPENA USCITO:\n{lk}\n\nSCHEDE DB FUT.GG:\n{schede_db[:3200]}"
                analisi = analizza_leak_e_schede_con_gemini(p_h24, max_ovr_f=m_ovr, ruoli_f=ruoli_lk)
                box_links = formatta_box_link_schede(links_schede)
                pul = lk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(f"🚨 <b>NUOVO LEAK INTERCETTATO!</b>\n📢 <i>{pul}</i>\n\n{analisi}\n{box_links}")

def motore_h24():
    invia_telegram(
        "🎯 <b>BOT AGGIORNATO: RISOLTO IL BUG DEL BOX LATERALE TRENDING (OPENDA/STOICA) + ID CARTA COMPLETO!</b>\n\n"
        "• Ora lo scraper ignora il box laterale di FUT.GG e punta <b>solo agli URL completi della carta (<code>/players/.../27-.../</code>)</b> filtrati anche per <b>Ruolo (es. LB/RB)</b>!\n"
        "• Prova subito <b>/leak</b> o <b>/simula Leak Evo LB RB Max 80 OVR</b>!"
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
    return "FC 27 Full Card-ID & Position Filter Scraper OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
