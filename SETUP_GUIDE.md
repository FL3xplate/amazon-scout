# Amazon Scout — Setup & Deployment Guide

## What This Does
- Scrapes Amazon's outdoor/camping bestseller lists every 12 hours
- Scores each product 0–100 for FBA profit potential
- Estimates your real net margin after all Amazon fees
- Texts you the top opportunities automatically via SMS

---

## Step 1 — Get a Free Twilio Account (SMS)
1. Go to https://www.twilio.com/try-twilio and sign up free
2. They give you ~$15 in trial credits (enough for hundreds of texts)
3. In your Twilio dashboard, grab:
   - Account SID
   - Auth Token
   - Your Twilio phone number (they assign you one free)
4. You'll also need your own real cell phone number to receive texts

---

## Step 2 — Set Your Credentials
Open `scout.py` and fill in these 4 lines near the top, OR set them
as environment variables (recommended for cloud deployment):

```python
TWILIO_ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_AUTH_TOKEN  = "your_auth_token_here"
TWILIO_FROM_NUMBER = "+15551234567"   # your Twilio number
YOUR_PHONE_NUMBER  = "+15559876543"   # your real cell
```

---

## Step 3 — Run Locally (Optional Test)
```bash
pip install -r requirements.txt
python scout.py
```

It will scrape immediately, print results, and text you. Check `results.csv`
for the full scored product list.

---

## Step 4 — Deploy to Railway (Free Cloud, Runs 24/7)

### One-time setup:
1. Go to https://railway.app and sign up with GitHub (free)
2. Click "New Project" → "Deploy from GitHub repo"
   - Push this folder to a GitHub repo first (see below)
3. In Railway project settings → Variables, add:
   ```
   TWILIO_ACCOUNT_SID   = ACxxx...
   TWILIO_AUTH_TOKEN    = your_token
   TWILIO_FROM_NUMBER   = +15551234567
   YOUR_PHONE_NUMBER    = +15559876543
   ```
4. Railway auto-detects `railway.toml` and starts the script
5. Done — it runs every 12 hours and texts you automatically

### Push to GitHub:
```bash
git init
git add .
git commit -m "Initial scout setup"
git remote add origin https://github.com/YOURUSERNAME/amazon-scout.git
git push -u origin main
```

---

## Customizing the Scout

### Change how often it runs
In `scout.py`, find this line and change the interval:
```python
schedule.every(12).hours.do(run_scout)
# Other options:
# schedule.every(6).hours.do(run_scout)
# schedule.every().day.at("08:00").do(run_scout)
```

### Change the price range
```python
MIN_PRICE = 15.00   # ignore products cheaper than this
MAX_PRICE = 60.00   # ignore products more expensive than this
```

### Add more Amazon categories
Find the `CATEGORIES` dict and add any Amazon bestseller URL:
```python
CATEGORIES = {
    "Camping & Hiking": "https://www.amazon.com/Best-Sellers-.../zgbs/...",
    "Pet Supplies":     "https://www.amazon.com/Best-Sellers-Pet-Supplies/zgbs/pet-supplies",
    "Kitchen":          "https://www.amazon.com/Best-Sellers-Kitchen/zgbs/kitchen",
}
```

### Adjust the score threshold (how picky to be)
```python
MIN_SCORE = 60   # lower = more alerts, higher = only the best
```

---

## How the Scoring Works (0–100)

| Factor | Points | Why |
|---|---|---|
| Price $20–$40 sweet spot | 30 | Best margin/competition balance |
| Low review count (<200) | 30 | Easier to compete as new seller |
| High sales rank (top 10) | 20 | Proven demand |
| Rating 4.0–4.5 | 20 | Room to beat existing products |

**Score 80+** = Strong opportunity, alert immediately
**Score 60–79** = Worth watching
**Score <60** = Too competitive or wrong price point

---

## Reading results.csv
Every run appends to this file. Columns:
- `score` — opportunity score (higher = better)
- `net_profit` — estimated $ profit per unit after all fees
- `margin_pct` — estimated % margin
- `reviews` — current review count on the listing
- `rank` — position in bestseller list

---

## Important Notes
- Amazon occasionally blocks scrapers. If you get 0 results, wait an hour and retry.
- This is for research only. Always verify manually on Amazon before buying inventory.
- Margins are ESTIMATES. Use the Amazon FBA Revenue Calculator for exact numbers:
  https://sellercentral.amazon.com/revcalc/ref=xx_revCalc_dnav_xx
