"""Proxy rotation for web scraping — ScraperAPI or custom proxies."""
import os
import requests
import logging
from itertools import cycle

logger = logging.getLogger(__name__)

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
PROXY_LIST = os.getenv("PROXY_LIST", "").split(",")  # comma-separated proxy URLs

_proxy_pool = cycle([p.strip() for p in PROXY_LIST if p.strip()]) if any(PROXY_LIST) else None


class ProxySession:
    """
    Requests session with automatic proxy rotation.

    Priority:
    1. ScraperAPI (if key set) — handles rotation, CAPTCHAs, retries
    2. Custom proxy list rotation
    3. Direct connection (no proxy)
    """

    def __init__(self, use_proxy=True):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SauronVision/1.0 (Trading Intelligence Platform)",
        })
        self.use_proxy = use_proxy

    def get(self, url, **kwargs):
        """GET request with automatic proxy handling."""
        timeout = kwargs.pop("timeout", 15)

        if self.use_proxy and SCRAPER_API_KEY:
            # ScraperAPI: prepend their proxy URL
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={url}"
            return self.session.get(proxy_url, timeout=timeout, **kwargs)

        if self.use_proxy and _proxy_pool:
            proxy = next(_proxy_pool)
            proxies = {"http": proxy, "https": proxy}
            try:
                return self.session.get(url, proxies=proxies, timeout=timeout, **kwargs)
            except requests.exceptions.ProxyError:
                logger.warning(f"Proxy failed: {proxy}, trying next")
                proxy = next(_proxy_pool)
                proxies = {"http": proxy, "https": proxy}
                return self.session.get(url, proxies=proxies, timeout=timeout, **kwargs)

        # Direct connection
        return self.session.get(url, timeout=timeout, **kwargs)

    def post(self, url, **kwargs):
        """POST request with proxy handling."""
        timeout = kwargs.pop("timeout", 15)

        if self.use_proxy and SCRAPER_API_KEY:
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={url}"
            return self.session.post(proxy_url, timeout=timeout, **kwargs)

        if self.use_proxy and _proxy_pool:
            proxy = next(_proxy_pool)
            proxies = {"http": proxy, "https": proxy}
            return self.session.post(url, proxies=proxies, timeout=timeout, **kwargs)

        return self.session.post(url, timeout=timeout, **kwargs)


def get_session(use_proxy=True):
    """Get a proxy-enabled session for scraping."""
    return ProxySession(use_proxy=use_proxy)


def proxy_status():
    """Return proxy configuration status."""
    if SCRAPER_API_KEY:
        return {"provider": "ScraperAPI", "configured": True}
    elif any(p.strip() for p in PROXY_LIST if p):
        count = len([p for p in PROXY_LIST if p.strip()])
        return {"provider": f"Custom ({count} proxies)", "configured": True}
    return {"provider": "None (direct)", "configured": False}
