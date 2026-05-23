"""
NSE Corporate Announcements Scraper
====================================
Fetches real-time corporate filings and announcements from NSE India.
Handles session management, cookie rotation, and anti-blocking headers.
"""

import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class NSEScraper:
    """
    Scrapes corporate announcements from NSE India's API.

    NSE requires:
    1. A valid session cookie obtained by visiting the main site first
    2. Proper User-Agent and Referer headers
    3. Rate limiting to avoid IP blocks
    """

    BASE_URL = "https://www.nseindia.com"
    ANNOUNCEMENTS_API = f"{BASE_URL}/api/corporate-announcements"

    # Rotate User-Agents to reduce blocking risk
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    ]

    def __init__(self):
        self.session: Optional[requests.Session] = None
        self._session_created_at: float = 0
        self._ua_index: int = 0
        self._request_count: int = 0
        self.SESSION_TTL = 120  # Refresh session every 2 minutes

    def _get_headers(self) -> dict:
        """Build request headers with rotating User-Agent."""
        ua = self.USER_AGENTS[self._ua_index % len(self.USER_AGENTS)]
        return {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            "X-Requested-With": "XMLHttpRequest",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }

    def _create_session(self) -> requests.Session:
        """
        Create a fresh session by visiting the NSE homepage first.
        This is required to obtain the session cookies that NSE validates.
        """
        session = requests.Session()
        headers = self._get_headers()
        session.headers.update(headers)

        try:
            # Step 1: Visit the main page to get initial cookies
            logger.info("🔄 Creating new NSE session...")
            response = session.get(
                self.BASE_URL,
                headers=headers,
                timeout=15,
                allow_redirects=True,
            )
            response.raise_for_status()

            # Step 2: Visit the announcements page to get page-specific cookies
            session.get(
                f"{self.BASE_URL}/companies-listing/corporate-filings-announcements",
                headers=headers,
                timeout=15,
            )

            cookies = dict(session.cookies)
            logger.info(f"✅ NSE session created. Cookies obtained: {list(cookies.keys())}")

            self._session_created_at = time.time()
            self._ua_index += 1
            return session

        except requests.RequestException as e:
            logger.error(f"❌ Failed to create NSE session: {e}")
            raise

    def _ensure_session(self):
        """Ensure we have a valid, non-expired session."""
        elapsed = time.time() - self._session_created_at
        if self.session is None or elapsed > self.SESSION_TTL:
            self.session = self._create_session()

    def _throttle(self):
        """Rate limiting: pause between requests to avoid blocks."""
        self._request_count += 1
        if self._request_count % 5 == 0:
            delay = 2.0
            logger.debug(f"⏳ Throttling: sleeping {delay}s after {self._request_count} requests")
            time.sleep(delay)

    def fetch_announcements_by_symbol(self, symbol: str, from_date: str = None, to_date: str = None) -> list:
        """
        Fetch corporate announcements for a specific company symbol.

        Args:
            symbol: NSE stock symbol (e.g., 'RELIANCE', 'TCS')
            from_date: Start date in DD-MM-YYYY format (default: today)
            to_date: End date in DD-MM-YYYY format (default: today)

        Returns:
            List of announcement dicts from NSE API
        """
        self._ensure_session()
        self._throttle()

        today = datetime.now()
        if not from_date:
            from_date = (today - timedelta(days=1)).strftime("%d-%m-%Y")
        if not to_date:
            to_date = today.strftime("%d-%m-%Y")

        params = {
            "index": "equities",
            "symbol": symbol.upper(),
            "from_date": from_date,
            "to_date": to_date,
        }

        try:
            logger.info(f"📡 Fetching announcements for {symbol} ({from_date} to {to_date})")
            response = self.session.get(
                self.ANNOUNCEMENTS_API,
                params=params,
                timeout=15,
            )

            if response.status_code == 401 or response.status_code == 403:
                logger.warning(f"⚠️ Session expired (HTTP {response.status_code}). Refreshing...")
                self.session = self._create_session()
                response = self.session.get(
                    self.ANNOUNCEMENTS_API,
                    params=params,
                    timeout=15,
                )

            response.raise_for_status()
            data = response.json()

            # NSE returns a list of announcements directly or under a key
            announcements = data if isinstance(data, list) else data.get("data", data.get("announcements", []))
            logger.info(f"📋 Found {len(announcements)} announcements for {symbol}")
            return announcements

        except requests.exceptions.JSONDecodeError:
            logger.error(f"❌ Non-JSON response for {symbol}. NSE may be blocking. Response: {response.text[:200]}")
            return []
        except requests.RequestException as e:
            logger.error(f"❌ Failed to fetch announcements for {symbol}: {e}")
            return []

    def fetch_all_recent_announcements(self, from_date: str = None, to_date: str = None) -> list:
        """
        Fetch ALL recent corporate announcements (not filtered by symbol).
        Useful for catching announcements across your entire watchlist in one call.

        Args:
            from_date: Start date in DD-MM-YYYY format
            to_date: End date in DD-MM-YYYY format

        Returns:
            List of announcement dicts
        """
        self._ensure_session()
        self._throttle()

        today = datetime.now()
        if not from_date:
            from_date = today.strftime("%d-%m-%Y")
        if not to_date:
            to_date = today.strftime("%d-%m-%Y")

        params = {
            "index": "equities",
            "from_date": from_date,
            "to_date": to_date,
        }

        try:
            logger.info(f"📡 Fetching all announcements ({from_date} to {to_date})")
            response = self.session.get(
                self.ANNOUNCEMENTS_API,
                params=params,
                timeout=15,
            )

            if response.status_code in (401, 403):
                logger.warning("⚠️ Session expired. Refreshing...")
                self.session = self._create_session()
                response = self.session.get(
                    self.ANNOUNCEMENTS_API,
                    params=params,
                    timeout=15,
                )

            response.raise_for_status()
            data = response.json()
            announcements = data if isinstance(data, list) else data.get("data", data.get("announcements", []))
            logger.info(f"📋 Found {len(announcements)} total announcements")
            return announcements

        except requests.exceptions.JSONDecodeError:
            logger.error(f"❌ Non-JSON response. NSE may be blocking.")
            return []
        except requests.RequestException as e:
            logger.error(f"❌ Failed to fetch announcements: {e}")
            return []

    def filter_by_watchlist(self, announcements: list, watchlist_symbols: list) -> list:
        """
        Filter announcements to only include companies from the watchlist.

        Args:
            announcements: Full list of announcements from NSE
            watchlist_symbols: List of NSE symbols to track

        Returns:
            Filtered list of announcements matching watchlist
        """
        symbols_upper = {s.upper() for s in watchlist_symbols}
        filtered = [
            a for a in announcements
            if a.get("symbol", "").upper() in symbols_upper
        ]
        if filtered:
            logger.info(f"🎯 {len(filtered)} announcements match watchlist out of {len(announcements)} total")
        return filtered


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
    scraper = NSEScraper()

    # Test with a single symbol
    results = scraper.fetch_announcements_by_symbol("RELIANCE")
    for r in results[:3]:
        print(f"\n--- Announcement ---")
        print(f"  Company: {r.get('symbol', 'N/A')}")
        print(f"  Subject: {r.get('desc', r.get('subject', 'N/A'))}")
        print(f"  Date:    {r.get('an_dt', r.get('date', 'N/A'))}")
        print(f"  PDF:     {r.get('attchmntFile', r.get('attachment', 'N/A'))}")
