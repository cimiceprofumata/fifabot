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
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."

    tz_it = timezone(timedelta(hours=2))
    oggi = datetime.now(tz_it).strftime("%d/%m/%Y %H:%M")
    sistema = (
        f"Data e ora attuale italiana: {oggi}. Sei un analista tecnico di mercato di EA Sports FC 27 Ultimate Team (PlayStation). "
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

def scarica_html_grezzo(target_url):
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
    testo_evo_page = scarica_testo_jina("https://www.fut.gg/evolutions/")
    testo_momentum = scarica_testo_jina("https://www.fut.gg/players/momentum/")
    testo_best_evo = scarica_testo_jina("https://www.fut.gg/evolutions/trending/")

    giocatori = []
    for sorgente in [testo_best_evo, testo_momentum]:
        matches = re.findall(r"/players/\d+-([a-zA-Z0-9-]+)/", sorgente)
        for slug in matches:
            nome = slug.replace("-", " ").title()
            if len(nome) > 3 and nome not in giocatori:
                giocatori.append(nome)

    evoluzioni = []
    links_evo = re.findall(r"/evolutions/\d+-([a-zA-Z0-9-]+)/", testo_evo_page)
    for slug in links_evo:
        nome_e = slug.replace("-", " ").title()
        if nome_e not in evoluzioni:
            evoluzioni.append(nome_e)

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
            "🔥 <b>/leak</b> - Mostra gli ultimi leak REALI con <b>Data, Ora, Stats e PlayStyles aggiunti</b> + carte reali con prezzi veri\n\n"
            "🧬 <b>/evo</b> - Legge le Evoluzioni reali su FUT.GG, requisiti, boost e giocatori in trending\n\n"
            "🔮 <b>/simula [requisiti e boost]</b> - Analizza un leak specifico che hai visto su X\n\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram("🕵️‍♂️ <i>Estrazione post REALI con Data/Ora dai canali Leak + Verifica Evoluzioni e Prezzi su FUT.GG...</i>", chat_id)
        leaks = leggi_leak_telegram_con_data_ora()
        evoluzioni_attive, giocatori_caldi, dettagli_evo_futgg = leggi_dettagli_evo_e_trending_futgg()

        if leaks:
            blocco_leaks_reali = "\n".join([f"- [{x['data_ora']}] {x['canale']}: {x['testo']}" for x in leaks[-8:]])
        else:
            blocco_leaks_reali = "Nessun post estratto da Telegram web in questo istante."

        str_evo = ", ".join(evoluzioni_attive)
        str_caldi = ", ".join(giocatori_caldi)

        prompt = (
            f"ULTIMI POST REALI ESTRATTI CON DATA E ORA DAI LEAKER:\n{blocco_leaks_reali}\n\n"
            f"EVOLUZIONI ATTUALMENTE RILEVATE SU FUT.GG: {str_evo}\n"
            f"ESTRATTO PAGINA EVOLUZIONI FUT.GG:\n{dettagli_evo_futgg}\n\n"
            f"GIOCATORI PIÙ CLICCATI ORA SU FUT.GG (TRENDING/MOMENTUM): {str_caldi}\n\n"
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
            str_evo5 = ", ".join(evoluzioni_attive[:5])
            msg += f"🧬 <b>Ultime Evo su FUT.GG:</b> <code>{str_evo5}</code>\n"
        if giocatori_caldi:
            str_caldi8 = ", ".join(giocatori_caldi[:8])
            msg += f"📈 <b>Giocatori più cercati ora:</b> <code>{str_caldi8}</code>\n\n"

        msg += f"🎯 <b>DETTAGLIO LEAK (STATS/PLAYSTYLES) & CARTE REALI:</b>\n{analisi}"
        invia_telegram(msg, chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 <i>Lettura diretta delle Evoluzioni attive, Requisiti, Boost e Trending su FUT.GG...</i>", chat_id)
        evoluzioni_attive, giocatori_caldi, dettagli_evo_futgg = leggi_dettagli_evo_e_trending_futgg()

        str_evo = ", ".join(evoluzioni_attive)
        str_caldi = ", ".join(giocatori_caldi)

        prompt = (
            f"EVOLUZIONI RILEVATE SU FUT.GG: {str_evo}\n"
            f"TESTO ESTRATTO DA FUT.GG EVOLUTIONS:\n{dettagli_evo_futgg}\n"
            f"GIOCATORI IN TRENDING EVO SU FUT.GG: {str_caldi}\n\n"
            "Per ciascuna delle ultime Evoluzioni elencate:\n"
            "1) Specifica Nome dell'Evoluzione, Requisiti di ingresso, quali Stats e quali PlayStyles/PlayStyle+ aggiunge.\n"
            "2) Indica i giocatori specifici (Nome, Cognome, OVR, Club) tra quelli in Trending su FUT.GG che ci entrano meglio.\n"
            "3) Indica prezzi di acquisto e rivendita REALISTICI per PlayStation (ricorda che gli Oro <83 hanno tetto massimo a 10.000 crediti!)."
        )
        consiglio = analizza_senza_allucinazioni(prompt)
        str_evo6 = ", ".join(evoluzioni_attive[:6])
        str_caldi10 = ", ".join(giocatori_caldi[:10])
        msg = (
            f"🔥 <b>REPORT EVOLUZIONI REALI FUT.GG:</b>\n\n"
            f"🧬 <b>Evo attive:</b> <code>{str_evo6}</code>\n"
            f"📈 <b>Trending Players:</b> <code>{str_caldi10}</code>\n\n"
            f"🧠 <b>REQUISITI, BOOST STATS/PLAYSTYLES & CARTE DA COMPRARE:</b>\n{consiglio}\n\n"
            f"🔗 <a href='https://www.fut.gg/evolutions/trending/'>Verifica Prezzi Live su FUT.GG Trending</a>"
        )
        invia_telegram(msg, chat_id)

    elif comando == "/simula":
        if len(parti) < 2:
            invia_telegram(
                "🔮 <b>SIMULATORE REQUISITI & BOOST</b>\n"
                "Incolla il testo esatto di un leak visto su X:\n"
                "<code>/simula Evo Max 82 OVR Max 86 PAC +6 PAC +8 SHO PlayStyle+ Finesse Shot</code>",
                chat_id
            )
            return
        leak_input = " ".join(parti[1:])
        invia_telegram("🔮 <i>Analisi tecnica del leak e ricerca carte con prezzi reali...</i>", chat_id)
        _, giocatori_caldi, _ = leggi_dettagli_evo_e_trending_futgg()
        str_caldi = ", ".join(giocatori_caldi)
        prompt = (
            f"L'utente ha fornito questo leak specifico: '{leak_input}'\n"
            f"Giocatori attualmente caldi su FUT.GG: {str_caldi}\n"
            "1) Riepiloga quali Stats e PlayStyles aggiunge questo leak e quali sono i limiti dei requisiti.\n"
            "2) Indica 6 carte REALI (Nome, Cognome, OVR, versione e Club) che rispettano questi requisiti e combinano ottimi PlayStyles di base.\n"
            "3) Indica i veri prezzi di mercato PS (650-2.000 cr per carte oro scarto, con target 3.500-9.500 cr nell'hype)."
        )
        risp = analizza_senza_allucinazioni(prompt)
        invia_telegram(f"🎯 <b>SIMULAZIONE TECNICA DEL LEAK:</b>\n\n{risp}", chat_id)

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
            invia_telegram("Scrivi una domanda! Es: <code>/chiedi quanto vale Pedro Neto oro e in quale Evo entra?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 <i>Verifica dati reali in corso...</i>", chat_id)
        risp = analizza_senza_allucinazioni(domanda)
        invia_telegram(f"🤖 <b>RISPOSTA VERIFICATA:</b>\n\n{risp}", chat_id)

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

def scansiona_e_simula_h24():
    global messaggi_gia_visti
    leaks = leggi_leak_telegram_con_data_ora()
    for item in leaks:
        txt = item["testo"]
        id_msg = hash(txt[:85])
        if id_msg not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_msg)
            if any(k in txt.lower() for k in PAROLE_TRIGGER):
                if len(messaggi_gia_visti) > 6:
                    _, giocatori_caldi, _ = leggi_dettagli_evo_e_trending_futgg()
                    str_caldi8 = ", ".join(giocatori_caldi[:8])
                    analisi = analizza_senza_allucinazioni(
                        f"NUOVO LEAK APPENA PUBBLICATO:\n"
                        f"Fonte: {item['canale']} | Data e Ora: {item['data_ora']}\n"
                        f"Testo del Leak: '{txt}'\n"
                        f"Giocatori attualmente in Trending su FUT.GG: {str_caldi8}\n\n"
                        "1) Spiega esattamente di quale leak si tratta, riportando Data/Ora, quali Stats e quali PlayStyles aggiunge e i requisiti.\n"
                        "2) Indica 5-6 carte specifiche (Nome, Cognome, OVR, Club) che entrano in questi requisiti.\n"
                        "3) Indica prezzi REALISTICI di mercato su PS (senza inventare cifre fuori Price Range)."
                    )
                    pulito = txt[:350].replace("<", "&lt;").replace(">", "&gt;")
                    notifica = (
                        f"🚨 <b>NUOVO LEAK IN TEMPO REALE!</b>\n"
                        f"🕒 <b>{item['data_ora']} | Fonte: {item['canale']}</b>\n\n"
                        f"📝 <i>{pulito}</i>\n\n"
                        f"🎯 <b>DETTAGLIO STATS/PLAYSTYLES & CARTE DA COMPRARE:</b>\n{analisi}\n\n"
                        f"🔗 <a href='https://www.fut.gg/evolutions/trending/'>Controlla Prezzi Reali su FUT.GG</a>"
                    )
                    invia_telegram(notifica)

def motore_h24():
    avvio = (
        "🛡️ <b>BOT AGGIORNATO: MODALITÀ 'DATI REALI, DATA/ORA LEAK & PREZZI VERI'!</b>\n\n"
        "• Aggiunta estrazione di <b>Giorno e Orario esatto</b> di ogni leak.\n"
        "• Dettaglio obbligatorio di <b>quali Stats e quali PlayStyles</b> aggiunge il leak.\n"
        "• <b>Blocco Anti-Allucinazione</b> sui prezzi (rispetto dei Price Range reali: Oro 75-82 tra 700 e 10k crediti!).\n\n"
        "Scrivi subito <b>/leak</b> o <b>/evo</b> per testarlo!"
    )
    invia_telegram(avvio)
    scansiona_e_simula_h24()
    ultimo_orario = ""

    while True:
        try:
            scansiona_e_simula_h24()
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
    return "FC 27 Verified Leak & Price Bot Running!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
