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
    "embed",
    "log in",
    "sign up"
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
        if resp.status_code == 200 and len(resp.text) > 150:
            return resp.text
    except Exception:
        pass
    return ""

def pulisci_righe(raw_text, min_len=15):
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

    # 1. Canali Telegram pubblici (più stabili da leggere)
    for can in CANALI_TG:
        raw_tg = scarica_jina(f"https://t.me/s/{can}")
        righe = pulisci_righe(raw_tg, 25)
        for post in righe[-4:]:
            if any(k in post.lower() for k in TRIGGERS):
                raccolta.append(f"[{ora_str} | @{can} TG]: {post[:320]}")

    # 2. Profili X Leakers
    for u in PROFILI_X[:4]:
        handle = u.split("/")[-1]
        righe_x = pulisci_righe(scarica_jina(u), 30)
        for linea in righe_x[-5:]:
            if any(k in linea.lower() for k in TRIGGERS):
                raccolta.append(f"[{ora_str} | @{handle} X]: {linea[:320]}")

    return raccolta[:10]

def estrai_max_ovr(testo):
    m = re.search(r"max\s*(?:ovr|overall|rating)?\s*(\d{2})", testo.lower())
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d{2})\s*max", testo.lower())
    if m2:
        return int(m2.group(1))
    return 80

def apri_schede_reali_giocatori_futgg(max_ovr=80):
    """
    1) Legge l'ultima Evoluzione reale su FUT.GG con i suoi veri Requisiti e Boost.
    2) Prende i giocatori dal filtro OVR <= max_ovr su FUT.GG e APRE LE SINGOLE PAGINE
       di 6 giocatori per leggere i VERI PlayStyles, il VERO Club FC 27 e il VERO GG Rating!
    """
    blocchi = []

    # A. Legge le Evoluzioni reali attive su FUT.GG e apre la prima per avere i dettagli veri
    raw_evos = scarica_jina("https://www.fut.gg/evolutions/")
    righe_evos = pulisci_righe(raw_evos, 12)
    if righe_evos:
        blocchi.append("=== EVOLUZIONI REALI ATTIVE SU FUT.GG ===\n" + "\n".join(righe_evos[:30]))

    links_evo = re.findall(r"(/evolutions/\d+-[a-zA-Z0-9-]+/)", raw_evos)
    if links_evo:
        prima_evo_url = f"https://www.fut.gg{links_evo[0]}"
        raw_prima_evo = scarica_jina(prima_evo_url)
        righe_pe = pulisci_righe(raw_prima_evo, 10)
        if righe_pe:
            blocchi.append(
                f"=== DETTAGLI REQUISITI E BOOST ULTIMA EVO ({prima_evo_url}) ===\n"
                + "\n".join(righe_pe[:35])
            )

    # B. Cerca i giocatori nel database FUT.GG con OVR tra (max_ovr - 2) e max_ovr
    min_o = max_ovr - 2
    u_db = f"https://www.fut.gg/players/?overall__lte={max_ovr}&overall__gte={min_o}"
    raw_db = scarica_jina(u_db)

    # Estrae i link alle pagine singole dei giocatori (es. /players/12345-nome/27-67890/)
    player_urls = re.findall(r"(/players/\d+-[a-zA-Z0-9-]+(?:/\d+-\d+)?/)", raw_db)
    visti = []
    for pu in player_urls:
        slug_base = "/".join(pu.split("/")[:3])
        if slug_base not in visti:
            visti.append(slug_base)

    # C. Apre le pagine singole dei primi 6 giocatori per leggere PlayStyles e GG Rating reali!
    schede_complete = []
    for pu in visti[:6]:
        full_p_url = f"https://www.fut.gg{pu}"
        raw_scheda = scarica_jina(full_p_url)
        righe_s = pulisci_righe(raw_scheda, 8)
        if righe_s:
            testo_scheda = " | ".join(righe_s[:28])
            schede_complete.append(f"SCHEDA REALE FUT.GG ({full_p_url}):\n{testo_scheda[:600]}")

    if schede_complete:
        blocchi.append(
            f"=== SCHEDE COMPLETE GIOCATORI (OVR <= {max_ovr}) LETTE DA FUT.GG ===\n"
            + "\n\n".join(schede_complete)
        )
    else:
        r_db = pulisci_righe(raw_db, 10)
        blocchi.append("=== ELENCO GIOCATORI FUT.GG ===\n" + "\n".join(r_db[:40]))

    return "\n\n".join(blocchi)

def analizza_senza_inventare(prompt_u, max_ovr_f=80):
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY mancante."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")

    sys_l = [
        f"Data: {oggi} (EA Sports FC 27, PS).",
        "SEI OBBLIGATO A SEGUIRE QUESTE REGOLE CONTRO LE ALLUCINAZIONI:",
        "1) NON INVENTARE MAI NULLA: È SEVERAMENTE VIETATO usare la tua memoria per indovinare Overall, Club, GG Rating o PlayStyles!",
        "2) USA SOLO LE SCHEDE REALI FORNITE SOTTO: Puoi elencare SOLO i giocatori di cui vedi la 'SCHEDA REALE FUT.GG' nei dati qui sotto.",
        "3) SE UN DATO NON C'È SCRITTO NELLA SCHEDA ESTRATTA (es. se nella scheda non vedi scritto il numero del GG Rating o i PlayStyles), "
        "DEVI SCRIVERE 'Dato non visibile nella pagina estratta' — NON INVENTARE MAI NUMERI COME 81.5 O PLAYSTYLES A CASO!",
        "4) NON SOMMARE I PLAYSTYLES DEL LEAK A QUELLI DELLA CARTA SENZA DIRLO: "
        "Scrivi separatamente 'PlayStyles Base attuali sulla carta' e 'Boost aggiunto dall'Evo'.",
        "5) ALL'INIZIO DI OGNI RISPOSTA DEVI SEMPRE INSERIRE QUESTO BLOCCO OBBLIGATORIO:",
        "📋 DETTAGLI DEL LEAK / EVO DI RIFERIMENTO:",
        "• Fonte e Orario: [indica esattamente quale post/leak o quale Evoluzione reale di FUT.GG stai usando]",
        "• Requisiti di Ingresso: [Max OVR, Ruolo, Max PlayStyles base, Max PS+]",
        "• Boost dell'Evo: [Statistiche aggiunte + nuovi PlayStyles/PS+ aggiunti]",
        f"6) Controlla che ogni carta consigliata abbia OVR <= {max_ovr_f}. Non usare asterischi (*) o cancelletti (#)."
    ]
    full_p = "\n".join(sys_l) + "\n\nDATI REALI SCARICATI ORA DA FUT.GG E LEAKER:\n" + prompt_u
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
                    return out.replace("<", "&lt;").replace(">", "&gt;")
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
            "🎯 <b>BOT SNIPER EA FC 27 (SCHEDE SINGOLE FUT.GG & ZERO INVENZIONI)</b>",
            f"👥 <i>Utenti collegati H24: {len(utenti_iscritti)}</i>\n",
            "🔥 <b>/leak</b> - Mostra i dettagli del leak di riferimento + apre le schede singole su FUT.GG",
            "🔮 <b>/simula [req]</b> - Es: <code>/simula Evo LB RB Max 80 OVR Max 6 PlayStyles Boost +4 DEF +PlayStyle+ Intercept</code>",
            "🧬 <b>/evo</b> - Legge l'ultima Evoluzione reale su FUT.GG con Requisiti e Boost",
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        ]
        invia_telegram("\n".join(m_lines), chat_id)

    elif cmd in ["/leak", "/evo"]:
        invia_telegram(
            "🕵️‍♂️ <i>Apertura schede singole giocatori su FUT.GG e lettura dettagli Leak/Evo in corso (richiede circa 15-20 secondi)...</i>",
            chat_id
        )
        leaks = leggi_leak_live()
        t_leaks = "\n".join(leaks)
        m_ovr = estrai_max_ovr(t_leaks) if leaks else 80
        dati_schede = apri_schede_reali_giocatori_futgg(max_ovr=m_ovr)

        b_lk = t_leaks if leaks else "Nessun post testuale nuovo letto da Telegram/X in questo minuto. Usa l'ultima Evoluzione reale estratta da FUT.GG qui sotto."

        p_lines = [
            f"POST LEAK INTERCETTATI:\n{b_lk}\n",
            f"DATI E SCHEDE SINGOLE ESTRATTE DA FUT.GG (OVR <= {m_ovr}):\n{dati_schede[:3200]}\n",
            "ISTRUZIONI:",
            "1) Compila prima il blocco obbligatorio '📋 DETTAGLI DEL LEAK / EVO DI RIFERIMENTO' riportando esattamente la fonte, i requisiti e i boost letti nei dati qui sopra.",
            "2) Elenca SOLO i giocatori presenti nelle 'SCHEDE COMPLETE GIOCATORI LETTE DA FUT.GG' qui sopra.",
            "3) Per ciascuno riporta SOLO i PlayStyles, il Club, l'OVR e il GG Rating scritti testualmente nella sua scheda (senza inventare nessun numero!)."
        ]
        analisi = analizza_senza_inventare("\n".join(p_lines), max_ovr_f=m_ovr)

        msg = f"🚨 <b>REPORT VERIFICATO (CON DETTAGLI LEAK & SCHEDE SINGOLE FUT.GG):</b>\n\n"
        if leaks:
            for lk in leaks[:2]:
                pul = lk.replace("<", "&lt;").replace(">", "&gt;")
                msg += f"📢 <i>{pul[:220]}</i>\n\n"
        msg += f"{analisi}\n\n"
        msg += f"🔗 <a href='https://www.fut.gg/players/?overall__lte={m_ovr}'>Verifica su FUT.GG (OVR &lt;= {m_ovr})</a>"
        invia_telegram(msg, chat_id)

    elif cmd == "/simula":
        if len(parti) < 2:
            invia_telegram(
                "🔮 Incolla i dettagli del leak! Es:\n"
                "<code>/simula Leak FutSheriff Evo LB RB Max 80 OVR Max 6 PlayStyles Boost +4 OVR +PlayStyle+ Intercept</code>",
                chat_id
            )
            return
        q_in = " ".join(parti[1:])
        m_ovr = estrai_max_ovr(q_in)
        invia_telegram(
            f"🔮 <i>Apertura schede giocatori OVR &lt;= {m_ovr} su FUT.GG per simulare il leak...</i>",
            chat_id
        )
        dati_schede = apri_schede_reali_giocatori_futgg(max_ovr=m_ovr)
        p_sim = (
            f"LEAK DI RIFERIMENTO FORNITO DALL'UTENTE:\n'{q_in}'\n\n"
            f"SCHEDE GIOCATORI ESTRATTE DA FUT.GG (OVR <= {m_ovr}):\n{dati_schede[:3000]}\n\n"
            "1) Stampa all'inizio tutti i dettagli del leak di riferimento fornito dall'utente.\n"
            "2) Analizza le carte estratte dalle schede reali di FUT.GG qui sopra senza inventare PlayStyles o GG Rating non presenti nel testo!"
        )
        risp = analizza_senza_inventare(p_sim, max_ovr_f=m_ovr)
        invia_telegram(f"🎯 <b>SIMULAZIONE CON DETTAGLI LEAK (MAX {m_ovr} OVR):</b>\n\n{risp}", chat_id)

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
            invia_telegram("Es: <code>/chiedi dettagli ultima evo su fut.gg</code>", chat_id)
            return
        dom = " ".join(parti[1:])
        m_ovr = estrai_max_ovr(dom) if "max" in dom.lower() else 82
        invia_telegram("🧠 <i>Lettura schede FUT.GG...</i>", chat_id)
        dati_schede = apri_schede_reali_giocatori_futgg(max_ovr=m_ovr)
        risp = analizza_senza_inventare(f"Domanda: {dom}\n\n{dati_schede[:2500]}", max_ovr_f=m_ovr)
        invia_telegram(f"🤖 <b>RISPOSTA VERIFICATA FUT.GG:</b>\n\n{risp}", chat_id)

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
                dati_schede = apri_schede_reali_giocatori_futgg(max_ovr=m_ovr)
                p_h24 = (
                    f"NUOVO LEAK APPENA INTERCETTATO:\n{lk}\n\n"
                    f"SCHEDE FUT.GG (OVR <= {m_ovr}):\n{dati_schede[:2500]}\n\n"
                    "Stampa prima il blocco '📋 DETTAGLI DEL LEAK DI RIFERIMENTO' e poi le carte lette dalle schede FUT.GG!"
                )
                analisi = analizza_senza_inventare(p_h24, max_ovr_f=m_ovr)
                pul = lk.replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(f"🚨 <b>NUOVO LEAK RILEVATO!</b>\n📢 <i>{pul}</i>\n\n{analisi}")

def motore_h24():
    invia_telegram(
        "🛡️ <b>BOT AGGIORNATO: DETTAGLI LEAK SEMPRE VISIBILI + APERTURA SCHEDE SINGOLE FUT.GG!</b>\n"
        "• Ora il bot apre le pagine singole dei giocatori su FUT.GG per leggere i veri PlayStyles e vieta a Gemini di inventare numeri non presenti.\n"
        "• Ogni risposta inizia sempre con la scheda completa del Leak di riferimento usato!"
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
    return "FC 27 Single-Card Verified Scraper Running!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
