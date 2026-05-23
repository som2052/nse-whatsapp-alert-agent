"""
Alert Tracking Database
========================
SQLite database to track which announcements have already been sent.
Prevents duplicate WhatsApp alerts for the same announcement.
"""

import sqlite3
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Database file location (same directory as the script)
DB_PATH = Path(__file__).parent / "alerts.db"


class AlertDB:
    """
    Tracks sent alerts using SQLite to prevent duplicates.

    Each announcement is identified by a unique hash of:
    symbol + subject + date
    """

    def __init__(self, db_path: str = None):
        """
        Initialize the database.

        Args:
            db_path: Path to SQLite database file. Defaults to alerts.db in project root.
        """
        self.db_path = db_path or str(DB_PATH)
        self._init_db()

    def _init_db(self):
        """Create the database tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sent_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_hash TEXT UNIQUE NOT NULL,
                    symbol TEXT NOT NULL,
                    subject TEXT,
                    announcement_date TEXT,
                    sent_at TEXT NOT NULL,
                    whatsapp_status TEXT DEFAULT 'sent'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_hash ON sent_alerts(alert_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol ON sent_alerts(symbol)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
        logger.info(f"✅ Database initialized at {self.db_path}")

    @staticmethod
    def _generate_hash(announcement: dict) -> str:
        """
        Generate a unique hash for an announcement.

        Uses symbol + subject + date to create a fingerprint.
        """
        symbol = announcement.get("symbol", "")
        subject = announcement.get("desc", announcement.get("subject", ""))
        date = announcement.get("an_dt", announcement.get("date", ""))
        # Also include seq_id or any unique NSE identifier if available
        seq_id = str(announcement.get("seq_id", announcement.get("id", "")))

        raw = f"{symbol}|{subject}|{date}|{seq_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def is_already_sent(self, announcement: dict) -> bool:
        """
        Check if an alert for this announcement was already sent.

        Args:
            announcement: NSE announcement dict

        Returns:
            True if already sent, False otherwise
        """
        alert_hash = self._generate_hash(announcement)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM sent_alerts WHERE alert_hash = ?",
                (alert_hash,),
            )
            exists = cursor.fetchone() is not None

        if exists:
            logger.debug(f"⏭️ Already sent: {announcement.get('symbol', '?')} - {announcement.get('desc', '?')[:50]}")
        return exists

    def mark_as_sent(self, announcement: dict, status: str = "sent"):
        """
        Record that an alert was sent for this announcement.

        Args:
            announcement: NSE announcement dict
            status: Delivery status
        """
        alert_hash = self._generate_hash(announcement)
        symbol = announcement.get("symbol", "")
        subject = announcement.get("desc", announcement.get("subject", ""))
        ann_date = announcement.get("an_dt", announcement.get("date", ""))
        sent_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sent_alerts (alert_hash, symbol, subject, announcement_date, sent_at, whatsapp_status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alert_hash, symbol, subject, ann_date, sent_at, status),
            )
            conn.commit()
        logger.info(f"📝 Recorded alert: {symbol} - {subject[:50]}")

    def get_sent_count(self, symbol: Optional[str] = None) -> int:
        """Get total number of sent alerts, optionally filtered by symbol."""
        with sqlite3.connect(self.db_path) as conn:
            if symbol:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM sent_alerts WHERE symbol = ?",
                    (symbol,),
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM sent_alerts")
            return cursor.fetchone()[0]

    def get_recent_alerts(self, limit: int = 20) -> list:
        """Get the most recently sent alerts."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT symbol, subject, announcement_date, sent_at FROM sent_alerts ORDER BY sent_at DESC LIMIT ?",
                (limit,),
            )
            return [
                {"symbol": row[0], "subject": row[1], "date": row[2], "sent_at": row[3]}
                for row in cursor.fetchall()
            ]

    def set_state(self, key: str, value: str):
        """Store a key-value pair for agent state tracking."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_state (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, datetime.now().isoformat()),
            )
            conn.commit()

    def get_state(self, key: str) -> Optional[str]:
        """Retrieve a stored state value."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM agent_state WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def cleanup_old_alerts(self, days: int = 90):
        """Remove alerts older than specified days to keep DB lean."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM sent_alerts
                WHERE sent_at < datetime('now', ? || ' days')
                """,
                (f"-{days}",),
            )
            conn.commit()
        logger.info(f"🧹 Cleaned up alerts older than {days} days")


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    db = AlertDB("/tmp/test_alerts.db")

    test = {"symbol": "TCS", "desc": "Test announcement", "an_dt": "23-05-2026"}

    print(f"Already sent? {db.is_already_sent(test)}")
    db.mark_as_sent(test)
    print(f"Already sent? {db.is_already_sent(test)}")
    print(f"Total sent: {db.get_sent_count()}")
    print(f"Recent: {db.get_recent_alerts()}")
