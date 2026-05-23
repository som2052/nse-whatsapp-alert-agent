#!/usr/bin/env python3
"""
NSE Alert — Single Check Runner (for GitHub Actions / Cron)
============================================================
Runs one check cycle and exits. Designed for scheduled execution
via GitHub Actions cron, system cron, or any scheduler.

Unlike agent.py which loops forever, this script:
1. Checks NSE for all watchlist companies
2. Sends WhatsApp alerts for new filings
3. Updates the SQLite DB
4. Exits with code 0 (success) or 1 (error)
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

# Load env vars (from .env file locally, from GitHub Secrets in CI)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass  # dotenv not needed in GitHub Actions (secrets are env vars)

from nse_scraper import NSEScraper
from whatsapp_sender import WhatsAppSender
from summarizer import AnnouncementSummarizer
from db import AlertDB

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("nse-alert-runner")


def load_watchlist() -> list:
    """Load company watchlist from companies.json."""
    watchlist_path = Path(__file__).parent / "companies.json"
    with open(watchlist_path) as f:
        data = json.load(f)
    return data.get("watchlist", [])


def main():
    logger.info("🔔 NSE Alert — Single check starting")

    # Load watchlist
    companies = load_watchlist()
    symbols = [c["symbol"] for c in companies]
    logger.info(f"📊 Watchlist: {len(symbols)} companies")

    # Validate Twilio credentials
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_from = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    whatsapp_to = os.getenv("WHATSAPP_TO", "whatsapp:+918951308984")

    if not twilio_sid or not twilio_token:
        logger.error("❌ TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required")
        sys.exit(1)

    # Initialize components
    scraper = NSEScraper()
    db = AlertDB()
    summarizer = AnnouncementSummarizer()
    whatsapp = WhatsAppSender(
        account_sid=twilio_sid,
        auth_token=twilio_token,
        from_number=twilio_from,
        to_number=whatsapp_to,
    )

    # Check each company
    new_alerts_sent = 0
    all_new = []

    for company in companies:
        symbol = company["symbol"]
        try:
            announcements = scraper.fetch_announcements_by_symbol(symbol)
            for ann in announcements:
                if not db.is_already_sent(ann):
                    all_new.append(ann)
            time.sleep(1)  # Rate limit
        except Exception as e:
            logger.error(f"❌ Error fetching {symbol}: {e}")
            continue

    if not all_new:
        logger.info(f"📭 No new announcements found at {datetime.now().strftime('%H:%M:%S IST')}")
        return

    # Sort by priority and send
    all_new.sort(key=lambda a: summarizer.get_priority(a))
    logger.info(f"🆕 {len(all_new)} new announcements to send!")

    for ann in all_new:
        try:
            summary = summarizer.summarize(ann)
            success = whatsapp.send_alert(ann, summary)

            if success:
                db.mark_as_sent(ann, status="sent")
                new_alerts_sent += 1
                logger.info(f"✅ Alert sent: {ann.get('symbol')} - {ann.get('desc', 'N/A')[:60]}")
            else:
                db.mark_as_sent(ann, status="failed")
                logger.warning(f"⚠️ Failed: {ann.get('symbol')}")

            time.sleep(1.5)  # Rate limit WhatsApp
        except Exception as e:
            logger.error(f"❌ Error processing: {e}")
            continue

    logger.info(f"✅ Done! {new_alerts_sent} alerts sent.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
