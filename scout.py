"""
Amazon Product Scout - Automated Research & Notification System
===============================================================
Scrapes Amazon bestseller categories, scores products by profit potential,
saves results to Google Sheets, and sends push notifications via ntfy.sh
"""

import requests
from bs4 import BeautifulSoup
import time
import json
import os
import schedule
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ─── LOGGING ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── CONFIG ─────────────────────────────────────────────────────────────────
NTFY_TOPIC        = os.getenv("NTFY_TOPIC", "amazingscout_kt_8472")
SPREADSHEET_ID    = os.getenv("SPREADSHEET_ID", "18VBpthZnwcVGiJFWrN8IMXdxEgugjXdjVfXUNszVBFI")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

# Amazon bestseller category URLs to monitor
CATEGORIES = {
    "Camping & Hiking":   "https://www.amazon.com/Best-Sellers-Sports-Outdoors-Camping-Hiking/zgbs/sporting-goods/3400371",
    "Outdoor Recreation": "https://www.amazon.com/Best-Sellers-Outdoor-Recreation/zgbs/sporting-goods/706814011",
    "Hiking Clothing":    "https://www.amazon.com/Best-Sellers-Sports-Outdoors-Hiking-Clothing/zgbs/sporting-goods/2371054011",
}

MIN_PRICE   = 15.00
MAX_PRICE   = 60.00
MIN_SCORE   = 60
ALERT_TOP_N = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── GOOGLE SHEETS ───────────────────────────────────────────────────────────
def get_sheet():
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        return sheet
    except Exception as e:
        log.error(f"Google Sheets connection failed: {e}")
        return None


def ensure_headers(sheet):
    try:
        if not sheet.get_all_values():
            sheet.insert_row([
                "Date", "Rank", "Title", "Price", "Rating", "Reviews",
                "Score", "Net Profit", "Margin %", "Category", "URL"
            ], 1)
    except:
        pass


def save_to_sheets(products: list):
    sheet = get_sheet()
    if not sheet:
        log.warning("Skipping Google Sheets save.")
        return
    ensure_headers(sheet)
    rows = [[
        p.get("scraped",""), p.get("rank",""), p.get("title",""),
        p.get("price",""), p.get("rating",""), p.get("reviews",""),
        p.get("score",""), p.get("net_profit",""), p.get("margin_pct",""),
        p.get("category",""), p.get("url","")
    ] for p in products]
    sheet.append_rows(rows)
    log.info(f"Saved {len(rows)} rows to Google Sheets.")


# ─── SCRAPER ─────────────────────────────────────────────────────────────────
def scrape_category(name: str, url: str) -> list:
    log.info(f"Scraping: {name}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.warning(f"  Failed to fetch {name}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    products = []
    items = soup.select("div.zg-grid-general-faceout") or \
            soup.select("li.zg-item-immersion")

    for rank, item in enumerate(items[:50], start=1):
        try:
            title_el = (
                item.select_one("div._cDEzb_p13n-sc-css-line-clamp-3_g3dy1") or
                item.select_one("span.zg-text-center-align") or
                item.select_one("div.p13n-sc-truncate")
            )
            title = title_el.get_text(strip=True) if title_el else "Unknown"
            price_el = (
                item.select_one("span.p13n-sc-price") or
                item.select_one("span._cDEzb_p13n-sc-price_3mJ9Z")
            )
            price = parse_price(price_el.get_text(strip=True) if price_el else "")
            rating_el  = item.select_one("span.a-icon-alt")
            reviews_el = item.select_one("span.a-size-small")
            rating  = float(rating_el.get_text().split()[0]) if rating_el else 0.0
            reviews = parse_reviews(reviews_el.get_text(strip=True) if reviews_el else "0")
            link_el = item.select_one("a.a-link-normal")
            link = "https://www.amazon.com" + link_el["href"] if link_el else ""
            products.append({
                "rank": rank, "title": title[:120], "price": price,
                "rating": rating, "reviews": reviews, "category": name,
                "url": link, "scraped": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
        except Exception as e:
            log.debug(f"  Parse error on item {rank}: {e}")
    log.info(f"  Found {len(products)} products")
    time.sleep(3)
    return products


def parse_price(text: str) -> float:
    try:
        return float(text.replace("$","").replace(",","").strip())
    except:
        return 0.0


def parse_reviews(text: str) -> int:
    try:
        text = text.replace(",","").replace(" ","")
        if "K" in text.upper():
            return int(float(text.upper().replace("K","")) * 1000)
        return int("".join(filter(str.isdigit, text)) or 0)
    except:
        return 0


# ─── SCORER ──────────────────────────────────────────────────────────────────
def score_product(p: dict) -> int:
    score = 0
    if MIN_PRICE <= p["price"] <= MAX_PRICE:
        score += 30 if 20 <= p["price"] <= 40 else 15
    r = p["reviews"]
    if r == 0:       score += 5
    elif r < 200:    score += 30
    elif r < 500:    score += 22
    elif r < 1000:   score += 14
    elif r < 3000:   score += 7
    rank = p["rank"]
    if rank <= 10:   score += 20
    elif rank <= 25: score += 14
    elif rank <= 50: score += 8
    rat = p["rating"]
    if 4.0 <= rat <= 4.5:  score += 20
    elif rat > 4.5:        score += 12
    elif rat >= 3.5:       score += 8
    return min(score, 100)


def estimate_margin(price: float) -> dict:
    referral = round(price * 0.15, 2)
    fba      = 4.50 if price < 20 else 5.50 if price < 40 else 7.00
    cogs     = round(price * 0.08, 2)
    ppc      = round(price * 0.12, 2)
    net      = round(price - referral - fba - cogs - ppc, 2)
    margin   = round((net / price) * 100, 1) if price > 0 else 0
    return {"net_profit": net, "margin_pct": margin}


# ─── NOTIFICATIONS ───────────────────────────────────────────────────────────
def send_notification(message: str):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": "Amazon Scout Alert"}
        )
        log.info("Notification sent successfully.")
    except Exception as e:
        log.error(f"Notification failed: {e}")


def build_alert(top_products: list) -> str:
    lines = [f"Amazon Scout — {datetime.now().strftime('%b %d %I:%M %p')}\n"]
    for i, p in enumerate(top_products, 1):
        m = estimate_margin(p["price"])
        lines.append(
            f"{i}. {p['title'][:55]}...\n"
            f"   ${p['price']} | Score: {p['score']}/100\n"
            f"   Net ~${m['net_profit']} ({m['margin_pct']}% margin)\n"
            f"   {p['rating']} stars | {p['reviews']} reviews | Rank #{p['rank']}\n"
        )
    lines.append("Check Google Sheets for full data.")
    return "\n".join(lines)


# ─── MAIN JOB ────────────────────────────────────────────────────────────────
def run_scout():
    log.info("=" * 50)
    log.info("Scout run started")
    all_products = []
    for name, url in CATEGORIES.items():
        all_products.extend(scrape_category(name, url))

    filtered = [p for p in all_products if MIN_PRICE <= p["price"] <= MAX_PRICE]
    for p in filtered:
        p["score"] = score_product(p)
        m = estimate_margin(p["price"])
        p["net_profit"] = m["net_profit"]
        p["margin_pct"] = m["margin_pct"]

    filtered.sort(key=lambda x: x["score"], reverse=True)
    save_to_sheets(filtered)

    top = [p for p in filtered if p["score"] >= MIN_SCORE][:ALERT_TOP_N]
    if top:
        send_notification(build_alert(top))
    else:
        log.info("No products met the score threshold.")

    log.info(f"Run complete. Total scored: {len(filtered)}")


# ─── SCHEDULER ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Amazon Scout starting up...")
    run_scout()
    schedule.every(12).hours.do(run_scout)
    log.info("Scheduler running.")
    while True:
        schedule.run_pending()
        time.sleep(60)

