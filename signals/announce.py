"""Every new Signal is announced, from every creator, once (2026-09-26).

MEASURED ON THE VPS, 2026-09-26: ten signals in 24 hours, and the last
one (pk 464, "starter_stock_momentum matched on MSFT", written by the
opportunity scanner at 09:00 UTC), replayed by hand through the very
text dispatch used, reached the Sauron Vision group at once. Neither the
Markdown nor the preferences had blocked it: nothing had ever sent it.
Only the rule engine (signals/tasks.py) announced a new row; the
opportunity scanner, the fast rules and the TradingView webhook wrote
Signal rows and said nothing.

announce_new_signal does what the rule engine always did, in its order:
  1. the live banner: push_eye_event "new_signal" to every active staff
     user. Signals were the one thing the operator most wants to know the
     moment it happens, and the only events on the socket were fills;
  2. the bell: alerts.notify.notify_new_signal;
  3. the channels: alerts.dispatch.dispatch_signal_alert (Telegram,
     email, WhatsApp by each user's rules and preferences; Telegram once
     per chat, at most 20 signal messages per chat per rolling hour).
Each step is wrapped, and logged at the level the rule engine used: a
broken notifier never aborts a creator whose row is already written.

A SHUT MARKET IS SAID, NEVER HELD BACK (2026-11-12). The operator asked
to keep receiving every signal the moment it fires ("faites que l'on
reçoive quand même les signaux live"), so a signal born while its
instrument's market is shut is announced at once like any other, and each
step says so in plain words with the hour the market opens: the banner's
line, the bell's body, one line of the Telegram message and one clause of
the email and WhatsApp copies (signals/market_hold.shut_label, no switch).
An open market's announcement keeps its bytes.

THE OPTIONAL HOLD (the switch signal_market_hold, OFF on arrival). With
it on, announce_new_signal first asks signals/market_hold.hold_at_birth:
a signal whose market cannot trade now is not announced, one SignalHold
row is written, and the caller gets {"signal_id", "held": the words}. The
signal lifecycle task's release pass announces it once at the open
through announce_released, the same three steps with one more sentence
("fired Sunday 09:00 UTC, while its market was shut"), or drops it with a
named reason. With the switch off, or a hold that cannot be written,
nothing is held.

WHO CALLS IT
  signals/tasks.py          _create_signals_and_notify, after each create
  signals/opportunity_scanner.py
                            _emit_match, only when it CREATES the row on
                            a live pass: never on the reuse branch, never
                            with emit=False, never on an as_of replay
  signals/fast_rules.py     dispatch_event, each row it created, once the
                            audit row is written; never for the HQ "fire
                            test event" button (source="admin"), whose
                            price is typed by hand
  signals/tradingview_webhook.py
                            announce_after_commit: queued for the default
                            worker (signals.tasks.announce_signal) once
                            the row is committed; the HTTP caller never
                            waits on Telegram
Signals written before 2026-09-26 are not backfilled.
"""
from __future__ import annotations

import logging
from functools import partial

logger = logging.getLogger(__name__)


def banner_payload(signal, note: str = "") -> dict:
    """The "new_signal" event the live banner draws.

    A signal announced while its market is shut says so (2026-11-12,
    signals/market_hold): one more key, "market", with the words the
    banner adds to its line ("market shut · opens Sun 22:00 UTC"). An
    open market's payload has no such key and keeps its bytes. A signal
    released by the optional hold carries its `note` under the same key
    ("fired Sunday 09:00 UTC, while its market was shut")."""
    payload = {
        "signal_id": signal.pk,
        "symbol": signal.instrument.symbol,
        "title": signal.title,
        "direction": signal.direction,
        "score": round(float(signal.score or 0), 2),
        "rule_name": signal.rule_name,
        "entry": str(signal.suggested_entry or signal.price_at_signal or ""),
        "stop": str(signal.suggested_stop or ""),
        "target": str(signal.suggested_target or ""),
        "rr": signal.risk_reward_ratio,
        "url": "/signals/",
    }
    from signals.market_hold import shut_label
    market = note or shut_label(signal.instrument)
    if market:
        payload["market"] = market
    return payload


def announce_new_signal(signal) -> dict:
    """Announce one freshly created Signal. Never raises.

    Returns what each step did: {"signal_id", "banner": the staff users
    pushed or "failed", "bell": "ok" or "failed", "channels": what
    dispatch_signal_alert reported or "failed"}; or, when the optional
    hold kept the announcement for the market's open, {"signal_id",
    "held": why}.
    """
    pk = getattr(signal, "pk", None)
    # THE OPTIONAL HOLD (signals/market_hold, the switch
    # signal_market_hold): "" unless the switch is on and this signal's
    # market cannot trade now. A hold that cannot be read announces.
    try:
        from signals.market_hold import hold_at_birth
        held = hold_at_birth(signal)
    except Exception as e:  # noqa: BLE001 — a signal is never swallowed
        logger.warning("[announce] signal #%s: the market hold could not "
                       "be asked (%s): announced now", pk, e)
        held = ""
    if held:
        return {"signal_id": pk, "held": held}
    return _announce(signal)


def announce_released(signal, note: dict) -> dict:
    """Announce a signal the optional hold kept for its market's open
    (signals/market_hold.release_due): the three steps of a birth, in the
    same order, each with one more sentence. `note` is {"clause": for the
    banner and the bell, "line": for the Telegram message and its email
    and WhatsApp copies}. Never raises."""
    return _announce(signal, note=note)


def _announce(signal, note=None) -> dict:
    """The three steps. A birth (note None) keeps its one-argument calls
    of the bell and the channels; a release hands each its sentence."""
    pk = getattr(signal, "pk", None)
    out = {"signal_id": pk}
    clause = str((note or {}).get("clause") or "")
    line = str((note or {}).get("line") or "")

    # 1. The live banner. Best-effort: a broken socket must never abort a
    # creator that has already persisted its row.
    try:
        from django.contrib.auth.models import User

        from dashboard.consumers import push_eye_event
        payload = (banner_payload(signal) if note is None
                   else banner_payload(signal, note=clause))
        pushed = 0
        for u in User.objects.filter(is_active=True, is_staff=True):
            if push_eye_event(u, "new_signal", payload):
                pushed += 1
        out["banner"] = pushed
    except Exception as e:  # noqa: BLE001
        logger.debug("new_signal push failed for pk=%s: %s", pk, e)
        out["banner"] = "failed"

    # 2. The bell.
    try:
        from alerts.notify import notify_new_signal
        if note is None:
            notify_new_signal(signal)
        else:
            notify_new_signal(signal, note=clause)
        out["bell"] = "ok"
    except Exception:  # noqa: BLE001
        logger.exception("notify_new_signal failed for signal pk=%s", pk)
        out["bell"] = "failed"

    # 3. Telegram, email, WhatsApp — not for a born-at-research rule still
    # at research (2026-10-31, signals/rule_birth): ten new rules across
    # the whole universe would spend the 20-an-hour Telegram budget before
    # the signals a bot trades reach the phone. Stored, graded, on the
    # banner and the bell; the channels wait for the ladder.
    try:
        from signals.rule_birth import is_still_at_research
        if is_still_at_research(getattr(signal, "rule_name", "") or ""):
            out["channels"] = "quiet: born at research, no bot trades it"
            return out
    except Exception:  # noqa: BLE001 — an unread stage announces as before
        pass
    try:
        from alerts.dispatch import dispatch_signal_alert
        sent = (dispatch_signal_alert(signal) if note is None
                else dispatch_signal_alert(signal, note=line))
        out["channels"] = sent if isinstance(sent, dict) else "ok"
    except Exception:  # noqa: BLE001
        logger.exception("dispatch_signal_alert failed for signal pk=%s", pk)
        out["channels"] = "failed"
    return out


def queue_announcement(signal_id) -> bool:
    """Hand one announcement to the default worker
    (signals.tasks.announce_signal).

    One publish, no retries (retry=False): outside a transaction the
    commit hook runs at once, inside the request, so Celery's default
    publish retries would hold the HTTP caller while the broker is down.
    A broker that cannot take it is logged at WARNING and the signal
    stays on the platform unannounced. There is no inline fallback on
    purpose: the caller is an HTTP request, and a caller left waiting on
    Telegram retries, which is a duplicate alert.
    """
    try:
        from signals.tasks import announce_signal
        announce_signal.apply_async((signal_id,), retry=False)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[announce] signal #%s could not be queued (%s): it "
                       "is on the platform and was not announced",
                       signal_id, e)
        return False


def announce_after_commit(signal) -> None:
    """For a creator inside an HTTP request: queue the announcement once
    the row is committed (at once outside a transaction: this project
    sets no ATOMIC_REQUESTS), so the worker never reads a row that is not
    there yet and the caller never waits on Telegram, only on one publish
    to the broker."""
    try:
        from django.db import transaction
        transaction.on_commit(partial(queue_announcement, signal.pk),
                              robust=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("[announce] signal #%s: the announcement could not "
                       "be scheduled (%s)", getattr(signal, "pk", None), e)
