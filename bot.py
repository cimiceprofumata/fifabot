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

# Canali con anteprima web pubblica reale (t.me/s/)
CANALI_TELEGRAM_APERTI = [
    "Fut_Scoreboard",
    "fifatradingromania",
    "futpoliceleaks"
]

# Frasi di sistema di Telegram da BLOCCARE SEMPRE (così non legge i banner di iscrizione)
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
    "evo", "evolution", "max ", "req", "boost", "playstyle",
    "pace", "overall", "rating", "sbc", "potm", "leaked", "upcoming"
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

def scarica_testo_jina(target_url):
    """Legge le pagine di FUT.GG e Telegram superando Cloudflare senza cache."""
    try:
        h = dict(HEADERS)
        h["X-No-Cache"] = "true"
        resp = requests.get(f"https://r.jina.ai/{target_url}", headers=h, timeout=18)
        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text
    except Exception:
        pass
    return ""

def leggi_post_reali_telegram():
    """Legge SOLO veri post di testo dai canali Telegram e scarta qualsiasi avviso 'If you have Telegram...'."""
    raccolta = []
    tz_it = timezone(timedelta(hours=2))
    oggi_str = datetime.now(tz_it).strftime("%d/%m/%Y")

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

def estrai_database_reale_fc27_da_futgg():
    """
    Entra direttamente su FUT.GG (Database EA FC 27), legge le ultime Evoluzioni uscite,
    apre le prime 2 Evoluzioni ed estrae i requisiti, i boost e i GIOCATORI REALI di FC 27 compatibili!
    """
    pagina_evo = scarica_testo_jina("https://www.fut.gg/evolutions/")
    pagina_players = scarica_testo_jina("https://www.fut.gg/players/")

    # 1. Trova gli URL e i nomi delle ultime Evoluzioni di FC 27
    evo_trovate = []
    matches_evo = re.findall(r"(/evolutions/(\d+-[a-zA-Z0-9-]+)/)", pagina_evo)
    visti_slug = set()
    for path_completo, slug in matches_evo:
        if slug not in visti_slug:
            visti_slug.add(slug)
            nome_pulito = slug.split("-", 1)[-1].replace("-", " ").title()
            evo_trovate.append((nome_pulito, f"https://www.fut.gg{path_completo}"))

    # 2. Entra nelle prime 2 Evoluzioni su FUT.GG per leggere Requisiti, Boost e i Giocatori di FC 27 che ci entrano
    dettagli_evo_estratti = []
    giocatori_db_fc27 = []

    for nome_evo, url_evo in evo_trovate[:2]:
        testo_evo = scarica_testo_jina(url_evo)
        if not testo_evo:
            continue

        # Estrae i giocatori del database FC 27 elencati dentro quella specifica Evoluzione
        player_matches = re.findall(r"/players/\d+-([a-zA-Z0-9-]+)/", testo_evo)
        nomi_in_questa_evo = []
        for p_slug in player_matches:
            nome_p = p_slug.replace("-", " ").title()
            if len(nome_p) > 3 and nome_p not in nomi_in_questa_evo:
                nomi_in_questa_evo.append(nome_p)
            if nome_p not in giocatori_db_fc27:
                giocatori_db_fc27.append(nome_p)

        # Estrae le righe di testo con i Requisiti e gli Upgrade dell'Evoluzione
        righe_testo = []
        for line in testo_evo.split("\n"):
            lc = line.strip()
            if len(lc) > 12 and not lc.startswith("![") and "http" not in lc:
                righe_testo.append(lc)

        blocco = (
            f"=== EVOLUZIONE FUT.GG: {nome_evo} ({url_evo}) ===\n"
            f"Testo Requisiti/Boost estratto da FUT.GG:\n" + "\n".join(righe_testo[:30]) + "\n"
            f"Giocatori del DB FC 27 compatibili con {nome_evo}: {', '.join(nomi_in_questa_evo[:15])}\n"
        )
        dettagli_evo_estratti.append(blocco)

    # 3. Aggiunge anche gli ultimi giocatori inseriti/aggiornati nel database generale di FC 27
    ultimi_players_db = re.findall(r"/players/\d+-([a-zA-Z0-9-]+)/", pagina_players)
    for p_slug in ultimi_players_db[:15]:
        nome_p = p_slug.replace("-", " ").title()
        if len(nome_p) > 3 and nome_p not in giocatori_db_fc27:
            giocatori_db_fc27.append(nome_p)

    testo_finale_evo = "\n\n".join(dettagli_evo_estratti)
    return evo_trovate[:6], giocatori_db_fc27[:25], testo_finale_evo[:3000]

def analizza_solo_db_fc27(prompt_specifico):
    """Impedisce a Gemini di usare vecchi database (FC 24/25) e lo obbliga a usare SOLO i dati estratti da FUT.GG."""
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    sistema = (
        f"Data e ora: {oggi}. Sei l'analista ufficiale collegato al database live di FUT.GG per EA Sports FC 27 (PlayStation). "
        "REGOLE ASSOLUTE CONTRO I VECCHI DATABASE:\n"
        "1) VIETATO USARE LA TUA MEMORIA INTERNA DI VECCHI FIFA / FC 24 / FC 25! Non inventare mai club vecchi (es. non mettere mai giocatori con trasferimenti di 2 anni fa) "
        "e NON inventare nomi di Evoluzioni che non siano scritte nei dati estratti qui sotto.\n"
        "2) DEVI SELEZIONARE I GIOCATORI ESCLUSIVAMENTE DALLA LISTA 'GIOCATORI DEL DB FC 27 ESTRATTI DA FUT.GG' fornita nel prompt qui sotto "
        "(oppure verificando su fut.gg tramite Google Search il loro club e overall attuale nella stagione 2026/2027 di EA FC 27).\n"
        "3) Se i canali Telegram non hanno restituito nuovi leak testuali nelle ultime ore, NON INVENTARE UN LEAK FINTO: analizza invece le ULTIME EVOLUZIONI REALI "
        "estratte da FUT.GG qui sotto, riportando i loro veri nomi, i requisiti/boost letti dalla pagina e le migliori carte del database FC 27 da comprare.\n"
        "4) Per ogni carta consigliata indica: Nome e Cognome (preso dai dati FUT.GG), perché è meta nell'Evoluzione di FC 27, "
        "prezzo reale di acquisto su PS (700-1.500 cr per carte oro base, 12k-30k per carte speciali) e target di rivendita.\n"
        "Non usare simboli Markdown come asterischi (*) o cancelletti (#). Usa solo elenchi con •."
    )
    testo_completo = f"{sistema}\n\nDATI ESTRATTI IN TEMPO REALE DA FUT.GG (EA FC 27):\n{prompt_specifico}"

    modelli_da_provare = trova_modelli_attivi()
    ultimo_errore = "Nessuna risposta"

    for modello in modelli_da_provare:
        for tool_config in [[{"google_search": {}}], []]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent?key={GEMINI_API_KEY}"
            body = {
                "contents": [{"parts": [{"text": testo_completo}]}],
                "generationConfig": {"temperature": 0.05}
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
            "🎯 <b>BOT EA FC 27 (DATABASE LIVE FUT.GG VERIFICATO)</b>\n"
            "💰 Budget: 800.000 crediti (PlayStation)\n\n"
            "🔥 <b>/leak</b> - Controlla i leak reali e incrocia <b>SOLO le carte del database di EA FC 27</b> estratte live da FUT.GG\n\n"
            "🧬 <b>/evo</b> - Apre le ultime Evoluzioni su FUT.GG ed estrae i giocatori compatibili del DB FC 27\n\n"
            "🔮 <b>/simula [requisiti leak]</b> - Testa un leak sul database FC 27\n\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        )
        invia_telegram(menu, chat_id)

    elif comando in ["/leak", "/evo"]:
        invia_telegram("⚡ <i>Connessione diretta al Database EA FC 27 di FUT.GG + Scansione post reali dei Leaker...</i>", chat_id)
        post_leaker = leggi_post_reali_telegram()
        evo_trovate, giocatori_fc27, dettagli_pagine_evo = estrai_database_reale_fc27_da_futgg()

        if post_leaker:
            testo_leaker = "\n".join([f"- [{p['data_ora']}] {p['canale']}: {p['testo']}" for p in post_leaker[-5:]])
        else:
            testo_leaker = "Nessun nuovo messaggio testuale su Telegram in questo minuto; usa i dati estratti da FUT.GG qui sotto."

        nomi_evo_str = ", ".join([n for n, _ in evo_trovate])
        giocatori_fc27_str = ", ".join(giocatori_fc27)

        prompt = (
            f"POST REALI DEI LEAKER:\n{testo_leaker}\n\n"
            f"EVOLUZIONI ATTIVE NEL DATABASE EA FC 27 DI FUT.GG:\n{nomi_evo_str}\n\n"
            f"DETTAGLI E GIOCATORI COMPATIBILI ESTRATTI DALLE PAGINE EVO DI FUT.GG:\n{dettagli_pagine_evo}\n\n"
            f"LISTA GIOCATORI REALI DEL DATABASE EA FC 27 ESTRATTI ORA DA FUT.GG:\n{giocatori_fc27_str}\n\n"
            "COMPITO:\n"
            "1) Analizza le Evoluzioni e i leak reali presenti qui sopra (NON inventare nomi di Evoluzioni non presenti nella lista!).\n"
            "2) Riporta i requisiti e i boost di Stats/PlayStyles che vedi nel testo estratto da FUT.GG.\n"
            "3) Scegli 6 GIOCATORI ESCLUSIVAMENTE DALLA LISTA 'GIOCATORI REALI DEL DATABASE EA FC 27' qui sopra, verificando il loro vero club nella stagione 2026/27 (EA FC 27) "
            "e spiegando quali comprare adesso a basso prezzo su PlayStation per fare compravendita con queste Evoluzioni."
        )
        analisi = analizza_solo_db_fc27(prompt)

        msg = "🚨 <b>REPORT DATABASE LIVE EA FC 27 (FUT.GG):</b>\n\n"
        if post_leaker:
            for p in post_leaker[-2:]:
                pulito = p["testo"].replace("<", "&lt;").replace(">", "&gt;")
                msg += f"📢 <b>{p['canale']} ({p['data_ora']}):</b>\n<i>{pulito[:200]}</i>\n\n"

        if evo_trovate:
             msg += "🧬 <b>Ultime Evoluzioni FC 27 su FUT.GG:</b>\n"
            for n, link in evo_trovate[:4]:
                msg += f"• <a href='{link}'>{n}</a>\n"
            msg += "\n"

        if giocatori_fc27:
            str_g10 = ", ".join(giocatori_fc27[:10])
            msg += f"⚽ <b>Carte DB FC 27 estratte dalle Evo:</b>\n<code>{str_g10}</code>\n\n"

        msg += f"🎯 <b>ANALISI REQUISITI & CARTE DA COMPRARE (DB FC 27):</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/simula":
        if len(parti) < 2:
            invia_telegram(
                "🔮 <b>SIMULATORE SU DATABASE FC 27</b>\n"
                "Incolla il testo di un leak visto su X:\n"
                "<code>/simula Evo Max 82 OVR Max 86 PAC +6 PAC PlayStyle+ Quick Step</code>",
                chat_id
            )
            return
        leak_input = " ".join(parti[1:])
        invia_telegram("🔮 <i>Incrocio del leak con i giocatori reali del database EA FC 27 di FUT.GG...</i>", chat_id)
        _, giocatori_fc27, dettagli_pagine_evo = estrai_database_reale_fc27_da_futgg()
        str_g = ", ".join(giocatori_fc27)
        prompt = (
            f"Leak inserito dall'utente: '{leak_input}'\n"
            f"Giocatori estratti dal database FC 27 di FUT.GG: {str_g}\n"
            f"Dati Evo FC 27: {dettagli_pagine_evo[:800]}\n"
            "Seleziona 6 carte REALI del database di EA FC 27 (con club e overall aggiornati alla stagione 2026/27 su FUT.GG) "
            "che rientrano in questi requisiti e indica prezzo di acquisto e vendita su PlayStation."
        )
        risp = analizza_solo_db_fc27(prompt)
        invia_telegram(f"🎯 <b>SIMULAZIONE SU DATABASE EA FC 27:</b>\n\n{risp}", chat_id)

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
            invia_telegram("Scrivi una domanda! Es: <code>/chiedi quali sono le migliori carte per l'evoluzione Touchline Magic?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 <i>Verifica sul database EA FC 27 di FUT.GG in corso...</i>", chat_id)
        _, giocatori_fc27, dettagli_pagine_evo = estrai_database_reale_fc27_da_futgg()
        str_g = ", ".join(giocatori_fc27)
        risp = analizza_solo_db_fc27(f"Domanda utente: {domanda}\nDati live FUT.GG FC 27: {dettagli_pagine_evo[:1000]}\nGiocatori DB FC 27: {str_g}")
        invia_telegram(f"🤖 <b>RISPOSTA DATABASE FC 27:</b>\n\n{risp}", chat_id)

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

def scansiona_e_anticipa_h24():
    global messaggi_gia_visti, evo_gia_viste

    # 1. Controlla veri post nuovi sui canali Telegram aperti
    leaks = leggi_post_reali_telegram()
    for item in leaks:
        txt = item["testo"]
        id_msg = hash(txt[:80])
        if id_msg not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_msg)
            if any(k in txt.lower() for k in PAROLE_TRIGGER):
                if len(messaggi_gia_visti) > 4:
                    _, giocatori_fc27, dettagli_evo = estrai_database_reale_fc27_da_futgg()
                    str_g = ", ".join(giocatori_fc27[:15])
                    analisi = analizza_solo_db_fc27(
                        f"NUOVO POST LEAK REALE DA {item['canale']} ({item['data_ora']}):\n'{txt}'\n"
                        f"Giocatori del DB FC 27 su FUT.GG: {str_g}\n"
                        "Analizza questo leak usando SOLO carte reali del database di EA FC 27!"
                    )
                    pulito = txt[:340].replace("<", "&lt;").replace(">", "&gt;")
                    invia_telegram(
                        f"🚨 <b>NUOVO LEAK VERIFICATO ({item['canale']})!</b>\n\n"
                        f"📝 <i>{pulito}</i>\n\n"
                        f"🎯 <b>CARTE DB FC 27 DA COMPRARE:</b>\n{analisi}"
                    )

    # 2. Controlla se esce una nuova Evoluzione su FUT.GG
    evo_trovate, giocatori_fc27, dettagli_pagine_evo = estrai_database_reale_fc27_da_futgg()
    for nome_evo, link_evo in evo_trovate:
        if nome_evo not in evo_gia_viste:
            evo_gia_viste.add(nome_evo)
            if len(evo_gia_viste) > 6:
                str_g = ", ".join(giocatori_fc27[:15])
                analisi_evo = analizza_solo_db_fc27(
                    f"NUOVA EVOLUZIONE APPENA USCITA SU FUT.GG: {nome_evo}\n"
                    f"Dettagli e giocatori compatibili estratti da FUT.GG:\n{dettagli_pagine_evo}\n"
                    f"Lista giocatori DB FC 27: {str_g}\n"
                    "Indica le 6 migliori carte del DB FC 27 da comprare subito per questa Evoluzione!"
                )
                invia_telegram(
                    f"🔥 <b>NUOVA EVOLUZIONE RILEVATA SU FUT.GG: {nome_evo}!</b>\n\n"
                    f"🎯 <b>CARTE DB FC 27 DA COMPRARE ORA:</b>\n{analisi_evo}\n\n"
                    f"🔗 <a href='{link_evo}'>Apri {nome_evo} su FUT.GG</a>"
                )

def motore_h24():
    avvio = (
        "✅ <b>BOT AGGIORNATO: FILTRO ANTI-BANNER TELEGRAM + DATABASE PURO EA FC 27!</b>\n\n"
        "• Rimossi i falsi messaggi <i>'If you have Telegram...'</i>.\n"
        "• Vietato a Gemini l'uso di vecchi database: ora legge <b>direttamente dentro le pagine delle Evoluzioni di FUT.GG</b> i giocatori reali di EA FC 27!\n\n"
        "Scrivi subito <b>/leak</b> o <b>/evo</b> per provarlo!"
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
    return "FC 27 Pure FUT.GG Database Bot Running!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

