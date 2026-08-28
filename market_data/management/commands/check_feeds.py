"""Ask every declared feed why it is quiet.

The health panel says WHAT a feed's state is — `never`, `idle`, `red`. It
cannot say WHY, because it only reads the quote table, and a feed that has
never written leaves nothing there to read. That gap is a real cost: on
2026-08-28 an operator supplied OANDA credentials, redeployed, and the
panel still said `never` — with no way to tell from the platform whether
the container was down, the credentials were wrong, the market was shut, or
the ticks were arriving and being dropped.

This runs the checks a human would run, in order, and stops at the first
one that fails:

    1. Are the credentials present in THIS process's environment?
       A streamer container and the web container read the same env_file,
       but only if both were recreated after it changed.
    2. Does the vendor accept them?  One authenticated call, nothing
       written.
    3. Is the market for this feed even open?  A silent OANDA at the
       weekend is correct.
    4. Has it ever written a quote, and how long ago?

    manage.py check_feeds              # every declared feed
    manage.py check_feeds --feed oanda_stream

Read-only: it places no orders, writes no quotes, and changes no row.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand
from django.utils import timezone

OK = "  ok  "
BAD = " FAIL "
SKIP = " skip "


class Command(BaseCommand):
    help = "Diagnose why a declared quote feed is not delivering."

    def add_arguments(self, parser):
        parser.add_argument("--feed", default="",
                            help="One feed key (default: all declared)")
        parser.add_argument("--timeout", type=int, default=10)

    def handle(self, *args, **opts):
        from market_data.feeds import FEEDS, missing_credentials

        only = (opts.get("feed") or "").strip()
        feeds = [f for f in FEEDS if not only or f["key"] == only]
        if not feeds:
            self.stderr.write(f"No declared feed named {only!r}.")
            self.stderr.write("Declared: "
                              + ", ".join(f["key"] for f in FEEDS))
            return

        now = timezone.now()
        for feed in feeds:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"{feed['label']}  ({feed['key']})"))

            missing = missing_credentials(feed)
            if missing:
                self._line(SKIP, "credentials",
                           "not configured — " + ", ".join(missing))
                self._line(SKIP, "verdict",
                           "OFF. Nothing is wrong; this feed was never "
                           "switched on.")
                continue
            self._line(OK, "credentials",
                       "present" if feed["requires"]
                       else "none required")

            reachable, detail = self._probe(feed, opts["timeout"])
            if reachable is True:
                self._line(OK, "vendor", detail)
            elif reachable is False:
                self._line(BAD, "vendor", detail)
                self._line(BAD, "verdict",
                           "The credentials are present and the vendor "
                           "refused them. Fix the key before looking at "
                           "anything else.")
                continue
            else:
                self._line(SKIP, "vendor", detail)

            self._market(feed, now)
            self._delivery(feed, now)

    # ── one authenticated call, nothing written ──────────────────────
    def _probe(self, feed, timeout):
        """(True|False|None, detail). None means "no probe for this feed"."""
        key = feed["key"]
        try:
            if key in ("oanda_stream",):
                return self._probe_oanda(timeout)
            if key in ("finnhub_ws",):
                return self._probe_finnhub(timeout)
        except Exception as e:  # noqa: BLE001 — a diagnostic must not raise
            return False, f"probe failed: {e}"
        return None, "no credential probe for this feed"

    def _probe_oanda(self, timeout):
        import requests
        env = os.environ.get("OANDA_ENV", "practice").lower()
        host = ("https://api-fxtrade.oanda.com" if env == "live"
                else "https://api-fxpractice.oanda.com")
        acct = os.environ.get("OANDA_ACCOUNT_ID", "")
        r = requests.get(
            f"{host}/v3/accounts/{acct}/summary",
            headers={"Authorization":
                     f"Bearer {os.environ.get('OANDA_API_KEY', '')}"},
            timeout=timeout)
        if r.status_code == 200:
            return True, f"{env} endpoint accepted the key and account id"
        if r.status_code in (401, 403):
            # The commonest real cause, and invisible from the panel: a
            # practice token against the live host, or the reverse. OANDA
            # answers 401 either way.
            other = "live" if env == "practice" else "practice"
            return False, (f"{env} endpoint refused ({r.status_code}). "
                           f"If this token is a {other} one, set "
                           f"OANDA_ENV={other} and redeploy.")
        return False, f"{env} endpoint answered {r.status_code}"

    def _probe_finnhub(self, timeout):
        import requests
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": "AAPL",
                    "token": os.environ.get("FINNHUB_API_KEY", "")},
            timeout=timeout)
        if r.status_code == 200 and isinstance(r.json(), dict):
            return True, "the key is accepted"
        return False, f"answered {r.status_code}"

    # ── is it even supposed to be speaking? ──────────────────────────
    def _market(self, feed, now):
        from market_data.feeds import Window, window_is_open
        if feed["window"] == Window.ALWAYS:
            self._line(OK, "market", "trades continuously")
            return
        if window_is_open(feed["window"], now):
            self._line(OK, "market", "open right now")
        else:
            self._line(SKIP, "market",
                       "CLOSED right now — silence here is correct, and "
                       "the panel shows it as `idle` rather than a fault")

    def _delivery(self, feed, now):
        from market_data.models import LiveQuote
        rows = LiveQuote.objects.filter(source=feed["key"])
        n = rows.count()
        if not n:
            self._line(BAD, "delivery", "has NEVER written a quote")
            self._line(BAD, "verdict", self._never_advice(feed))
            return
        newest = rows.order_by("-updated_at").first()
        age = (now - newest.updated_at).total_seconds()
        warn = feed["ages"][0]
        mark = OK if age < warn else BAD
        self._line(mark, "delivery",
                   f"{n} instrument(s), newest {int(age)}s ago "
                   f"(fresh under {warn}s)")
        if age >= warn:
            self._line(BAD, "verdict",
                       "Credentials work and the market is open, but the "
                       "ticks stopped. Check the streamer container's logs.")

    def _never_advice(self, feed) -> str:
        if feed["kind"] == "stream":
            svc = {"oanda_stream": "stream-oanda",
                   "finnhub_ws": "stream-finnhub",
                   "binance_ws": "stream-binance"}.get(feed["key"], "")
            if svc:
                return (
                    f"Credentials work but nothing has ever arrived. The "
                    f"streamer is a PROFILED service: plain `up -d` does "
                    f"not start it.\n"
                    f"          ./deploy/dc --profile streamers up -d\n"
                    f"          ./deploy/dc logs --tail=50 {svc}")
        return ("Credentials work but nothing has ever arrived — check "
                "that the task or worker that writes this feed is running.")

    def _line(self, mark, label, detail):
        style = (self.style.SUCCESS if mark == OK
                 else self.style.ERROR if mark == BAD
                 else self.style.WARNING)
        self.stdout.write(f"  [{style(mark)}] {label:<12} {detail}")
