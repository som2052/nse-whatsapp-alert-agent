"""
NSE Corporate Announcements Scraper
====================================
Fetches real-time corporate filings from NSE India.

NSE uses Akamai Bot Manager which blocks cloud IPs and detects
automation. This scraper uses curl_cffi to impersonate Chrome's
TLS fingerprint — the proven approach to bypass Akamai from cloud.

Strategy:
  1. curl_cffi with Chrome impersonation (works from cloud IPs)
  2. Direct requests with session cookies (works from residential IPs)
"""

import time
import logging
import os
import json
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Try importing curl_cffi first (works from cloud), fallback to requests
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
    logger.debug("✅ curl_cffi available — Chrome TLS impersonation enabled")
except ImportError:
    HAS_CURL_CFFI = False
    logger.debug("⚠️ curl_cffi not available — using standard requests")

import requests


class NSEScraper:
    """
    Scrapes corporate announcements from NSE India.
    Uses curl_cffi Chrome impersonation to bypass Akamai Bot Manager.
    """

    BASE_URL = "https://www.nseindia.com"
    ANNOUNCEMENTS_API = f"{BASE_URL}/api/corporate-announcements"

    HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        "Origin": "https://www.nseindia.com",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    def __init__(self):
        self._cffi_session = None
        self._requests_session = None
        self._session_created_at: float = 0
        self._request_count: int = 0
        self.SESSION_TTL = 90
        self._is_cloud = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"
        self._use_cffi = HAS_CURL_CFFI

        if self._is_cloud:
            logger.info("☁️ Cloud environment detected (GitHub Actions)")
        if self._use_cffi:
            logger.info("🔒 curl_cffi enabled — Chrome TLS impersonation active")
        else:
            logger.info("📡 Using standard requests (residential IP assumed)")

    def _create_cffi_session(self):
        """Create a curl_cffi session that impersonates Chrome."""
        session = cffi_requests.Session(impersonate="chrome131")

        try:
            logger.info("🔄 Creating NSE session via curl_cffi (Chrome impersonation)...")

            # Step 1: Visit homepage to get cookies
            resp = session.get(self.BASE_URL, headers=self.HEADERS, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"⚠️ Homepage returned {resp.status_code}")

            time.sleep(1)

            # Step 2: Visit announcements page
            session.get(
                f"{self.BASE_URL}/companies-listing/corporate-filings-announcements",
                headers=self.HEADERS,
                timeout=15,
            )

            cookies = dict(session.cookies)
            logger.info(f"✅ curl_cffi session created. Cookies: {list(cookies.keys())}")
            self._session_created_at = time.time()
            return session

        except Exception as e:
            logger.error(f"❌ curl_cffi session failed: {e}")
            raise

    def _create_requests_session(self):
        """Create a standard requests session (for residential IPs)."""
        session = requests.Session()
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        headers = {**self.HEADERS, "User-Agent": ua}
        session.headers.update(headers)

        try:
            logger.info("🔄 Creating NSE session via requests...")
            resp = session.get(self.BASE_URL, timeout=15, allow_redirects=True)
            resp.raise_for_status()
            session.get(
                f"{self.BASE_URL}/companies-listing/corporate-filings-announcements",
                timeout=15,
            )
            cookies = dict(session.cookies)
            logger.info(f"✅ Requests session created. Cookies: {list(cookies.keys())}")
            self._session_created_at = time.time()
            return session
        except Exception as e:
            logger.error(f"❌ Requests session failed: {e}")
            raise

    def _ensure_session(self):
        """Ensure we have a valid session, preferring curl_cffi."""
        elapsed = time.time() - self._session_created_at

        if self._use_cffi:
            if self._cffi_session is None or elapsed > self.SESSION_TTL:
                try:
                    self._cffi_session = self._create_cffi_session()
                except Exception:
                    logger.warning("⚠️ curl_cffi session failed. Trying standard requests...")
                    self._use_cffi = False
                    self._requests_session = self._create_requests_session()
        else:
            if self._requests_session is None or elapsed > self.SESSION_TTL:
                self._requests_session = self._create_requests_session()

    def _get(self, url: str, params: dict = None, timeout: int = 15):
        """Make a GET request using the active session."""
        if self._use_cffi and self._cffi_session:
            return self._cffi_session.get(url, params=params, headers=self.HEADERS, timeout=timeout)
        elif self._requests_session:
            return self._requests_session.get(url, params=params, timeout=timeout)
        else:
            raise RuntimeError("No active session")

    def _throttle(self):
        """Rate limiting between requests."""
        self._request_count += 1
        if self._request_count % 5 == 0:
            time.sleep(2.0)

    def fetch_all_recent_announcements(self, from_date: str = None, to_date: str = None) -> list:
        """
        Fetch ALL recent corporate announcements in one API call.
        Most efficient approach — fetch all, then filter by watchlist.
        """
        self._ensure_session()

        today = datetime.now()
        if not from_date:
            from_date = (today - timedelta(days=1)).strftime("%d-%m-%Y")
        if not to_date:
            to_date = today.strftime("%d-%m-%Y")

        params = {
            "index": "equities",
            "from_date": from_date,
            "to_date": to_date,
        }

        # Try with current session
        for attempt in range(2):
            try:
                logger.info(f"📡 Fetching all announcements ({from_date} to {to_date}) [attempt {attempt + 1}]")
                response = self._get(self.ANNOUNCEMENTS_API, params=params)

                if response.status_code in (401, 403):
                    logger.warning(f"⚠️ HTTP {response.status_code}. Refreshing session...")
                    self._session_created_at = 0  # Force refresh
                    self._ensure_session()
                    continue

                if response.status_code == 200:
                    data = response.json()
                    announcements = data if isinstance(data, list) else data.get("data", data.get("announcements", []))
                    logger.info(f"📋 Found {len(announcements)} total announcements")
                    return announcements
                else:
                    logger.warning(f"⚠️ Unexpected HTTP {response.status_code}")

            except Exception as e:
                logger.warning(f"⚠️ Attempt {attempt + 1} failed: {e}")
                self._session_created_at = 0
                # If curl_cffi failed, try switching to standard requests
                if self._use_cffi and attempt == 0:
                    logger.info("🔄 Switching from curl_cffi to standard requests...")
                    self._use_cffi = False
                    try:
                        self._requests_session = self._create_requests_session()
                    except Exception:
                        pass

        logger.error("❌ All fetch attempts failed")
        return []

    def fetch_announcements_by_symbol(self, symbol: str, from_date: str = None, to_date: str = None) -> list:
        """Fetch announcements for a specific company symbol."""
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
            response = self._get(self.ANNOUNCEMENTS_API, params=params)

            if response.status_code in (401, 403):
                logger.warning(f"⚠️ HTTP {response.status_code}. Refreshing session...")
                self._session_created_at = 0
                self._ensure_session()
                response = self._get(self.ANNOUNCEMENTS_API, params=params)

            if response.status_code != 200:
                logger.warning(f"⚠️ HTTP {response.status_code} for {symbol}")
                return []

            data = response.json()
            announcements = data if isinstance(data, list) else data.get("data", data.get("announcements", []))
            logger.info(f"📋 Found {len(announcements)} announcements for {symbol}")
            return announcements

        except Exception as e:
            logger.error(f"❌ Failed to fetch {symbol}: {e}")
            return []

    def filter_by_watchlist(self, announcements: list, watchlist_symbols: list) -> list:
        """Filter announcements to only include watchlist companies."""
        symbols_upper = {s.upper() for s in watchlist_symbols}
        filtered = [
            a for a in announcements
            if a.get("symbol", "").upper() in symbols_upper
        ]
        if filtered:
            logger.info(f"🎯 {len(filtered)} match watchlist out of {len(announcements)} total")
        return filtered


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
    scraper = NSEScraper()
    results = scraper.fetch_all_recent_announcements()
    print(f"\nTotal: {len(results)} announcements")
    for r in results[:5]:
        print(f"  {r.get('symbol', 'N/A'):>12} | {r.get('desc', 'N/A')[:60]}")
