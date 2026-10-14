
import os
import re
import time
import threading
import requests
import cloudscraper
from urllib.parse import quote
from bs4 import BeautifulSoup
from flask import Flask
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
EA_TAX = 0.05

CANALI_X_LEAKERS = [
    "Fut_Scoreboard",
    "FutSheriff_Official",
    "AsyFutTrader",
    "DonkTrading",
    "FutPoliceLeaks",
    "fifatradingromania"
]

PAROLE_TRIGGER = [
    "evo", "evolution", "max ", "req", "boost", "playstyle",
    "pace", "overall", "rating", "sbc", "potm", "leaked", "upcoming", "stats"
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

def analizza_senza_allucinazioni(prompt_specifico):
    """Interroga Gemini OBBLIGANDO la verifica dei dati reali e vietando l'invenzione di prezzi o leak."""
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    sistema = (
        f"Data e ora attuale italiana: {oggi}. Sei un analista tecnico di mercato di EA Sports FC Ultimate Team (PlayStation). "
        "REGOLE FERREE ANTI-ALLUCINAZIONE (VIETATO INVENTARE DATI):\n"
        "1) NON INVENTARE MAI leak, prezzi, Meta Rating o PlayStyles. Basati SOLO sui post reali forniti qui sotto e sulla ricerca web live.\n"
        "2) PREZZI REALISTICI DEL MERCATO: Ricorda che le carte Oro Raro 75-82 OVR hanno un Price Range massimo di 10.000 crediti e di base costano "
        "650 - 1.500 crediti (quando vanno in hype per un'Evo salgono a 2.500 - 9.500 crediti o vanno extinct a 10k, MAI a 50k o 150k!). "
        "Solo le carte Promo/TOTW/Icon o Oro 88+ superano i 30k-100k.\n"
        "3) DESCRIZIONE SPECIFICA DI OGNI LEAK: All'inizio della risposta elenca chiaramente QUALE leak o Evoluzione stai analizzando, "
        "indicando: FONTE (@Fut_Scoreboard / @FutSheriff / FUT.GG), DATA e ORARIO di uscita del leak, REQUISITI ESATTI (Max OVR, Max Pace, Ruolo, Max PlayStyles) "
        "e QUALI STATS (+Pace, +Shooting, +Passing...) e QUALI PLAYSTYLES / PLAYSTYLE+ va ad aggiungere.\n"
        "4) Se nei dati ricevuti non c'è scritto il dettaglio di un boost o di un Meta Rating esatto, scrivi onestamente 'Non ancora specificato nel leak' "
        "invece di tirare a indovinare.\n"
        "5) Per ogni carta consigliata scrivi: Nome e Cognome, OVR e versione, perché entra nei requisiti dell'Evo, prezzo reale attuale su PS (es. 700-1.200 cr) e target reale nell'hype (es. 3.500-8.000 cr).\n"
        "Non usare simboli Markdown come asterischi (*) o cancelletti (#). Usa solo elenchi con •."
    )
    testo_completo = f"{sistema}\n\nDATI REALI RACCOLTI ORA:\n{prompt_specifico}"

    modelli_da_provare = trova_modelli_attivi()
    ultimo_errore = "Nessuna risposta"

    for modello in modelli_da_provare:
        # Tenta prima con Google Search Grounding (sia 'google_search' che 'googleSearchRetrieval')
        for tool_config in [[{"google_search": {}}], []]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent?key={GEMINI_API_KEY}"
            body = {
                "contents": [{"parts": [{"text": testo_completo}]}],
                "generationConfig": {"temperature": 0.1} # Temperatura bassissima = zero fantasia, massima precisione!
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

def scarica_html_grezzo(target_url):
    """Scarica l'HTML originale senza cache per estrarre i tag <time> e i messaggi di Telegram."""
    tentativi = [
        target_url,
        f"https://api.allorigins.win/raw?url={quote(target_url, safe='')}",
        f"https://api.codetabs.com/v1/proxy?quest={quote(target_url, safe='')}"
    ]
    for u in tentativi:
        try:
            resp = scraper.get(u, headers=HEADERS, timeout=12)
            if resp.status_code == 200 and len(resp.text) > 500:
                return resp.text
        except Exception:
            continue
    return ""

def scarica_testo_jina(target_url):
    """Usa il reader Jina con X-No-Cache per leggere i contenuti testuali di FUT.GG superando Cloudflare."""
    try:
        h = dict(HEADERS)
        h["X-No-Cache"] = "true"
        resp = requests.get(f"https://r.jina.ai/{target_url}", headers=h, timeout=15)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return ""

def leggi_leak_telegram_con_data_ora():
    """Estrae gli ultimi post reali dei leaker con DATA, ORA ESATTA e TESTO COMPLETO."""
    raccolta = []
    tz_it = timezone(timedelta(hours=2))

    for canale in CANALI_X_LEAKERS:
        html = scarica_html_grezzo(f"https://t.me/s/{canale}")
        if "tgme_widget_message" in html:
            soup = BeautifulSoup(html, "html.parser")
            messaggi = soup.find_all("div", class_="tgme_widget_message")
            for m in messaggi[-4:]:
                box_testo = m.find("div", class_="tgme_widget_message_text")
                if not box_testo:
                    continue
                txt = box_testo.get_text(separator=" ").strip()
                if len(txt) < 15:
                    continue

                # Estrae Data e Ora esatta dal tag <time datetime="..."> di Telegram
                data_ora_str = "Orario N/D"
                tag_time = m.find("time")
                if tag_time and tag_time.get("datetime"):
                    try:
                        dt_utc = datetime.fromisoformat(tag_time["datetime"].replace("Z", "+00:00"))
                        dt_it = dt_utc.astimezone(tz_it)
                        data_ora_str = dt_it.strftime("%d/%m/%Y ore %H:%M")
                    except Exception:
                        data_ora_str = tag_time.get("datetime")[:16]

                raccolta.append({
                    "canale": f"@{canale}",
                    "data_ora": data_ora_str,
                    "testo": txt[:450]
                })
    return raccolta

def leggi_dettagli_evo_e_trending_futgg():
    """Legge da FUT.GG i nomi reali delle Evoluzioni, i loro dettagli e i giocatori in Momentum."""
    testo_evo_page = scarica_testo_jina("https://www.fut.gg/evolutions/")
    testo_momentum = scarica_testo_jina("https://www.fut.gg/players/momentum/")
    testo_best_evo = scarica_testo_jina("https://www.fut.gg/evolutions/trending/")

    # Estrae i nomi dei calciatori più caldi
    giocatori = []
    for sorgente in [testo_best_evo, testo_momentum]:
        matches = re.findall(r"/players/\d+-([a-zA-Z0-9-]+)/", sorgente)
        for slug in matches:
            nome = slug.replace("-", " ").title()
            if len(nome) > 3 and nome not in giocatori:
                giocatori.append(nome)

    # Estrae i link e nomi delle Evoluzioni attive su FUT.GG
    evoluzioni = []
    links_evo = re.findall(r"/evolutions/\d+-([a-zA-Z0-9-]+)/", testo_evo_page)
    for slug in links_evo:
        nome_e = slug.replace("-", " ").title()
        if nome_e not in evoluzioni:
            evoluzioni.append(nome_e)

    # Prende anche un estratto pulito del testo della pagina Evoluzioni di FUT.GG (dove ci sono requisiti e boost)
    righe_evo = [r.strip() for r in testo_evo_page.split("\n") if len(r.strip()) > 25 and "http" not in r]
    estratto_dettagli_evo = "\n".join(righe_evo[:25])

    return evoluzioni[:8], giocatori[:15], estratto_dettagli_evo[:1500]

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    if not parti:
        return
    comando = parti[0].lower().split("@")[0]

    if comando in ["/start", "/help", "/menu"]:
        menu = (
            "🎯 <b>BOT SNIPER REAL-DATA (ZERO ALLUCINAZIONI)</b>\n"
            "💰 Budget: 800.000 crediti (PlayStation)\n\n"
            "🔥 <b>/leak</b> - Mostra gli ultimi leak REALI con <b>Data, Ora, Stats e PlayStyles aggiunti</b> + carte reali con prezzi veri (700-10k cr per gli Oro, ecc.)\n\n"
            "🧬 <b>/evo</b> - Legge le Evoluzioni reali su FUT.GG, requisiti, boost e giocatori in trending\n\n"
            "🔮 <b>/simula [requisiti e boost]</b> - Analizza un leak specifico che hai visto su X\n\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram("🕵️‍♂️ <i>Estrazione post REALI con Data/Ora dai canali Leak + Verifica Evoluzioni e Prezzi su FUT.GG...</i>", chat_id)
        leaks = leggi_leak_telegram_con_data_ora()
        evoluzioni_attive, giocatori_caldi, dettagli_evo_futgg = leggi_dettagli_evo_e_trending_futgg()

        # Prepara il blocco con Data e Ora esatta dei post reali
        if leaks:
            blocco_leaks_reali = "\n".join([f"- [{x['data_ora']}] {x['canale']}: {x['testo']}" for x in leaks[-8:]])
        else:
            blocco_leaks_reali = "Nessun post estratto da Telegram web in questo istante."

        prompt = (
            f"ULTIMI POST REALI ESTRATTI CON DATA E ORA DAI LEAKER:\n{blocco_leaks_reali}\n\n"
            f"EVOLUZIONI ATTUALMENTE RILEVATE SU FUT.GG: {', '.join(evoluzioni_attive)}\n"
            f"ESTRATTO PAGINA EVOLUZIONI FUT.GG:\n{dettagli_evo_futgg}\n\n"
            f"GIOCATORI PIÙ CLICCATI ORA SU FUT.GG (TRENDING/MOMENTUM): {', '.join(giocatori_caldi)}\n\n"
            "ISTRUZIONI TASSATIVE:\n"
            "1) Prima di tutto, descrivi in modo specifico QUALI sono gli ultimi leak o le ultime Evoluzioni reali presenti nei dati qui sopra "
            "(o trovati tramite ricerca web delle ultime 24 ore), specificando per ciascuno: GIORNO E ORARIO del leak, REQUISITI ESATTI, "
            "QUALI STATS (+Pace, +Shooting, +Dribbling, ecc.) e QUALI PLAYSTYLES va ad aggiungere.\n"
            "2) Poi indica 5-6 CARTE REALI (Nome, Cognome, OVR, Club) tra quelle in Trending su FUT.GG o che entrano in questi requisiti.\n"
            "3) USA SOLO PREZZI REALI DI MERCATO: se consigli una carta Oro Raro 78-82 OVR (come Nusa, Gruda, Gloukh, Neto), ricorda che il suo prezzo base è 700-1.500 crediti "
            "e nell'hype di un'Evo sale tra 2.500 e 9.500 crediti (max price range 10.000). NON scrivere mai prezzi assurdi come 50.000 o 150.000 per una carta oro bassa!"
        )
        analisi = analizza_senza_allucinazioni(prompt)

        msg = "🚨 <b>ULTIMI LEAK VERIFICATI (CON DATA/ORA, STATS & PLAYSTYLES):</b>\n\n"
        if leaks:
            for item in leaks[-4:]:
                pulito = item["testo"].replace("<", "&lt;").replace(">", "&gt;")
                msg += f"🕒 <b>{item['data_ora']} | {item['canale']}:</b>\n<i>{pulito[:220]}</i>\n\n"
        else:
            msg += "⚠️ <i>Canali Telegram temporaneamente schermati, analisi basata sui dati live estratti da FUT.GG:</i>\n\n"

        if evoluzioni_attive:
            msg += f"🧬 <b>Ultime Evo su FUT.GG:</b> <code>{', '.join(evoluzioni_attive[:5])}</code>\n"
        if giocatori_caldi:
            msg += f"📈 <b>Giocatori più cercati ora:</b> <code>{', '.join(giocatori_caldi[:8])}</code>\n\n"

        msg += f"🎯 <b>DETTAGLIO LEAK (STATS/PLAYSTYLES) & CARTE REALI:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 <i>Lettura diretta delle Evoluzioni attive, Requisiti, Boost e Trending su FUT.GG...</i>", chat_id)
        evoluzioni_attive, giocatori_caldi, dettagli_evo_futgg = leggi_dettagli_evo_e_trending_futgg()

        prompt = (
            f"EVOLUZIONI RILEVATE SU FUT.GG: {', '.join(evoluzioni_attive)}\n"
            f"TESTO ESTRATTO DA FUT.GG EVOLUTIONS:\n{dettagli_evo_futgg}\n"
            f"GIOCATORI IN TRENDING EVO SU FUT.GG: {', '.join(giocatori
