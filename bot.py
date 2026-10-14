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

utenti_iscritti = set()
if TELEGRAM_CHAT_ID:
    for cid in TELEGRAM_CHAT_ID.split(","):
        if cid.strip():
            utenti_iscritti.add(cid.strip())

CANALI_TG = [
    "Fut_Scoreboard",
    "futpoliceleaks",
    "fifatradingromania",
    "futtrading"
]

PROFILI_X = [
    "https://x.com/Fut_Scoreboard",
    "https://x.com/FutPoliceLeaks",
    "https://x.com/KillerFutTrade",
    "https://x.com/FutSheriff",
    "https://x.com/AsyFutTrader",
    "https://x.com/DonkTrading"
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
    "embed"
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
        r = requests.get(f"{base}?key={GEMINI_API_KEY}", timeout=10).json()
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
        resp = requests.get(f"https://r.jina.ai/{target_url}", headers=h, timeout=18)
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text
    except Exception:
        pass
    return ""

def pulisci_righe(raw_text, min_len=20):
    buone = []
    for r in raw_text.split("\n"):
        rc = r.strip()
        rl = rc.lower()
        if len(rc) < min_len:
            continue
        if rc.startswith("![") or rc.startswith("http"):
            continue
        if rc.startswith("Title:") or rc.startswith("URL Source:"):
            continue
        if any(b in rl for b in SPAM_WORDS):
            continue
        buone.append(rc)
    return buone

def leggi_leak_live():
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_str = datetime.now(tz_it).strftime("%d/%m %H:%M")

    for u in PROFILI_X[:4]:
        handle = u.split("/")[-1]
        righe = pulisci_righe(scarica_jina(u), 35)
        for linea in righe:
            ll = linea.lower()
            if any(k in ll for k in TRIGGERS):
                if "log in" not in ll and "sign up" not in ll:
                    raccolta.append(f"[{ora_str} @{handle}]: {linea[:280]}")

    for can in CANALI_TG:
        righe = pulisci_righe(scarica_jina(f"https://t.me/s/{can}"), 30)
        ultime = righe[-3:]
        for post in ultime:
            if any(k in post.lower() for k in TRIGGERS):
                raccolta.append(f"[{ora_str} @{can}]: {post[:280]}")

    return raccolta[:10]

def estrai_max_ovr(testo):
    m = re.search(r"max\s*(?:ovr|overall|rating)?\s*(\d{2})", testo.lower())
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d{2})\s*max", testo.lower())
    if m2:
        return int(m2.group(1))
    return 80

def scarica_futgg(max_ovr=80):
    blocchi = []
    min_o = max_ovr - 3
    u_db = f"https://www.fut.gg/players/?overall__lte={max_ovr}&overall__gte={min_o}"
    r_db = pulisci_righe(scarica_jina(u_db), 12)
    if r_db:
        blocchi.append("=== DB FUT.GG ===\n" + "\n".join(r_db[:50]))

    r_best = pulisci_righe(scarica_jina("https://www.fut.gg/evolutions/best/"), 15)
    if r_best:
        blocchi.append("=== BEST EVO ===\n" + "\n".join(r_best[:35]))

    r_evos = pulisci_righe(scarica_jina("https://www.fut.gg/evolutions/"), 15)
    if r_evos:
        blocchi.append("=== EVOS ===\n" + "\n".join(r_evos[:30]))

    return "\n\n".join(blocchi)

def filtra_errori_ia(testo_ia, max_ovr_lim=None):
    paragrafi = testo_ia.split("\n\n")
    validi = []

    for p in paragrafi:
        pl = p.lower()
        if "ruolo: gk" in pl or "nota di sicurezza" in pl:
            continue

        if max_ovr_lim:
            ovrs = re.findall(r"(?:ovr|overall)[^0-9]{0,25}(\d{2})", pl)
            ovrs += re.findall(r"\b(\d{2})\s*ovr\b", pl)
            sfora = False
            for val in ovrs:
                num = int(val)
                if num > max_ovr_lim and "post" not in pl and "dopo" not in pl:
                    sfora = True
            if sfora:
                continue

        spec_w = ["totw", "inform", "promo", "special", "hero", "icon", "rush"]
        if not any(s in pl for s in spec_w):
            if re.search(r"\b([1-9]\d|[1-9]\d{2})\.000\b", p):
                nuove = []
                for r in p.split("\n"):
                    rl = r.lower()
                    if "prezzo" in rl or "target" in rl or "acquisto" in rl:
                        nuove.append(
                            "• Prezzo PS (Oro <=82): Compra 750-1.300 cr | "
                            "Target Hype: 3.800-8.500 cr (Max Range 10k)"
                        )
                    else:
                        nuove.append(r)
                p = "\n".join(nuove)

        validi.append(p)

    return "\n\n".join(validi)

def analizza_futgg(prompt_u, max_ovr_f=None):
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY mancante."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    lim_s = str(max_ovr_f) if max_ovr_f else "80"

    sys_l = [
        f"Data: {oggi} (EA Sports FC 27, PS).",
        "REGOLE INDEROGABILI:",
        f"1) MAX {lim_s} OVR: Vietato citare carte con OVR > {lim_s}!",
        "2) Nessun portiere (GK).",
        "3) Verifica su site:fut.gg Club 2026/27, GG Rating e Max PlayStyles.",
        "4) Le carte Oro <=82 costano 700-1.400 cr (Max Price Range EA: 10.000 cr).",
        "5) Per ogni carta (separa ogni giocatore con riga vuota):",
        "• Nome Cognome | Ruolo | OVR in FC 27 | Club in FC 27",
        "• GG Rating FUT.GG + Numero e lista PlayStyles",
        "• Prezzo Acquisto PS -> Target Rivendita.",
        "Niente asterischi (*) o cancelletti (#)."
    ]
    full_p = "\n".join(sys_l) + "\n\nDATI:\n" + prompt_u
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
                r = requests.post(url, json=body, timeout=35).json()
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
                    out = out.replace("<", "&lt;").replace(">", "&gt;")
                    return filtra_errori_ia(out, max_ovr_lim=max_ovr_f)
            except Exception as e:
                err = str(e)
    return f"⚠️ Errore IA: {err[:120]}"

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    if not parti:
        return
    cmd = parti[0].lower().split("@")[0]

    if cmd in ["/start", "/help", "/menu"]:
        utenti_iscritti.add(str(chat_id))
        m_lines = [
            "🎯 <b>BOT SNIPER EA FC 27 (FILTRO OVR & MULTI-UTENTE)</b>",
            f"👥 <i>Utenti collegati H24: {len(utenti_iscritti)}</i>\n",
            "🔥 <b>/leak</b> - Leak X + Carte FUT.GG filtrate per OVR e PlayStyles",
            "🔮 <b>/simula [req]</b> - Es: <code>/simula Evo LB RB Max 80 OVR</code>",
            "🧬 <b>/evo</b> - Migliori Evoluzioni FUT.GG per GG Rating",
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        ]
        invia_telegram("\n".join(m_lines), chat_id)

    elif cmd in ["/leak", "/evo"]:
        invia_telegram("🕵️‍♂️ <i>Scansione Leak + Filtro FUT.GG in corso...</i>", chat_id)
        leaks = leggi_leak_live()
        t_leaks = "\n".join(leaks)
        m_ovr = estrai_max_ovr(t_leaks) if leaks else 80
        d_fut = scarica_futgg(max_ovr=m_ovr)
        b_lk = t_leaks if leaks else "Cerca su X i leak di oggi (Evo LB/RB Max 80)."

        p_lines = [
            f"LEAK:\n{b_lk}\n",
            f"FUT.GG (OVR <= {m_ovr}):\n{d_fut[:2500]}\n",
            f"Elenca 6 carte REALI di FC 27 con OVR <= {m_ovr} (VIETATO OVR > {m_ovr}), ",
            "con Club 2026/27, GG Rating, numero PlayStyles e prezzi PS."
        ]
        analisi = analizza_futgg("\n".join(p_lines), max_ovr_f=m_ovr)

        msg = f"🚨 <b>REPORT FUT.GG (FILTRO OVR &lt;= {m_ovr}):</b>\n\n"
        for lk in leaks[:2]:
            pul = lk.replace("<", "&lt;").replace(">", "&gt;")
            msg += f"📢 <i>{pul[:200]}</i>\n\n"
        msg += f"🎯 <b>CARTE VERIFICATE:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif cmd == "/simula":
        if len(parti) < 2:
            invia_telegram("Usa: <code>/simula Evo LB RB Max 80 OVR</code>", chat_id)
            return
        q_in = " ".join(parti[1:])
        m_ovr = estrai_max_ovr(q_in)
        invia_telegram(f"🔮 <i>Filtro FUT.GG per OVR &lt;= {m_ovr}...</i>", chat_id)
        d_fut = scarica_futgg(max_ovr=m_ovr)
        p_sim = (
            f"Simula leak FC 27: '{q_in}' (MAX OVR <= {m_ovr}).\n"
            f"Dati FUT.GG:\n{d_fut[:2300]}\n"
            f"Trova 6 carte REALI di FC 27 con OVR <= {m_ovr}, ordinate per GG Rating."
        )
        risp = analizza_futgg(p_sim, max_ovr_f=m_ovr)
        invia_telegram(f"🎯 <b>SIMULAZIONE (MAX {m_ovr} OVR):</b>\n\n{risp}", chat_id)

    elif cmd == "/tassa":
        if len(parti) < 2:
            invia_telegram("Usa: <code>/tassa 50000</code>", chat_id)
            return
        try:
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
        except Exception:
            invia_telegram("⚠️ Inserisci solo numeri!", chat_id)

    elif cmd == "/chiedi":
        if len(parti) < 2:
            invia_telegram("Es: <code>/chiedi terzini max 80 FC 27?</code>", chat_id)
            return
        dom = " ".join(parti[1:])
        m_ovr = estrai_max_ovr(dom) if "max" in dom.lower() else None
        invia_telegram("🧠 <i>Verifica FUT.GG...</i>", chat_id)
        d_fut = scarica_futgg(max_ovr=m_ovr or 82)
        risp = analizza_futgg(f"Domanda: {dom}\n{d_fut[:2000]}", max_ovr_f=m_ovr)
        invia_telegram(f"🤖 <b>RISPOSTA FUT.GG:</b>\n\n{risp}", chat_id)

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
                m_ovr = estrai_max_ovr(lk)
                d_fut = scarica_futgg(max_ovr=m_ovr)
                p_h24 = f"NUOVO LEAK: {lk}\nFUT.GG:\n{d_fut[:1800]}\nTrova 6 carte OVR <= {m_ovr}!"
                analisi = analizza_futgg(p_h24, max_ovr_f=m_ovr)
                pul = lk.replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(f"🚨 <b>NUOVO LEAK!</b>\n<i>{pul}</i>\n\n{analisi}")

def motore_h24():
    invia_telegram(
        "✅ <b>BOT ONLINE: FILTRO OVR MATEMATICO + CONDIVISIONE AMICI ATTIVA!</b>\n"
        "Prova subito <b>/leak</b> o <b>/simula Evo LB RB Max 80 OVR</b>!"
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
            time.sleep(60)
        except Exception:
            time.sleep(60)

@app.route("/")
def home():
    return "FC 27 Bot OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
