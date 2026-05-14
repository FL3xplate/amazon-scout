"""
Amazon Product Scout - Automated Research & SMS Alert System
============================================================
Scrapes Amazon bestseller categories, scores products by profit potential,
and sends SMS alerts via Twilio when good opportunities are found.

SETUP:
1. pip install requests beautifulsoup4 twilio schedule
2. Fill in your credentials in config.py (or set as env vars)
3. Run: python scout.py
4. Deploy to Railway/Render for 24/7 cloud scheduling
"""

import requests
from bs4 import BeautifulSoup
import time
import json
import csv
import os
import schedule
import logging
from datetime import datetime
from twilio.rest import Client

# ─── LOGGING ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scout.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── CONFIG ─────────────────────────────────────────────────────────────────
# Set these as environment variables on Railway/Render, or fill in directly.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "YOUR_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN",  "YOUR_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "YOUR_TWILIO_NUMBER")
YOUR_PHONE_NUMBER  = os.getenv("YOUR_PHONE_NUMBER",  "YOUR_REAL_NUMBER")

# Amazon bestseller category URLs to monitor
CATEGORIES = {
    "Camping & Hiking":    "https://www.amazon.com/Best-Sellers-Sports-Outdoors-Camping-Hiking/zgbs/sporting-goods/3400371",
    "Outdoor Recreation":  "https://www.amazon.com/Best-Sellers-Outdoor-Recreation/zgbs/sporting-goods/706814011",
    "Hiking Clothing":     "https://www.amazon.com/Best-Sellers-Sports-Outdoors-Hiking-Clothing/zgbs/sporting-goods/2371054011",
}

# Profit scoring thresholds
MIN_PRICE        = 15.00   # ignore anything cheaper (margins too thin)
MAX_PRICE        = 60.00   # ignore anything too expensive (high capital required)
MIN_SCORE        = 60      # only alert on products scoring above this (0–100)
ALERT_TOP_N      = 3       # text you the top N products per run

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── SCRAPER ─────────────────────────────────────────────────────────────────
def scrape_category(name: str, url: str) -> list[dict]:
    """Fetch and parse one Amazon bestseller category page."""
    log.info(f"Scraping: {name}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.warning(f"  Failed to fetch {name}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    products = []

    # Amazon uses several grid item selectors; try both
    items = soup.select("div.zg-grid-general-faceout") or \
            soup.select("li.zg-item-immersion")

    for rank, item in enumerate(items[:50], start=1):
        try:
            # Title
            title_el = (
                item.select_one("div._cDEzb_p13n-sc-css-line-clamp-3_g3dy1") or
                item.select_one("span.zg-text-center-align") or
                item.select_one("div.p13n-sc-truncate")
            )
            title = title_el.get_text(strip=True) if title_el else "Unknown"

            # Price
            price_el = (
                item.select_one("span.p13n-sc-price") or
                item.select_one("span._cDEzb_p13n-sc-price_3mJ9Z")
            )
            price_text = price_el.get_text(strip=True) if price_el else ""
            price = parse_price(price_text)

            # Rating & review count
            rating_el  = item.select_one("span.a-icon-alt")
            reviews_el = item.select_one("span.a-size-small")
            rating  = float(rating_el.get_text().split()[0]) if rating_el else 0.0
            reviews = parse_reviews(reviews_el.get_text(strip=True) if reviews_el else "0")

            # Product URL
            link_el = item.select_one("a.a-link-normal")
            link = "https://www.amazon.com" + link_el["href"] if link_el else ""

            products.append({
                "rank":     rank,
                "title":    title[:120],
                "price":    price,
                "rating":   rating,
                "reviews":  reviews,
                "category": name,
                "url":      link,
                "scraped":  datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
        except Exception as e:
            log.debug(f"  Parse error on item {rank}: {e}")
            continue

    log.info(f"  Found {len(products)} products")
    time.sleep(3)  # be polite — avoid rate limiting
    return products


def parse_price(text: str) -> float:
    """Extract float from a price string like '$24.99'."""
    try:
        return float(text.replace("$", "").replace(",", "").strip())
    except:
        return 0.0


def parse_reviews(text: str) -> int:
    """Extract int from strings like '1,234' or '12K'."""
    try:
        text = text.replace(",", "").replace(" ", "")
        if "K" in text.upper():
            return int(float(text.upper().replace("K", "")) * 1000)
        return int("".join(filter(str.isdigit, text)) or 0)
    except:
        return 0


# ─── SCORER ──────────────────────────────────────────────────────────────────
def score_product(p: dict) -> int:
    """
    Score a product 0–100 for FBA profit potential.
    Higher = better opportunity for a new seller.

    Factors:
      + Price in the $15–$60 sweet spot       (up to 30 pts)
      + Low review count = easier to compete  (up to 30 pts)
      + High sales rank (top of bestsellers)  (up to 20 pts)
      + Good rating (customers like it)       (up to 20 pts)
    """
    score = 0

    # Price sweet spot
    if MIN_PRICE <= p["price"] <= MAX_PRICE:
        if 20 <= p["price"] <= 40:
            score += 30
        else:
            score += 15

    # Review count — fewer reviews = easier to enter
    r = p["reviews"]
    if r == 0:
        score += 5  # suspicious, might not have data
    elif r < 200:
        score += 30
    elif r < 500:
        score += 22
    elif r < 1000:
        score += 14
    elif r < 3000:
        score += 7
    else:
        score += 0  # heavily entrenched

    # Sales rank
    rank = p["rank"]
    if rank <= 10:
        score += 20
    elif rank <= 25:
        score += 14
    elif rank <= 50:
        score += 8

    # Rating quality
    rat = p["rating"]
    if 4.0 <= rat <= 4.5:
        score += 20   # sweet spot: room to beat them
    elif rat > 4.5:
        score += 12   # great product but hard to beat
    elif rat >= 3.5:
        score += 8    # ok product
    else:
        score += 0    # poor product, avoid

    return min(score, 100)


def estimate_margin(price: float) -> dict:
    """Rough FBA margin estimate at a given sale price."""
    referral_fee   = round(price * 0.15, 2)
    fba_fee        = 4.50 if price < 20 else 5.50 if price < 40 else 7.00
    est_cogs       = round(price * 0.08, 2)   # assume ~8% of sale price landed
    ppc_estimate   = round(price * 0.12, 2)   # ~12% on ads
    net            = round(price - referral_fee - fba_fee - est_cogs - ppc_estimate, 2)
    margin_pct     = round((net / price) * 100, 1) if price > 0 else 0

    return {
        "sale_price":   price,
        "referral_fee": referral_fee,
        "fba_fee":      fba_fee,
        "est_cogs":     est_cogs,
        "ppc_estimate": ppc_estimate,
        "net_profit":   net,
        "margin_pct":   margin_pct,
    }


# ─── STORAGE ─────────────────────────────────────────────────────────────────
def save_results(products: list[dict]):
    """Append scored products to a CSV log."""
    path = "results.csv"
    fieldnames = ["rank","title","price","rating","reviews","score",
                  "net_profit","margin_pct","category","url","scraped"]
    write_header = not os.path.exists(path)

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for p in products:
            writer.writerow({k: p.get(k, "") for k in fieldnames})

    log.info(f"Saved {len(products)} products to {path}")


# ─── SMS ALERTS ──────────────────────────────────────────────────────────────
def send_sms(message: str):
    """Send a push notification via ntfy.sh"""
    try:
        requests.post(
            "https://ntfy.sh/amazingscout_kt_8472",
            data=message.encode("utf-8"),
            headers={"Title": "Amazon Scout Alert"}
        )
        log.info("Notification sent successfully.")
    except Exception as e:
        log.error(f"Notification failed: {e}")



def build_alert(top_products: list[dict]) -> str:
    """Format the top products into a readable SMS."""
    lines = [f"🛒 Amazon Scout Report — {datetime.now().strftime('%b %d %I:%M %p')}\n"]
    for i, p in enumerate(top_products, 1):
        m = estimate_margin(p["price"])
        lines.append(
            f"{i}. {p['title'][:55]}...\n"
            f"   💰 ${p['price']} | Score: {p['score']}/100\n"
            f"   Net ~${m['net_profit']} ({m['margin_pct']}% margin)\n"
            f"   ⭐ {p['rating']} | {p['reviews']} reviews | Rank #{p['rank']}\n"
        )
    lines.append("Check results.csv for full data.")
    return "\n".join(lines)


# ─── MAIN JOB ────────────────────────────────────────────────────────────────
def run_scout():
    log.info("=" * 50)
    log.info("Scout run started")
    all_products = []

    for name, url in CATEGORIES.items():
        products = scrape_category(name, url)
        all_products.extend(products)

    # Filter by price range, then score
    filtered = [p for p in all_products if MIN_PRICE <= p["price"] <= MAX_PRICE]
    for p in filtered:
        p["score"] = score_product(p)
        m = estimate_margin(p["price"])
        p["net_profit"]  = m["net_profit"]
        p["margin_pct"]  = m["margin_pct"]

    # Sort by score descending
    filtered.sort(key=lambda x: x["score"], reverse=True)

    # Save everything
    save_results(filtered)

    # Alert on top products above threshold
    top = [p for p in filtered if p["score"] >= MIN_SCORE][:ALERT_TOP_N]
    if top:
        msg = build_alert(top)
        log.info(f"Sending alert for {len(top)} products")
        send_sms(msg)
    else:
        log.info("No products met the score threshold this run.")

    log.info(f"Run complete. Total scored: {len(filtered)}")
    return filtered


# ─── SCHEDULER ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Amazon Scout starting up...")

    # Run immediately on startup
    run_scout()

    # Then run every 12 hours
    schedule.every(12).hours.do(run_scout)

    log.info("Scheduler running. Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(60)
