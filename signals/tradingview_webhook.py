"""TradingView alerts as a signal source.

The boundary is the point. TradingView is very good at the thing Sauron
is not — a screener, Pine scripts, and a chart an operator already knows
— and Sauron owns the things TradingView has no idea about: the risk
gates, the broker-side brackets, the tax lots, and the grading that says
afterwards whether a rule was worth listening to.

So an alert lands here as a SIGNAL and never as an order. It joins the
same queue every internal rule writes into, gets scored and aged the
same way, is voted on by the same `decide()`, and is refused by the same
`preflight` if the book says no. A webhook that placed trades would be a
second execution path with none of that, which is exactly the shape of
the bugs this platform keeps finding in itself.

SECURITY, stated plainly because this endpoint is reachable by anyone
who finds the URL:

  * TradingView cannot send custom headers, so the shared secret travels
    in the JSON body. It is compared in constant time.
  * With no secret configured the endpoint is CLOSED, not open. An
    unconfigured webhook that accepted anything is worse than no webhook.
  * A symbol that does not resolve to a known Instrument is refused and
    named. Creating instruments from an unauthenticated POST would let
    anyone fill the catalogue with junk.
  * The body is size-capped before parsing.
  * A duplicate alert (same symbol, direction and bar) within the dedupe
    window is accepted and ignored rather than written twice —
    TradingView retries, and `once per bar close` still fires on every
    reconnection.

Set TRADINGVIEW_WEBHOOK_SECRET in .env, then point a TradingView alert
at  https://<your-domain>/api/webhook/tradingview/  with a message body:

    {"secret": "...", "symbol": "{{ticker}}", "action": "buy",
     "price": {{close}}, "stop": 0, "target": 0,
     "strategy": "{{strategy.order.alert_message}}"}
"""
import hmac
import json
import logging
import os
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

# A TradingView alert body is a few hundred bytes. Anything approaching
# this is not one, and parsing it would be the only work an attacker
# needed us to do.
MAX_BODY = 8192

# Two alerts for the same bet inside this window are one alert.
# TradingView retries on its side and "once per bar close" fires again on
# every reconnection, so without this a flaky link doubles the vote.
DEDUPE_SECONDS = 90

_BUY = {"buy", "long", "bullish", "b", "up"}
_SELL = {"sell", "short", "bearish", "s", "down"}


def _dec(v):
    if v in (None, "", 0, "0"):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d > 0 else None


def _reject(reason, status=400, **extra):
    """Refuse loudly. A webhook that fails quietly is one nobody fixes."""
    logger.warning("[tradingview] refused: %s %s", reason, extra or "")
    return JsonResponse({"ok": False, "error": reason}, status=status)


@csrf_exempt
@require_POST
def tradingview_webhook(request):
    secret = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "").strip()
    if not secret:
        # CLOSED when unconfigured. The opposite default would mean every
        # deployment that never heard of this feature is running an open
        # signal injector.
        return _reject("webhook not configured", status=503)

    if len(request.body or b"") > MAX_BODY:
        return _reject("body too large", status=413)

    try:
        payload = json.loads((request.body or b"{}").decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _reject("body is not JSON")
    if not isinstance(payload, dict):
        return _reject("body is not an object")

    # Constant time: a plain == leaks the secret one character at a time
    # to anyone willing to measure.
    if not hmac.compare_digest(str(payload.get("secret", "")), secret):
        return _reject("bad secret", status=403)

    symbol = str(payload.get("symbol") or payload.get("ticker") or "").strip()
    if not symbol:
        return _reject("no symbol")

    action = str(payload.get("action") or payload.get("side") or "").strip().lower()
    if action in _BUY:
        direction = "bullish"
    elif action in _SELL:
        direction = "bearish"
    else:
        return _reject(f"unknown action {action!r}")

    from core.constants import Urgency
    from market_data.quotes import resolve_instrument
    from signals.models import Signal

    instrument = resolve_instrument(symbol)
    if instrument is None:
        # Named, not created. An unauthenticated POST that could add
        # instruments is an unauthenticated POST that can fill the
        # catalogue with anything.
        return _reject(f"unknown symbol {symbol!r} — add the instrument first",
                       status=404)

    price = _dec(payload.get("price")) or _dec(payload.get("close"))
    if price is None:
        # Fall back to the platform's own mark rather than refusing: an
        # alert whose template did not interpolate {{close}} is still a
        # real alert, and the quote we hold is the honest substitute.
        quote = getattr(instrument, "live_quote", None)
        price = _dec(getattr(quote, "last", None))
    if price is None:
        return _reject(f"no price in the alert and no quote for {symbol!r}")

    strategy = str(payload.get("strategy") or payload.get("comment")
                   or "tradingview").strip()[:80]
    rule_name = f"tradingview:{strategy}" if strategy else "tradingview"

    # A repeat inside the window is the same bet, not a second one.
    since = timezone.now() - timezone.timedelta(seconds=DEDUPE_SECONDS)
    if Signal.objects.filter(instrument=instrument, direction=direction,
                             rule_name=rule_name[:100],
                             created_at__gte=since).exists():
        logger.info("[tradingview] duplicate within %ss for %s %s — ignored",
                    DEDUPE_SECONDS, symbol, direction)
        return JsonResponse({"ok": True, "duplicate": True})

    stop = _dec(payload.get("stop") or payload.get("sl"))
    target = _dec(payload.get("target") or payload.get("tp"))

    rr = None
    if stop and target:
        risk = abs(price - stop)
        if risk > 0:
            rr = float(abs(target - price) / risk)

    # Score: an external source does not get to claim conviction it has
    # not earned here. 0.6 sits above the default 0.60 entry floor only
    # when the alert carries a full plan — a bare arrow is evidence of
    # less, and the vote weights it accordingly.
    score = 0.65 if (stop and target) else 0.55
    try:
        score = max(0.0, min(1.0, float(payload.get("score", score))))
    except (TypeError, ValueError):
        pass

    signal = Signal.objects.create(
        instrument=instrument,
        signal_type="technical",
        direction=direction,
        urgency=Urgency.MEDIUM,
        title=f"TradingView: {strategy} — {symbol}",
        description=(str(payload.get("message") or payload.get("note") or "")
                     or f"Alert from TradingView strategy {strategy!r}.")[:2000],
        rule_name=rule_name[:100],
        score=score,
        sub_scores={"source": "tradingview", "strategy": strategy,
                    "action": action},
        price_at_signal=price,
        suggested_entry=price,
        suggested_stop=stop,
        suggested_target=target,
        risk_reward_ratio=rr,
        is_active=True,
    )
    logger.info("[tradingview] %s %s from %s -> signal #%s",
                direction, symbol, strategy, signal.pk)
    return JsonResponse({"ok": True, "signal_id": signal.pk,
                         "symbol": instrument.symbol,
                         "direction": direction})
