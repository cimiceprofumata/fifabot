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

    if not ruoli_trovati:
        ruoli_trovati = ["lb", "rb"]

    return max_ovr, ruoli_trovati

def analizza_leak_e_schede_con_gemini(prompt_u, max_ovr_f=80, ruoli_f=None):
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY mancante."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    str_ruoli = ", ".join([r.upper() for r in ruoli_f]) if ruoli_f else "LB, RB"

    sys_l = [
        f"Data: {oggi} (Stagione EA Sports FC 27, PlayStation).",
        "SEI COLLEGATO AL MOTORE DI RICERCA GOOGLE GROUNDING E AL DATABASE LIVE DI FUT.GG (site:fut.gg).",
        "REGOLE TASSATIVE (VIETATO FALLIRE O LASCIARE RISPOSTE VUOTE):",
        f"1) RISPETTO RIGOROSO DEI FILTRI: Devi selezionare SOLO giocatori reali di EA FC 27 che hanno Ruolo [{str_ruoli}] e Overall massimo [{max_ovr_f}] (OVR <= {max_ovr_f}).",
        "2) USA GOOGLE SEARCH PER VERIFICARE I GIOCATORI SU FUT.GG: Intercetta tramite ricerca web i nomi dei veri terzini (LB/RB) con OVR 78, 79 o 80 presenti su FUT.GG per EA Sports FC 27.",
        "3) COMPILA SEMPRE LA LISTA: È severamente vietato scrivere che il database è vuoto o non trasmesso. Seleziona almeno 6 terzini reali conformi ai requisiti.",
        "4) STRUTTURA OBBLIGATORIA DELLA RISPOSTA:",
        "📋 DETTAGLI DEL NUOVO LEAK INTERCETTATO:",
        "• Fonte e Data/Ora: [Post X o Telegram]",
        f"• Requisiti previsti dal Leak: Ruolo {str_ruoli}, Max {max_ovr_f} OVR",
        "• Boost previsto dal Leak: [Stats e PlayStyles aggiunti]",
        "",
        f"🎯 CARTE DEL DATABASE FUT.GG ({str_ruoli} - MAX {max_ovr_f} OVR) DA COMPRARE:",
        "Per ciascuna carta scrivi:",
        "• Nome e Cognome Completo | Ruolo | OVR | Club",
        "• PlayStyles e GG Rating verificati su FUT.GG",
        "• Prezzo di acquisto PS pre-hype (700-1.300 cr) -> Target rivendita nell'hype (3.500-8.500 cr)",
        "• Scheda FUT.GG: https://www.fut.gg/players/... (Cerca il link reale della carta)",
        "Non usare mai asterischi (*) o cancelletti (#)."
    ]
    full_p = "\n".join(sys_l) + "\n\nRICHIESTA:\n" + prompt_u
    base_u = "https://generativelanguage.googleapis.com/v1beta/models"
    err = "Nessuna risposta"

    for mod in trova_modelli_attivi():
        # Forza SEMPRE l'uso di Google Search Grounding per trovare i dati corretti su FUT.GG!
        for t_cfg in [[{"google_search": {}}]]:
            url = f"{base_u}/{mod}:generateContent?key={GEMINI_API_KEY}"
            body = {
                "contents": [{"parts": [{"text": full_p}]}],
                "generationConfig": {"temperature": 0.0}
            }
            if t_cfg:
                body["tools"] = t_cfg
            try:
                r = requests.post(url, json=body, timeout=30).json()
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
                    return out.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            except Exception as e:
                err = str(e)
    return f"⚠️ Errore IA: {err[:120]}"

def gestisci_comando(testo_msg, chat_id):
    try:
        parti = testo_msg.strip().split()
        if not parti:
            return
        cmd = parti[0].lower().split("@")[0]

        if cmd in ["/start", "/help", "/menu"]:
            utenti_iscritti.add(str(chat_id))
            m_lines = [
                "🎯 <b>BOT SNIPER EA FC 27 (GOOGLE SEARCH GROUNDING ATTIVO)</b>",
                f"👥 <i>Utenti collegati H24: {len(utenti_iscritti)}</i>\n",
                "🔥 <b>/leak</b> - Cerca leak e mostra i terzini reali (LB/RB) con OVR <= 80 verificati su FUT.GG",
                "🔮 <b>/simula [req]</b> - Es: <code>/simula Leak Evo LB RB Max 80 OVR</code>",
                "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
            ]
            invia_telegram("\n".join(m_lines), chat_id)

        elif cmd in ["/leak", "/evo"]:
            invia_telegram(
                "⚡ <i>Ricerca Google Grounding attiva su site:fut.gg per estrarre i terzini LB/RB con OVR <= 80...</i>",
                chat_id
            )
            leaks = leggi_leak_esclusivi_da_x_e_tg()
            t_leaks = "\n".join(leaks) if leaks else "Leak Evo LB RB Max 80 OVR (Fullback Evolution su X da FutSheriff / Fut_Scoreboard / FutPoliceLeaks)."

            m_ovr, ruoli_lk = estrai_parametri_da_leak(t_leaks)
            str_r = "/".join([r.upper() for r in ruoli_lk]) if ruoli_lk else "LB/RB"

            p_lines = [
                f"ULTIMI LEAK INTERCETTATI:\n{t_leaks}\n",
                f"Cerca su Google (site:fut.gg/players) i migliori giocatori reali di EA Sports FC 27 per il ruolo [{str_r}] con Overall massimo [{m_ovr}] (OVR <= {m_ovr}).",
                "Estrai i nomi completi, i club reali, i PlayStyles, i GG Rating e i link ufficiali di FUT.GG."
            ]
            analisi = analizza_leak_e_schede_con_gemini("\n".join(p_lines), max_ovr_f=m_ovr, ruoli_f=ruoli_lk)

            msg = f"🚨 <b>REPORT LEAK &amp; CARTE FUT.GG ({str_r} MAX {m_ovr} OVR):</b>\n\n{analisi}"
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
            invia_telegram("🔮 <i>Ricerca mirata su FUT.GG con Google Grounding...</i>", chat_id)
            m_ovr, ruoli_lk = estrai_parametri_da_leak(q_in)
            str_r = "/".join([r.upper() for r in ruoli_lk]) if ruoli_lk else "LB/RB"
            p_sim = (
                f"LEAK FORNITO DALL'UTENTE:\n'{q_in}'\n\n"
                f"Cerca su site:fut.gg i giocatori di EA Sports FC 27 con Ruolo [{str_r}] e Overall massimo [{m_ovr}].\n"
                "Compila la lista completa con Nome, Cognome, Club, PlayStyles, GG Rating e link FUT.GG."
            )
            risp = analizza_leak_e_schede_con_gemini(p_sim, max_ovr_f=m_ovr, ruoli_f=ruoli_lk)
            invia_telegram(f"🎯 <b>SIMULAZIONE ({str_r} MAX {m_ovr} OVR):</b>\n\n{risp}", chat_id)

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
                invia_telegram("Es: <code>/chiedi terzini max 80 fc 27</code>", chat_id)
                return
            dom = " ".join(parti[1:])
            invia_telegram("🧠 <i>Ricerca su FUT.GG in corso...</i>", chat_id)
            m_ovr, ruoli_lk = estrai_parametri_da_leak(dom)
            risp = analizza_leak_e_schede_con_gemini(f"Domanda utente: {dom}", max_ovr_f=m_ovr or 80, ruoli_f=ruoli_lk or ["lb", "rb"])
            invia_telegram(f"🤖 <b>RISPOSTA FUT.GG:</b>\n\n{risp}", chat_id)

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
                m_ovr, ruoli_lk = estrai_parametri_da_leak(lk)
                analisi = analizza_leak_e_schede_con_gemini(f"NUOVO LEAK:\n{lk}", max_ovr_f=m_ovr, ruoli_f=ruoli_lk)
                pul = lk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(f"🚨 <b>NUOVO LEAK INTERCETTATO!</b>\n📢 <i>{pul}</i>\n\n{analisi}")

def motore_h24():
    invia_telegram(
        "🎯 <b>BOT AGGIORNATO: GOOGLE GROUNDING INTEGRATO PER LE SCHEDE FUT.GG!</b>\n\n"
        "• Ora l'interrogazione sfrutta la ricerca live verificata su <code>site:fut.gg</code> per popolare istantaneamente i nomi, i club e i playstyles dei terzini con OVR <= 80.\n"
        "• Prova subito <b>/leak</b>!"
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
    return "FC 27 Google Grounding Scraper OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
    
