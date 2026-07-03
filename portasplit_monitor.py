#!/usr/bin/env python3
"""
PortaSplit Stock Monitor
========================
Surveille la disponibilité du Midea PortaSplit sur Boulanger, Darty,
Leroy Merlin et Amazon. Envoie une alerte Telegram dès qu'un stock est détecté.

INSTALLATION (une seule fois) :
  pip install requests

CONFIGURATION :
  1. Créez un bot Telegram via @BotFather sur Telegram → /newbot
     Copiez le TOKEN dans TELEGRAM_TOKEN ci-dessous (ou variable d'env)

  2. Récupérez votre Chat ID :
     → Envoyez n'importe quel message à votre bot
     → Visitez https://api.telegram.org/bot<VOTRE_TOKEN>/getUpdates
     → Copiez la valeur "id" dans le bloc "chat"

  3. Vérifiez les URLs des boutiques ci-dessous (section STORES)
     Darty et Leroy Merlin : ouvrez le produit dans votre navigateur
     et copiez l'URL exacte — les URLs fournies ici sont indicatives.

UTILISATION :
  En continu (local) :    python portasplit_monitor.py
  Une seule vérif :       python portasplit_monitor.py --once
  (le mode --once est utilisé par cron / GitHub Actions)

LIMITATION IMPORTANTE :
  Darty et Boulanger affichent le statut de stock via JavaScript.
  Le script tente d'abord une approche HTML simple. Si le résultat est
  systématiquement "❓ indéterminé", installez playwright et relancez :
    pip install playwright && playwright install chromium
  puis décommentez la section Playwright en bas de ce fichier.
"""

import os
import sys
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
#  Remplissez ici OU passez ces valeurs en variables d'environnement
#  (recommandé pour GitHub Actions via Settings > Secrets)
# ═══════════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "VOTRE_TOKEN_BOT")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "VOTRE_CHAT_ID")
CHECK_INTERVAL   = int(os.getenv("CHECK_INTERVAL", "300"))  # secondes (300 = 5 min)

# ═══════════════════════════════════════════════════════════════════════════════
#  BOUTIQUES À SURVEILLER
#  ⚠️  Vérifiez que les URLs ci-dessous correspondent bien aux pages produit
#      chez vous — elles peuvent changer. Copiez-les depuis votre navigateur.
# ═══════════════════════════════════════════════════════════════════════════════

STORES = [
    {
        "name": "Boulanger",
        "url": "https://www.boulanger.com/ref/1216685",
        "in_stock":     ["ajouter au panier", "en stock"],
        "out_of_stock": ["rupture de stock", "momentanément indisponible"],
    },
    {
        "name": "Darty",
        "url": "https://www.darty.com/nav/achat/gros_electromenager/chauffage_climatisation/climatiseur/midea_mmcs-12hrn8-qrd0.html",
        "in_stock":     ["ajouter au panier", "commander"],
        "out_of_stock": ["rupture", "indisponible"],
    },
    {
        "name": "Amazon Midea Portasplit",
        "url": "https://www.amazon.fr/dp/B0CY2YW8BT/",
        "in_stock":     ["ajouter au panier", "add to cart"],
        "out_of_stock": [],
    },
    {
        "name": "Amazon Bosch Cool 2000",
        "url": "https://www.amazon.fr/dp/B0BXT6XHLC/",
        "in_stock":     ["ajouter au panier", "add to cart"],
        "out_of_stock": [],
    },
    {
        "name": "Amazon OLIMPIA SPLENDID",
        "url": "https://www.amazon.fr/dp/B083X59QZF/",
        "in_stock":     ["ajouter au panier", "add to cart"],
        "out_of_stock": [],
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
#  HEADERS — imitent un navigateur Chrome normal
# ═══════════════════════════════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.fr/",
    "DNT": "1",
    "Cache-Control": "no-cache",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  FONCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def send_telegram(message: str) -> None:
    """Envoie un message via l'API Telegram Bot."""
    if TELEGRAM_TOKEN == "VOTRE_TOKEN_BOT":
        print(f"  📵  Telegram non configuré — message : {message[:80]}…")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        resp.raise_for_status()
        print("  📤  Telegram envoyé ✓")
    except Exception as e:
        print(f"  ⚠️   Erreur Telegram : {e}")


def check_store(store: dict) -> tuple:
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(store["url"], timeout=15, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text

        # Détection CAPTCHA
        if "captcha" in html.lower() or "enter the characters" in html.lower():
            return None, "⚠️ CAPTCHA détecté"

        # Amazon : cibler uniquement le buy box du produit principal
        if "amazon.fr" in store["url"]:
            soup = BeautifulSoup(html, "html.parser")
        
            if "captcha" in html.lower() or "enter the characters" in html.lower():
                return None, "⚠️ CAPTCHA détecté"
        
            # 1. Bouton achat en priorité absolue — s'il existe, c'est en stock
            add_to_cart = (
                soup.find("input", {"id": "add-to-cart-button"}) or
                soup.find("input", {"name": "submit.add-to-cart"}) or
                soup.find("input", {"id": "buy-now-button"}) or
                soup.find("button", {"id": "buy-now-button"})
            )
            if add_to_cart:
                return True, "bouton 'Ajouter au panier' trouvé ✓"
        
            # 2. #availability seulement si pas de bouton trouvé
            availability = soup.find("div", {"id": "availability"})
            if availability:
                text = availability.get_text().lower().strip()
                if "en stock" in text:
                    return True, f"disponibilité : '{text[:60]}'"
                if "indisponible" in text or "rupture" in text:
                    return False, f"disponibilité : '{text[:60]}'"
        
            # 3. Ni bouton ni #availability lisibles → indéterminé
            return None, "statut indéterminé (page différente servie au script)"

        # Autres stores : logique texte classique
        html_lower = html.lower()
        for phrase in store["out_of_stock"]:
            if phrase.lower() in html_lower:
                return False, f"'{phrase}' trouvé"
        for phrase in store["in_stock"]:
            if phrase.lower() in html_lower:
                return True, f"'{phrase}' trouvé"

        return None, "statut non trouvé"

    except requests.exceptions.Timeout:
        return None, "timeout"
    except requests.exceptions.RequestException as e:
        return None, f"erreur : {e}"


def run_cycle() -> list:
    """
    Effectue un cycle complet de vérification sur toutes les boutiques.
    Retourne la liste des boutiques où le produit est EN STOCK.
    """
    available = []
    for store in STORES:
        status, reason = check_store(store)
        icon = {True: "✅", False: "❌", None: "❓"}.get(status, "❓")
        print(f"  {icon}  {store['name']:<14} {reason}")
        if status is True:
            available.append(store)
    return available


def run_once() -> None:
    """Un seul cycle — idéal pour cron ou GitHub Actions."""
    now = datetime.now().strftime("%d/%m à %H:%M")
    print(f"[{now}] Vérification en cours…")
    available = run_cycle()

    if available:
        for s in available:
            send_telegram(
                f"🚨 <b>{s['name']} EN STOCK !</b>  [{now}]\n\n"
                f'👉 <a href="{s["url"]}">Acheter maintenant</a>\n\n'
                "⚡ <b>Dépêchez-vous, ça part vite !</b>"
            )
    else:
        print(f"  Rien en stock. Prochaine vérif dans {CHECK_INTERVAL // 60} min.\n")


def run_loop() -> None:
    """Boucle infinie pour un fonctionnement en local continu."""
    print("🚀 PortaSplit Monitor démarré")
    print(f"🔄 Vérification toutes les {CHECK_INTERVAL // 60} min | {len(STORES)} boutiques\n")

    send_telegram(
        "🤖 <b>Moniteur PortaSplit démarré</b>\n"
        f"Vérification toutes les {CHECK_INTERVAL // 60} min "
        f"sur {len(STORES)} boutiques.\n"
        "Je vous préviendrai dès qu'il est disponible quelque part."
    )

    while True:
        run_once()
        time.sleep(CHECK_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════════
#  ALTERNATIVE PLAYWRIGHT (si le HTML simple ne suffit pas)
#  Décommentez ce bloc et remplacez check_store() si les résultats sont ❓
#
# from playwright.sync_api import sync_playwright
#
# def check_store_playwright(store: dict) -> tuple:
#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         page = browser.new_page(extra_http_headers={"Accept-Language": "fr-FR"})
#         page.goto(store["url"], wait_until="networkidle", timeout=30000)
#         html = page.content().lower()
#         browser.close()
#         for phrase in store["out_of_stock"]:
#             if phrase.lower() in html:
#                 return False, f"'{phrase}' trouvé (Playwright)"
#         for phrase in store["in_stock"]:
#             if phrase.lower() in html:
#                 return True, f"'{phrase}' trouvé (Playwright)"
#         return None, "statut non trouvé même avec Playwright"
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "--test" in sys.argv:
        print("📤 Envoi d'un message de test Telegram...")
        send_telegram(
            "🧪 <b>TEST — Moniteur PortaSplit</b>\n\n"
            "Si vous lisez ce message, la configuration Telegram fonctionne ✅\n\n"
            "🏪 <b>Amazon</b>\n"
            f'👉 <a href="https://www.amazon.fr/dp/B0CY2YW8BT/">Acheter sur Amazon</a>\n\n'
            "⚡ Dépêchez-vous, ça part vite !"
        )
        print("Vérifiez votre Telegram !")
    elif "--once" in sys.argv:
        run_once()
    else:
        run_loop()
