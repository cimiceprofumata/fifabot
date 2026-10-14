
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

# Canali Telegram pubblici attivi
CANALI_TELEGRAM_APERTI = [
    "Fut_Scoreboard",
    "futpoliceleaks",
    "fifatradingromania",
    "futtrading"
]

# Profili X (Twitter) scansionati in tempo reale (inclusi FUT Police e Killer FUT Trading)
PROFILI_X_LEAKERS = [
    "https://x.com/Fut_Scoreboard",
    "https://x.com/FutPoliceLeaks",
    "https://x.com/KillerFutTrade",
    "https://x.com/FutSheriff",
    "https://x.com/AsyFutTrader",
    "https://x.com/DonkTrading",
    "https://x.com/Criminal__x"
]

FRASI_SPAZZATURA_TELEGRAM = [
    "if you have telegram",
    "you can contact",
    "right away",
    "view in telegram",
    "download telegram",
    "join channel",
    "subscribers",
    "preview channel"
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

def cerca_leak_su_x_tramite_jina():
    """Interroga direttamente i profili X (inclusi FUT Police e Killer FUT Trading) tramite Jina."""
    raccolta_x = []
    for u in PROFILI_X_LEAKERS:
        handle = u.split("/")[-1]
        raw = scarica_testo_jina(u)
        if not raw:
            continue
        for line in raw.split("\n"):
            lc = line.strip()
            lc_low = lc.lower()
            if len(lc) > 30 and not lc.startswith("![") and "http" not in lc:
                if any(k in lc_low for k in PAROLE_TRIGGER):
                    if not any(bad in lc_low for bad in ["log in", "sign up", "cookies", "terms of service"]):
                        raccolta_x.append(f"[@{handle} su X]: {lc[:350]}")
    return raccolta_x[:10]

def leggi_post_reali_telegram():
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    oggi_str = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")

    for canale in CANALI_TELEGRAM_APERTI:
        raw = scarica_testo_jina(f"https://t.me/s/{canale}")
        if not raw:
            continue

        righe_pulite = []
        for r in raw.split("\n"):
            rc = r.strip()
            rc_low = rc.lower()
            if len(rc) < 25:
                continue
            if rc.startswith("![") or rc.startswith("http") or rc.startswith("Title:") or rc.startswith("URL Source:"):
                continue
            if any(spazzatura in rc_low for spazzatura in FRASI_SPAZZATURA_TELEGRAM):
                continue
            righe_pulite.append(rc)

        for post in righe_pulite[-3:]:
            raccolta.append({
                "canale": f"@{canale}",
                "data_ora": oggi_str,
                "testo": post[:400]
            })

    return raccolta

def cerca_giocatori_futgg_per_requisiti():
    giocatori_estratti = []
    urls_da_leggere = [
        "https://www.fut.gg/players/momentum/",
        "https://www.fut.gg/evolutions/trending/",
        "https://www.fut.gg/players/"
    ]
    for u in urls_da_leggere:
        raw = scarica_testo_jina(u)
        if not raw:
            continue
        matches = re.findall(r"/players/\d+-([a-zA-Z0-9-]+)/", raw)
        for slug in matches:
            nome = slug.replace("-", " ").title()
            if len(nome) > 3 and nome not in giocatori_estratti:
                giocatori_estratti.append(nome)
    return giocatori_estratti[:30]

def interroga_gemini_con_x_search(prompt_utente):
    """
    Usa Google Search Grounding forzato su X (inclusi FUT Police e Killer FUT Trading) e FUT.GG,
    verificando rigorosamente il NUMERO MASSIMO DI PLAYSTYLES consentito dalle Evoluzioni.
    """
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    sistema = (
        f"Data e ora attuale italiana: {oggi} (Ottobre 2026, stagione EA Sports FC 27). "
        "Sei lo scanner predittivo di leak X e FUT.GG per EA Sports FC 27 Ultimate Team (PlayStation, budget 800k).\n"
        "REGOLE FONDAMENTALI DI ANALISI:\n"
        "1) FONTI X PRIORITARIE: Cerca su X (Twitter) i post e i leak di OGGI di: @Fut_Scoreboard, @FutPoliceLeaks (FUT Police), "
        "Killer FUT Trading (@KillerFutTrade), @FutSheriff, @AsyFutTrader, @DonkTrading e @Criminal__x.\n"
        "2) CONTROLLO RIGOROSO DEL LIMITE NUMERO MASSIMO DI PLAYSTYLES (FONDAMENTALE): "
        "Le Evoluzioni di EA FC 27 impongono quasi sempre un limite sul numero massimo di PlayStyles totali (es. Max 6, Max 7 o Max 8 PlayStyles base) "
        "e di PlayStyles+ (es. Max 0 o Max 1 PS+). Quando selezioni i giocatori su FUT.GG:\n"
        "   - SCARTA le carte che hanno troppi PlayStyles base inutili (8+ PlayStyles) che rischierebbero di essere bloccate dal requisito 'Max PlayStyles'!\n"
        "   - PRIVILEGIA le carte che hanno un numero contenuto di PlayStyles (es. da 3 a 6 PlayStyles base totali, e 0 o 1 PS+), ma tutti altamente META "
        "(Quick Step, Rapid, Anticipate, Jockey, Intercept, Finesse Shot, Incisive Pass, Technical, Whipped Pass).\n"
        "3) SCHEDA TECNICA DEL LEAK: Riporta sempre Fonte, Data/Ora, Requisiti (Ruolo, Max OVR, Max Pace, MAX PLAYSTYLES e MAX PLAYSTYLES+) "
        "e quali Stats/PlayStyles+ aggiunge il boost.\n"
        "4) LISTA CARTE EA FC 27 (Stagione 2026/2027 su FUT.GG): Per ogni giocatore consigliato scrivi:\n"
        "   • Nome, Cognome, OVR in FC 27 e Club attuale in FC 27.\n"
        "   • NUMERO ESATTO DI PLAYSTYLES ATTUALI (es. '4 PlayStyles base + 0 PS+: Quick Step, Jockey...') spiegando perché rispetta il limite Max PlayStyles.\n"
        "   • Prezzo reale attuale pre-hype su PlayStation (650-1.200 cr per gli Oro 75-81) e target di rivendita nell'hype (3.500-9.000 cr).\n"
        "Non usare simboli Markdown come asterischi (*) o cancelletti (#). Usa solo elenchi con •."
    )
    testo_completo = f"{sistema}\n\nRICHIESTA OPERATIVA:\n{prompt_utente}"

    modelli_da_provare = trova_modelli_attivi()
    ultimo_errore = "Nessuna risposta"

    for modello in modelli_da_provare:
        for tool_config in [[{"google_search": {}}], []]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent?key={GEMINI_API_KEY}"
            body = {
                "contents": [{"parts": [{"text": testo_completo}]}],
                "generationConfig": {"temperature": 0.1}
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
            "🎯 <b>BOT SNIPER LEAK X & FILTRO MAX PLAYSTYLES (FC 27)</b>\n"
            "💰 Budget: 800.000 crediti (PlayStation)\n"
            "📡 <i>Fonti X attive: FUT Scoreboard, FUT Police, Killer FUT Trading, Sheriff, AsyFut, Donk</i>\n\n"
            "🔥 <b>/leak</b> - Scansiona i leak di oggi e seleziona le carte su FUT.GG verificando <b>Overall, Ruolo e Limite Max PlayStyles</b>\n\n"
            "🔮 <b>/simula [requisiti leak]</b> - Es: <code>/simula Evo LB RB Max 80 OVR Max 7 PlayStyles</code>\n\n"
            "🧬 <b>/evo</b> - Analizza le Evoluzioni su FUT.GG filtrando per conteggio PlayStyles e Meta Rating\n\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram(
            "🕵️‍♂️ <i>Scansione X (FUT Police, Killer FUT Trading, Scoreboard, Sheriff) + Filtro Max PlayStyles su FUT.GG...</i>",
            chat_id
        )
        tweet_x = cerca_leak_su_x_tramite_jina()
        post_tg = leggi_post_reali_telegram()
        giocatori_futgg = cerca_giocatori_futgg_per_requisiti()

        blocco_x = "\n".join(tweet_x) if tweet_x else "Cerca direttamente su X.com i post di oggi."
        blocco_tg = "\n".join([f"- {p['canale']}: {p['testo']}" for p in post_tg[-5:]]) if post_tg else "Nessun post Telegram."
        str_g = ", ".join(giocatori_futgg[:20])

        prompt = (
            f"TWEET INTERCETTATI DA X:\n{blocco_x}\n\n"
            f"POST INTERCETTATI DA TELEGRAM:\n{blocco_tg}\n\n"
            f"GIOCATORI RILEVATI SU FUT.GG (EA FC 27): {str_g}\n\n"
            "COMPITO PRIORITARIO:\n"
            "1) Cerca su X tutti i leak usciti nelle ultime ore su EA Sports FC 27 da FUT Police (@FutPoliceLeaks), Killer FUT Trading (@KillerFutTrade), "
            "@Fut_Scoreboard, @FutSheriff e @AsyFutTrader (inclusa la nuova Evoluzione per LB/RB Max 80 OVR e qualsiasi altra Evo in arrivo).\n"
            "2) Riporta i requisiti completi: Ruolo, Max OVR, Max Pace e soprattutto il LIMITE MASSIMO DI PLAYSTYLES E PLAYSTYLES+.\n"
            "3) Seleziona nel database EA FC 27 di FUT.GG i 7 MIGLIORI GIOCATORI SPECIFICI (Nome, Cognome, OVR in FC 27, Club in FC 27) "
            "che rispettano anche il limite sul numero massimo di PlayStyles (carte con 3-6 PlayStyles base ma tutti Meta, così entrano sicuramente nell'Evo!).\n"
            "4) Indica per ciascuno il numero di PlayStyles attuali, prezzo di acquisto a scarto su PS e target di rivendita."
        )
        analisi = interroga_gemini_con_x_search(prompt)

        msg = "🚨 <b>RADAR LEAK X (FUT POLICE / KILLER FUT / SCOREBOARD) & FILTRO PLAYSTYLES:</b>\n\n"
        if tweet_x:
            for tx in tweet_x[:3]:
                pulito = tx.replace("<", "&lt;").replace(">", "&gt;")
                msg += f"🐦 <i>{pulito[:200]}</i>\n\n"
        elif post_tg:
            for p in post_tg[-2:]:
                pulito = p["testo"].replace("<", "&lt;").replace(">", "&gt;")
                msg += f"📢 <b>{p['canale']} ({p['data_ora']}):</b> <i>{pulito[:200]}</i>\n\n"

        msg += f"🎯 <b>ANALISI LEAK & CARTE CON CONTROLLO MAX PLAYSTYLES:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/simula":
        if len(parti) < 2:
            invia_telegram(
                "🔮 <b>SIMULATORE CON FILTRO MAX PLAYSTYLES</b>\n"
                "Scrivi i requisiti del leak visto su X! Esempio:\n"
                "<code>/simula Evo LB RB Max 80 OVR Max 7 PlayStyles Max 0 PS+</code>",
                chat_id
            )
            return
        leak_input = " ".join(parti[1:])
        invia_telegram(f"🔮 <i>Verifica su FUT.GG delle carte EA FC 27 compatibili (controllo Overall + Max PlayStyles) per: '{leak_input}'...</i>", chat_id)
        prompt = (
            f"Simula questo leak di X per EA FC 27: '{leak_input}'.\n"
            "1) Verifica i limiti di Overall, Statistiche e NUMERO MASSIMO DI PLAYSTYLES / PLAYSTYLES+.\n"
            "2) Trova su FUT.GG (database EA FC 27 stagione 2026/2027) gli 8 MIGLIORI GIOCATORI REALI (Nome, Cognome, OVR in FC 27, Club in FC 27) "
            "che NON superano il numero massimo di PlayStyles consentito e che possiedono i PlayStyles più in meta.\n"
            "3) Specifica per ogni carta quanti PlayStyles ha attualmente, il prezzo di acquisto su PS e il target di rivendita."
        )
        risp = interroga_gemini_con_x_search(prompt)
        invia_telegram(f"🎯 <b>CARTE COMPATIBILI (FILTRO MAX PLAYSTYLES) PER '{leak_input.upper()}':</b>\n\n{risp}", chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 <i>Analisi Evoluzioni FUT.GG con verifica limiti Max PlayStyles...</i>", chat_id)
        giocatori_futgg = cerca_giocatori_futgg_per_requisiti()
        str_g = ", ".join(giocatori_futgg[:20])
        prompt = (
            f"Giocatori in movimento su FUT.GG (EA FC 27): {str_g}.\n"
            "Analizza le ultime Evoluzioni uscite e leakate oggi su EA FC 27 (tenendo conto dei blocchi sul numero massimo di PlayStyles base e PS+). "
            "Elenca 7 carte specifiche del database di EA FC 27 che entrano senza blocchi di PlayStyles e raggiungono il Meta Rating più alto."
        )
        consiglio = interroga_gemini_con_x_search(prompt)
        invia_telegram(f"🔥 <b>REPORT EVOLUZIONI & CONTROLLO PLAYSTYLES (FUT.GG):</b>\n\n{consiglio}", chat_id)

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
            invia_telegram("Scrivi una domanda! Es: <code>/chiedi terzini max 80 con massimo 6 playstyles per la nuova evo?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 <i>Ricerca live su X e FUT.GG in corso...</i>", chat_id)
        risp = interroga_gemini_con_x_search(domanda)
        invia_telegram(f"🤖 <b>ANALISTA FC 27:</b>\n\n{risp}", chat_id)

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
    """Controlla ogni 60 secondi i profili X (inclusi FUT Police e Killer FUT Trading) e i canali Telegram."""
    global messaggi_gia_visti

    # 1. Scansiona i profili X
    tweet_x = cerca_leak_su_x_tramite_jina()
    for tx in tweet_x:
        id_tx = hash(tx[:90])
        if id_tx not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_tx)
            if len(messaggi_gia_visti) > 4:
                analisi = interroga_gemini_con_x_search(
                    f"NUOVO TWEET LEAK INTERCETTATO SU X:\n'{tx}'\n"
                    "Estrai subito i requisiti (ruolo, max overall, limite MAX PLAYSTYLES e boost) e indica i 6 migliori giocatori reali "
                    "del database EA FC 27 su FUT.GG che rispettano il numero massimo di PlayStyles da comprare ADESSO su PS!"
                )
                pulito = tx.replace("<", "&lt;").replace(">", "&gt;")
                invia_telegram(
                    f"🚨 <b>NUOVO LEAK RILEVATO DA X!</b>\n\n"
                    f"🐦 <i>{pulito}</i>\n\n"
                    f"🎯 <b>CARTE COMPATIBILI (VERIFICA MAX PLAYSTYLES):</b>\n{analisi}"
                )

    # 2. Scansiona i canali Telegram
    leaks_tg = leggi_post_reali_telegram()
    for item in leaks_tg:
        txt = item["testo"]
        id_msg = hash(txt[:80])
        if id_msg not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_msg)
            if any(k in txt.lower() for k in PAROLE_TRIGGER):
                if len(messaggi_gia_visti) > 4:
                    analisi = interroga_gemini_con_x_search(
                        f"NUOVO LEAK DA {item['canale']} ({item['data_ora']}):\n'{txt}'\n"
                        "Trova subito nel database EA FC 27 di FUT.GG i 6 giocatori migliori verificando anche il limite massimo di PlayStyles!"
                    )
                    pulito = txt[:340].replace("<", "&lt;").replace(">", "&gt;")
                    invia_telegram(
                        f"🚨 <b>NUOVO LEAK INTERCETTATO ({item['canale']})!</b>\n\n"
                        f"📝 <i>{pulito}</i>\n\n"
                        f"🎯 <b>CARTE COMPATIBILI (VERIFICA MAX PLAYSTYLES):</b>\n{analisi}"
                    )

def motore_h24():
    avvio = (
        "🛡️ <b>BOT AGGIORNATO: AGGIUNTI 'FUT POLICE', 'KILLER FUT TRADING' + FILTRO MAX PLAYSTYLES!</b>\n\n"
        "• Nuove fonti X monitorate H24: <b>@FutPoliceLeaks, @KillerFutTrade, @Fut_Scoreboard, @FutSheriff, @AsyFutTrader, @DonkTrading</b>.\n"
        "• <b>Controllo Max PlayStyles attivo:</b> il bot ora verifica quanti PlayStyles base e PS+ ha ogni carta per scartare quelle che vengono bloccate dai limiti dell'Evo!\n\n"
        "Scrivi <b>/leak</b> o <b>/simula Evo LB RB Max 80 OVR Max 7 PlayStyles</b> per testarlo!"
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
    return "FC 27 X Scanner (FUT Police + Killer FUT + Max PlayStyles Filter) Running!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
