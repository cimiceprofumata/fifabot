
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

# Canali X/Telegram prioritari monitorati ogni 60 secondi H24
CANALI_X_LEAKERS = [
    "Fut_Scoreboard",
    "FutSheriff_Official",
    "AsyFutTrader",
    "DonkTrading",
    "FutPoliceLeaks",
    "fifatradingromania"
]

PAROLE_TRIGGER_SIMULAZIONE = [
    "evo", "evolution", "max ", "req", "boost", "playstyle",
    "pace", "overall", "rating", "sbc", "potm", "leaked", "upcoming", "stats"
]

PAROLE_BANNATE = [
    "patch", "title update", "career mode", "clubs", "fixes",
    "fifa 20", "fifa 21", "fifa 22", "fifa 23", "fc 24", "fc 25"
]

messaggi_gia_visti = set()
ultimo_update_id = 0
modello_scoperto = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
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
    modelli = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.0-flash", "gemini-flash-latest"]
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

def simula_carte_meta_futgg(prompt_specifico):
    """Motore di Simulazione Automatica: valuta Requisiti + Boost + PlayStyles Meta + FUT.GG Meta Rating."""
    global modello_scoperto
    if not GEMINI_API_KEY:
        return "⚠️ Chiave GEMINI_API_KEY non trovata su Render."

    oggi = datetime.now().strftime("%d/%m/%Y %H:%M")
    sistema = (
        f"Data e ora: {oggi}. Sei il motore di simulazione predittiva di EA Sports FC 27 Ultimate Team "
        "(mercato PlayStation, budget 800.000 crediti). "
        "DEVI SIMULARE IN ANTICIPO QUALI CARTE ESPLODERANNO DI PREZZO INCROCIANDO I LEAK DI X CON IL META RATING DI FUT.GG:\n"
        "1) CRITERIO PLAYSTYLES META (FONDAMENTALE): Seleziona solo giocatori che possiedono già (o otterranno col boost senza sovrapporsi) "
        "i PlayStyles più forti del meta di FC 27:\n"
        "   - Difensori/Terzini: Anticipate (Anticipo), Jockey (Affronta), Intercept, Quick Step, Bruiser.\n"
        "   - Centrocampisti: Incisive Pass (Filtrante), Pinged Pass (Passaggio Teso), Intercept, Tiki Taka, Press Proven, Technical.\n"
        "   - Attaccanti/Ali: Finesse Shot (Tiro a Giro), Quick Step (Passo Veloce), Rapid (Rapido), Technical, Trivela.\n"
        "2) CRITERIO FUT.GG META RATING: Scegli le carte 'al limite massimo dei requisiti' (es. se il leak dice Max 82 OVR, cerca gli 81-82 OVR, non i 76) "
        "con Body Type meta, 4/5 stelle Skill/Piede Debole, ruoli secondari utili e link top (Francia, Brasile, Premier League, LaLiga, Serie A) "
        "che raggiungeranno un Meta Rating di 90+ su FUT.GG una volta evoluti.\n"
        "3) FORMATO RISPOSTA OBBLIGATORIO (Nessun discorso generico, solo 6-8 carte specifiche):\n"
        "   Per ogni carta scrivi:\n"
        "   • NOME E COGNOME + OVR + Versione (Oro/TOTW/Promo) + Club\n"
        "   • PlayStyles attuali + Sinergia col Boost del Leak + Meta Rating FUT.GG previsto\n"
        "   • Prezzo Max Acquisto ORA (su PS) -> Target Rivendita nell'Hype (netto tassa 5%).\n"
        "Non usare mai simboli Markdown come asterischi (*) o cancelletti (#)."
    )
    testo_completo = f"{sistema}\n\nDATI DA SIMULARE:\n{prompt_specifico}"

    modelli_da_provare = trova_modelli_attivi()
    ultimo_errore = "Nessuna risposta"

    for modello in modelli_da_provare:
        for con_search in [True, False]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent?key={GEMINI_API_KEY}"
            body = {"contents": [{"parts": [{"text": testo_completo}]}]}
            if con_search:
                body["tools"] = [{"google_search": {}}]
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

def scarica_pagina_con_bypass(target_url):
    tentativi = [
        target_url,
        f"https://api.codetabs.com/v1/proxy?quest={quote(target_url, safe='')}",
        f"https://api.allorigins.win/raw?url={quote(target_url, safe='')}",
        f"https://r.jina.ai/{target_url}"
    ]
    for u in tentativi:
        try:
            resp = scraper.get(u, headers=HEADERS, timeout=12)
            if resp.status_code == 200 and len(resp.text) > 300:
                return resp.text
        except Exception:
            continue
    return ""

def leggi_leak_x_e_telegram():
    """Legge gli ultimissimi post dai canali mirror dei leaker di X."""
    raccolta = []
    for canale in CANALI_X_LEAKERS:
        html = scarica_pagina_con_bypass(f"https://t.me/s/{canale}")
        if "tgme_widget_message_text" in html:
            soup = BeautifulSoup(html, "html.parser")
            blocchi = soup.find_all("div", class_="tgme_widget_message_text")
            for b in blocchi[-3:]:
                txt = b.get_text(separator=" ").strip()
                txt_low = txt.lower()
                if len(txt) > 20 and "Download" not in txt and "Send Message" not in txt:
                    if not any(ban in txt_low for ban in PAROLE_BANNATE):
                        raccolta.append((f"@{canale}", txt[:350]))
    return raccolta

def estrai_dati_futgg():
    """Estrae da FUT.GG i giocatori in hype (Momentum / Best Evolutions / Trending)."""
    giocatori_hype = []
    urls = [
        "https://www.fut.gg/evolutions/best/",
        "https://www.fut.gg/evolutions/trending/",
        "https://www.fut.gg/players/momentum/"
    ]
    for u in urls:
        html_p = scarica_pagina_con_bypass(u)
        if html_p:
            matches = re.findall(r"/players/\d+-([a-zA-Z0-9-]+)/", html_p)
            for slug in matches:
                nome = slug.replace("-", " ").title()
                if len(nome) > 3 and nome not in giocatori_hype:
                    giocatori_hype.append(nome)
        if len(giocatori_hype) >= 18:
            break
    return giocatori_hype[:18]

def gestisci_comando(testo_msg, chat_id):
    parti = testo_msg.strip().split()
    if not parti:
        return
    comando = parti[0].lower().split("@")[0]

    if comando in ["/start", "/help", "/menu"]:
        menu = (
            "🎯 <b>BOT AUTO-SIMULATORE LEAK X, PLAYSTYLES & FUT.GG META</b>\n"
            "💰 Budget: 800.000 crediti (PlayStation)\n"
            "📡 <i>Monitoraggio Live H24 attivo ogni 60 secondi!</i>\n\n"
            "🔥 <b>/leak</b> (COMANDO TUTTO-IN-UNO)\n"
            "Cerca all'istante gli ultimi leak di X (@FutSheriff, @Fut_Scoreboard, @AsyFutTrader) e <b>simula automaticamente</b> le carte migliori per PlayStyles e Meta Rating di FUT.GG.\n\n"
            "🔮 <b>/simula [requisiti + boost]</b>\n"
            "Simula manualmente un requisito specifico su FUT.GG.\n\n"
            "🧬 <b>/evo</b> - Classifica carte con Meta Rating più alto e PlayStyles top nelle Evo di FUT.GG\n"
            "🧮 <b>/tassa 50000</b> - Calcola pareggio (5%) e profitto\n"
            "🧠 <b>/chiedi [domanda]</b> - Domanda libera al bot"
        )
        invia_telegram(menu, chat_id)

    elif comando == "/leak":
        invia_telegram(
            "🕵️‍♂️ <i>Ricerca immediata ultimi Leak di X + Auto-Simulazione PlayStyles Meta e FUT.GG Meta Rating in corso...</i>",
            chat_id
        )
        leaks = leggi_leak_x_e_telegram()
        giocatori_futgg = estrai_dati_futgg()

        contesto_leak = "\n".join([f"{c}: {t}" for c, t in leaks]) if leaks else "Cerca direttamente gli ultimi post X di @FutSheriff, @Fut_Scoreboard, @AsyFutTrader e @DonkTrading."
        contesto_futgg = ", ".join(giocatori_futgg) if giocatori_futgg else "Classifica Meta Rating FUT.GG"

        prompt = (
            f"ULTIMI LEAK INTERCETTATI DAI CANALI X/TELEGRAM:\n{contesto_leak}\n\n"
            f"CARTE ATTUALMENTE IN CIMA A FUT.GG (BEST/TRENDING/MOMENTUM): {contesto_futgg}\n\n"
            "ESEGUI ORA LA SIMULAZIONE AUTOMATICA:\n"
            "1) Prendi gli ultimissimi leak delle ultime ore su EA FC 27 (nuove Evoluzioni con requisiti e boost, o nuove SBC/Promo leakate da @FutSheriff e @Fut_Scoreboard).\n"
            "2) Simula automaticamente l'incrocio tra REQUISITI + BOOST previsti e il database di FUT.GG.\n"
            "3) Seleziona 6-8 GIOCATORI ESATTI (Nome, Cognome, OVR e Club) che hanno i PLAYSTYLES PIÙ IN META (Anticipate, Quick Step, Finesse Shot, Incisive Pass, Intercept, Technical, Rapid) "
            "e che otterranno il META RATING PIÙ ALTO su FUT.GG.\n"
            "4) Indica per ogni carta: Nome e Cognome, PlayStyles chiave, perché sarà la più desiderata dalla community, prezzo di acquisto immediato su PS e target di rivendita."
        )
        simulazione = simula_carte_meta_futgg(prompt)

        msg = "🚨 <b>ULTIMI LEAK X & AUTO-SIMULAZIONE CARTE META (FUT.GG):</b>\n\n"
        if leaks:
            for c, t in leaks[-3:]:
                pulito = t.replace("<", "&lt;").replace(">", "&gt;")
                msg += f"🐦 <b>{c}:</b> <i>{pulito[:180]}</i>\n\n"
        if giocatori_futgg:
            msg += f"📈 <b>Top FUT.GG Best/Momentum:</b> <code>{', '.join(giocatori_futgg[:8])}</code>\n\n"
        msg += f"🔮 <b>SIMULAZIONE CARTE DA COMPRARE ORA (PLAYSTYLES & META RATING):</b>\n{simulazione}"
        invia_telegram(msg, chat_id)

    elif comando == "/simula":
        if len(parti) < 2:
            invia_telegram(
                "🔮 <b>SIMULATORE PLAYSTYLES & META RATING FUT.GG</b>\n"
                "Scrivi i requisiti/boost del leak:\n"
                "<code>/simula Evo DC Max 83 OVR Max 82 PAC Boost +8 PAC PlayStyle+ Anticipate</code>",
                chat_id
            )
            return
        leak_input = " ".join(parti[1:])
        invia_telegram("🔮 <i>Simulazione PlayStyles Meta + Calcolo Meta Rating FUT.GG in corso...</i>", chat_id)
        prompt = (
            f"Simula questo leak di Evoluzione per EA FC 27:\n'{leak_input}'\n\n"
            "Trova nel database di FUT.GG gli 8 GIOCATORI ESATTI (Nome, Cognome, OVR, Versione e Club) che:\n"
            "• Rientrano al limite massimo dei requisiti.\n"
            "• Hanno già i migliori PlayStyles in meta (es. Quick Step, Anticipate, Finesse Shot, Incisive Pass, Jockey, Technical) che si combinano col boost.\n"
            "• Raggiungeranno il Meta Rating più alto su FUT.GG.\n"
            "Indica per ciascuno prezzo di acquisto su PS e target di rivendita."
        )
        risp = simula_carte_meta_futgg(prompt)
        invia_telegram(f"🎯 <b>RISULTATO SIMULAZIONE PLAYSTYLES & META RATING:</b>\n\n{risp}", chat_id)

    elif comando == "/evo":
        invia_telegram("🧬 <i>Analisi PlayStyles Meta e Classifica Meta Rating FUT.GG in corso...</i>", chat_id)
        giocatori_futgg = estrai_dati_futgg()
        nomi_player = ", ".join(giocatori_futgg) if giocatori_futgg else "fut.gg/evolutions/best/"

        prompt = (
            f"Carte attualmente in evidenza su FUT.GG Best & Trending: {nomi_player}.\n"
            "Analizza le ultime Evoluzioni e le catene di Evoluzioni (Evo Chains) di EA FC 27 su FUT.GG. "
            "Dammi 7 NOMI E COGNOMI di carte scambiabili sul mercato PlayStation (fascia 1.500 - 100.000 crediti) "
            "che hanno il META RATING più alto su FUT.GG grazie ai loro PlayStyles (Anticipate, Finesse Shot, Quick Step, Incisive Pass, Rapid) "
            "con prezzo di acquisto e target di vendita."
        )
        consiglio = simula_carte_meta_futgg(prompt)
        msg = (
            f"🔥 <b>TOP META RATING & PLAYSTYLES (FUT.GG):</b>\n\n"
            f"⚡ <b>Rilevati su FUT.GG:</b> <code>{nomi_player}</code>\n\n"
            f"🧠 <b>CARTE CON IL META RATING PIÙ ALTO DA COMPRARE:</b>\n{consiglio}\n\n"
            f"🔗 <a href='https://www.fut.gg/evolutions/best/'>Apri FUT.GG Best Meta Rating</a>"
        )
        invia_telegram(msg, chat_id)

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
            invia_telegram("Scrivi una domanda! Es: <code>/chiedi migliori DC con PlayStyle Anticipo sotto i 50k per future Evo?</code>", chat_id)
            return
        domanda = " ".join(parti[1:])
        invia_telegram("🧠 <i>Simulazione PlayStyles e Meta Rating su FUT.GG in corso...</i>", chat_id)
        risp = simula_carte_meta_futgg(domanda)
        invia_telegram(f"🤖 <b>ANALISI META RATING & PLAYSTYLES:</b>\n\n{risp}", chat_id)

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

# ================= MONITORAGGIO LIVE H24 (OGNI 60 SECONDI) =================
def scansiona_e_simula_h24():
    """Controlla ogni 60 secondi i canali dei leaker. Appena esce un leak, simula da solo le carte migliori e manda la notifica."""
    global messaggi_gia_visti
    leaks = leggi_leak_x_e_telegram()
    for fonte, txt in leaks:
        id_msg = hash(txt[:85])
        if id_msg not in messaggi_gia_visti:
            messaggi_gia_visti.add(id_msg)
            txt_low = txt.lower()
            if any(k in txt_low for k in PAROLE_TRIGGER_SIMULAZIONE):
                # Evita di mandare i post già presenti al momento del riavvio del server
                if len(messaggi_gia_visti) > 5:
                    giocatori_futgg = estrai_dati_futgg()
                    simulazione_auto = simula_carte_meta_futgg(
                        f"ALERT AUTOMATICO H24 - NUOVO LEAK APPENA PUBBLICATO DA {fonte}:\n'{txt}'\n"
                        f"Carte attualmente in tendenza su FUT.GG: {', '.join(giocatori_futgg[:8])}.\n"
                        "SIMULA IMMEDIATAMENTE: in base ai requisiti e ai boost di questo leak, trova nel database di FUT.GG "
                        "i 6 NOMI E COGNOMI ESATTI delle carte che hanno i PlayStyles più in meta (Anticipate, Quick Step, Finesse Shot, Incisive Pass, Intercept, Technical) "
                        "e che avranno il Meta Rating più alto su FUT.GG. Indica prezzo massimo di acquisto ORA su PS e target di rivendita!"
                    )
                    pulito = txt[:320].replace("<", "&lt;").replace(">", "&gt;")
                    notifica_push = (
                        f"🚨 <b>NUOVO LEAK LIVE RILEVATO DA {fonte}!</b>\n\n"
                        f"📝 <i>{pulito}</i>\n\n"
                        f"🔮 <b>SIMULAZIONE AUTOMATICA (PLAYSTYLES & META RATING FUT.GG):</b>\n{simulazione_auto}\n\n"
                        f"🔗 <a href='https://www.fut.gg/evolutions/best/'>Apri FUT.GG Meta Rating</a> | "
                        f"<a href='https://www.fut.gg/players/momentum/'>Momentum Live</a>"
                    )
                    invia_telegram(notifica_push)

def motore_h24():
    avvio = (
        "🔥 <b>SISTEMA AUTO-SIMULAZIONE H24 + PLAYSTYLES META ATTIVO!</b>\n\n"
        "• <b>Monitoraggio Live H24 (ogni 60s):</b> Appena esce un leak su @FutSheriff, @Fut_Scoreboard o @AsyFutTrader, il bot simula da solo i PlayStyles Meta e il Meta Rating di FUT.GG e ti manda subito la notifica con i Nomi da comprare!\n"
        "• <b>Comando /leak immediato:</b> Scrivilo ora per forzare subito la ricerca e la simulazione automatica sugli ultimi leak usciti!"
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
                    invia_telegram(
                        "⏰ <b>18:55 - DROP EA TRA 5 MINUTI!</b>\n"
                        "• Vendi ORA nell'hype le carte comprate sui leak.\n"
                        "• Alle 19:01 scrivi <b>/leak</b> o <b>/evo</b> per la simulazione sul nuovo contenuto!"
                    )
                    ultimo_orario = ora_str
                elif ora_str == "08:55" and now.weekday() == 3:
                    invia_telegram("📉 <b>08:55 - PREMI RIVALS TRA 5 MINUTI!</b>")
                    ultimo_orario = ora_str

            # Scansione continua ogni 60 secondi H24
            time.sleep(60)
        except Exception:
            time.sleep(60)

@app.route("/")
def home():
    return "FC 27 Auto-Simulator H24 (PlayStyles & FUT.GG Meta Rating) Running!"

threading.Thread(target=motore_h24, daemon=True).start()
threading.Thread(target=ascolta_comandi_telegram, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
