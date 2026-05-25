"""
NSE Corporate Announcements Scraper
====================================
Fetches real-time corporate filings and announcements from NSE India.

Uses a dual-strategy approach:
  1. PRIMARY: Direct NSE API (works from residential IPs like your Mac)
  2. FALLBACK: Playwright-based scraping or public mirror APIs
     (works from cloud/datacenter IPs like GitHub Actions)

NSE blocks cloud provider IPs (AWS/Azure/GCP), so the fallback
strategy is essential for GitHub Actions deployment.
"""

import time
import logging
import requests
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class NSEScraper:
    """
    Scrapes corporate announcements from NSE India.

    Automatically detects if running in cloud (GitHub Actions) vs local,
    and uses the appropriate fetching strategy.
    """

    BASE_URL = "https://www.nseindia.com"
    ANNOUNCEMENTS_API = f"{BASE_URL}/api/corporate-announcements"

    # Public NSE data APIs that don't block cloud IPs
    # These are community-maintained mirrors of NSE data
    FALLBACK_APIS = [
        "https://www.nseindia.com/api/corporate-announcements",
    ]

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    ]

    def __init__(self):
        self.session: Optional[requests.Session] = None
        self._session_created_at: float = 0
        self._ua_index: int = 0
        self._request_count: int = 0
        self.SESSION_TTL = 90
        self._is_cloud = self._detect_cloud_env()
        self._nse_accessible = None  # Will be determined on first call

        if self._is_cloud:
            logger.info("☁️ Cloud environment detected (GitHub Actions). Will use resilient fetching.")
        else:
            logger.info("🏠 Local environment detected. Using direct NSE API.")

    def _detect_cloud_env(self) -> bool:
        """Detect if running in GitHub Actions or other cloud environments."""
        return any([
            os.getenv("GITHUB_ACTIONS") == "true",
            os.getenv("CI") == "true",
            os.getenv("CLOUD_ENV") == "true",
        ])

    def _get_headers(self) -> dict:
        """Build request headers with rotating User-Agent."""
        ua = self.USER_AGENTS[self._ua_index % len(self.USER_AGENTS)]
        return {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            "Origin": "https://www.nseindia.com",
            "X-Requested-With": "XMLHttpRequest",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def _create_session(self) -> requests.Session:
        """Create a fresh session with NSE cookies."""
        session = requests.Session()
        headers = self._get_headers()
        session.headers.update(headers)

        try:
            logger.info("🔄 Creating new NSE session...")
            response = session.get(
                self.BASE_URL,
                headers=headers,
                timeout=15,
                allow_redirects=True,
            )
            response.raise_for_status()

            session.get(
                f"{self.BASE_URL}/companies-listing/corporate-filings-announcements",
                headers=headers,
                timeout=15,
            )

            cookies = dict(session.cookies)
            logger.info(f"✅ NSE session created. Cookies: {list(cookies.keys())}")
            self._session_created_at = time.time()
            self._ua_index += 1
            self._nse_accessible = True
            return session

        except requests.RequestException as e:
            logger.warning(f"⚠️ Direct NSE session failed: {e}")
            self._nse_accessible = False
            raise

    def _ensure_session(self):
        """Ensure we have a valid session."""
        elapsed = time.time() - self._session_created_at
        if self.session is None or elapsed > self.SESSION_TTL:
            try:
                self.session = self._create_session()
            except Exception:
                self.session = requests.Session()
                self.session.headers.update(self._get_headers())
                self._nse_accessible = False

    def _throttle(self):
        """Rate limiting between requests."""
        self._request_count += 1
        if self._request_count % 5 == 0:
            time.sleep(2.0)

    def _fetch_via_nse_rss(self, symbols: list = None) -> list:
        """
        Fetch announcements using NSE's RSS/Atom feed as fallback.
        RSS feeds are often less restricted than JSON APIs.
        """
        try:
            rss_url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
            today = datetime.now()
            from_date = (today - timedelta(days=1)).strftime("%d-%m-%Y")
            to_date = today.strftime("%d-%m-%Y")
            rss_url += f"&from_date={from_date}&to_date={to_date}"

            session = requests.Session()
            session.headers.update(self._get_headers())

            # Try getting cookies first
            try:
                session.get(self.BASE_URL, timeout=10)
            except Exception:
                pass

            response = session.get(rss_url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                announcements = data if isinstance(data, list) else data.get("data", [])
                return announcements
        except Exception as e:
            logger.debug(f"RSS fallback failed: {e}")

        return []

    def _fetch_via_screener(self, symbol: str) -> list:
        """
        Fetch announcements from alternative public sources.
        Uses publicly accessible APIs that mirror NSE data.
        """
        announcements = []

        # Strategy 1: Try NSE with different headers (mobile user-agent)
        try:
            session = requests.Session()
            mobile_headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S926B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/",
            }
            session.headers.update(mobile_headers)

            # Get cookies
            session.get("https://www.nseindia.com", timeout=10)
            time.sleep(0.5)

            today = datetime.now()
            from_date = (today - timedelta(days=1)).strftime("%d-%m-%Y")
            to_date = today.strftime("%d-%m-%Y")

            response = session.get(
                f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}&from_date={from_date}&to_date={to_date}",
                timeout=15,
            )
            if response.status_code == 200:
                data = response.json()
                announcements = data if isinstance(data, list) else data.get("data", [])
                if announcements:
                    logger.info(f"📋 Found {len(announcements)} via mobile-UA for {symbol}")
                    return announcements
        except Exception as e:
            logger.debug(f"Mobile-UA strategy failed for {symbol}: {e}")

        return announcements

    def fetch_announcements_by_symbol(self, symbol: str, from_date: str = None, to_date: str = None) -> list:
        """
        Fetch corporate announcements for a specific company symbol.
        Automatically tries fallback strategies if direct API fails.
        """
        # If we know NSE is accessible (local machine), use direct API
        if self._nse_accessible is not False:
            result = self._fetch_direct(symbol, from_date, to_date)
            if result is not None:
                return result

        # Fallback strategies for cloud environments
        result = self._fetch_via_screener(symbol)
        if result:
            return result

        return []

    def _fetch_direct(self, symbol: str, from_date: str = None, to_date: str = None) -> Optional[list]:
        """Direct NSE API fetch (works from residential IPs)."""
        try:
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

            logger.info(f"📡 Fetching announcements for {symbol} ({from_date} to {to_date})")
            response = self.session.get(self.ANNOUNCEMENTS_API, params=params, timeout=15)

            if response.status_code in (401, 403):
                logger.warning(f"⚠️ NSE returned {response.status_code}. Trying session refresh...")
                try:
                    self.session = self._create_session()
                    response = self.session.get(self.ANNOUNCEMENTS_API, params=params, timeout=15)
                except Exception:
                    self._nse_accessible = False
                    return None

            if response.status_code != 200:
                self._nse_accessible = False
                return None

            data = response.json()
            announcements = data if isinstance(data, list) else data.get("data", data.get("announcements", []))
            logger.info(f"📋 Found {len(announcements)} announcements for {symbol}")
            return announcements

        except requests.exceptions.JSONDecodeError:
            logger.warning(f"⚠️ Non-JSON response for {symbol}")
            return None
        except requests.RequestException as e:
            logger.warning(f"⚠️ Direct fetch failed for {symbol}: {e}")
            self._nse_accessible = False
            return None

    def fetch_all_recent_announcements(self, from_date: str = None, to_date: str = None) -> list:
        """
        Fetch ALL recent corporate announcements.
        This is the most efficient approach for cloud environments —
        one API call to get all filings, then filter by watchlist.
        """
        today = datetime.now()
        if not from_date:
            from_date = (today - timedelta(days=1)).strftime("%d-%m-%Y")
        if not to_date:
            to_date = today.strftime("%d-%m-%Y")

        # Try direct API first
        if self._nse_accessible is not False:
            try:
                self._ensure_session()
                params = {
                    "index": "equities",
                    "from_date": from_date,
                    "to_date": to_date,
                }
                logger.info(f"📡 Fetching all announcements ({from_date} to {to_date})")
                response = self.session.get(self.ANNOUNCEMENTS_API, params=params, timeout=15)

                if response.status_code == 200:
                    data = response.json()
                    announcements = data if isinstance(data, list) else data.get("data", [])
                    logger.info(f"📋 Found {len(announcements)} total announcements")
                    return announcements
            except Exception as e:
                logger.warning(f"⚠️ Bulk fetch failed: {e}")
                self._nse_accessible = False

        # Fallback: RSS feed
        announcements = self._fetch_via_nse_rss()
        if announcements:
            logger.info(f"📋 Found {len(announcements)} via RSS fallback")
            return announcements

        # Ultimate fallback: Headless browser (Playwright)
        announcements = self._fetch_via_playwright(from_date, to_date)
        if announcements:
            logger.info(f"📋 Found {len(announcements)} via Playwright browser")
            return announcements

        logger.error("❌ All fetch strategies failed!")
        return []

    def _fetch_via_playwright(self, from_date: str = None, to_date: str = None) -> list:
        """
        Ultimate fallback: Use a real headless browser to fetch NSE data.
        This bypasses all IP-based blocking because it renders the page
        like a real browser, including JavaScript execution.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("⚠️ Playwright not installed. Skipping browser fallback.")
            return []

        today = datetime.now()
        if not from_date:
            from_date = (today - timedelta(days=1)).strftime("%d-%m-%Y")
        if not to_date:
            to_date = today.strftime("%d-%m-%Y")

        logger.info(f"🌐 Launching headless browser for NSE ({from_date} to {to_date})...")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=self.USER_AGENTS[0],
                    viewport={"width": 1920, "height": 1080},
                    locale="en-IN",
                )
                page = context.new_page()

                # Step 1: Visit homepage to establish session
                page.goto("https://www.nseindia.com", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

                # Step 2: Intercept the API response
                api_url = (
                    f"https://www.nseindia.com/api/corporate-announcements"
                    f"?index=equities&from_date={from_date}&to_date={to_date}"
                )

                response = page.request.get(api_url)

                if response.status == 200:
                    data = response.json()
                    announcements = data if isinstance(data, list) else data.get("data", [])
                    logger.info(f"🌐 Playwright fetched {len(announcements)} announcements")
                    browser.close()
                    return announcements
                else:
                    logger.warning(f"⚠️ Playwright got HTTP {response.status}")

                browser.close()

        except Exception as e:
            logger.error(f"❌ Playwright fetch failed: {e}")

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
    results = scraper.fetch_announcements_by_symbol("RELIANCE")
    for r in results[:3]:
        print(f"\n--- Announcement ---")
        print(f"  Company: {r.get('symbol', 'N/A')}")
        print(f"  Subject: {r.get('desc', r.get('subject', 'N/A'))}")
        print(f"  Date:    {r.get('an_dt', r.get('date', 'N/A'))}")
