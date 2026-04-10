"""API rate limit manager to prevent hitting provider limits."""
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone


class RateLimiter:
    """Thread-safe rate limiter for API calls."""

    def __init__(self):
        self._locks = defaultdict(threading.Lock)
        self._last_call = defaultdict(float)
        self._call_counts = defaultdict(list)
        self._total_counts = defaultdict(int)
        self._hourly_counts = defaultdict(list)

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

            now_after_wait = time.time()
            self._last_call[provider] = now_after_wait
            self._call_counts[provider].append(now_after_wait)
            self._total_counts[provider] += 1
            self._hourly_counts[provider].append(now_after_wait)

    def get_stats(self) -> dict:
        """Return per-provider call statistics.

        Returns a dict keyed by provider name with fields:
            calls_last_minute, calls_last_hour, total_calls, last_call_at
        """
        now = time.time()
        stats = {}
        all_providers = set(self._total_counts.keys()) | set(self._call_counts.keys())
        for provider in all_providers:
            # Minute-level counts (already maintained by wait_if_needed)
            minute_calls = [t for t in self._call_counts[provider] if now - t < 60.0]
            # Hour-level counts — clean up stale entries in place
            self._hourly_counts[provider] = [
                t for t in self._hourly_counts[provider] if now - t < 3600.0
            ]
            hourly_calls = self._hourly_counts[provider]
            last_ts = self._last_call.get(provider, 0.0)
            last_call_at = (
                datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
                if last_ts > 0
                else None
            )
            stats[provider] = {
                "calls_last_minute": len(minute_calls),
                "calls_last_hour": len(hourly_calls),
                "total_calls": self._total_counts[provider],
                "last_call_at": last_call_at,
            }
        return stats

    def get_quota_usage(self, provider: str, calls_per_minute: int) -> float:
        """Return the fraction (0.0-100.0) of the per-minute quota currently used."""
        now = time.time()
        minute_calls = [t for t in self._call_counts[provider] if now - t < 60.0]
        return round(len(minute_calls) / calls_per_minute * 100, 1)


# Global rate limiter instance
rate_limiter = RateLimiter()
