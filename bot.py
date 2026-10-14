import os
import re
import time
import threading
import requests
import cloudscraper
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

CANALI_TG = [
    "Fut_Scoreboard",
    "futpoliceleaks",
    "fifatradingromania"
]

PROFILI_X = [
    "https://x.com/Fut_Scoreboard",
    "https://x.com/FutPoliceLeaks",
    "https://x.com/KillerFutTrade",
    "https://x.com/FutSheriff"
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
    "rate limit"
]

TRIGGERS = [
    "evo", "evolution", "max ", "max 8", "max 7", "req", "boost",
    "playstyle", "ps+", "pace", "overall", "rating", "sbc", "potm", "leaked",
    "lb", "rb", "cb", "cdm", "cm", "cam", "lw", "rw", "st", "fullback"
]

messaggi_gia_visti = set()
ultimo_update_id = 0
modello_scoperto = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache"
}

scraper = cloudscraper.create_scraper()

def invia_telegram(testo, chat_id=None):
    """Invia il messaggio su Telegram. Se l'HTML contiene caratteri che danno errore, lo rimanda subito come testo puro!"""
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
            # Salvagente: se Telegram rifiuta l'HTML (codice != 200), rimanda senza parse_mode!
            if r.status_code != 200:
                testo_puro = re.sub(r"<[^>]+>", "", testo)[:4000]
                payload_fallback = {
                    "chat_id": target,
                    "text": testo_puro,
                    "disable_web_page_preview": True
                }
                requests.post(url, json=payload_fallback, timeout=10)
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
    """Timeout ridotto a 8 secondi per non bloccare mai il comando /leak."""
    try:
        h = dict(HEADERS)
        resp = requests.get(f"https://r.jina.ai/{target_url}", headers=h, timeout=8)
        if resp.status_code == 200 and len(resp.text) > 120:
            return resp.text
    except Exception:
        pass
    return ""

def scarica_parallelo(lista_urls):
    """Scarica più pagine contemporaneamente in parallelo (5 volte più veloce!)."""
    if not lista_urls:
        return []
    with ThreadPoolExecutor(max_workers=5) as ex:
        return list(ex.map(scarica_jina, lista_urls))

def pulisci_testo_futgg(raw_text):
    if not raw_text:
        return []
    buone = []
    for r in raw_text.split("\n"):
        r_no_img = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r" \1 ", r)
        r_clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", r_no_img).strip()
        rl = r_clean.lower()

        if len(r_clean) < 2:
            continue
        if r_clean.startswith("http") or r_clean.startswith("Title:") or r_clean.startswith("URL Source:"):
            continue
        if any(b in rl for b in SPAM_WORDS):
            continue
        buone.append(r_clean)
    return buone

def leggi_leak_live():
    """Scarica in parallelo i canali Telegram e X in meno di 4 secondi."""
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_str = datetime.now(tz_it).strftime("%d/%m %H:%M")

    urls_tg = [f"https://t.me/s/{c}" for c in CANALI_TG]
    urls_x = PROFILI_X[:2]
    tutti_urls = urls_tg + urls_x
    risultati_raw = scarica_parallelo(tutti_urls)

    for idx, raw in enumerate(risultati_raw):
        if not raw:
            continue
        righe = pulisci_testo_futgg(raw)
        if idx < len(CANALI_TG):
            nome_fonte = f"@{CANALI_TG[idx]} TG"
        else:
            nome_fonte = f"@{urls_x[idx - len(CANALI_TG)].split('/')[-1]} X"

        for post in righe[-5:]:
            if len(post) > 25 and any(k in post.lower() for k in TRIGGERS):
                raccolta.append(f"[{ora_str} | {nome_fonte}]: {post[:300]}")

    return raccolta[:8]

def estrai_parametri_da_testo(testo):
    t_low = testo.lower()
    max_ovr = None
    patterns = [
        r"overall\s*max\s*(\d{2})",
        r"max\s*(?:ovr|overall|rating)?\s*[:=]?\s*(\d{2})",
        r"(\d{2})\s*max\s*(?:ovr|overall)"
    ]
    for pat in patterns:
        m = re.search(pat, t_low)
        if m:
            val = int(m.group(1))
            if 65 <= val <= 92:
                max_ovr = val
                break
    return max_ovr

def estrai_evo_e_schede_coerenti(testo_leak_o_cmd=""):
    blocchi = []
    max_ovr_input = estrai_parametri_da_testo(testo_leak_o_cmd)

    # 1. Legge la lista delle Evoluzioni su FUT.GG
    raw_evos = scarica_jina("https://www.fut.gg/evolutions/")
    links_evo = re.findall(r"(/evolutions/\d+-([a-zA-Z0-9-]+)/)", raw_evos)

    evo_scelta_url = ""
    evo_scelta_nome = ""
    for full_p, slug_e in links_evo:
        if "academy" not in slug_e.lower() and "cosmetic" not in slug_e.lower():
            evo_scelta_url = f"https://www.fut.gg{full_p}"
            evo_scelta_nome = slug_e.replace("-", " ").title()
            break

    if not evo_scelta_url and links_evo:
        evo_scelta_url = f"https://www.fut.gg{links_evo[0][0]}"
        evo_scelta_nome = links_evo[0][1].replace("-", " ").title()

    raw_pe = ""
    testo_evo_dettaglio = ""
    if evo_scelta_url:
        raw_pe = scarica_jina(evo_scelta_url)
        righe_pe = pulisci_testo_futgg(raw_pe)
        testo_evo_dettaglio = "\n".join(righe_pe[:65])
        blocchi.append(
            f"=== EVOLUZIONE DI RIFERIMENTO SU FUT.GG: {evo_scelta_nome} ===\n"
            f"Link Evo: {evo_scelta_url}\n"
            f"Dettagli Requisiti e Boost:\n{testo_evo_dettaglio[:1500]}"
        )

    ovr_evo = estrai_parametri_da_testo(testo_evo_dettaglio)
    max_ovr_finale = max_ovr_input or ovr_evo or 80

    # 2. Cerca i giocatori compatibili
    min_o = max_ovr_finale - 2
    u_db = f"https://www.fut.gg/players/?overall__lte={max_ovr_finale}&overall__gte={min_o}"
    raw_db = scarica_jina(u_db)

    sorgente_urls = raw_pe + "\n" + raw_db
    matches_p = re.findall(r"(/players/(\d+)-([a-zA-Z0-9-]+)/(?:27-\d+/)?)", sorgente_urls)

    giocatori_unici = []
    visti_id = set()
    for full_path, pid, slug_nome in matches_p:
        if pid not in visti_id:
            visti_id.add(pid)
            nome_cognome = slug_nome.replace("-", " ").title()
            link_scheda = f"https://www.fut.gg{full_path}"
            giocatori_unici.append((nome_cognome, link_scheda))

    # 3. Scarica le schede dei primi 4 giocatori IN PARALLELO (impiega solo 3 secondi!)
    top_giocatori = giocatori_unici[:4]
    urls_schede = [lk for _, lk in top_giocatori]
    raw_schede_list = scarica_parallelo(urls_schede)

    schede_complete = []
    links_allegati = []

    for idx, (nome_cognome, link_scheda) in enumerate(top_giocatori):
        raw_scheda = raw_schede_list[idx] if idx < len(raw_schede_list) else ""
        righe_s = pulisci_testo_futgg(raw_scheda)
        if righe_s:
            testo_scheda = " | ".join(righe_s[:100])
            schede_complete.append(
                f"--- GIOCATORE: {nome_cognome} ---\n"
                f"URL SCHEDA FUT.GG: {link_scheda}\n"
                f"DATI SCHEDA: {testo_scheda[:900]}"
            )
            links_allegati.append((nome_cognome, link_scheda))

    if schede_complete:
        blocchi.append(
            f"=== SCHEDE SINGOLE GIOCATORI (FILTRO OVR <= {max_ovr_finale}) ===\n"
            + "\n\n".join(schede_complete)
        )

    return "\n\n".join(blocchi), max_ovr_finale, links_allegati

def analizza_con_schede_complete(prompt_u, max_ovr_f=80):
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY mancante."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")

    sys_l = [
        f"Data: {oggi} (EA Sports FC 27, PS).",
        "REGOLE TASSATIVE:",
        "1) COERENZA TOTALE: Non confondere mai due Evoluzioni diverse! Usa i requisiti del leak o dell'Evo indicata qui sotto.",
        "2) NOME E COGNOME COMPLETO + LINK SCHEDA: Scrivi sempre Nome e Cognome completo e il link della scheda FUT.GG di ogni giocatore.",
        "3) Leggi OVR, Ruolo, Club, PlayStyles e GG Rating dai blocchi 'DATI SCHEDA' e dalla ricerca su site:fut.gg senza inventare dati.",
        "4) STRUTTURA OBBLIGATORIA DELLA RISPOSTA:",
        "📋 DETTAGLI DEL LEAK / EVO DI RIFERIMENTO:",
        "• Nome e Fonte: ...",
        "• Requisiti Esatti: ...",
        "• Boost Applicato: ...",
        "",
        "🎯 CARTE IDENTIFICATE CON SCHEDA FUT.GG:",
        "• Nome e Cognome Completo | Ruolo | OVR | Club",
        "• GG Rating e PlayStyles",
        "• Prezzo acquisto PS (700-1.300 cr per gli Oro <=82) -> Target rivendita (3.500-8.500 cr)",
        "• Scheda FUT.GG: [URL completo]",
        "Non usare mai asterischi (*) o cancelletti (#)."
    ]
    full_p = "\n".join(sys_l) + "\n\nDATI ESTRATTI:\n" + prompt_u
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
                r = requests.post(url, json=body, timeout=25).json()
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
                "⚡ <b>BOT SNIPER EA FC 27 (MODALITÀ TURBO PARALLELA)</b>",
                f"👥 <i>Utenti collegati H24: {len(utenti_iscritti)}</i>\n",
                "🔥 <b>/leak</b> - Analizza l'ultimo leak/Evo + allega le schede FUT.GG in 6 secondi",
                "🔮 <b>/simula [req]</b> - Es: <code>/simula Evo LB RB Max 80 OVR Max 6 PlayStyles</code>",
                "🧬 <b>/evo</b> - Analizza l'ultima Evoluzione di mercato su FUT.GG",
                "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
            ]
            invia_telegram("\n".join(m_lines), chat_id)

        elif cmd in ["/leak", "/evo"]:
            invia_telegram(
                "⚡ <i>Download parallelo Leak + Schede Giocatori da FUT.GG in corso (6-8 secondi)...</i>",
                chat_id
            )
            leaks = leggi_leak_live()
            t_leaks = "\n".join(leaks)
            dati_completi, m_ovr, links_schede = estrai_evo_e_schede_coerenti(t_leaks)

            b_lk = t_leaks if leaks else "Usa l'Evoluzione scambiabile di FUT.GG estratta qui sotto."

            p_lines = [
                f"LEAK RECENTI:\n{b_lk}\n",
                f"EVOLUZIONE E SCHEDE GIOCATORI ESTRATTE DA FUT.GG (OVR <= {m_ovr}):\n{dati_completi[:3400]}\n",
                "Riporta i dettagli dell'Evoluzione/Leak e analizza i giocatori estratti indicando SEMPRE Nome e Cognome completo, Club, OVR, PlayStyles, GG Rating e URL della scheda FUT.GG!"
            ]
            analisi = analizza_con_schede_complete("\n".join(p_lines), max_ovr_f=m_ovr)
            box_links = formatta_box_link_schede(links_schede)

            msg = f"🚨 <b>REPORT VERIFICATO CON SCHEDE FUT.GG (MAX {m_ovr} OVR):</b>\n\n{analisi}\n{box_links}"
            invia_telegram(msg, chat_id)

        elif cmd == "/simula":
            if len(parti) < 2:
                invia_telegram(
                    "🔮 Scrivi i requisiti! Es:\n"
                    "<code>/simula Evo LB RB Max 80 OVR Max 6 PlayStyles Boost +4 DEF</code>",
                    chat_id
                )
                return
            q_in = " ".join(parti[1:])
            invia_telegram("🔮 <i>Download parallelo schede FUT.GG corrispondenti ai requisiti...</i>", chat_id)
            dati_completi, m_ovr, links_schede = estrai_evo_e_schede_coerenti(q_in)
            p_sim = (
                f"LEAK FORNITO DALL'UTENTE:\n'{q_in}'\n\n"
                f"SCHEDE GIOCATORI ESTRATTE DA FUT.GG (OVR <= {m_ovr}):\n{dati_completi[:3200]}\n\n"
                "Riporta i dettagli del leak fornito dall'utente e analizza i giocatori estratti con Nome e Cognome completo, Club, OVR, PlayStyles e link scheda!"
            )
            risp = analizza_con_schede_complete(p_sim, max_ovr_f=m_ovr)
            box_links = formatta_box_link_schede(links_schede)
            invia_telegram(f"🎯 <b>SIMULAZIONE LEAK (MAX {m_ovr} OVR):</b>\n\n{risp}\n{box_links}", chat_id)

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
                invia_telegram("Es: <code>/chiedi terzini max 80 FC 27?</code>", chat_id)
                return
            dom = " ".join(parti[1:])
            invia_telegram("🧠 <i>Lettura rapida FUT.GG...</i>", chat_id)
            dati_completi, m_ovr, links_schede = estrai_evo_e_schede_coerenti(dom)
            risp = analizza_con_schede_complete(f"Domanda: {dom}\n\n{dati_completi[:2800]}", max_ovr_f=m_ovr)
            box_links = formatta_box_link_schede(links_schede)
            invia_telegram(f"🤖 <b>RISPOSTA FUT.GG:</b>\n\n{risp}\n{box_links}", chat_id)

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
    for lk in leggi_leak_live():
        id_lk = hash(lk[:90])
        if id_lk not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_lk)
            if len(messaggi_gia_visti) > 4:
                dati_completi, m_ovr, links_schede = estrai_evo_e_schede_coerenti(lk)
                p_h24 = f"NUOVO LEAK:\n{lk}\n\nSCHEDE FUT.GG:\n{dati_completi[:2800]}"
                analisi = analizza_con_schede_complete(p_h24, max_ovr_f=m_ovr)
                box_links = formatta_box_link_schede(links_schede)
                pul = lk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(f"🚨 <b>NUOVO LEAK RILEVATO!</b>\n📢 <i>{pul}</i>\n\n{analisi}\n{box_links}")

def motore_h24():
    invia_telegram(
        "⚡ <b>BOT RIATTIVATO: MODALITÀ TURBO PARALLELA + SALVAGENTE INVIO MESSAGGI!</b>\n"
        "• Risolto il blocco per timeout e per caratteri HTML speciali su <b>/leak</b>.\n"
        "• Scaricamento schede FUT.GG in parallelo (risposta in 6-8 secondi).\n\n"
        "Scrivi subito <b>/leak</b> per provarlo!"
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
    return "FC 27 Turbo Parallel Bot OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
