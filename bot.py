import os
import re
import time
import threading
import requests
import cloudscraper
from bs4 import BeautifulSoup
from flask import Flask
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# Dati letti in automatico dalle impostazioni di Render.com
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") # Opzionale ma consigliata per far analizzare il leak all'IA

# Canali Telegram pubblici di Leak e Trading (leggibili via web senza account!)
CANALI_LEAK = [
    "https://t.me/s/Fut_Scoreboard",
    "https://t.me/s/FutSheriff_Official",
    "https://t.me/s/fifatradingromania"
]

PAROLE_CHIAVE_CALDE = ["evo", "evolution", "sbc", "potm", "leak", "max ", "req", "upgrade", "playstyle"]

messaggi_gia_visti = set()
evo_gia_viste = set()

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

def invia_telegram(testo):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Mancano Token o Chat ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": testo,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def analizza_leak_con_ia(testo_leak):
    """Se hai inserito la chiave gratuita Gemini, analizza il leak e ti dice esattamente chi comprare."""
    if not GEMINI_API_KEY:
        return (
            "💡 <b>Azione Rapida Consigliata:</b>\n"
            "• Se è una <b>EVO</b>: apri FUT.GG -> Evo Lab, imposta i requisiti del leak e compra le carte Meta (Premier/Liga/Serie A) tra 2k e 30k.\n"
            "• Se è una <b>SBC</b>: compra subito i link verdi (stesso club/nazione) prima delle 19:00!"
        )
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        f"Sei un top trader di EA Sports FC 27 Ultimate Team (mercato PlayStation, budget 800k). "
        f"È appena uscito questo leak o notizia in tempo reale:\n'{testo_leak}'\n"
        f"Dimmi in massimo 4 punti brevissimi: "
        f"1) Quali carte o filtri esatti devo comprare ADESSO per fare crediti nell'hype. "
        f"2) Fascia di prezzo consigliata e prezzo di rivendita (considerando il 5% di tassa EA). "
        f"3) Quando vendere."
    )
    try:
        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        risposta = r.json()
        consiglio = risposta["candidates"][0]["content"]["parts"][0]["text"]
        # Pulisce la formattazione per Telegram
        consiglio_pulito = consiglio.replace("**", "").replace("*", "•")
        return f"🧠 <b>ANALISI AUTOMATICA INVESTIMENTO:</b>\n{consiglio_pulito}"
    except Exception as e:
        return "⚡ Leak rilevato! Controlla subito i filtri su FUT.GG per anticipare il mercato."

def scansiona_leak_telegram_web():
    """Legge i canali di leak pubblici in tempo reale senza bisogno di API X o login."""
    global messaggi_gia_visti
    for url in CANALI_LEAK:
        try:
            resp = scraper.get(url, timeout=12)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            blocchi = soup.find_all("div", class_="tgme_widget_message_text")
            
            # Controlla gli ultimi 3 messaggi del canale
            for blocco in blocchi[-3:]:
                testo = blocco.get_text(separator="\n").strip()
                id_msg = hash(testo[:80])
                
                if id_msg not in messaggi_gia_visti and len(testo) > 15:
                    messaggi_gia_visti.add(id_msg)
                    testo_lower = testo.lower()
                    
                    # Verifica se parla di Evoluzioni, SBC o Requisiti
                    if any(k in testo_lower for k in PAROLE_CHIAVE_CALDE):
                         # Evita di mandare notifiche per i vecchi post al primo avvio
                        if len(messaggi_gia_visti) > 6:
                            analisi = analizza_leak_con_ia(testo)
                            notifica = (
                                f"🚨 <b>NUOVO LEAK RILEVATO IN TEMPO REALE!</b>\n\n"
                                f"📝 <i>{testo[:400]}</i>\n\n"
                                f"{analisi}\n\n"
                                f"🔗 <a href='https://www.fut.gg/evolutions/best/'>Apri Best Evolutions su FUT.GG</a>"
                            )
                            invia_telegram(notifica)
        except Exception as e:
            print(f"Errore scansione leak {url}: {e}")

def scansiona_nuove_evo_futgg():
    """Controlla direttamente su FUT.GG se è uscita una nuova Evoluzione o carta Trending."""
    global evo_gia_viste
    try:
        resp = scraper.get("https://www.fut.gg/evolutions/", timeout=12)
        if resp.status_code == 200:
            # Cerca i link alle singole evoluzioni presenti nella pagina
            links = re.findall(r'/evolutions/\d+-[a-zA-Z0-9-]+/', resp.text)
            for link in set(links):
                if link not in evo_gia_viste:
                    evo_gia_viste.add(link)
                    # Se non è il primo avvio del server, significa che è appena uscita!
                    if len(evo_gia_viste) > 5:
                        nome_evo = link.split("-", 1)[-1].replace("/", "").replace("-", " ").upper()
                        analisi = analizza_leak_con_ia(f"Nuova Evoluzione appena uscita su FC 27: {nome_evo}")
                        invia_telegram(
                            f"🔥 <b>NUOVA EVOLUZIONE RILEVATA SU FUT.GG!</b>\n"
                            f"📌 Nome: <b>{nome_evo}</b>\n\n"
                            f"{analisi}\n\n"
                            f"👉 <a href='https://www.fut.gg{link}'>Vedi Giocatori Compatibili su FUT.GG</a>"
                        )
    except Exception as e:
        print(f"Errore scansione FUT.GG: {e}")

def motore_h24():
    """Gira senza sosta 24 ore su 24 sul server Render."""
    invia_telegram(
        "✅ <b>SERVER RENDER H24 ATTIVO!</b>\n"
        "Sto monitorando in automatico:\n"
        "• Leak su Evoluzioni, SBC e POTM\n"
        "• Uscite in tempo reale su FUT.GG\n"
        "• Orari chiave del mercato PlayStation (800k budget)\n\n"
        "<i>Non devi fare nulla: ti scriverò io appena esce un'occasione d'oro!</i>"
    )
    
    # Primo giro di registrazione silenziosa (per non mandarti i post di ieri)
    scansiona_leak_telegram_web()
    scansiona_nuove_evo_futgg()
    ultimo_orario = ""

    while True:
        try:
            scansiona_leak_telegram_web()
            scansiona_nuove_evo_futgg()

            # Controllo orari fissi italiani (18:55 hype e Giovedì 08:55 premi)
            tz_it = timezone(timedelta(hours=2))
            now = datetime.now(tz_it)
            ora_str = now.strftime("%H:%M")

            if ora_str != ultimo_orario:
                if ora_str == "18:55":
                    invia_telegram(
                        "⏰ <b>18:55 - CONTENUTI EA TRA 5 MINUTI!</b>\n"
                        "• Vendi ORA le carte comprate sui leak di oggi.\n"
                        "• Alle 19:00 spaccate ti avviserò se esce una nuova Evo su FUT.GG!"
                    )
                    ultimo_orario = ora_str
                elif ora_str == "08:55" and now.weekday() == 3:
                    invia_telegram(
                        "📉 <b>08:55 - PREMI RIVALS TRA 5 MINUTI!</b>\n"
                        "Entra sulla Companion App: tra le 09:05 e le 09:25 compra Fodder 85-88 e carte Meta colpite dal panic selling."
                    )
                    ultimo_orario = ora_str

            # Controlla tutto ogni 2 minuti (120 secondi)
            time.sleep(120)
        except Exception as e:
            print(f"Errore nel ciclo: {e}")
            time.sleep(60)

@app.route('/')
def home():
    return "FC 27 Automated Leak & Evo Radar is Active 24/7!"

# Avvia il motore in background appena Render accende il server
threading.Thread(target=motore_h24, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
