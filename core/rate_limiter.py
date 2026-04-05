"""API rate limit manager to prevent hitting provider limits."""
import time
import threading
from collections import defaultdict


class RateLimiter:
    """Thread-safe rate limiter for API calls."""

    def __init__(self):
        self._locks = defaultdict(threading.Lock)
        self._last_call = defaultdict(float)
        self._call_counts = defaultdict(list)

    def wait_if_needed(self, provider: str, calls_per_minute: int = 5):
        """Block until it's safe to make another API call."""
        with self._locks[provider]:
            now = time.time()
            min_interval = 60.0 / calls_per_minute

            # Clean old timestamps
            self._call_counts[provider] = [
                t for t in self._call_counts[provider]
                if now - t < 60.0
            ]

            # If at limit, wait
            if len(self._call_counts[provider]) >= calls_per_minute:
                oldest = self._call_counts[provider][0]
                wait_time = 60.0 - (now - oldest) + 0.1
                if wait_time > 0:
                    time.sleep(wait_time)

            # Also respect minimum interval between calls
            elapsed = now - self._last_call[provider]
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)

            self._last_call[provider] = time.time()
            self._call_counts[provider].append(time.time())


# Global rate limiter instance
rate_limiter = RateLimiter()
