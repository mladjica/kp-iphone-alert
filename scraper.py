import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re

GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SEEN_ADS_FILE   = "seen_ads.json"

KEYWORDS = ["iphone 15", "iphone 16", "iphone 17"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "sr-RS,sr;q=0.9",
}


# ── Seen ads ──────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_ADS_FILE):
        with open(SEEN_ADS_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_ADS_FILE, "w") as f:
        json.dump(list(seen), f)


# ── Scraping KP ───────────────────────────────────────────
def scrape_kp(keyword):
    url = (
        "https://www.kupujemprodajem.com/pretraga"
        f"?keywords={keyword.replace(' ', '%20')}"
        "&currency=eur"
        "&condition=as-new"
        "&condition=used"
        "&period=3day"
        "&ignoreUserId=no"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"Greška pri dohvatu {keyword}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    ads = []

    # Pronađi sve linkove ka oglasima (/oglas/ u URL-u)
    seen_hrefs = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/oglas/" not in href:
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        # Izvuci ID oglasa iz URL-a
        m = re.search(r"/oglas/(\d+)", href)
        if not m:
            continue
        ad_id = m.group(1)

        # Naslov — tekst linka ili nearest heading
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 4:
            continue

        # Cena (ako postoji u roditeljskom elementu)
        parent = a.find_parent()
        price_el = parent.find(string=re.compile(r"\d+\s*(rsd|eur|€|din)", re.I)) if parent else None
        price = price_el.strip() if price_el else "—"

        full_link = "https://www.kupujemprodajem.com" + href

        ads.append({
            "id": ad_id,
            "title": title,
            "price": price,
            "link": full_link,
        })

    return ads


# ── AI filter (Groq) ──────────────────────────────────────
def is_phone(title):
    prompt = (
        "Oglas sa kupujemprodajem.com.\n"
        f"Naslov: {title}\n\n"
        "Da li se radi o iPhone TELEFONU (ne masci, futroli, kablu, punjacu, "
        "staklu za ekran, bateriji, ili drugoj opremi)?\n"
        "Odgovori SAMO rečju DA ili NE."
    )
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 5,
        "temperature": 0,
    }
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=body,
            timeout=10,
        )
        answer = r.json()["choices"][0]["message"]["content"].strip().upper()
        return answer.startswith("DA")
    except Exception as e:
        print(f"Groq greška: {e}")
        return False  # ne šalji ako nisi siguran


# ── Telegram ──────────────────────────────────────────────
def send_telegram(ad):
    text = (
        f"📱 <b>Novi iPhone oglas!</b>\n\n"
        f"<b>{ad['title']}</b>\n"
        f"💰 {ad['price']}\n\n"
        f"🔗 <a href='{ad['link']}'>Otvori oglas</a>"
    )
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=10,
    )


# ── Main ──────────────────────────────────────────────────
def main():
    seen = load_seen()
    new_count = 0

    for kw in KEYWORDS:
        print(f"Tražim: {kw}")
        ads = scrape_kp(kw)
        print(f"  Pronašao {len(ads)} oglasa")

        for ad in ads:
            if ad["id"] in seen:
                continue
            seen.add(ad["id"])

            print(f"  Nov oglas: {ad['title']}")
            if is_phone(ad["title"]):
                print(f"  ✅ AI potvrdio — šaljem na Telegram")
                send_telegram(ad)
                new_count += 1
            else:
                print(f"  ❌ AI rekao nije telefon — preskačem")

            time.sleep(0.5)  # ne spamuj API

        time.sleep(2)  # pauza između upita

    save_seen(seen)
    print(f"\nGotovo. Poslato notifikacija: {new_count}")


if __name__ == "__main__":
    main()
