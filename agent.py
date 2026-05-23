#!/usr/bin/env python3
"""
NSE WhatsApp Alert Agent
=========================
Main orchestrator that monitors NSE corporate filings for your watchlist
companies and sends real-time WhatsApp alerts via Twilio.

Usage:
    python agent.py                  # Run with default settings
    python agent.py --test           # Send a test WhatsApp message
    python agent.py --once           # Run one check cycle and exit
    python agent.py --status         # Show agent status and recent alerts

Architecture:
    ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
    │  NSE India   │────▶│  Alert Agent  │────▶│  WhatsApp   │
    │  (Scraper)   │     │ (Orchestrator)│     │  (Twilio)   │
    └─────────────┘     └──────┬───────┘     └─────────────┘
                               │
                    ┌──────────┴───────────┐
                    │                      │
               ┌────▼─────┐        ┌──────▼──────┐
               │ SQLite DB │        │ Summarizer  │
               │ (Dedup)   │        │ (AI/Rules)  │
               └──────────┘        └─────────────┘
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load .env EARLY so SSL cert env vars are set before any imports that make HTTP calls
load_dotenv(Path(__file__).parent / ".env", override=True)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from nse_scraper import NSEScraper
from whatsapp_sender import WhatsAppSender
from summarizer import AnnouncementSummarizer
from db import AlertDB

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

# .env already loaded at top of file for SSL cert vars

# Logging setup
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "agent.log", mode="a"),
    ],
)
logger = logging.getLogger("nse-alert-agent")

# Polling interval
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))

# ──────────────────────────────────────────────
# Watchlist Loader
# ──────────────────────────────────────────────

def load_watchlist() -> list:
    """Load company watchlist from companies.json."""
    watchlist_path = Path(__file__).parent / "companies.json"
    if not watchlist_path.exists():
        logger.error(f"❌ companies.json not found at {watchlist_path}")
        sys.exit(1)

    with open(watchlist_path) as f:
        data = json.load(f)

    companies = data.get("watchlist", [])
    if not companies:
        logger.error("❌ No companies in watchlist! Edit companies.json to add your companies.")
        sys.exit(1)

    symbols = [c["symbol"] for c in companies]
    logger.info(f"📊 Watchlist loaded: {len(symbols)} companies — {', '.join(symbols)}")
    return companies


# ──────────────────────────────────────────────
# Main Agent Class
# ──────────────────────────────────────────────

class NSEAlertAgent:
    """
    The main agent that orchestrates:
    1. Polling NSE for new announcements
    2. Filtering by watchlist
    3. Deduplicating via SQLite
    4. Summarizing announcements
    5. Sending WhatsApp alerts
    """

    def __init__(self):
        self.running = False
        self.cycle_count = 0

        # Load watchlist
        self.companies = load_watchlist()
        self.symbols = [c["symbol"] for c in self.companies]

        # Initialize components
        self.scraper = NSEScraper()
        self.db = AlertDB()
        self.summarizer = AnnouncementSummarizer(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )

        # Initialize WhatsApp sender
        twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
        twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
        twilio_from = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
        whatsapp_to = os.getenv("WHATSAPP_TO", "whatsapp:+918951308984")

        if not twilio_sid or not twilio_token:
            logger.error("❌ TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env")
            sys.exit(1)

        self.whatsapp = WhatsAppSender(
            account_sid=twilio_sid,
            auth_token=twilio_token,
            from_number=twilio_from,
            to_number=whatsapp_to,
        )

        logger.info("✅ NSE Alert Agent initialized successfully")

    def check_and_alert(self) -> int:
        """
        Run one check cycle:
        1. Fetch announcements for each watchlist company
        2. Filter out already-sent alerts
        3. Summarize and send new alerts via WhatsApp

        Returns:
            Number of new alerts sent
        """
        self.cycle_count += 1
        logger.info(f"🔄 === Check cycle #{self.cycle_count} started at {datetime.now().strftime('%H:%M:%S')} ===")

        new_alerts_sent = 0
        all_new_announcements = []

        # Strategy: Fetch per-symbol for targeted results
        for company in self.companies:
            symbol = company["symbol"]
            try:
                announcements = self.scraper.fetch_announcements_by_symbol(symbol)

                for ann in announcements:
                    if not self.db.is_already_sent(ann):
                        all_new_announcements.append(ann)

                # Small delay between companies to be respectful to NSE
                time.sleep(1)

            except Exception as e:
                logger.error(f"❌ Error fetching {symbol}: {e}")
                continue

        if not all_new_announcements:
            logger.info(f"📭 No new announcements in cycle #{self.cycle_count}")
            return 0

        # Sort by priority (high priority first)
        all_new_announcements.sort(key=lambda a: self.summarizer.get_priority(a))

        logger.info(f"🆕 {len(all_new_announcements)} new announcements to send!")

        for ann in all_new_announcements:
            try:
                # Generate summary
                summary = self.summarizer.summarize(ann)

                # Send WhatsApp alert
                success = self.whatsapp.send_alert(ann, summary)

                if success:
                    self.db.mark_as_sent(ann, status="sent")
                    new_alerts_sent += 1
                    logger.info(
                        f"✅ Alert sent: {ann.get('symbol')} - "
                        f"{ann.get('desc', 'N/A')[:60]}"
                    )
                else:
                    self.db.mark_as_sent(ann, status="failed")
                    logger.warning(f"⚠️ Failed to send alert for {ann.get('symbol')}")

                # Rate limit WhatsApp sends (1 per second)
                time.sleep(1.5)

            except Exception as e:
                logger.error(f"❌ Error processing announcement: {e}")
                continue

        logger.info(f"📊 Cycle #{self.cycle_count} complete: {new_alerts_sent} alerts sent")
        return new_alerts_sent

    def run_forever(self):
        """
        Run the agent in continuous polling mode.
        Press Ctrl+C to stop gracefully.
        """
        self.running = True

        # Handle graceful shutdown
        def signal_handler(signum, frame):
            logger.info("\n🛑 Shutdown signal received. Stopping gracefully...")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Send startup notification
        logger.info("🚀 Starting NSE Alert Agent in continuous mode")
        logger.info(f"⏱️ Poll interval: {POLL_INTERVAL} seconds")
        logger.info(f"📊 Monitoring: {', '.join(self.symbols)}")

        try:
            self.whatsapp.send_startup_notification(self.symbols)
        except Exception as e:
            logger.warning(f"⚠️ Could not send startup notification: {e}")

        # Main loop
        while self.running:
            try:
                self.check_and_alert()
            except Exception as e:
                logger.error(f"❌ Unexpected error in check cycle: {e}", exc_info=True)
                # Notify via WhatsApp about errors (but not every cycle)
                if self.cycle_count % 10 == 0:
                    try:
                        self.whatsapp.send_error_notification(f"Agent error: {str(e)[:200]}")
                    except Exception:
                        pass

            # Wait for next cycle
            if self.running:
                logger.info(f"⏳ Next check in {POLL_INTERVAL} seconds...")
                # Sleep in small increments so we can respond to signals quickly
                for _ in range(POLL_INTERVAL):
                    if not self.running:
                        break
                    time.sleep(1)

        logger.info("👋 NSE Alert Agent stopped. Total cycles: {self.cycle_count}")

    def show_status(self):
        """Display current agent status and recent alerts."""
        total_sent = self.db.get_sent_count()
        recent = self.db.get_recent_alerts(10)

        print("\n" + "=" * 60)
        print("  📊 NSE WhatsApp Alert Agent — Status")
        print("=" * 60)
        print(f"  Watchlist:     {', '.join(self.symbols)}")
        print(f"  Total alerts:  {total_sent}")
        print(f"  Poll interval: {POLL_INTERVAL}s")
        print(f"  AI summary:    {'✅ Enabled' if self.summarizer.ai_enabled else '❌ Disabled'}")
        print(f"  Database:      {self.db.db_path}")

        if recent:
            print(f"\n  📋 Recent Alerts (last 10):")
            print(f"  {'─' * 56}")
            for alert in recent:
                subject_short = (alert['subject'] or 'N/A')[:45]
                print(f"  {alert['symbol']:>10} │ {alert['date'] or 'N/A':>12} │ {subject_short}")

        print("=" * 60 + "\n")


# ──────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🔔 NSE WhatsApp Alert Agent — Real-time corporate filing alerts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent.py               # Start continuous monitoring
  python agent.py --test        # Send a test message to verify WhatsApp setup
  python agent.py --once        # Run one check cycle and exit
  python agent.py --status      # Show agent status and recent alerts
        """,
    )
    parser.add_argument("--test", action="store_true", help="Send a test WhatsApp message and exit")
    parser.add_argument("--once", action="store_true", help="Run one check cycle and exit")
    parser.add_argument("--status", action="store_true", help="Show agent status and recent alerts")
    args = parser.parse_args()

    print("""
    ╔══════════════════════════════════════════════╗
    ║  🔔 NSE WhatsApp Alert Agent                 ║
    ║  Real-time Corporate Filing Alerts for SMEs  ║
    ╚══════════════════════════════════════════════╝
    """)

    agent = NSEAlertAgent()

    if args.test:
        logger.info("🧪 Sending test message...")
        success = agent.whatsapp.send_message(
            "🧪 *Test Message*\n\n"
            "NSE WhatsApp Alert Agent is configured correctly!\n\n"
            f"📊 Monitoring: {', '.join(agent.symbols)}\n"
            f"⏱️ Poll interval: {POLL_INTERVAL}s\n"
            f"🤖 AI Summary: {'Enabled' if agent.summarizer.ai_enabled else 'Disabled'}\n\n"
            "You'll receive alerts when new corporate filings are posted. 🚀"
        )
        if success:
            print("✅ Test message sent! Check your WhatsApp.")
        else:
            print("❌ Failed to send test message. Check your Twilio credentials.")
        return

    if args.status:
        agent.show_status()
        return

    if args.once:
        count = agent.check_and_alert()
        print(f"\n✅ Check complete. {count} new alerts sent.")
        return

    # Default: run forever
    agent.run_forever()


if __name__ == "__main__":
    main()
