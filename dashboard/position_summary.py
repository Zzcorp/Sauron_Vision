# -*- coding: utf-8 -*-
"""THE POSITION PAGE'S PLAIN SUMMARY (2026-09-26).

The operator, on /forensics/<id>/: "I want the position pages detail to be
styled in a perfect manner for the father, this is too nerdy". The father
runs Sauron from his phone for three weeks. This builds the words and the
numbers at the top of that page — for every position, open or closed,
paper or live — out of readers the platform already has, so the summary
can never quote a figure another page would contradict:

  * the mark and the open P&L: portfolio.services._normalize_trades, the one
    reader the positions page marks a bot row with (LiveQuote.last, the
    row's value_per_unit, the sign). Never a broker call and never
    preview_close: the live endpoint runs this on a 15-second timer;
  * the time of that mark: the same LiveQuote row's updated_at, called
    stale past views_system_health.QUOTE_STALE_SECONDS, the platform's own
    quote bound;
  * whether the market is open: core.exchange_status.market_status_for,
    the instrument page's answer — no hours are invented here;
  * the venue: the row's own stamps (metadata broker / broker_env, written
    by AssetBot.venue_stamps from the client that filled it) and
    trade.paper — never today's routing rule;
  * the risk: manual_close._risk_dollars, the size of 1R the close dialog
    and the positions card already quote; the PIN: manual_close.requires_pin,
    the rule the close endpoint enforces;
  * how it ended: the outcome code bot_grading, the kill switch and
    reconciliation write, refined by the tag _close_trade appends to the
    reason ("closed:MANUAL" is a hand close). An unknown code reads "Closed".

Nothing here writes, sends or claims. An unknown is an em dash or a
sentence that says so — never 0, never "None", never a raw key.
"""
from __future__ import annotations

import logging
import re
from datetime import timezone as _utc_tz
from decimal import Decimal, InvalidOperation

from django.utils import timezone

logger = logging.getLogger(__name__)

DASH = "—"

#: The page's refresh cadence, stated once so the words match the script.
REFRESH_SECONDS = 15

#: adapter_key -> the name printed on the page (capabilities.ADAPTER_CLASS_KEYS).
BROKER_NAMES = {
    "etoro": "eToro",
    "ibkr": "IBKR",
    "oanda": "OANDA",
    "saxo": "Saxo",
    "alpaca": "Alpaca",
    "binance": "Binance",
    "binance_futures": "Binance Futures",
}

#: The same carriers in their rehearsal world (broker_env == "paper").
DEMO_NAMES = {
    "etoro": "eToro demo",
    "ibkr": "IBKR paper account",
    "oanda": "OANDA practice",
    "saxo": "Saxo simulation",
    "alpaca": "Alpaca paper",
    "binance": "Binance testnet",
    "binance_futures": "Binance testnet",
}

#: The outcome codes the code writes (AssetBotTrade.OUTCOME_CHOICES).
#: "manual_close" is refined by the close tag below: bot_grading's default,
#: the kill switch and reconciliation all write it too.
ENDINGS = {
    "hit_target": "Target reached",
    "stopped_out": "Stop loss hit",
    "time_stop": "Time limit reached",
    "expired": "Closed at expiry",
    "manual_close": "Closed",
}

#: Tokens a rule name spells in capitals when it is read aloud.
_ACRONYMS = frozenset({
    "adx", "ai", "atr", "bb", "btc", "cci", "cot", "cpi", "dmi", "dxy",
    "ema", "eth", "fomc", "fvg", "fx", "gdp", "hma", "ict", "macd", "mfi",
    "ml", "ndx", "nfp", "obv", "orb", "pmi", "psar", "roc", "rsi", "sar",
    "sma", "smc", "spx", "vix", "vwap", "wma",
})

#: Rule names that mean "a person took it", never a strategy.
_MANUAL_RULES = frozenset({"manual_take", "manual"})

#: The engine's fallback names when no single rule led the entry
#: (asset_engine/base.py: the weighted verdict and the signal consensus).
_CONSENSUS_RULES = frozenset({"asset_bot_weighted_consensus",
                              "asset_bot_signal_consensus"})


# ── formatting ───────────────────────────────────────────────────────────

def _num(value):
    """float, or None for anything that is not a number."""
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None          # NaN is not a number here


def money(value, ccy="", signed=False):
    """1,234.56 USD / +17.38 USD, or the em dash."""
    n = _num(value)
    if n is None:
        return DASH
    text = "{:+,.2f}".format(n) if signed else "{:,.2f}".format(n)
    return (text + " " + ccy).strip() if ccy else text


def percent(value, signed=True):
    n = _num(value)
    if n is None:
        return DASH
    return ("{:+.2f}%" if signed else "{:.2f}%").format(n)


def quantity(value):
    """A quantity without trailing zeros: 1,000 / 0.0002 / 0.5."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return DASH
    if not d.is_finite():
        return DASH
    d = abs(d).normalize()
    if d == d.to_integral():
        d = d.quantize(Decimal(1))
    return format(d, ",f")


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def duration_words(seconds):
    """"3 days 4 hours", "2 hours 5 minutes", "less than a minute"."""
    n = _num(seconds)
    if n is None:
        return DASH
    total = int(max(0, n))
    if total < 60:
        return "less than a minute"
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(_plural(days, "day"))
    if hours:
        parts.append(_plural(hours, "hour"))
    if not days and minutes:
        parts.append(_plural(minutes, "minute"))
    return " ".join(parts[:2])


_UNIT = {"d": "day", "h": "hour", "m": "minute"}


def countdown_words(text):
    """exchange_status's "1d 2h" / "5h 3m" / "45m" / "now" in words, or ""."""
    raw = str(text or "").strip().lower()
    if raw == "now":
        return "a moment"
    found = re.findall(r"(\d+)\s*([dhm])", raw)
    if not found:
        return ""
    return " ".join(_plural(int(n), _UNIT[u]) for n, u in found)


def utc_clock(moment, with_date=False):
    """"14:05:12 UTC" or "2026-09-26 14:05 UTC"; the em dash when absent."""
    if moment is None:
        return DASH
    at = moment.astimezone(_utc_tz.utc)
    return at.strftime("%Y-%m-%d %H:%M UTC" if with_date else "%H:%M:%S UTC")


def rule_words(name):
    """A rule name read aloud: golden_cross -> "Golden cross",
    rsi_reversal_4h -> "RSI reversal 4h". "" for none and for the manual
    lane, which is not a strategy. The engine's consensus fallbacks and a
    TradingView webhook's "tradingview:<strategy>" read as what they are."""
    raw = str(name or "").strip()
    if not raw or raw.lower() in _MANUAL_RULES:
        return ""
    if raw.lower() in _CONSENSUS_RULES:
        return "Several of Sauron's signals agreed"
    if re.match(r"tradingview(?![a-z0-9])", raw.lower()):
        return "TradingView alert"
    words = []
    for token in re.split(r"[_\-\s.:/|]+", raw):
        if not token:
            continue
        low = token.lower()
        if low in _ACRONYMS or (token.isupper() and len(token) <= 5
                                and token.isalpha()):
            words.append(low.upper())
        elif re.fullmatch(r"\d+[a-z]{1,2}", low):
            words.append(low)
        elif token.islower() or token.isupper():
            words.append(low)
        else:
            words.append(token)
    text = " ".join(words)
    return text[:1].upper() + text[1:]


# ── the row's facts ──────────────────────────────────────────────────────

def venue_of(trade):
    """(money words, real?, broker words) from the ROW's own stamps.

    trade.paper is the platform's simulator whatever else the row carries.
    A live-mode row stamped broker_env "paper" traded in a broker's
    rehearsal world (the eToro demo): simulated money, but held at a
    broker — so the close endpoint still asks for the PIN (requires_pin is
    `not trade.paper`) and the page says why. A live row with no stamp is
    real money at a broker the row never named: said so, not guessed.
    """
    meta = trade.metadata or {}
    carrier = str(meta.get("broker") or "").strip().lower()
    world = str(meta.get("broker_env") or "").strip().lower()
    if trade.paper or carrier == "paper":
        return "Simulated", False, "Paper trading"
    named = BROKER_NAMES.get(carrier) or carrier.replace("_", " ").title()
    if world == "paper":
        demo = DEMO_NAMES.get(carrier) or (
            (named + " demo") if carrier else "Broker demo account")
        return "Simulated", False, demo
    return "Real money", True, (named or "Broker not recorded")


#: THE THREE MONEY WORLDS (2026-09-30), one word each, read by every
#: surface through world_of and the money_world tag. The operator: live and
#: paper "still light" for him and his father. A demo row (paper False,
#: broker_env "paper") is simulated money and never prints as real.
WORLD_LIVE, WORLD_DEMO, WORLD_PAPER = "live", "demo", "paper"
WORLD_WORDS = {WORLD_LIVE: "REAL MONEY", WORLD_DEMO: "DEMO",
               WORLD_PAPER: "PAPER"}


def world_of(row) -> str:
    """"live", "demo" or "paper" from the row's own stamps, as venue_of
    reads them; "" when the row states no venue at all (a legacy Position,
    whose `paper` is None). Takes a trade, any object with `paper` and
    `metadata`, or a dict carrying the same keys."""
    if isinstance(row, dict):
        paper, meta = row.get("paper"), row.get("metadata")
    else:
        paper, meta = getattr(row, "paper", None), getattr(row, "metadata", None)
    if paper is None:
        return ""
    meta = meta if isinstance(meta, dict) else {}
    carrier = str(meta.get("broker") or "").strip().lower()
    if paper or carrier == "paper":
        return WORLD_PAPER
    if str(meta.get("broker_env") or "").strip().lower() == "paper":
        return WORLD_DEMO
    return WORLD_LIVE


def _state(trade):
    """(kind, chip words, "open" | "closed") for the row's status."""
    from bot_program.asset_engine.base import is_entry_working
    status = trade.status
    if status == "OPEN":
        if is_entry_working(trade):
            return "working", "Order waiting", "open"
        return "open", "Open", "open"
    if status == "CLOSE_PENDING":
        return "pending", "Closing", "open"
    if status == "CLOSED":
        return "closed", "Closed", "closed"
    if status == "CANCELED":
        return "canceled", "Withdrawn", "closed"
    return "error", "Needs attention", "closed"


def ending_words(trade):
    """How a closed position ended, in words the father reads."""
    reason = trade.reason or ""
    outcome = (trade.outcome or "").strip()
    # 2026-10-07: an exit booked at the level NEAREST the price when the
    # close was found is an estimate of the cause too — never "Stop loss
    # hit" as a fact.
    basis = (trade.metadata or {}).get("exit_priced_at")
    if isinstance(basis, dict) and basis.get("evidence") == "nearest" \
            and outcome in ("stopped_out", "hit_target"):
        return ("Closed at the broker, most likely by its stop (an estimate)"
                if outcome == "stopped_out" else
                "Closed at the broker, most likely at its target (an estimate)")
    if outcome == "manual_close" or not outcome:
        if "closed:MANUAL" in reason:
            return "Closed by hand"
        if "closed:FUNDING" in reason:
            return "Closed to make room for a new trade"
        if "reconciled-orphan" in reason:
            return "Closed at the broker"
        if "EMERGENCY FLATTEN" in reason:
            return "Closed by the kill switch"
    return ENDINGS.get(outcome, "Closed")


def _signal_rule(signal_id):
    """The rule of the signal a hand-taken trade came from, or ""."""
    try:
        sid = int(signal_id)
    except (TypeError, ValueError):
        return ""
    from signals.models import Signal
    row = Signal.objects.filter(pk=sid).only("id", "rule_name").first()
    return (row.rule_name or "") if row is not None else ""


def why_words(trade):
    """One sentence: what Sauron saw, and who pulled the trigger."""
    meta = trade.metadata or {}
    sym = trade.symbol
    manual = bool(meta.get("manual")) or (
        (trade.rule_name or "").lower() in _MANUAL_RULES)
    if manual:
        sid = meta.get("signal_id")
        if sid:
            rule = rule_words(_signal_rule(sid))
            if rule:
                return "%s on %s — taken by hand from signal #%s." % (
                    rule, sym, sid)
            return "Taken by hand on %s from signal #%s." % (sym, sid)
        return "Taken by hand on %s from its instrument page." % sym
    rule = rule_words(trade.rule_name)
    if rule:
        return "%s on %s — opened automatically by Sauron." % (rule, sym)
    return "Opened automatically by Sauron on %s." % sym


def _units(asset_class):
    return {"stock": "shares", "etf": "shares",
            "options": "contracts"}.get(asset_class or "", "units")


def _unconverted_ccy(trade, ccy):
    """The currency a forex row's marked figures are really in, when it is
    not the account's; "" otherwise.

    A forex row opened before value_per_unit was stamped is marked with
    value_per_unit 1 (portfolio.services.value_per_unit, the positions
    page's reader), so its profit and its size come out in the pair's
    QUOTE currency — a GBPJPY row's "1,100" is yen. The number is the
    positions page's; only its label is corrected here. Sizing refuses to
    open a forex trade without the rate, so only an older row reaches this.
    """
    if (trade.asset_class or "") != "forex":
        return ""
    if (trade.metadata or {}).get("value_per_unit"):
        return ""
    letters = re.sub(r"[^A-Za-z]", "", trade.symbol or "").upper()
    if len(letters) != 6:
        return ""
    quote = letters[3:]
    return "" if quote == (ccy or "").upper() else quote


def _away(mark, level, resolves_below):
    """"5.2% away" / "already reached" / "" — views._pos_distance's reading
    (the positions card's), at one decimal."""
    from dashboard.views import _pos_distance
    pct, through = _pos_distance(mark, level, resolves_below)
    if pct == "":
        return ""
    if through:
        return "already reached"
    return "{:.1f}% away".format(float(pct))


def _level(label, text, away):
    return "the %s %s%s" % (label, text, (" (%s)" % away) if away else "")


def _fact(label, value, sub=""):
    return {"label": label, "value": value, "sub": sub}


# ── the summary ──────────────────────────────────────────────────────────

def build_summary(trade, now=None):
    """Everything the summary shows, formatted — see the module docstring."""
    from bot_program.manual_close import _risk_dollars, requires_pin
    from core.price_format import format_price, price_decimals
    from dashboard.views_system_health import QUOTE_STALE_SECONDS
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    from portfolio.services import _normalize_trades, value_per_unit

    now = now or timezone.now()
    ac = trade.asset_class or ""
    sym = trade.symbol or ""
    ccy = (getattr(trade.config, "base_currency", "") or "USD").strip()
    is_long = (trade.side or "").upper() in ("BUY", "LONG")
    headline = "%s %s" % ("Long" if is_long else "Short", sym)
    kind, status_text, state = _state(trade)
    money_text, real, broker_text = venue_of(trade)
    # The currency the MARKED figures (open profit, size) are in: the
    # account's, or an older forex row's quote currency — never mislabelled.
    raw_ccy = _unconverted_ccy(trade, ccy)
    mark_ccy = raw_ccy or ccy
    # Held at a broker (real money or a broker's demo), not in the
    # platform's own simulator: venue_of says "Paper trading" only there.
    at_broker = broker_text != "Paper trading"

    def price(value):
        return format_price(value, ac, sym)

    # The positions page's own reader: the row it would print for this trade.
    try:
        rows = _normalize_trades([trade])
    except Exception:  # noqa: BLE001 — unmarked is a state, not a crash
        logger.exception("[position page] mark failed for #%s", trade.id)
        rows = []
    row = rows[0] if rows else None
    quote = (LiveQuote.objects.select_related("instrument")
             .filter(instrument__symbol=sym).first())
    inst = (quote.instrument if quote is not None
            else Instrument.objects.filter(symbol=sym).first())

    entry = _num(trade.entry_price)
    held_from = trade.opened_at
    facts, notes = [], []
    open_like = state == "open"

    risk = _risk_dollars(trade)
    if kind == "working":
        # Nothing is held yet: the risk is the one it takes on IF it fills.
        risk_words = ("If it fills, it carries %s of risk: the loss at its "
                      "stop." % money(risk, ccy) if risk > 0 else
                      "No stop is set on the order, so the risk it would "
                      "carry is unknown.")
    elif risk > 0:
        risk_words = ("It %s %s of risk: the loss at the stop it opened with."
                      % ("carries" if open_like else "carried",
                         money(risk, ccy)))
    else:
        risk_words = ("No stop was recorded when it opened, so the risk it "
                      "%s is unknown." % ("carries" if open_like else "carried"))

    summary = {
        "headline": headline,
        "status_kind": kind,
        "status_text": status_text,
        "state": state,
        "money_text": money_text,
        "real": real,
        "broker_text": broker_text,
        "ccy": ccy,
        "decimals": price_decimals(trade.entry_price, ac, sym),
        "why": why_words(trade),
        "risk_words": risk_words,
        "checked_at": utc_clock(now),
        "refresh_seconds": REFRESH_SECONDS,
        "closable": kind in ("open", "working", "pending"),
        "action_text": {"working": "Withdraw this order",
                        "pending": "Retry the close"}.get(
                            kind, "Close this position"),
        "needs_pin": bool(requires_pin(trade)),
        "facts": facts,
        "notes": notes,
    }
    if real:
        summary["close_note"] = ("This is real money. A close at the broker "
                                 "cannot be undone.")
    elif summary["needs_pin"]:
        summary["close_note"] = ("This position is held at a broker, so your "
                                 "trading PIN is needed to close it.")
    else:
        summary["close_note"] = ("This is a simulated position: no real money "
                                 "moves.")

    if open_like:
        mark = _num(row.current_price) if row is not None else None
        pnl = _num(row.unrealized_pnl) if row is not None else None
        pnl_pct = _num(row.unrealized_pnl_pct) if row is not None else None
        # WHEN THE PRICE SHOWN WAS READ (2026-10-08): the row's own mark
        # time (venue_mark.resolve — the venue's stamp for a real row, the
        # quote's time for a quote), never the LiveQuote's when the price
        # is the venue's: a fresh feed beside a two-day-old venue print
        # said "as of" the wrong one.
        mark_src = getattr(row, "mark_source", None) if row is not None \
            else None
        waiting = mark_src == "awaiting_venue"
        quote_at = getattr(row, "mark_at", None) if row is not None else None
        if quote_at is None and mark_src in (None, "quote"):
            quote_at = quote.updated_at if quote is not None else None
        age = ((now - quote_at).total_seconds()
               if quote_at is not None else None)

        if kind == "working":
            # The sentence below says why there is no number; said once.
            summary.update(big_label="Profit or loss", big_value=DASH,
                           big_tone="", big_sub="")
        elif pnl is None and waiting:
            summary.update(
                big_label="Profit or loss now", big_value=DASH, big_tone="",
                big_sub=("Waiting for the venue's price: the platform's "
                         "own quote for %s is a different instrument, so it "
                         "is not used." % sym))
        elif pnl is None:
            summary.update(big_label="Profit or loss now", big_value=DASH,
                           big_tone="",
                           big_sub="It shows as soon as a live price arrives.")
        else:
            summary.update(
                big_label="Profit or loss now",
                big_value=money(pnl, mark_ccy, signed=True),
                big_tone="up" if pnl > 0 else "down" if pnl < 0 else "",
                big_sub=("%s of the position" % percent(pnl_pct)
                         if pnl_pct is not None else ""))

        facts.append(_fact(
            "Order price" if kind == "working" else "Entry price",
            price(trade.entry_price),
            ("placed " if kind == "working" else "opened ")
            + utc_clock(held_from, True)))
        if mark is not None:
            facts.append(_fact("Price now", price(mark),
                               ("the venue's own rate, as of "
                                if mark_src in ("venue", "venue_stale")
                                else "as of ") + utc_clock(quote_at)))
        elif waiting:
            facts.append(_fact("Price now", DASH,
                               "waiting for the venue's price"))
        else:
            facts.append(_fact("Price now", DASH, "no live price yet"))

        qty = abs(_num(trade.qty) or 0.0)
        basis = mark if mark is not None else entry
        size = (qty * basis * value_per_unit(trade)
                if qty and basis else None)
        facts.append(_fact(
            "Order size" if kind == "working" else "Position size",
            money(size, mark_ccy),
            "%s %s at the %s price" % (quantity(trade.qty), _units(ac),
                                       "current" if mark is not None
                                       else "entry")))

        stop = _num(trade.stop_loss)
        target = _num(trade.take_profit)
        stop_away = _away(mark, stop, is_long) if stop is not None else ""
        target_away = (_away(mark, target, not is_long)
                       if target is not None else "")
        facts.append(_fact("Stop", price(stop) if stop is not None
                           else "Not set", stop_away))
        facts.append(_fact("Target", price(target) if target is not None
                           else "Not set", target_away))
        facts.append(_fact(
            # A working order is not held yet: it has been waiting.
            "Waiting for" if kind == "working" else "Held for",
            duration_words((now - held_from).total_seconds()
                           if held_from else None)))

        if kind == "working":
            summary["sentence"] = ("The entry order is waiting at the broker. "
                                   "Nothing has filled yet, so there is no "
                                   "profit or loss.")
        elif kind == "pending":
            tries = int(_num((trade.metadata or {}).get(
                "close_retry_attempts")) or 0)
            summary["sentence"] = (
                "Sauron asked the broker to close it and the broker refused"
                + (" %s" % _plural(tries, "time") if tries else "")
                + ". It is still open there; Sauron tries again every "
                  "5 minutes.")
        else:
            s_text = price(stop) if stop is not None else ""
            t_text = price(target) if target is not None else ""
            # "protected" is the engine's own fact that a stop RESTS at the
            # venue (asset_engine/base.py). A row held at a broker without
            # it is guarded by Sauron's engine alone: said so, never "by
            # itself" (the IBKR positions of 2026-09-23 had no stop resting).
            protected = bool((trade.metadata or {}).get("protected"))
            engine_only = at_broker and not protected
            if engine_only:
                closes, tail = ("Sauron closes it at",
                                " as long as Sauron itself is running; the broker does not "
                                "hold %s" % ("these levels"
                                             if stop is not None
                                             and target is not None
                                             else "this level"))
            else:
                closes, tail = "It closes by itself at", ""
            if stop is not None and target is not None:
                sentence = "%s %s or %s%s." % (
                    closes, _level("stop", s_text, stop_away),
                    _level("target", t_text, target_away), tail)
            elif stop is not None:
                sentence = ("%s %s%s. No target is set."
                            % (closes, _level("stop", s_text, stop_away),
                               tail))
            elif target is not None:
                sentence = ("%s %s%s. No stop is set, so a loss is not "
                            "capped." % (closes, _level("target", t_text,
                                                        target_away), tail))
            else:
                sentence = ("No stop and no target are set: it stays open "
                            "until someone closes it.")
            if protected and (stop is not None or target is not None):
                sentence += (" The broker holds these levels, so they work "
                             "even when Sauron is offline.")
            summary["sentence"] = sentence

        market = None
        try:
            from core.exchange_status import market_status_for
            market = market_status_for(
                getattr(inst, "asset_class", "") or ac,
                getattr(inst, "exchange", "") or "",
                now_utc=now, symbol=sym)
        except Exception:  # noqa: BLE001 — no answer is no note
            logger.debug("[position page] market status unavailable",
                         exc_info=True)
        shut = bool(market) and not market.get("is_open", True)
        if shut:
            when = countdown_words(market.get("time_until_change"))
            notes.append({"tone": "info", "text": (
                "The market for %s is shut right now%s. The price does not "
                "move until then." % (
                    sym, ("; it opens again in " + when) if when else ""))})
        if waiting and kind != "working":
            notes.append({"tone": "warn", "text": (
                "No price has come in from the venue for %s yet. The "
                "platform's own quote for it is a different instrument (a "
                "futures contract or a cash index), so valuing the position "
                "against it would show the gap between the two as profit or "
                "loss; nothing is shown until the venue's price arrives."
                % sym)})
        elif age is not None and age > QUOTE_STALE_SECONDS:
            if shut:
                text = ("The last price came in %s ago, which is normal "
                        "while the market is shut." % duration_words(age))
            else:
                text = ("The price is stale: the last one came in %s ago, so "
                        "the profit or loss may be out of date."
                        % duration_words(age))
            notes.append({"tone": "warn", "text": text})
        elif mark is None and not waiting and kind != "working":
            notes.append({"tone": "warn", "text": (
                "No live price has come in for %s yet, so the profit or loss "
                "cannot be shown." % sym)})
        if raw_ccy:
            notes.append({"tone": "info", "text": (
                "This position was opened before Sauron stored a conversion "
                "rate, so its profit or loss and its size are shown in %s, "
                "not %s." % (raw_ccy, ccy))})
        return summary

    # ── closed, withdrawn or abandoned ──────────────────────────────────
    ended = trade.closed_at
    if kind == "canceled":
        summary.update(big_label="Result", big_value="Nothing traded",
                       big_tone="", big_sub="")
        summary["sentence"] = (
            "Withdrawn by the kill switch before it filled."
            if "EMERGENCY FLATTEN" in (trade.reason or "")
            else "The order was withdrawn before it filled, so nothing was "
                 "traded.")
    elif kind == "error":
        summary.update(big_label="Result", big_value=DASH, big_tone="",
                       big_sub="")
        summary["sentence"] = (
            "Sauron stopped trying to close this position after the broker "
            "refused several times. It may still be open at the broker: "
            "check it there.")
    else:
        pnl = _num(trade.pnl)
        r = _num(trade.realized_r)
        r_words = ""
        if r is not None:
            r_words = ("{:.2f} times the risk".format(r) if r >= 0 else
                       "a loss of {:.2f} times the risk".format(abs(r)))
        summary.update(
            big_label="Result",
            big_value=money(pnl, ccy, signed=True),
            big_tone=("up" if pnl and pnl > 0 else
                      "down" if pnl and pnl < 0 else ""),
            big_sub=r_words)
        summary["sentence"] = (
            "%s on %s." % (ending_words(trade), utc_clock(ended, True))
            if ended else ending_words(trade) + ".")
        if pnl is None:
            notes.append({"tone": "warn", "text": (
                "The exit could not be priced, so the result is unknown.")})

    facts.append(_fact("Entry price", price(trade.entry_price),
                       "opened " + utc_clock(held_from, True)))
    if kind == "closed":
        facts.append(_fact("Exit price", price(trade.exit_price),
                           ("closed " + utc_clock(ended, True))
                           if ended else ""))
    qty = abs(_num(trade.qty) or 0.0)
    size = qty * entry * value_per_unit(trade) if qty and entry else None
    facts.append(_fact("Position size", money(size, mark_ccy),
                       "%s %s at the entry price" % (quantity(trade.qty),
                                                     _units(ac))))
    if raw_ccy and size is not None:
        notes.append({"tone": "info", "text": (
            "This position was opened before Sauron stored a conversion "
            "rate, so its size is shown in %s, not %s." % (raw_ccy, ccy))})
    if held_from and ended:
        facts.append(_fact("Held for", duration_words(
            (ended - held_from).total_seconds())))
    return summary
