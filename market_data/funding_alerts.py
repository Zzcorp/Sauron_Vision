"""Funding rate analyser — raises Notification rows when funding
conditions signal potential squeezes or extreme crowding."""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.contrib.auth.models import User

log = logging.getLogger(__name__)

EXTREME_THRESHOLD = 0.001   # 0.1% per 8h funding interval
LOOKBACK_MIN = 15           # compare current vs 15 minutes ago
PRICE_LOOKBACK_HOURS = 1

def _notify(user, title: str, body: str, url: str = "/liquidations/"):
    try:
        from alerts.models import Notification
        # notification_type was omitted for as long as this file existed,
        # so the bell rendered a blank kind chip (class "ni-").
        Notification.objects.create(
            user=user, notification_type="signal",
            title=title, body=body, url=url, read=False)
    except Exception as e:
        log.debug("notify failed: %s", e)

def _notify_all(title: str, body: str, url: str = "/liquidations/"):
    for u in User.objects.filter(is_active=True):
        prof = getattr(u, "trader_profile", None)
        if prof and getattr(prof, "notify_signals", True):
            _notify(u, title, body, url)

@shared_task
def scan_funding_signals():
    from market_data.models import FundingRate, LiveQuote
    from instruments.models import Instrument

    now = timezone.now()
    window_start = now - timedelta(minutes=LOOKBACK_MIN + 5)
    # Distinct symbols with recent funding data
    symbols = (FundingRate.objects.filter(timestamp__gte=window_start)
               .values_list("symbol", flat=True).distinct())
    alerts = 0
    for sym in symbols:
        recent = list(FundingRate.objects.filter(
            symbol=sym, timestamp__gte=window_start).order_by("-timestamp")[:2])
        if len(recent) < 2: continue
        cur, prev = recent[0], recent[1]
        cur_r = float(cur.funding_rate)
        prev_r = float(prev.funding_rate)

        # (a) Sign flip
        if cur_r * prev_r < 0:
            _notify_all(
                f"⚡ {sym} funding flipped",
                f"Funding rate flipped {prev_r*100:+.4f}% → {cur_r*100:+.4f}% · mark {cur.mark_price}",
            )
            alerts += 1

        # (b) Extreme
        if abs(cur_r) >= EXTREME_THRESHOLD:
            direction = "CROWDED LONGS" if cur_r > 0 else "CROWDED SHORTS"
            _notify_all(
                f"🔥 {sym} extreme funding — {direction}",
                f"Funding {cur_r*100:+.4f}% (≥±0.1%). Squeeze risk elevated.",
            )
            alerts += 1

        # (c) Funding / price divergence: price up but funding negative,
        # or price down but funding positive → squeeze setup
        try:
            inst = Instrument.objects.filter(symbol__iexact=sym).first()
            if not inst: continue
            q = LiveQuote.objects.filter(instrument=inst).first()
            if not q or q.change_pct is None: continue
            price_chg = float(q.change_pct)
            if price_chg > 1.0 and cur_r < 0:
                _notify_all(
                    f"⚠ {sym} divergence — shorts bleeding",
                    f"Price +{price_chg:.2f}% but funding {cur_r*100:+.4f}%. Classic short squeeze setup.",
                )
                alerts += 1
            elif price_chg < -1.0 and cur_r > 0:
                _notify_all(
                    f"⚠ {sym} divergence — longs bleeding",
                    f"Price {price_chg:.2f}% but funding {cur_r*100:+.4f}%. Long squeeze setup.",
                )
                alerts += 1
        except Exception as e:
            log.debug("divergence check failed for %s: %s", sym, e)

    log.info("scan_funding_signals: raised %d alerts across %d symbols", alerts, len(list(symbols)))
    return alerts
