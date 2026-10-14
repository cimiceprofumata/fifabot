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
    "sign up",
    "cookie",
    "privacy policy"
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

def pulisci_testo_futgg(raw_text):
    """
    NON CANCELLA più le righe corte (dove ci sono OVR, Ruolo, Club e PlayStyles)
    e trasforma le icone ![Nome Club/PlayStyle](url) in testo leggibile!
    """
    buone = []
    for r in raw_text.split("\n"):
        # Estrae il testo alternativo dalle immagini Markdown: ![Chelsea](...) -> Chelsea
        r_no_img = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r" \1 ", r)
        # Rimuove i link Markdown lasciando solo il testo: [Testo](url) -> Testo
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
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    ora_str = datetime.now(tz_it).strftime("%d/%m %H:%M")

    for can in CANALI_TG:
        raw_tg = scarica_jina(f"https://t.me/s/{can}")
        righe = pulisci_testo_futgg(raw_tg)
        for post in righe[-6:]:
            if len(post) > 25 and any(k in post.lower() for k in TRIGGERS):
                raccolta.append(f"[{ora_str} | @{can} TG]: {post[:320]}")

    for u in PROFILI_X[:4]:
        handle = u.split("/")[-1]
        righe_x = pulisci_testo_futgg(scarica_jina(u))
        for linea in righe_x[-8:]:
            if len(linea) > 30 and any(k in linea.lower() for k in TRIGGERS):
                raccolta.append(f"[{ora_str} | @{handle} X]: {linea[:320]}")

    return raccolta[:10]

def estrai_parametri_da_testo(testo):
    """Estrae dinamicamente sia il Max OVR sia l'eventuale Ruolo dal testo del leak o dell'Evo."""
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

    ruolo_trovato = None
    for r_code in ["lb", "rb", "cb", "cdm", "cm", "cam", "lw", "rw", "st"]:
        if re.search(rf"\b{r_code}\b", t_low):
            ruolo_trovato = r_code
            break

    return max_ovr, ruolo_trovato

def estrai_evo_e_schede_coerenti(testo_leak_o_cmd=""):
    """
    1) Seleziona un'Evoluzione SCAMBIABILE (scarta Future Stars Academy che usa token non comprabili!).
    2) Legge il Max OVR direttamente da quell'Evoluzione (o dal leak) così NON mescola mai Evo 82 con filtri 80!
    3) Estrae Nome + Cognome completo dall'URL, apre la scheda completa (fino a 120 righe) e salva il LINK DIRETTO!
    """
    blocchi = []
    max_ovr_input, ruolo_input = estrai_parametri_da_testo(testo_leak_o_cmd)

    # 1. Legge la lista delle Evoluzioni su FUT.GG
    raw_evos = scarica_jina("https://www.fut.gg/evolutions/")
    links_evo = re.findall(r"(/evolutions/\d+-([a-zA-Z0-9-]+)/)", raw_evos)

    evo_scelta_url = ""
    evo_scelta_nome = ""
    for full_p, slug_e in links_evo:
        # Scarta le Evo "academy" o "obj" che richiedono carte obiettivo non scambiabili sul mercato!
        if "academy" not in slug_e.lower() and "cosmetic" not in slug_e.lower():
            evo_scelta_url = f"https://www.fut.gg{full_p}"
            evo_scelta_nome = slug_e.replace("-", " ").title()
            break

    if not evo_scelta_url and links_evo:
        evo_scelta_url = f"https://www.fut.gg{links_evo[0][0]}"
        evo_scelta_nome = links_evo[0][1].replace("-", " ").title()

    testo_evo_dettaglio = ""
    if evo_scelta_url:
        raw_pe = scarica_jina(evo_scelta_url)
        righe_pe = pulisci_testo_futgg(raw_pe)
        testo_evo_dettaglio = "\n".join(righe_pe[:70])
        blocchi.append(
            f"=== EVOLUZIONE DI RIFERIMENTO SU FUT.GG: {evo_scelta_nome} ===\n"
            f"Link Evo: {evo_scelta_url}\n"
            f"Dettagli Requisiti e Boost letti dalla pagina:\n{testo_evo_dettaglio[:1600]}"
        )

    # 2. Determina il Max OVR coerente (prima dall'input utente/leak, altrimenti dal testo dell'Evo scelta!)
    ovr_evo, ruolo_evo = estrai_parametri_da_testo(testo_evo_dettaglio)
    max_ovr_finale = max_ovr_input or ovr_evo or 82

    # 3. Prende i giocatori compatibili direttamente dalla pagina dell'Evo scelta E dal database FUT.GG con quello stesso Max OVR!
    min_o = max_ovr_finale - 2
    u_db = f"https://www.fut.gg/players/?overall__lte={max_ovr_finale}&overall__gte={min_o}"
    raw_db = scarica_jina(u_db)

    sorgente_urls = (raw_pe if evo_scelta_url else "") + "\n" + raw_db
    matches_p = re.findall(r"(/players/(\d+)-([a-zA-Z0-9-]+)/(?:27-\d+/)?)", sorgente_urls)

    giocatori_unici = []
    visti_id = set()
    for full_path, pid, slug_nome in matches_p:
        if pid not in visti_id:
            visti_id.add(pid)
            nome_cognome = slug_nome.replace("-", " ").title()
            link_scheda = f"https://www.fut.gg{full_path}"
            giocatori_unici.append((nome_cognome, link_scheda))

    # 4. Apre le schede singole dei primi 5 giocatori leggendo fino a 110 righe (inclusi Club, OVR, GG Rating e PlayStyles!)
    schede_complete = []
    links_allegati = []

    for nome_cognome, link_scheda in giocatori_unici[:5]:
        raw_scheda = scarica_jina(link_scheda)
        righe_s = pulisci_testo_futgg(raw_scheda)
        if righe_s:
            testo_scheda = " | ".join(righe_s[:110])
            schede_complete.append(
                f"--- GIOCATORE: {nome_cognome} ---\n"
                f"URL SCHEDA FUT.GG: {link_scheda}\n"
                f"DATI ESTRATTI DALLA SCHEDA: {testo_scheda[:950]}"
            )
            links_allegati.append((nome_cognome, link_scheda))

    if schede_complete:
        blocchi.append(
            f"=== SCHEDE SINGOLE GIOCATORI ESTRATTE DA FUT.GG (FILTRO OVR <= {max_ovr_finale}) ===\n"
            + "\n\n".join(schede_complete)
        )

    return "\n\n".join(blocchi), max_ovr_finale, links_allegati

def analizza_con_schede_complete(prompt_u, max_ovr_f=82):
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY mancante."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")

    sys_l = [
        f"Data: {oggi} (EA Sports FC 27, PS).",
        "REGOLE TASSATIVE PER L'ANALISI:",
        "1) COERENZA TOTALE: Analizza l'Evoluzione o il Leak indicato nei dati qui sotto senza MAI confondere due Evoluzioni diverse!",
        "2) NOME E COGNOME COMPLETO + LINK SCHEDA: Per ogni giocatore scrivi SEMPRE il Nome e Cognome completo (es. 'Kenneth Taylor', mai solo 'Taylor') "
        "e incolla subito sotto l'URL esatto della sua scheda FUT.GG fornito nei dati!",
        "3) ESTRAZIONE COMPLETA DAI DATI DELLA SCHEDA: Nei dati di ogni scheda ora trovi scritti l'OVR, il Ruolo (es. CM, LB, RB), il Club, la Nazionalità, "
        "i PlayStyles e il GG Rating. Leggili attentamente dal blocco 'DATI ESTRATTI DALLA SCHEDA' senza inventare nulla.",
        "4) STRUTTURA OBBLIGATORIA DELLA RISPOSTA:",
        "📋 DETTAGLI DEL LEAK / EVO DI RIFERIMENTO:",
        "• Nome e Fonte: ...",
        "• Requisiti Esatti: ...",
        "• Boost Applicato: ...",
        "",
        "🎯 CARTE IDENTIFICATE CON SCHEDA FUT.GG:",
        "(Per ciascuno dei giocatori estratti scrivi:)",
        "• Nome e Cognome Completo | Ruolo | OVR | Club",
        "• GG Rating e PlayStyles rilevati nella scheda",
        "• Prezzo consigliato di acquisto e target di rivendita su PS",
        "• Scheda FUT.GG: [incolla qui l'URL completo https://www.fut.gg/players/...]",
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

def formatta_box_link_schede(links_allegati):
    """Aggiunge sempre in fondo al messaggio i link diretti cliccabili a tutte le schede FUT.GG dei giocatori!"""
    if not links_allegati:
        return ""
    righe = ["\n📎 <b>SCHEDE UFFICIALI FUT.GG ALLEGATE:</b>"]
    for nome_c, url_s in links_allegati:
        righe.append(f"• <a href='{url_s}'>Apri Scheda di {nome_c} su FUT.GG</a>")
    return "\n".join(righe)

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    if not parti:
        return
    cmd = parti[0].lower().split("@")[0]

    if cmd in ["/start", "/help", "/menu"]:
        utenti_iscritti.add(str(chat_id))
        m_lines = [
            "🎯 <b>BOT SNIPER EA FC 27 (SCHEDE COMPLETE + LINK FUT.GG ALLEGATI)</b>",
            f"👥 <i>Utenti collegati H24: {len(utenti_iscritti)}</i>\n",
            "🔥 <b>/leak</b> - Analizza l'ultimo leak/Evo scambiabile + allega le schede FUT.GG di ogni giocatore",
            "🔮 <b>/simula [req]</b> - Es: <code>/simula Evo LB RB Max 80 OVR Max 6 PlayStyles</code>",
            "🧬 <b>/evo</b> - Analizza l'ultima Evoluzione di mercato su FUT.GG",
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        ]
        invia_telegram("\n".join(m_lines), chat_id)

    elif cmd in ["/leak", "/evo"]:
        invia_telegram(
            "🕵️‍♂️ <i>Estrazione Leak/Evo scambiabile + Lettura integrale schede giocatori (Nome, Cognome, Club, PlayStyles e Link FUT.GG)...</i>",
            chat_id
        )
        leaks = leggi_leak_live()
        t_leaks = "\n".join(leaks)
        dati_completi, m_ovr, links_schede = estrai_evo_e_schede_coerenti(t_leaks)

        b_lk = t_leaks if leaks else "Usa l'Evoluzione scambiabile di FUT.GG estratta qui sotto."

        p_lines = [
            f"LEAK RECENTI:\n{b_lk}\n",
            f"EVOLUZIONE E SCHEDE GIOCATORI ESTRATTE DA FUT.GG (OVR <= {m_ovr}):\n{dati_completi[:3500]}\n",
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
        invia_telegram("🔮 <i>Apertura schede FUT.GG corrispondenti ai requisiti del leak...</i>", chat_id)
        dati_completi, m_ovr, links_schede = estrai_evo_e_schede_coerenti(q_in)
        p_sim = (
            f"LEAK FORNITO DALL'UTENTE:\n'{q_in}'\n\n"
            f"SCHEDE GIOCATORI ESTRATTE DA FUT.GG (OVR <= {m_ovr}):\n{dati_completi[:3400]}\n\n"
            "Riporta i dettagli del leak fornito dall'utente e analizza i giocatori estratti con Nome e Cognome completo, Club, OVR, PlayStyles e link scheda!"
        )
        risp = analizza_con_schede_complete(p_sim, max_ovr_f=m_ovr)
        box_links = formatta_box_link_schede(links_schede)
        invia_telegram(f"🎯 <b>SIMULAZIONE LEAK (MAX {m_ovr} OVR):</b>\n\n{risp}\n{box_links}", chat_id)

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
        invia_telegram("🧠 <i>Lettura schede FUT.GG...</i>", chat_id)
        dati_completi, m_ovr, links_schede = estrai_evo_e_schede_coerenti(dom)
        risp = analizza_con_schede_complete(f"Domanda: {dom}\n\n{dati_completi[:3000]}", max_ovr_f=m_ovr)
        box_links = formatta_box_link_schede(links_schede)
        invia_telegram(f"🤖 <b>RISPOSTA FUT.GG:</b>\n\n{risp}\n{box_links}", chat_id)

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
                p_h24 = f"NUOVO LEAK:\n{lk}\n\nSCHEDE FUT.GG:\n{dati_completi[:3000]}"
                analisi = analizza_con_schede_complete(p_h24, max_ovr_f=m_ovr)
                box_links = formatta_box_link_schede(links_schede)
                pul = lk.replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(f"🚨 <b>NUOVO LEAK RILEVATO!</b>\n📢 <i>{pul}</i>\n\n{analisi}\n{box_links}")

def motore_h24():
    invia_telegram(
        "✅ <b>BOT AGGIORNATO: LETTURA INTEGRALE SCHEDE FUT.GG + LINK ALLEGATI!</b>\n"
        "• Rimosso il filtro che tagliava i nomi dei Club e dei PlayStyles.\n"
        "• Escluse le Evo 'Academy' non scambiabili.\n"
        "• Nome + Cognome completo e <b>Link diretto alla scheda FUT.GG</b> allegato per ogni giocatore!"
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
    return "FC 27 Complete Player Cards & Links Bot OK!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
