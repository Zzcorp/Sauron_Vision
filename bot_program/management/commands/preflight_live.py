"""Answer, in one pass, whether it is safe to arm REAL MONEY right now.

`why_no_trade` answers "why is nothing trading". `check_feeds` answers "are
quotes arriving". Neither answers the question an operator actually asks with
their finger over the arming button, and that question has about a dozen parts
spread across six modules — several of which fail SILENTLY in the expensive
direction:

  * the declared pool is a number typed into a form. `capital` is the
    denominator of the whole per-config risk stack (sizing divides by it, the
    daily-loss floor is a percentage of it, the drawdown curve starts at it)
    and arming live checks only the PIN. A pool declared LARGER than the
    account loosens every limit the operator set: 2% of a declared 100,000
    against a real 20,000 is a 10% daily loss.
  * `base_currency` on the config defaults to "USD". A UK ISA is GBP, the
    book defaults to EUR, and this codebase has no FX conversion anywhere by
    design — so three currencies can meet in one risk calculation with
    nothing to make them disagree out loud.
  * `broker_account_sync` is a PlatformComponent created DISABLED, while
    `tracking_freeze_reason` refuses every entry on an account-following pool
    until an equity reading lands. A live bot can therefore be armed, enabled,
    and frozen for hours with no order and no complaint.
  * the port decides paper/live. A port IBKR does not ship makes `env` None,
    which is not paper and not safe.
  * every alert ends in ONE external sender chosen per user, and the sender
    refuses silently when its own precondition is missing — a bot token in
    the WORKER's environment plus a chat id on a row only the notification
    preferences form creates. A platform can trade for weeks with every
    alert it raised living in the in-app bell (measured 2026-09-23).

EVERYTHING HERE IS READ-ONLY. It writes nothing, places no order, and makes
no broker round trip: every number comes from a cached column, because a
broker call in front of an arming decision is a network dependency at exactly
the wrong moment. Age is reported beside every reading so a stale one cannot
pass for a fresh one.

    python manage.py preflight_live
    python manage.py preflight_live --user mathe
"""
from django.core.management.base import BaseCommand


# How old the newest broker equity reading may be before a LIVE account is
# considered unreachable. `broker_account_sync` runs every 15 minutes, so two
# hours is eight missed passes — long enough to ride out a restart or a 2FA
# re-login, short enough that a Gateway which died at the open is named before
# the session is over.
BROKER_READING_STALE_HOURS = 2.0

# Imported, never restated. Three modules enforce the same six hours, and a
# fourth copy of the number here would be the copy that drifts:
#   signals/performance.py    _bar_close_fallback  -> no price, no outcome
#   signals/lifecycle.py      the SMC pass         -> no resolution
#   engine/paper_trader.py    ticker()             -> cannot mark a position
# Past it, a symbol produces no evidence at all. That is correct for a shut
# market and a failure for an open one, which is why the line below prints
# the market beside the age.
from signals.performance import MAX_BAR_AGE_SECONDS  # noqa: E402
BAR_DEAD_HOURS = MAX_BAR_AGE_SECONDS / 3600.0

# A ten-minute refresh (config/celery.py "refresh-bot-bars", schedule 600.0)
# writing 4h candles: the newest bar's own period is up to four hours wide,
# so age alone cannot detect a late writer. Only a gap well past one whole
# period can, and 4h + a margin is the honest line.
BAR_LATE_HOURS_WHILE_OPEN = 5.0

# Past this, "the market is shut" stops being an explanation. Borrowed from
# signals/lifecycle.py, which already decided four days is too old for the
# slowest frame this platform reads: a long weekend plus a holiday fits
# inside it, a dead bar writer does not. A closed market excused 923.6h -
# 38 days - before this line existed.
from signals.lifecycle import (  # noqa: E402
    MAX_BAR_AGE_SECONDS_BY_TIMEFRAME as _BAR_AGE_BY_TF)
BAR_SHUT_GRACE_HOURS = _BAR_AGE_BY_TF["1d"] / 3600.0

# IBKR's own floor, in IBKR's own words (Error 201, 2026-09-10, on the first
# GLDM order from a 500 EUR account): "MINIMUM OF 2000 USD (OR EQUIVALENT IN
# OTHER CURRENCIES) IS REQUIRED IN ORDER TO PURCHASE ON MARGIN, SELL SHORT,
# TRADE CURRENCY OR FUTURE." Below it an account buys stocks and ETFs with
# settled cash IN THE INSTRUMENT'S CURRENCY and does nothing else — and a
# EUR balance buying a USD ETF is a USD loan, which is margin, which is how
# a plain long on an 87-dollar ETF met this rule.
IBKR_MARGIN_FLOOR_USD = 2000.0
# Asset classes that are margin products at IBKR whatever the size: currency
# (CASH and FX CFDs), futures, commodity CFDs.
IBKR_FLOOR_CLASSES = {"forex", "futures", "commodity"}
# Conservative BOUNDS on how many USD one unit has been worth this decade —
# bounds, not rates. The platform converts nothing, by design; the floor is
# read only when the answer is the same at both ends of the band, and is
# called unsure otherwise.
USD_PER_UNIT_BOUNDS = {
    "USD": (1.0, 1.0), "EUR": (0.95, 1.30), "GBP": (1.05, 1.60),
    "CHF": (0.95, 1.35), "CAD": (0.65, 0.90), "AUD": (0.55, 0.85),
    "NZD": (0.50, 0.80), "JPY": (0.0055, 0.0120), "HKD": (0.12, 0.14),
    "SGD": (0.68, 0.82),
}


def _ibkr_floor(value, currency) -> str:
    """'below', 'above' or 'unsure' against IBKR's 2,000 USD floor."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "unsure"
    lo, hi = USD_PER_UNIT_BOUNDS.get((currency or "").upper(), (None, None))
    if lo is None:
        return "unsure"
    if value * hi < IBKR_MARGIN_FLOOR_USD:
        return "below"
    if value * lo >= IBKR_MARGIN_FLOOR_USD:
        return "above"
    return "unsure"


def _foreign_currency_symbols(configs, account_ccy) -> list:
    """'GLDM (USD)' for every symbol an enabled live config trades in a
    currency the account does not hold."""
    from instruments.models import Instrument
    want = (account_ccy or "").upper()
    symbols = sorted({s for cfg in configs if cfg.enabled
                      for s in (cfg.symbols or []) if s})
    if not symbols or not want:
        return []
    rows = Instrument.objects.filter(symbol__in=symbols).values_list(
        "symbol", "currency")
    return [f"{sym} ({ccy})" for sym, ccy in rows
            if ccy and ccy.upper() != want]


def _age(dt, now):
    """Human age of a timestamp, or "never"."""
    if dt is None:
        return "never"
    h = (now - dt).total_seconds() / 3600.0
    if h < 1:
        return f"{h * 60:.0f}m ago"
    if h < 48:
        return f"{h:.1f}h ago"
    return f"{h / 24:.1f}d ago"


def _bar_age_hours(newest, now) -> float:
    return (now - newest).total_seconds() / 3600.0


def _market_for(row, now=None):
    """The market clock this instrument keeps AT `now`, or None when
    unknowable. Until 2026-09-17 this read the wall regardless of the
    `now` its callers were given — right in production by coincidence,
    wrong under every fixed clock a test could set."""
    if not row:
        return None
    try:
        from core.exchange_status import market_status_for
        return market_status_for(row.get("instrument__asset_class") or "",
                                 row.get("instrument__exchange") or "",
                                 now_utc=now,
                                 symbol=row.get("instrument__symbol") or "")
    except Exception:  # noqa: BLE001 — a missing clock must not take the page
        return None


def _market_note(row, newest, now) -> str:
    """The clause that stops one number from carrying two diagnoses."""
    if newest is None:
        return ""
    market = _market_for(row, now)
    if market is None:
        return "  (market clock unknown)"
    age = _bar_age_hours(newest, now)
    name = market.get("session") or market.get("code") or "?"
    if market.get("is_open"):
        if age >= BAR_LATE_HOURS_WHILE_OPEN:
            return f"  · {name} OPEN and the bar is {age:.1f}h behind"
        return f"  · {name} open"
    if age >= BAR_SHUT_GRACE_HOURS:
        return (f"  · {name} shut, but {age / 24:.1f} DAYS of bars are "
                f"missing — a closed market does not explain this")
    if age >= BAR_DEAD_HOURS:
        return (f"  · {name} shut — past {BAR_DEAD_HOURS:.0f}h, this symbol "
                f"resolves nothing until it reopens")
    return f"  · {name} shut"


def _bar_verdict(row, newest, now) -> tuple:
    """(kind, market_name, age_hours) — the DECISION, with no prose.

    kind is one of:
      "ok"          nothing to say
      "late_open"   the market is open and the bar is behind: the feed
                    stopped, and an armed bot is deciding on a stale candle
      "shut_stale"  shut, past the six hours every price path enforces:
                    correct and temporary, and worth reading once
      "shut_dead"   "shut" for longer than a long weekend explains
      "unknown"     no market clock for this instrument

    Split out from `_bar_findings` on 2026-09-15 because one function that
    both decides and phrases forces every caller to take the same phrasing.
    `paper_readiness` walks a whole fleet and needs to group sixty-one
    identical verdicts into one line; the preflight walks a handful and
    wants one line each. Same rule, two renderings.
    """
    market = _market_for(row, now)
    if market is None:
        return ("unknown", "?", _bar_age_hours(newest, now))
    age = _bar_age_hours(newest, now)
    name = market.get("session") or market.get("code") or "?"
    if market.get("is_open"):
        if age >= BAR_LATE_HOURS_WHILE_OPEN:
            return ("late_open", name, age)
        return ("ok", name, age)
    if age >= BAR_SHUT_GRACE_HOURS:
        return ("shut_dead", name, age)
    if age >= BAR_DEAD_HOURS:
        return ("shut_stale", name, age)
    return ("ok", name, age)


def _bar_findings(sym, row, newest, now, blockers, warnings) -> None:
    """Split the one number into the two things it can mean.

    An OPEN market with a bar hours behind is a feed that stopped: a
    blocker, because an armed bot decides on that candle. A SHUT market
    past the six-hour mark is correct and temporary — but it is also the
    reason a paper campaign accumulates evidence only inside sessions, and
    an operator counting on 90 days of fills should read it once rather
    than discover it on day 90.
    """
    kind, name, age = _bar_verdict(row, newest, now)
    if kind in ("ok", "unknown"):
        return
    if kind == "late_open":
        blockers.append(
            f"{sym}: {name} is OPEN and the newest 4h bar is {age:.1f}h "
            f"old — refresh-bot-bars runs every 10 minutes, so the feed "
            f"has stopped. An armed bot is deciding on a stale candle")
        return
    if kind == "shut_dead":
        blockers.append(
            f"{sym}: {age / 24:.1f} days of 4h bars are missing. {name} being "
            f"shut explains a weekend, not this — the bar writer has "
            f"stopped for this symbol and no rule can form a decision on it")
        return
    if True:
        warnings.append(
            f"{sym}: {name} is shut and the newest bar is {age:.1f}h old, "
            f"past the {BAR_DEAD_HOURS:.0f}h limit the paper venue and the "
            f"signal lifecycle both enforce. Correct for a shut market — and "
            f"it means no signal on {sym} can reach an outcome, and no paper "
            f"position can be marked, until {name} reopens")


#: Every class a broker row can be flagged primary for. "options" is in
#: the list because the router sends options and CFDs to IBKR before it
#: consults any flag at all.
_VENUE_CLASSES = ("stock", "forex", "commodity", "crypto", "options")


def _venue_for(user, asset_class: str):
    """(row, kind) that will carry a LIVE order for `asset_class`.

    (None, "") means nothing carries it. That is not an absence of a broker:
    broker_router always returns some client and falls back to the
    PaperTrader, so a live pool in that class books SIMULATED fills while
    calling itself live, which is the failure this exists to name.

    The order is broker_router.VENUE_PRECEDENCE, imported rather than
    restated, and tests/test_preflight_venue.py walks every class against
    the router's own predicates — a second copy of this rule that drifted
    would make the preflight confidently name the wrong broker.
    """
    from bot_program.capital_truth import broker_kind
    from bot_program.engine.broker_router import VENUE_PRECEDENCE

    rows = {"saxo": getattr(user, "saxo_account", None),
            "etoro": getattr(user, "etoro_account", None),
            "ibkr": getattr(user, "ibkr_account", None)}
    for kind in VENUE_PRECEDENCE:
        row = rows.get(kind)
        try:
            if row is not None and row.is_primary_for(asset_class):
                return row, broker_kind(row)
        except Exception:  # noqa: BLE001 — an unreadable row carries nothing
            continue
    # The router's one exception, and it is not flag-driven.
    if asset_class in ("options", "cfd") and rows["ibkr"] is not None:
        return rows["ibkr"], "ibkr"
    return None, ""


def _primary_classes(row) -> str:
    out = []
    for c in _VENUE_CLASSES:
        try:
            if row.is_primary_for(c):
                out.append(c)
        except Exception:  # noqa: BLE001
            return "UNREADABLE"
    return ", ".join(out) or "nothing"


def _saxo_alive(row, now) -> bool:
    """A Saxo row that can still reach the venue without a new sign-in."""
    try:
        return bool(row.has_session and row.session_alive(now))
    except Exception:  # noqa: BLE001
        return False


#: Django's non-delivering mail backends. settings.py swaps the console one
#: in when EMAIL_HOST is empty, so "EMAIL_HOST set" alone proves nothing.
_NOT_SMTP = ("console.EmailBackend", "locmem.EmailBackend",
             "dummy.EmailBackend")


def _alert_channel(user) -> dict:
    """What one user's alert channel needs, by NAME, and whether it is there.

    Mirrors the senders in bot_program.notifications exactly: telegram
    wants TELEGRAM_BOT_TOKEN in the sender's environment and the per-user
    UserNotificationPrefs.telegram_chat_id — a row only the
    /notifications/settings/ form creates (NOT TELEGRAM_CHAT_ID, which
    feeds the price-alert digest, a different sender); email wants a
    delivering backend and user.email; discord wants DISCORD_WEBHOOK_URL
    (TraderProfile has no webhook field, so the env fallback IS the path).

    Reads os.environ of THIS process, the only one it can. Never a value.
    """
    import os
    import socket
    from django.conf import settings
    from bot_program.notifications import _in_quiet_hours, _user_channel

    prof = getattr(user, "trader_profile", None)
    prefs = getattr(user, "notification_prefs", None)
    channel = _user_channel(user) if prof is not None else "no trader profile"
    missing, facts, notes = [], [], []
    if channel == "telegram":
        token = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
        facts.append(f"TELEGRAM_BOT_TOKEN   "
                     f"{'set' if token else 'NOT SET'} in this process")
        if not token:
            missing.append("TELEGRAM_BOT_TOKEN is not set (.env)")
        if prefs is None:
            facts.append("telegram_chat_id     NO NOTIFICATION-PREFS ROW")
            missing.append("UserNotificationPrefs.telegram_chat_id has no "
                           "row (save the /notifications/settings/ form)")
        elif not prefs.telegram_chat_id:
            facts.append("telegram_chat_id     EMPTY on the prefs row")
            missing.append("UserNotificationPrefs.telegram_chat_id is empty "
                           "(the /notifications/settings/ form)")
        else:
            facts.append("telegram_chat_id     set on the prefs row")
    elif channel == "email":
        backend = str(getattr(settings, "EMAIL_BACKEND", "") or "")
        host = bool(getattr(settings, "EMAIL_HOST", ""))
        facts.append(f"EMAIL_HOST           "
                     f"{'set' if host else 'NOT SET'} in this process")
        facts.append(f"EMAIL_BACKEND        {backend or '(unset)'}")
        facts.append(f"user.email           "
                     f"{'set' if user.email else 'EMPTY'}")
        if not host:
            missing.append("EMAIL_HOST is not set (.env) — settings fall "
                           "back to the console backend, which prints mail "
                           "into the container log")
        elif backend.endswith(_NOT_SMTP):
            missing.append(f"EMAIL_BACKEND is {backend} — nothing leaves "
                           f"the box")
        elif not getattr(settings, "EMAIL_HOST_USER", ""):
            notes.append("SMTP without credentials (EMAIL_HOST_USER empty) "
                         "— unverified")
        if not user.email:
            missing.append("user.email is empty (the account has no address)")
    elif channel == "discord":
        url = bool(os.environ.get("DISCORD_WEBHOOK_URL"))
        facts.append(f"DISCORD_WEBHOOK_URL  "
                     f"{'set' if url else 'NOT SET'} in this process")
        if not url:
            missing.append("DISCORD_WEBHOOK_URL is not set (.env)")
    quiet = None
    if (prefs is not None and prefs.quiet_start is not None
            and prefs.quiet_end is not None
            and prefs.quiet_start != prefs.quiet_end):
        quiet = (prefs.quiet_start, prefs.quiet_end)
    return {
        "channel": channel, "missing": missing, "facts": facts,
        "notes": notes, "prefs": prefs, "quiet": quiet,
        "quiet_now": bool(quiet) and _in_quiet_hours(user),
        "ready": (channel in ("telegram", "email", "discord")
                  and not missing
                  and (prefs is None or bool(prefs.receive_bot_alerts))),
        "host": socket.gethostname(),
    }


class Command(BaseCommand):
    help = "Check whether it is safe to arm live trading. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--user", default="",
                            help="Only this username (default: every user "
                                 "that has an IBKR account).")
        parser.add_argument("--symbols", type=int, default=4,
                            help="How many symbols per live config to detail.")

    def handle(self, *args, **opts):
        from django.conf import settings
        from django.contrib.auth.models import User
        from django.utils import timezone

        from django.db.models import Q

        from bot_program.capital_truth import (account_equity, broker_backed,
                                               broker_env, broker_kind)
        from bot_program.models import AssetBotConfig, IBKRAccount
        from core.platform_control import PlatformComponent, is_component_enabled
        from market_data.models import PriceData

        w = self.stdout.write
        now = timezone.now()
        per = max(1, int(opts["symbols"]))
        blockers, warnings = [], []
        book_ccy = (settings.PORTFOLIO_CONFIG or {}).get("base_currency", "")

        w("=" * 70)
        w("PREFLIGHT — IS IT SAFE TO ARM REAL MONEY")
        w("=" * 70)

        # ── 1. the switches every live order passes through ─────────────
        w("\n1. PLATFORM SWITCHES")
        for key in ("platform_master", "pipeline_asset_bots",
                    "pipeline_signals", "broker_account_sync"):
            row = PlatformComponent.objects.filter(key=key).first()
            if row is None:
                w(f"   {key:<22} NO ROW  — the gated task no-ops forever")
                blockers.append(f"{key} has no PlatformComponent row "
                                f"(run: manage.py seed_components)")
                continue
            try:
                on = is_component_enabled(key)
            except Exception as exc:            # noqa: BLE001
                on = f"ERR {exc}"
            w(f"   {key:<22} {str(on):<6} last_run={_age(row.last_run_at, now)}")
            if on is False:
                # broker_account_sync is called out by name because its
                # failure mode is the quiet one: it does not stop the bot, it
                # stops the bot from ever getting an equity reading, and
                # tracking_freeze_reason then refuses every entry.
                extra = ("" if key != "broker_account_sync" else
                         " — an account-following live pool will refuse EVERY "
                         "entry until a reading lands")
                blockers.append(f"{key} is OFF{extra}")

        # ANY broker row, keyed or not. Keyed-only would skip the
        # half-configured row this command exists to name, and IBKR-only
        # reported a blocker on a box that is deliberately without one.
        users = (User.objects.filter(username=opts["user"])
                 if opts["user"] else
                 User.objects.filter(
                     Q(ibkr_account__isnull=False)
                     | Q(etoro_account__isnull=False)
                     | Q(saxo_account__isnull=False)).distinct())
        if opts["user"] and not users.exists():
            w(f"\n   no user named {opts['user']!r}")
            return
        if not users.exists():
            w("\n   NO BROKER ROW ON ANY USER — nothing to arm.")
            blockers.append("no broker row exists on any user — "
                            "IBKR, eToro or Saxo")

        for user in users.order_by("username"):
            acct = IBKRAccount.objects.filter(user=user).first()

            # ── 2. the venue that will carry the orders ──────────────────
            # Not "the IBKR connection" since 2026-09-20: the book can be a
            # Saxo or an eToro row, and this section used to end in `continue`
            # on any box without an IBKRAccount — skipping every check below
            # for the broker that was actually going to trade.
            book = broker_backed(user)
            w(f"\n2. THE BROKERS — {user.username}")
            for kind, row in (("saxo", getattr(user, "saxo_account", None)),
                              ("etoro", getattr(user, "etoro_account", None)),
                              ("ibkr", acct)):
                if row is None:
                    w(f"   {kind:<6} no row")
                    continue
                w(f"   {kind:<6} {(row.label or '-')[:20]:<20} "
                  f"env={(broker_env(row) or 'UNKNOWN'):<7} "
                  f"primary={_primary_classes(row)}")
            if book is None:
                # Not a blocker on its own: a paper-only box is a legitimate
                # state, and section 4 blocks the live configs that have
                # nowhere to go.
                w("   book   NOTHING — no keyed row is primary for any class, "
                  "so every order falls back to the PaperTrader")
            else:
                w(f"   book   {broker_kind(book)} "
                  f"({broker_env(book) or 'ENV UNKNOWN'}) — this is the "
                  f"account every share and every limit is measured against")

            saxo = getattr(user, "saxo_account", None)
            if saxo is not None and not _saxo_alive(saxo, now):
                # Stated once here, and turned into a blocker in section 4
                # only for the live configs that route to it.
                why = (saxo.session_lost_reason or "never signed in"
                       if not saxo.has_session else "past its life")
                w(f"   saxo   session NOT alive ({why}) — sign in again at "
                  f"/brokers/. The refresh token lives 40 minutes and "
                  f"rotates, so a box down longer than that always needs one")

            if acct is not None:
                w(f"   label        {acct.label}")
                w(f"   env          {acct.env_label}")
                w(f"   socket       {acct.host}:{acct.port}  "
                  f"(slot {acct.gateway_slot} -> {acct.gateway_host})")
                w(f"   client_id    {acct.client_id}")
                w(f"   login stored {acct.has_login}")
                # Labelled for what it is. Left bare it reads as live status, and
                # it is not: nothing but the TEST IBKR button and a form save ever
                # writes it. Section 3 answers reachability.
                w(f"   last manual probe: {acct.connected}  at="
                  f"{_age(acct.last_sync, now)}  (not live status — see THE MONEY)")

                if not acct.env_is_certain:
                    # None is NOT paper. Everything that renders this must show
                    # the unknown as an unknown and refuse to call it safe.
                    blockers.append(
                        f"{user.username}: port {acct.port} is not a port IBKR "
                        f"ships — the platform cannot tell paper from live")
                if acct.paper_flag_disagrees:
                    warnings.append(
                        f"{user.username}: the stored paper flag says "
                        f"{acct.paper} and the port says {acct.env} — somebody "
                        f"believes something false about which account this is")
                if not acct.has_login:
                    blockers.append(f"{user.username}: no Gateway login stored — "
                                    f"the container cannot sign in")
                if acct.host in ("127.0.0.1", "localhost") and acct.gateway_host:
                    warnings.append(
                        f"{user.username}: host is {acct.host}, but in the compose "
                        f"stack the Gateway is reachable as "
                        f"{acct.gateway_host!r} — 127.0.0.1 inside a worker "
                        f"container is the worker itself")

            # ── 3. the money, with its currency ─────────────────────────
            w(f"\n3. THE MONEY — {user.username}")
            reading = account_equity(user)
            if reading is None:
                w("   broker equity   NEVER MEASURED")
                warnings.append(
                    f"{user.username}: no equity reading has ever landed, so "
                    f"nothing can compare a declared pool against the account")
            else:
                w(f"   broker equity   {reading['value_text']} "
                  f"{reading['currency'] or '(currency UNLABELLED)'}  "
                  f"({reading['age_seconds'] / 3600.0:.1f}h old)")
                if not reading["currency"]:
                    warnings.append(
                        f"{user.username}: the equity reading carries no "
                        f"currency, and this platform converts nothing")
            w(f"   book currency   {book_ccy or '(unset)'}")
            # THE MARGIN CELLS, three states, off the BOOK row when it has
            # them (eToro since 2026-09-23); §4 reads the VENUE row's for a
            # levered config. Never computed from the equity: available +
            # used margin + pnl = total is the public reference's claim.
            if book is not None and hasattr(book, "last_margin_at"):
                _cash = getattr(book, "last_available_cash", None)
                _used = getattr(book, "last_used_margin", None)
                if _cash is None and _used is None:
                    w("   margin          NEVER MEASURED (available cash / "
                      "used margin: no sync has stored them)")
                else:
                    _m_at = getattr(book, "last_margin_at", None)
                    _m_age = ((now - _m_at).total_seconds() / 3600.0
                              if _m_at else float("nan"))
                    cash_s = "—" if _cash is None else f"{float(_cash):,.2f}"
                    used_s = "—" if _used is None else f"{float(_used):,.2f}"
                    w(f"   available cash  {cash_s}  used margin {used_s}  "
                      f"({_m_age:.1f}h old)")

            # REACHABILITY IS THE AGE OF THIS READING, NEVER THE `connected`
            # FLAG. The flag is written only when somebody presses TEST IBKR
            # or saves the credentials form, so it means "a socket answered
            # once" and has no expiry — capital_truth.broker_backed says
            # exactly that and refuses to use it, in both directions: it goes
            # on reading True forever after a gateway dies, and it sits at
            # False forever on a gateway nobody has pressed the button for.
            #
            # The first version of this command made a stale False into
            # blocker #1 on a Gateway that IBC had just logged into live, that
            # `docker ps` called healthy, and whose equity reading — printed
            # two lines above the blocker — was four minutes old. The command
            # contradicted itself on its own page. A reading that arrived is
            # proof the socket answered; nothing else here is.
            age_h = (None if reading is None
                     else reading["age_seconds"] / 3600.0)
            if (book is not None and broker_env(book) == "live"
                    and (age_h is None
                         or age_h > BROKER_READING_STALE_HOURS)):
                kind = broker_kind(book)
                blockers.append(
                    f"{user.username}: the book is a LIVE {kind} account and "
                    f"no equity reading has landed "
                    + ("at all" if age_h is None else f"for {age_h:.1f}h")
                    + f" (limit {BROKER_READING_STALE_HOURS:.0f}h) — the "
                    f"broker is not answering, whatever a stored flag says."
                    + (" Is the Gateway logged in?" if kind == "ibkr" else
                       " Is the session still alive on /brokers/?"))

            # ── IBKR's floor, read BEFORE the order rather than after ───
            # IBKR's rule (Error 201), not a property of money: printing it
            # against a Saxo or eToro book would state a limit that venue
            # does not have.
            if (reading is not None and reading["currency"]
                    and book is not None and broker_kind(book) == "ibkr"):
                floor = _ibkr_floor(reading["value"], reading["currency"])
                live_all = list(AssetBotConfig.objects.filter(
                    user=user, mode="live"))
                if floor == "below":
                    w(f"   IBKR floor      BELOW {IBKR_MARGIN_FLOOR_USD:,.0f} "
                      f"USD — cash purchases only, in the instrument's own "
                      f"currency; no margin, no shorts, no currency, no "
                      f"futures (IBKR refuses with Error 201)")
                    for cfg in live_all:
                        if cfg.enabled and cfg.asset_class in IBKR_FLOOR_CLASSES:
                            blockers.append(
                                f"config {cfg.id} ({cfg.name}) is LIVE and "
                                f"armed for {cfg.asset_class}, a margin "
                                f"product IBKR refuses under "
                                f"{IBKR_MARGIN_FLOOR_USD:,.0f} USD of equity "
                                f"(Error 201: currency, futures and CFDs need "
                                f"the floor) — the account holds "
                                f"{reading['value']:,.0f} "
                                f"{reading['currency']}")
                    foreign = _foreign_currency_symbols(
                        live_all, reading["currency"])
                    if foreign:
                        # WORTH READING, not a verdict: the equity reading
                        # is the account's BASE currency and says nothing
                        # about cash held in others. A EUR account that has
                        # already converted 400 into USD buys GLDM outright,
                        # and this command cannot see that from here.
                        shown = ", ".join(foreign[:8])
                        warnings.append(
                            f"{user.username}: {shown} trade in a currency "
                            f"other than the account's base "
                            f"({reading['currency']}) — unless that cash is "
                            f"already held, buying them borrows it, a loan "
                            f"is margin, and IBKR refuses margin under "
                            f"{IBKR_MARGIN_FLOOR_USD:,.0f} USD (Error 201 on "
                            f"GLDM, 2026-09-10). Convert "
                            f"{reading['currency']} into the instrument's "
                            f"currency at IBKR first; this reading cannot "
                            f"see cash by currency")
                    w(f"   any symbol quoted in another currency than "
                      f"{reading['currency']} needs that currency converted "
                      f"at IBKR first — the manual lane included")
                elif floor == "unsure":
                    w(f"   IBKR floor      NEAR {IBKR_MARGIN_FLOOR_USD:,.0f} "
                      f"USD — this platform converts nothing; check the "
                      f"USD equivalent at IBKR before arming currency, "
                      f"futures or CFDs")
                    warnings.append(
                        f"{user.username}: equity reads "
                        f"{reading['value']:,.0f} {reading['currency']}, "
                        f"near IBKR's {IBKR_MARGIN_FLOOR_USD:,.0f} USD "
                        f"floor for margin, shorts, currency and futures")
                else:
                    w(f"   IBKR floor      above "
                      f"{IBKR_MARGIN_FLOOR_USD:,.0f} USD")

            # ── 4. the live configs ─────────────────────────────────────
            live = list(AssetBotConfig.objects.filter(
                user=user, mode="live").order_by("asset_class", "name"))
            w(f"\n4. LIVE CONFIGS — {user.username}")
            if not live:
                w("   none — every config is in paper mode. Nothing is armed.")
            for cfg in live:
                w(f"   [{cfg.id}] {cfg.name[:20]:<20} {cfg.asset_class:<9} "
                  f"enabled={str(cfg.enabled):<5} "
                  f"pool={cfg.capital} {cfg.base_currency}")
                venue, kind = _venue_for(user, cfg.asset_class)
                if venue is None:
                    w(f"        ^ NO BROKER is primary for "
                      f"{cfg.asset_class} — the router falls back to the "
                      f"PaperTrader")
                    (blockers if cfg.enabled else warnings).append(
                        f"config {cfg.id} ({cfg.name}) is LIVE"
                        + (" and ENABLED" if cfg.enabled else "")
                        + f" for {cfg.asset_class} and no broker is primary "
                        f"for it — every order routes to the PaperTrader, so "
                        f"the pool books SIMULATED fills while calling itself "
                        f"live")
                else:
                    env = broker_env(venue) or "UNKNOWN"
                    w(f"        ^ routes to {kind} ({env})")
                    # AND MEASURED AGAINST THAT ACCOUNT. The pool check
                    # below uses the BOOK's reading, and when the routed
                    # venue is a different broker that comparison reports
                    # agreement by construction: a follower's pool is a
                    # share of the book, so it can never exceed it.
                    if book is not None and kind != broker_kind(book):
                        v_val = getattr(venue, "last_equity", None)
                        v_at = getattr(venue, "last_equity_at", None)
                        v_ccy = getattr(venue, "last_equity_currency", "") or ""
                        if v_val is None or v_at is None:
                            blockers.append(
                                f"config {cfg.id} ({cfg.name}) is LIVE and "
                                f"routes to {kind}, which has NEVER been "
                                f"measured — its pool of {cfg.capital} "
                                f"{cfg.base_currency} is compared against "
                                f"{broker_kind(book)}'s balance instead, and "
                                f"that comparison cannot fail")
                        else:
                            try:
                                pool_v = float(cfg.capital)
                            except (TypeError, ValueError):
                                pool_v = 0.0
                            w(f"          {kind} holds {float(v_val):,.2f} "
                              f"{v_ccy or '(currency UNLABELLED)'} "
                              f"({_age(v_at, now)})")
                            if pool_v > float(v_val):
                                blockers.append(
                                    f"config {cfg.id} ({cfg.name}) declares a "
                                    f"pool of {pool_v:,.0f} and trades at "
                                    f"{kind}, which holds "
                                    f"{float(v_val):,.0f} {v_ccy} — every "
                                    f"risk limit derived from `capital` is "
                                    f"{pool_v / max(float(v_val), 1e-9):.1f}x "
                                    f"looser than it reads")
                            if (v_ccy and cfg.base_currency
                                    and v_ccy.upper()
                                    != cfg.base_currency.upper()):
                                blockers.append(
                                    f"config {cfg.id} ({cfg.name}) declares "
                                    f"its pool in {cfg.base_currency} while "
                                    f"{kind} — the venue it trades at — is in "
                                    f"{v_ccy}, and nothing here converts")
                    if env == "paper" and cfg.enabled:
                        blockers.append(
                            f"config {cfg.id} ({cfg.name}) is LIVE and "
                            f"ENABLED and routes to the {kind} DEMO account — "
                            f"the orders reach a simulator while the platform "
                            f"books the fills as REAL money")
                    if (kind == "saxo" and cfg.enabled
                            and not _saxo_alive(venue, now)):
                        blockers.append(
                            f"config {cfg.id} ({cfg.name}) is LIVE and "
                            f"ENABLED and routes to Saxo, whose session is "
                            f"not alive — nothing can leave for the venue "
                            f"until somebody signs in again at /brokers/")

                # THE POOL AGAINST THE ACCOUNT. The direction matters: a pool
                # larger than the account loosens every limit derived from it.
                if reading is not None:
                    same_ccy = (reading["currency"] and cfg.base_currency
                                and reading["currency"].upper()
                                == cfg.base_currency.upper())
                    if not same_ccy and reading["currency"]:
                        w(f"        ^ CURRENCY MISMATCH: pool declared in "
                          f"{cfg.base_currency}, account reads in "
                          f"{reading['currency']}")
                        blockers.append(
                            f"config {cfg.id} ({cfg.name}) declares its pool "
                            f"in {cfg.base_currency} while the account is in "
                            f"{reading['currency']} — every limit derived from "
                            f"`capital` is wrong by the FX rate, and nothing "
                            f"here converts")
                    try:
                        pool = float(cfg.capital)
                    except (TypeError, ValueError):
                        pool = None
                    if pool and pool > reading["value"]:
                        over = pool / reading["value"]
                        w(f"        ^ POOL EXCEEDS THE ACCOUNT by {over:.1f}x")
                        blockers.append(
                            f"config {cfg.id} ({cfg.name}) declares a pool of "
                            f"{pool:,.0f} against an account holding "
                            f"{reading['value']:,.0f} — every risk limit is "
                            f"{over:.1f}x looser than it reads")

                # THE MULTIPLIER, judged with the engine's own rule on the
                # venue the router names (`kind`, "" when nothing carries
                # the class) — for EVERY live config, enabled or not, so the
                # operator meets the refusal here and not at 02:00. A key
                # present is judged whatever its value (None included);
                # absent prints the adapter's default. Enabled -> BLOCKER,
                # disabled -> WORTH READING, the split this section keeps.
                _extras = cfg.extras or {}
                if "leverage" not in _extras:
                    w("        leverage —  (no extras['leverage']; the "
                      "adapter sends 1)")
                else:
                    from bot_program.asset_engine.base import (
                        judge_order_leverage)
                    _raw_lev = _extras.get("leverage")
                    _lev, _lev_why = judge_order_leverage(
                        cfg, cfg.asset_class, kind)
                    if _lev_why:
                        w(f"        leverage {_raw_lev!r} (extras)  ← {_lev_why}")
                        (blockers if cfg.enabled else warnings).append(
                            f"config {cfg.id} ({cfg.name}): {_lev_why}")
                    elif _lev == 1:
                        w("        leverage 1 (extras) — the adapter's "
                          "default, recorded on the row")
                    else:
                        from portfolio.models import Portfolio
                        from portfolio.services import PER_USER_SUFFIX
                        _own = Portfolio.objects.filter(
                            name=f"{user.username}{PER_USER_SUFFIX}").first()
                        w(f"        leverage {_lev}x (extras) — rides the "
                          f"eToro order body; units, the notional ceiling "
                          f"and the loss at the stop are unchanged; cash "
                          f"pledged per position is notional/{_lev} "
                          f"(believed until D2b); MAX TOTAL EXPOSURE is a "
                          f"percentage of your /setup/ book: "
                          f"{float(_own.current_value):,.0f} "
                          f"{_own.currency or ''}")
                        _v_cash = getattr(venue, "last_available_cash", None)
                        _v_used = getattr(venue, "last_used_margin", None)
                        _v_at = getattr(venue, "last_margin_at", None)
                        if _v_cash is None or _v_used is None or _v_at is None:
                            w("          margin cells NEVER MEASURED on the "
                              "venue row — every levered entry is refused "
                              "until the sync stores them")
                            (blockers if cfg.enabled else warnings).append(
                                f"config {cfg.id} ({cfg.name}) at {_lev}x: "
                                f"the venue row's available cash / used "
                                f"margin have never been stored — every "
                                f"levered entry is refused (leverage_refused) "
                                f"until the sync stores them")
                        else:
                            w(f"          venue cash {float(_v_cash):,.2f}  "
                              f"used margin {float(_v_used):,.2f}  "
                              f"({_age(_v_at, now)})")
                        from bot_program.asset_models import (
                            DEFAULT_MAX_HOLD_HOURS)
                        _hz = (cfg.max_hold_hours if cfg.max_hold_hours
                               is not None else
                               DEFAULT_MAX_HOLD_HOURS.get(cfg.asset_class))
                        warnings.append(
                            f"config {cfg.id} ({cfg.name}) at {_lev}x: "
                            f"financing (overnight/weekend fees on a levered "
                            f"CFD) is charged by NOTHING here — the cost "
                            f"filter is spread only — and the position may "
                            f"be held up to {_hz} h; the rate is unmeasured "
                            f"until D2b's costs read")
                if cfg.enabled and not list(cfg.symbols or []):
                    from bot_program.manual_trade import MANUAL_CONFIG_NAME
                    if cfg.name != MANUAL_CONFIG_NAME:
                        blockers.append(f"config {cfg.id} ({cfg.name}) is LIVE "
                                        f"and enabled with no symbols")

            # ── shares of the account ───────────────────────────────────
            from bot_program.capital_truth import (allocate_shares,
                                                   followers_of, share_label)
            followers = followers_of(user)
            if followers:
                alloc = allocate_shares(followers)
                for cfg in followers:
                    w(f"   [{cfg.id}] {cfg.name:<20} follows the account · "
                      f"{share_label(cfg, alloc['plan'])}")
                if not alloc["ok"]:
                    blockers.append(
                        f"{user.username}: the pools that follow the "
                        f"account ask for more than one account — "
                        f"{alloc['reason']}; the sync retunes nothing "
                        f"until the shares fit in 100%")
            if reading is not None and reading["value"] > 0:
                armed_total = sum(float(c.capital or 0)
                                  for c in live if c.enabled)
                if armed_total > reading["value"] * (1 + 1e-9):
                    warnings.append(
                        f"{user.username}: the armed live pools total "
                        f"{armed_total:,.0f} against an account of "
                        f"{reading['value']:,.0f} {reading['currency']} — "
                        f"together they can deploy "
                        f"{armed_total / reading['value']:.1f}x the money; "
                        f"make them shares of the account (follow) so they "
                        f"always fit")

            # ── 5. fuel AND whether one unit even fits ──────────────────
            #
            # CAN THIS POOL PLACE AN ORDER AT ALL. The pool-vs-account check
            # above catches a pool that is too BIG. Nothing caught the other
            # end, and the other end fails silently: sizing multiplies the
            # pool by a risk fraction, divides by the stop distance, and a
            # result under one unit becomes zero. `stock_bot._round_qty`
            # says so in its own docstring — "int() truncation is why a live
            # $10,000 config at 2% could not buy a $201 stock ... a zero qty
            # exits the entry path with no log line."
            #
            # And before truncation there is the notional cap: 20% of the pool
            # for everything except forex. A 500-unit pool can therefore hold
            # at most 100 of notional, which forbids ONE share of any
            # megacap — so an operator can arm a config, watch it tick
            # forever, and never learn that the arithmetic settled it in
            # advance. Checked here against the newest close, which is the
            # same number sizing will see.
            armed = [c for c in live if c.enabled]
            if armed:
                w(f"\n5. FUEL AND SIZE FOR ARMED LIVE CONFIGS — "
                  f"{user.username}")
                from bot_program.asset_engine.sizing import (
                    _extras_float, max_notional_fraction,
                    min_stop_fraction, risk_fraction)
                for cfg in armed:
                    try:
                        pool = float(cfg.capital or 0)
                    except (TypeError, ValueError):
                        pool = 0.0
                    cap_frac = max_notional_fraction(cfg, cfg.asset_class)
                    ceiling = pool * cap_frac
                    w(f"   [{cfg.id}] {cfg.name} — pool {pool:,.0f}, notional "
                      f"ceiling {ceiling:,.0f} ({cap_frac:.0%})")
                    # WHOLE SHARES OR FRACTIONS is a fact of the VENUE and of
                    # the fractional_units_live switch — read off the
                    # capability TABLE (what the platform believes;
                    # test_broker_contract keeps it equal to the class) and
                    # the component row. No client is built here and no key
                    # is read. Only the stock bot floors to whole, so only
                    # stock configs are judged this way; the money floor is
                    # the OPERATOR's extras['venue_min_notional'], in the
                    # venue's currency — nothing here converts it.
                    from bot_program.engine.capabilities import declared
                    from core.platform_control import is_component_enabled
                    _, kind5 = _venue_for(user, cfg.asset_class)
                    takes = (cfg.asset_class == "stock"
                             and "fractional_units" in declared(kind5))
                    switch = is_component_enabled("fractional_units_live")
                    fractional = bool(takes and switch)
                    if takes:
                        w(f"        FRACTIONS at {kind5}: the adapter declares "
                          f"the tier as a belief from the public reference "
                          f"(unmeasured until D2c); switch "
                          f"fractional_units_live is "
                          + ("ON — fractions sent" if switch
                             else "OFF — whole shares, as before"))
                    if fractional:
                        _f = risk_fraction(cfg)
                        _risk = pool * _f
                        _min_pos = _extras_float(cfg, "venue_min_notional", 0.0)
                        if _min_pos > 0:
                            _bound = _risk / _min_pos
                            _floor = min_stop_fraction(cfg, cfg.asset_class, _f)
                            w(f"        risk {_risk:,.2f} per trade; the "
                              f"declared venue minimum {_min_pos:,.2f} "
                              f"(extras['venue_min_notional'], the venue's "
                              f"currency, unconverted) needs a stop within "
                              f"{_bound:.2%} — wider stops are refused as "
                              f"venue_min_size before the order")
                            if _bound < _floor:
                                # bound < floor <=> pool * cap < minimum:
                                # the risk fraction cancels out of both
                                # sides, so risk_per_trade_pct cannot move
                                # this; pool * cap = risk / floor
                                _cap_notional = _risk / _floor
                                warnings.append(
                                    f"config {cfg.id} ({cfg.name}): the "
                                    f"declared venue minimum {_min_pos:,.2f} "
                                    f"needs a stop within {_bound:.2%}, "
                                    f"tighter than the {_floor:.2%} stop floor "
                                    f"its own cap implies — the cap allows at "
                                    f"most {_cap_notional:,.2f} of notional, "
                                    f"under the minimum, so most entries will "
                                    f"be refused as venue_min_size; raise the "
                                    f"pool, raise max_notional_fraction, or "
                                    f"lower the declared minimum once D2c "
                                    f"measures it")
                        else:
                            w(f"        risk {_risk:,.2f} per trade; no venue "
                              f"minimum declared (extras['venue_min_notional'] "
                              f"absent) — the venue's own refusal is the only "
                              f"floor, remembered per symbol for 24h")
                        warnings.append(
                            f"config {cfg.id} ({cfg.name}): SELL signals become "
                            f"sellShort CFDs at {kind5}, with an overnight fee "
                            f"this platform's cost filter does not charge "
                            f"(unmeasured — D2c holds one overnight)")
                    for sym in list(cfg.symbols or [])[:per]:
                        row = (PriceData.objects
                               .filter(instrument__symbol=sym,
                                       timeframe="4h")
                               .order_by("-timestamp")
                               .values("timestamp", "close",
                                       "instrument__asset_class",
                                       "instrument__exchange",
                                       "instrument__symbol")
                               .first())
                        newest = row["timestamp"] if row else None
                        price = float(row["close"] or 0) if row else 0.0
                        note = ""
                        if price > 0 and ceiling > 0 and price > ceiling:
                            if fractional:
                                note = (f"  ← a whole unit ({price:,.2f}) "
                                        f"exceeds the ceiling; a fraction "
                                        f"fits (FRACTIONS at {kind5}, switch "
                                        f"ON, believed)")
                            else:
                                note = (f"  ← ONE UNIT ({price:,.2f}) EXCEEDS "
                                        f"THE CEILING")
                        market = _market_note(row, newest, now)
                        w(f"   {sym:<12} newest 4h bar {_age(newest, now)}"
                          f"{market}{note}")
                        if newest is None:
                            blockers.append(f"{sym} has no 4h bars — an armed "
                                            f"live bot cannot form a decision")
                        else:
                            _bar_findings(sym, row, newest, now,
                                          blockers, warnings)
                        if note and not fractional:
                            blockers.append(
                                f"config {cfg.id} ({cfg.name}): one unit of "
                                f"{sym} costs {price:,.2f} and the notional "
                                f"ceiling is {ceiling:,.0f} "
                                f"({cap_frac:.0%} of a {pool:,.0f} pool) — "
                                f"sizing rounds to zero and the bot will tick "
                                f"forever without opening anything")

            # ── 6. the PIN ──────────────────────────────────────────────
            prof = getattr(user, "trader_profile", None)
            has_pin = bool(prof and prof.access_pin_hash)
            w(f"\n6. TRADING PIN — {user.username}: "
              f"{'set' if has_pin else 'NOT SET'}")
            if not has_pin:
                blockers.append(
                    f"{user.username} has no trading PIN — configuring or "
                    f"arming a live bot is unreachable without one, by design")

            # ── 7. can an alert leave the box ───────────────────────────
            # Every alert ends in notifications.dispatch_notification: the
            # bell row, then — outside the user's quiet window — ONE
            # external sender chosen by TraderProfile.notify_channel. This
            # reads each sender's own preconditions, by name, never a
            # value (_alert_channel above), plus the two gates in front of
            # the channel: receive_bot_alerts, which drops every bot kind
            # before the bell row is even written, and is_staff, because
            # the engine's own failures go through notify_staff to staff
            # users only.
            #
            # It can only read THIS process — from /ops/ the web
            # container, while the senders run in worker-fast, worker-slow
            # and beat, and compose injects .env when a container is
            # CREATED. So it says "configured", never "reachable": this
            # command sends nothing, and the platform has never recorded a
            # channel answering.
            #
            # Why none BLOCKS and quiet hours only WARN: an unattended live
            # platform whose alerts stay in the bell is the state this
            # section exists to name, and none is a standing choice; a
            # quiet window is bounded, and a width past which it would
            # block would be an invented constant. receive_bot_alerts OFF
            # blocks because it is strictly more silent than none.
            ch = _alert_channel(user)
            prefs = ch["prefs"]
            armed = any(c.enabled for c in live)
            severe = blockers if armed else warnings
            bot_alerts = ("ON, no prefs row (the default)" if prefs is None
                          else ("ON" if prefs.receive_bot_alerts else "OFF"))
            w(f"\n7. ALERT CHANNEL — {user.username}: {ch['channel']}  "
              f"staff={user.is_staff}  bot_alerts={bot_alerts}")
            for line in ch["facts"]:
                w(f"   {line}")
            recreate = (
                f"Measured in this process only ({ch['host']}); compose "
                f"injects .env when a container is CREATED, so after "
                f"filling it run `./deploy/dc up -d --force-recreate "
                f"worker-fast worker-slow beat web`, then measure the "
                f"senders' own environment: `./deploy/dc exec worker-fast "
                f"python manage.py preflight_live --user {user.username}`")
            if ch["channel"] == "no trader profile":
                severe.append(
                    f"{user.username} has no trader profile — the alert "
                    f"channel is unreadable, the sender answers none, and "
                    f"the bell is all there is")
            elif ch["channel"] == "none":
                severe.append(
                    f"{user.username}: notify_channel is none — every alert "
                    f"stays in the in-app bell while this trades; choose "
                    f"telegram, email or discord on the profile form before "
                    f"arming")
            elif ch["missing"]:
                severe.append(
                    f"{user.username}: alert channel is {ch['channel']} but "
                    + "; ".join(ch["missing"])
                    + f" — nothing can reach you while this trades. "
                    f"{recreate}")
            else:
                w(f"   configured in this process ({ch['host']}) — delivery "
                  f"UNVERIFIED: this command sends nothing, the platform has "
                  f"never recorded {ch['channel']} answering, and the senders "
                  f"run in worker-fast, worker-slow and beat, whose "
                  f"environment this process cannot read; `./deploy/dc exec "
                  f"worker-fast python manage.py preflight_live --user "
                  f"{user.username}` measures theirs")
            for note in ch["notes"]:
                warnings.append(f"{user.username}: {note}")
            if prefs is not None and not prefs.receive_bot_alerts:
                severe.append(
                    f"{user.username}: bot alerts are switched OFF "
                    f"(receive_bot_alerts, /notifications/settings/) — "
                    f"drawdown, fill and system-health alerts are dropped "
                    f"before the bell row is written, before any channel; "
                    f"that is more silent than notify_channel none")
            if not user.is_staff:
                warnings.append(
                    f"{user.username} is not staff — the engine's own "
                    f"failure alerts (a close that FAILED, an order that may "
                    f"be live with no row) fan out through notify_staff to "
                    f"staff users only; another staff user must be "
                    f"configured, or nobody is told")
            if ch["quiet"]:
                q0, q1 = ch["quiet"]
                warnings.append(
                    f"{user.username}: quiet hours {q0:%H:%M}–{q1:%H:%M} UTC "
                    f"mute every external alert in that window, including "
                    f"the unprotected-position and close-refused ones"
                    + (" — ACTIVE NOW" if ch["quiet_now"] else "")
                    + "; an unattended platform is silent there every day")

        # ── 7b. who the engine tells ────────────────────────────────────
        # notify_staff fans the engine's own failures — a close that
        # FAILED, an order that may be live with no row — out to every
        # active is_staff user through the same per-user channel. Zero
        # staff with a configured channel means those are reported to
        # nobody, whatever any one user's section 7 said.
        staff = list(User.objects.filter(is_active=True, is_staff=True)
                     .order_by("username"))
        told = [s.username for s in staff if _alert_channel(s)["ready"]]
        any_armed = AssetBotConfig.objects.filter(
            mode="live", enabled=True).exists()
        w(f"\n7b. WHO THE ENGINE TELLS — active staff: {len(staff)}, with a "
          f"configured channel: {len(told)}"
          + (f" ({', '.join(told)})" if told else ""))
        if not told:
            (blockers if any_armed else warnings).append(
                "no active staff user has an alert channel configured — a "
                "close that FAILED (the order may be live with no row) is "
                "reported to nobody outside the bell")

        # ── the verdict ─────────────────────────────────────────────────
        w("\n" + "=" * 70)
        if blockers:
            w("BLOCKERS — do not arm until these are answered:")
            for i, b in enumerate(blockers, 1):
                w(f"  {i}. {b}")
        else:
            w("NO BLOCKERS FOUND.")
            w("Which is not the same as safe. This command reads cached")
            w("columns; it cannot tell you the Gateway is logged in RIGHT")
            w("NOW, and it has never seen your broker answer an order.")
        if warnings:
            w("\nWORTH READING:")
            for i, m in enumerate(warnings, 1):
                w(f"  {i}. {m}")
        w("=" * 70)
