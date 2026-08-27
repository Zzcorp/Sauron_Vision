"""Global context processors for Sauron Vision."""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .exchange_status import get_exchange_status

logger = logging.getLogger(__name__)

# The bottom headband is ONE measurement, taken once and shared by the cells
# and the dropdowns they open. It used to be two: the cells read stored
# columns in sauron_context while the dropdowns recomputed from the live
# book, so a cell and the popup underneath it could quote different numbers
# for the same position book on the same screen.
PANEL_TTL_SECONDS = 20

# Fallback cadence for the multi-asset bot tick, in seconds, if the beat
# schedule cannot be read. OVERDUE is judged against this: too low and the
# BOT cell cries wolf between ticks, too high and a dead scheduler reads as
# healthy — which is the failure the cell exists to catch.
FALLBACK_BOT_TICK_SECONDS = 300.0
BOT_TICK_OVERDUE_FACTOR = 2.5

# Rows shown inside a dropdown before it starts scrolling past usefulness.
PANEL_ROW_LIMIT = 8

_EPOCH = datetime.min.replace(tzinfo=dt_timezone.utc)


def running_rules_q(now=None):
    """`RuleControl.is_effectively_active()`, expressed as a queryset filter.

    The raw `status` column is NOT the population the engine runs, and every
    count built on `status="active"` silently subtracts rules that are live:

      - `reduced` is a running state. The module docstring calls it "new
        signals persist with weight_multiplier applied", and
        `rule_actuator.rule_size_multiplier` reads weight_multiplier ONLY when
        status == "reduced" — the field exists to size a rule that is still
        trading. Both engine gates (`rule_actuator.is_rule_active`,
        `technical_rules`' fork filter) call `is_effectively_active()`.
      - a `paused` rule whose `paused_until` has elapsed is running again.
        `is_effectively_active()` computes that expiry on the fly, but nothing
        anywhere writes the column back to "active" — the help_text's promise
        that "status reverts to active automatically" is true of the engine
        and false of the database. With PAUSE_DURATION_DAYS = 30, every
        expired pause becomes a permanently uncounted running rule.

    `is_effectively_active()` is a Python method and cannot be filtered on, so
    the predicate is restated here once and asserted against the method in
    tests/test_strategies_page.py rather than re-derived at each call site.
    """
    from signals.models_control import RuleControl

    now = now or timezone.now()
    return (Q(status__in=(RuleControl.STATUS_ACTIVE,
                          RuleControl.STATUS_REDUCED))
            | Q(status=RuleControl.STATUS_PAUSED, paused_until__lte=now))


# ── Small honesty helpers ────────────────────────────────────────────────
# Every one of these returns None rather than 0 for "not measured". A
# confident 0 in this strip is exactly how the platform lost a day: 0.0%
# drawdown reads as "no downside", 0 open R reads as "flat", and +0.00 reads
# as "closed even" on a day nothing closed at all.

def _f(value):
    """float(value), or None when it cannot be read. Never 0.0 as a fallback."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _signed(value, spec="{:+,.2f}"):
    """A signed money/ratio string, or None so the template can dash it."""
    return None if value is None else spec.format(value)


def _ago(seconds):
    """'40s' / '4m' / '2h' / '3d' — or None when the age is unknown."""
    if seconds is None:
        return None
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds // 60)}m"
    if seconds < 172800:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def _r_multiple(entry, stop, mark, sign):
    """(mark − entry) ÷ the risk the trade OPENED with, signed by direction.

    None whenever a leg is missing. R is the number that says whether a
    position is working, and "0.00R" reads as a scratch trade — not as
    "there is no quote for this symbol" or "this row never had a stop".
    """
    if entry is None or stop is None or mark is None:
        return None
    risk = abs(entry - stop)
    if risk <= 1e-12:
        return None
    return (mark - entry) * sign / risk


def _news_sentiment_24h(NewsArticle, hours=24):
    """Mean scored sentiment per hour for the last day, oldest first.

    Five headlines tell an operator what happened; they do not say
    whether the day has been getting better or worse, which is the one
    thing a glance at a news cell should answer. This is the smallest
    honest version of that: one bucket an hour, the mean of the articles
    the analyst pass actually scored.

    UNSCORED ARTICLES ARE NOT ZEROS. `ai_sentiment_score` is null until
    the analyst reaches a row, and averaging a null in as neutral would
    drag every bucket toward the middle and make a genuinely negative
    hour look calm — the analyst's backlog would read as equanimity. An
    hour with nothing scored returns None and the sparkline carries the
    previous value across rather than drawing a hole at zero.

    Returns {"points": [...], "n": int, "mean": float|None, "trend": str}
    or None when the window holds nothing to draw.
    """
    from django.db.models import Avg
    from django.db.models.functions import TruncHour
    from django.utils import timezone as tz

    since = tz.now() - tz.timedelta(hours=hours)
    try:
        rows = (NewsArticle.objects
                .filter(published_at__gte=since,
                        ai_sentiment_score__isnull=False)
                .annotate(bucket=TruncHour("published_at"))
                .values("bucket")
                .annotate(mean=Avg("ai_sentiment_score"), n=Count("id"))
                .order_by("bucket"))
        by_hour = {r["bucket"]: (r["mean"], r["n"]) for r in rows}
    except Exception:  # noqa: BLE001 — a headband cell must not 500 a page
        return None
    if not by_hour:
        return None

    start = (tz.now() - tz.timedelta(hours=hours - 1)).replace(
        minute=0, second=0, microsecond=0)
    points, total, scored = [], 0.0, 0
    last = None
    for i in range(hours):
        slot = start + tz.timedelta(hours=i)
        hit = by_hour.get(slot)
        if hit and hit[0] is not None:
            last = float(hit[0])
            total += last * hit[1]
            scored += hit[1]
        # Carry the previous reading across a quiet hour rather than
        # drawing a zero nobody measured. A leading gap stays absent.
        if last is not None:
            points.append(round(last, 4))

    if not points:
        return None
    mean = (total / scored) if scored else None
    trend = "flat"
    if len(points) >= 2:
        half = max(1, len(points) // 2)
        early = sum(points[:half]) / half
        late = sum(points[half:]) / max(1, len(points) - half)
        if late - early > 0.05:
            trend = "up"
        elif early - late > 0.05:
            trend = "down"
    return {"points": points, "n": scored, "mean": mean, "trend": trend,
            "min": min(points), "max": max(points)}


def _bot_tick_cadence_seconds():
    """How often the multi-asset bot tick is SCHEDULED to run, in seconds.

    Read from the beat schedule rather than hardcoded here: "overdue" is a
    claim about the scheduler, and a constant would keep making that claim
    against a cadence somebody has since retuned. A crontab entry has no
    seconds to read, so the fallback covers it.
    """
    try:
        from config.celery import app
        entry = (app.conf.beat_schedule or {}).get("tick-asset-bots") or {}
        return float(entry.get("schedule"))
    except Exception:  # noqa: BLE001 — a missing schedule must not blank the cell
        return FALLBACK_BOT_TICK_SECONDS


def _book_fingerprint(user, portfolio):
    """A cheap stamp that changes exactly when the headband's inputs change.

    The payload below is cached for 20 seconds because its aggregates are not
    free and it runs on EVERY render. A bare TTL, though, is what made the
    operator's complaint true a second time: a fill lands, the headband
    re-fetches 800ms later, and the server hands back the payload it computed
    before the fill — so the cell and its popup sit there unchanged and the
    refresh looks broken.

    Three indexed aggregates cost far less than the ~20 queries they gate,
    and they move the instant a trade opens or closes, or a bot writes its
    heartbeat (which bumps AssetBotConfig.updated_at every tick). Marks are
    the one input NOT in here — a quote moving is what the 20s TTL is for.
    """
    from bot_program.models import AssetBotConfig, AssetBotTrade

    trades = AssetBotTrade.objects.filter(config__user=user).aggregate(
        n=Count("id"), opened=Max("opened_at"), closed=Max("closed_at"))
    positions = portfolio.positions.aggregate(
        n=Count("id"), opened=Max("opened_at"), closed=Max("closed_at"))
    configs = AssetBotConfig.objects.filter(user=user).aggregate(
        n=Count("id"), on=Count("id", filter=Q(enabled=True)),
        touched=Max("updated_at"))
    return "|".join(str(block[k]) for block in (trades, positions, configs)
                    for k in sorted(block))


def _initial_stops(user):
    """{trade_id: the stop the trade OPENED with}.

    `bot_program.manual_close._initial_stop` is the platform's one definition
    of that number, and bot_grading books R against it. The unified position
    row cannot carry it — it exposes the CURRENT stop, which a trailing stop
    rewrites, and grading against that makes P&L and risk the same quantity
    so every trailed winner scores ~1.0R.
    """
    from bot_program.manual_close import _initial_stop
    from bot_program.models import AssetBotTrade

    return {
        trade.id: _initial_stop(trade)
        for trade in AssetBotTrade.objects.filter(
            config__user=user, status__in=("OPEN", "CLOSE_PENDING")
        ).only("id", "metadata", "stop_loss")
    }


def _book_truth(user, portfolio):
    """What the headband says about the position book — BOTH books, marked.

    The PORTFOLIO cell used to render `portfolio.current_value`, a stored
    column written only by `portfolio.tasks`, which valued the LEGACY book
    alone (portfolio.Position) and touched only the SHARED "Main" portfolio —
    while this headband reads the PER-USER book and the operator's trades are
    AssetBotTrade rows. So the column could never move off its seeded initial
    capital, and the cell sat at 10,000 forever with a dropdown underneath it
    listing live trades. The tasks now value both books on every portfolio,
    but the cell no longer waits on them: an hourly column cannot answer a
    question the operator asks the moment a fill lands.

    Everything here comes from `portfolio.services.live_book_value`, the one
    function that answers "what is this book worth right now" — cash plus the
    marked value of everything open across BOTH books, over the platform's
    single re-pricing union (`dashboard.views_command._open_book`). One
    implementation for the Operations Center, the portfolio page, the PDF
    report and this band, so none of them can disagree about how many
    positions are open or what they are worth.
    """
    from portfolio.services import live_book_value

    out = {}
    day_ago = timezone.now() - timedelta(hours=24)

    book = live_book_value(user, portfolio)
    rows, n_priced, unrealized = book.rows, book.n_priced, book.unrealized
    n_open = book.n_open
    stops = _initial_stops(user) if n_open else {}

    detail, r_sum, r_n, bot_r_sum, bot_r_n = [], 0.0, 0, 0.0, 0
    # The long/short split the POSITIONS cell prints under its count. A row
    # whose direction column is blank still renders as LONG below (the sign
    # defaults that way so its P&L has a side), but it cannot be COUNTED as
    # one: a split that silently files unknowns under long is a claim of
    # exposure the book never made, so one unreadable side dashes both.
    n_long, n_short, sides_unreadable = 0, 0, False
    for row in sorted(rows,
                      key=lambda p: getattr(p, "opened_at", None) or _EPOCH,
                      reverse=True):
        source = "bot" if getattr(row, "source", "") == "bot" else "manual"
        direction = (getattr(row, "direction", "") or "").lower()
        sign = -1 if direction in ("short", "sell") else 1
        if direction in ("short", "sell"):
            n_short += 1
        elif direction in ("long", "buy"):
            n_long += 1
        else:
            sides_unreadable = True
        trade_id = getattr(row, "trade_id", None)
        entry = _f(row.entry_price)
        mark = _f(row.current_price)
        # Legacy Position rows keep their opening stop: nothing on this
        # platform trails a Position, so its stop_loss IS the entry stop.
        stop = (stops.get(trade_id) if source == "bot"
                else _f(getattr(row, "stop_loss", None)))
        r_mult = _r_multiple(entry, stop, mark, sign)
        if r_mult is not None:
            r_sum += r_mult
            r_n += 1
            if source == "bot":
                bot_r_sum += r_mult
                bot_r_n += 1
        detail.append({
            # The trade id is what makes the row actionable: the CLOSE
            # control on each row posts against it. Legacy Position rows
            # carry no id and no close path anywhere in the platform.
            "id": trade_id,
            "symbol": getattr(getattr(row, "instrument", None), "symbol", "")
                      or "",
            "side": "LONG" if sign == 1 else "SHORT",
            "qty": _f(getattr(row, "quantity", None)),
            "entry": entry,
            "stop": stop,
            "last": mark,
            "r": None if r_mult is None else round(r_mult, 2),
            "pct": _f(getattr(row, "unrealized_pnl_pct", None)),
            "pnl": _f(getattr(row, "unrealized_pnl", None)),
            "paper": getattr(row, "paper", None),
            "source": source,
            "status": getattr(row, "status", "") or "",
            "opened_at": getattr(row, "opened_at", None),
        })

    # Each of the three can be None, and each None means NOT MEASURED: a cash
    # column that could not be read at all, and a deployed/value pair over an
    # open book nothing could price. The cells below print an em-dash for
    # every one of them rather than a 0 that reads as an emptied account.
    cash, deployed, value = book.cash, book.marked, book.value

    # The band hardcoded a € in front of every figure. The portfolio carries
    # its own currency and the bot configs carry theirs, so the sign is read
    # from the book rather than assumed — an unknown code prints as the code.
    # WHEN these numbers were computed — the popup notes print it, because
    # a 20s-cached figure labelled as live is a small lie repeated forever.
    out["panel_as_of"] = timezone.now().strftime("%H:%M:%S")
    out["panel_currency"] = book.currency
    out["panel_currency_symbol"] = book.currency_symbol
    out["panel_cash"] = None if cash is None else f"{cash:,.0f}"
    out["panel_deployed"] = None if deployed is None else f"{deployed:,.0f}"
    out["panel_portfolio_value"] = None if value is None else f"{value:,.0f}"
    out["panel_positions"] = n_open
    out["panel_positions_priced"] = n_priced
    # How much of the VALUE cell the marked half actually covers. The figure
    # is a partial sum whenever a position has no quote, and a cell that says
    # nothing about it looks exactly like a complete one.
    out["panel_positions_unpriced"] = book.n_unpriced
    out["panel_value_partial"] = book.partial and value is not None
    out["panel_max_dd"] = f"{portfolio.max_daily_loss_pct}"

    # The POOL economy — capital allocated to configs, committed to open
    # tickets, and still free — from the ONE service the portfolio and
    # positions pages read, so the popup and the page can never disagree.
    # Fenced like every sibling: an unreadable pool table costs these
    # three cells, not the band.
    try:
        from portfolio.services import capital_summary
        cap = capital_summary(user)
        out["panel_pool"] = f"{cap['pool_total']:,.0f}"
        out["panel_pool_used"] = f"{cap['used_total']:,.0f}"
        out["panel_pool_free"] = f"{cap['free_total']:,.0f}"
        out["panel_pool_free_neg"] = cap["free_total"] < 0
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Panel pools unavailable: {e}")

    if value is None or value <= 0:
        # Positions exist and not one could be priced: the split between cash
        # and exposure is unknown, and "100% cash" would be a claim of no
        # exposure at all — the opposite of the truth.
        out["panel_exposure"] = None if value is None else 0
        out["panel_cash_pct"] = None if value is None else 100
    else:
        exposure = int(round(deployed / value * 100))
        out["panel_exposure"] = exposure
        out["panel_cash_pct"] = max(0, 100 - exposure)

    out["panel_book_coverage"] = book.coverage

    out["panel_open_pnl"] = unrealized
    out["panel_open_pnl_display"] = _signed(unrealized)
    # Both 0 only for an EMPTY book; over an open book with a side nothing
    # could read, None — the cell prints an em-dash, never a 0 that reads
    # as "no shorts".
    if n_open and sides_unreadable:
        out["panel_n_long"] = out["panel_n_short"] = None
    else:
        out["panel_n_long"], out["panel_n_short"] = n_long, n_short
    out["panel_open_r"] = round(r_sum, 2) if r_n else None
    out["panel_open_r_display"] = f"{r_sum:+.2f}R" if r_n else None
    out["panel_open_r_n"] = r_n
    out["panel_bot_open_r"] = round(bot_r_sum, 2) if bot_r_n else None
    out["panel_bot_open_r_display"] = f"{bot_r_sum:+.2f}R" if bot_r_n else None

    out["panel_open_rows"] = detail[:PANEL_ROW_LIMIT]
    out["panel_open_rows_hidden"] = max(0, n_open - PANEL_ROW_LIMIT)
    # The bot subset keeps its own name: the BOT dropdown and older callers
    # ask for the trades, not for the union.
    out["panel_open_trades"] = [d for d in detail if d["source"] == "bot"]
    out["panel_recent_positions"] = [d for d in detail
                                     if d["source"] == "manual"][:5]

    # Realised P&L on the legacy half. Position closes have no realised
    # column — unrealized_pnl is the only P&L that model carries, which is
    # the same convention portfolio.services.unified_closed_positions uses.
    legacy_closed = portfolio.positions.filter(
        closed_at__gte=day_ago).aggregate(n=Count("id"),
                                          total=Sum("unrealized_pnl"))
    out["panel_legacy_closed_24h"] = legacy_closed["n"] or 0
    out["panel_legacy_pnl_24h"] = (_f(legacy_closed["total"])
                                   if legacy_closed["n"] else None)
    return out


def _is_manual_config(cfg):
    """True for the config TAKE TRADE books HAND-TAKEN positions against.

    `bot_program.manual_trade` opens every manual position on a per-user,
    per-class config named "manual", enabled with an EMPTY symbols list: the
    5-minute tick manages its open positions, and the entry scan has nothing
    to scan, so the config cannot open a thing on its own.

    Both halves of the test carry weight. `manual_trade._config_error`
    REFUSES to trade through a config the user themselves named "manual" and
    gave symbols to — that one is a real bot with a real universe — so the
    same pair (the reserved name, no symbols) is what separates the two here.
    """
    from bot_program.manual_trade import MANUAL_CONFIG_NAME

    return cfg.name == MANUAL_CONFIG_NAME and not cfg.symbols


def _bot_truth(user, book):
    """What the BOT cell says — the state of the bot PROGRAM right now.

    The cell used to print ARMED whenever one config had `enabled=True`.
    Enabled is not running. `tick_all_asset_bots` is wrapped in
    @guarded_task, so the platform master switch and the `pipeline_asset_bots`
    component each veto every tick on their own; a circuit breaker stops a
    config opening anything; shadow mode decides and submits nothing; and the
    kill switch disables every config outright. A cell claiming ARMED while
    any of those holds is the most expensive kind of wrong here, because it
    is the readout an operator uses to decide whether to intervene.

    The legacy crypto BotConfig is deliberately not counted: `tick_all_bots`
    has no beat entry, so those configs cannot be running and counting them
    would claim automation that nothing ticks.

    The "manual" config is not a bot either, and is carved out of every
    config-level and open-position figure below. TAKE TRADE books hand-taken
    positions against it (see `_is_manual_config`), and it can never open one
    on its own — so counting it made this cell report the operator's own
    click as automation. An account whose only config was that one read
    "0 live · 1 paper · 1 open", and STALLED in red on top of it, because a
    config nobody armed had naturally never ticked. Nothing is hidden by the
    carve-out: the hand-taken book is published under panel_bot["manual"],
    named in `reason` (which the dropdown prints and the cell shows on
    hover), and counted by the POSITIONS cell exactly as before. This is
    attribution, not concealment.
    """
    from bot_program.asset_engine.safety import (
        CircuitBreakers, heartbeat_age_seconds, is_shadow,
    )
    from bot_program.manual_trade import MANUAL_RULE
    from bot_program.models import AssetBotConfig, AssetBotTrade
    from core.platform_control import get_component

    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    out = {}

    all_configs = list(AssetBotConfig.objects.filter(user=user))
    manual_configs = [c for c in all_configs if _is_manual_config(c)]
    manual_config_ids = {c.id for c in manual_configs}
    configs = [c for c in all_configs if c.id not in manual_config_ids]
    enabled = [c for c in configs if c.enabled]
    n_live = sum(1 for c in enabled if c.mode == "live")
    n_paper = len(enabled) - n_live

    # A component row that does not exist is not "on": guarded_task treats a
    # missing key as OFF and skips, so the honest reading of both states is
    # "nothing runs" — but the popup names which of the two it is, because
    # the fix differs (flip the switch vs. seed the components).
    master = get_component("platform_master")
    gate = get_component("pipeline_asset_bots")
    master_on = bool(master and master.is_enabled)
    gate_on = bool(gate and gate.is_enabled)

    open_by_config = {
        row["config_id"]: row["n"] for row in AssetBotTrade.objects.filter(
            config__user=user, status__in=("OPEN", "CLOSE_PENDING")
        ).values("config_id").annotate(n=Count("id"))
    }
    # Split by CONFIG rather than by rule_name, even though every hand-taken
    # trade also carries rule_name="manual_take": the dropdown lists one row
    # per config with its own open count, and the OPEN cell above it has to
    # be the sum of the rows an operator can actually see. Splitting the two
    # numbers on different keys is how a cell and its popup start disagreeing.
    bot_open = sum(n for cid, n in open_by_config.items()
                   if cid not in manual_config_ids)
    manual_open = sum(n for cid, n in open_by_config.items()
                      if cid in manual_config_ids)

    bots = []
    for cfg in configs:
        extras = cfg.extras or {}
        reasons = []
        if cfg.enabled:
            try:
                _allowed, reasons = CircuitBreakers(cfg).check_all()
            except Exception as e:  # noqa: BLE001 — a probe must not blank the cell
                logger.debug("Bot breaker probe failed for cfg %s: %s",
                             cfg.pk, e)
                reasons = []
        age = heartbeat_age_seconds(cfg)
        bots.append({
            "name": cfg.name,
            "asset_class": cfg.asset_class,
            "mode": cfg.mode,
            "enabled": cfg.enabled,
            "shadow": is_shadow(cfg),
            "open": open_by_config.get(cfg.id, 0),
            # None means NEVER TICKED, and the template dashes it. Zero
            # would read as "ticked just now", which is the opposite.
            "tick_age": age,
            "tick_ago": _ago(age),
            "tick_status": (extras.get("last_tick_status") or ""),
            "tick_note": (extras.get("last_tick_note") or "")[:90],
            "halted": reasons,
        })

    halted = [b for b in bots if b["enabled"] and b["halted"]]
    shadowed = [b for b in bots if b["enabled"] and b["shadow"]]
    ages = [b["tick_age"] for b in bots
            if b["enabled"] and b["tick_age"] is not None]
    freshest = min(ages) if ages else None
    cadence = _bot_tick_cadence_seconds()
    overdue = None if freshest is None else freshest > cadence * BOT_TICK_OVERDUE_FACTOR

    # The kill switch leaves no flag behind — it disables every config and
    # posts one notification. That notification is the only trace of WHY the
    # bots are all off, and without it the cell can only say "OFF" to an
    # operator who is asking exactly that question.
    kill_at, kill_reason = None, ""
    try:
        from alerts.models import Notification
        kill = (Notification.objects
                .filter(user=user, title__startswith="KILL SWITCH ACTIVATED",
                        created_at__gte=now - timedelta(days=7))
                .order_by("-created_at").first())
        if kill is not None:
            kill_at = kill.created_at
            # "KILL SWITCH ACTIVATED — {reason}". No dash means no reason was
            # recorded; echoing the whole title back would print the words
            # "KILL SWITCH ACTIVATED" as if they were the operator's reason.
            _, _, tail = kill.title.partition("—")
            kill_reason = tail.strip()
    except Exception as e:  # noqa: BLE001
        logger.debug("Kill-switch probe unavailable: %s", e)

    if not configs:
        state, tone, reason = "NONE", "muted", "No bot is configured on this account."
    elif not enabled:
        state, tone = "OFF", "muted"
        reason = f"{len(configs)} bot(s) configured, none enabled."
        if kill_at is not None:
            reason = (f"The kill switch disabled every bot "
                      f"{_ago((now - kill_at).total_seconds())} ago"
                      + (f" ({kill_reason})." if kill_reason else "."))
    elif not master_on:
        state, tone = "HALTED", "red"
        reason = ("The platform master switch is "
                  + ("off" if master else "not registered")
                  + " — every scheduled task returns without running, so no "
                    "bot ticks whatever its own row says.")
    elif not gate_on:
        state, tone = "HALTED", "red"
        reason = ("The multi-asset bot component (pipeline_asset_bots) is "
                  + ("off" if gate else "not registered")
                  + " — the tick task is gated off before it reaches a bot.")
    elif len(halted) == len(enabled):
        state, tone = "HALTED", "red"
        reason = ("Every enabled bot is behind a circuit breaker: "
                  + "; ".join(r for b in halted for r in b["halted"])[:180])
    elif len(shadowed) == len(enabled):
        state, tone = "SHADOW", "gold"
        reason = ("Every enabled bot is in shadow mode — it decides and "
                  "submits nothing.")
    elif freshest is None:
        state, tone = "STALLED", "red"
        reason = ("No enabled bot has recorded a tick yet — the scheduler "
                  "has not reached them.")
    elif overdue:
        state, tone = "STALLED", "red"
        reason = (f"Last tick {_ago(freshest)} ago, against a "
                  f"{cadence / 60:.0f} min schedule.")
    elif n_live:
        state, tone = "LIVE", "gold"
        reason = f"{n_live} bot(s) armed with real funds."
    else:
        state, tone = "PAPER", ""
        reason = f"{len(enabled)} bot(s) armed on the paper venue."

    if state in ("LIVE", "PAPER"):
        if halted:
            reason += (f" {len(halted)} of {len(enabled)} behind a circuit "
                       f"breaker.")
        if shadowed:
            reason += f" {len(shadowed)} in shadow mode."

    # Where the operator's own positions went. `reason` is the one string
    # this cell shows in full — the dropdown note, and the cell's hover title
    # — so it is where the separation has to be said out loud. Without it an
    # operator who has just pressed TAKE TRADE reads "OPEN 0" here and has to
    # guess whether the platform lost the trade. It did not: it is on the
    # POSITIONS cell, which is where a position the operator took belongs.
    if manual_open:
        reason += (f" {manual_open} position(s) opened by hand are on your "
                   f"own book, not this program's.")

    # One aggregate, split by rule, rather than three queries over the same
    # rows. `manual_take` is written on every hand-taken trade and on nothing
    # else, so the negated half is the fleet's own history exactly.
    manual_q = Q(rule_name=MANUAL_RULE)
    closed = AssetBotTrade.objects.filter(
        config__user=user, status="CLOSED", closed_at__gte=day_ago)
    agg = closed.aggregate(
        bot_n=Count("id", filter=~manual_q),
        bot_wins=Count("id", filter=Q(pnl__gt=0) & ~manual_q),
        bot_pnl=Sum("pnl", filter=~manual_q),
        manual_n=Count("id", filter=manual_q),
        manual_pnl=Sum("pnl", filter=manual_q),
    )
    n_closed = agg["bot_n"] or 0
    wins = agg["bot_wins"] or 0
    pnl_24h = _f(agg["bot_pnl"])
    n_closed_manual = agg["manual_n"] or 0
    pnl_24h_manual = _f(agg["manual_pnl"])
    # Sum over an empty set is NULL, which is the honest answer here: no
    # close means no figure, and a confident +0.00 would read as "closed
    # even" on a day nothing closed at all.
    pnl_24h_all = (None if pnl_24h is None and pnl_24h_manual is None
                   else (pnl_24h or 0.0) + (pnl_24h_manual or 0.0))

    opened = AssetBotTrade.objects.filter(
        config__user=user, opened_at__gte=day_ago).aggregate(
        bot_n=Count("id", filter=~manual_q),
        manual_n=Count("id", filter=manual_q))
    opened_24h = opened["bot_n"] or 0
    opened_24h_manual = opened["manual_n"] or 0

    # The fleet's own last close. A hand-taken exit belongs in the note under
    # the POSITIONS book, not under "BOT PROGRAM · IS IT RUNNING?" — and it
    # would contradict the 24H FILLS count right above it, which is the
    # fleet's.
    last_closed = (closed.exclude(rule_name=MANUAL_RULE)
                   .order_by("-closed_at").first() if n_closed else None)

    # OPEN and OPEN R sit side by side in the dropdown and must therefore
    # count the same positions. The book's bot-half R includes the hand-taken
    # rows — every AssetBotTrade reads as source="bot" to `_open_book`, which
    # knows the two books apart and not the two hands — so it is re-summed
    # here without them. Only when there is something to remove, though: the
    # rows carry R already rounded to 2dp, and re-summing them drifts a cent
    # from the book's full-precision sum. A book with nothing taken by hand
    # keeps the book's own number, to the digit.
    open_r_display = book.get("panel_bot_open_r_display")
    if manual_open:
        hand_taken = set(AssetBotTrade.objects.filter(
            config_id__in=manual_config_ids,
            status__in=("OPEN", "CLOSE_PENDING")).values_list("id", flat=True))
        fleet_r = [row["r"] for row in (book.get("panel_open_trades") or [])
                   if row.get("r") is not None
                   and row.get("id") not in hand_taken]
        open_r_display = f"{sum(fleet_r):+.2f}R" if fleet_r else None

    out["panel_bot"] = {
        "state": state,
        "tone": tone,
        "reason": reason,
        "configs": len(configs),
        "enabled": len(enabled),
        "live": n_live,
        "paper": n_paper,
        "shadow": len(shadowed),
        "halted": len(halted),
        "master_on": master_on,
        "master_known": master is not None,
        "gate_on": gate_on,
        "gate_known": gate is not None,
        "cadence_min": round(cadence / 60, 1),
        "tick_ago": _ago(freshest),
        "tick_overdue": overdue,
        "never_ticked": sum(1 for b in bots
                            if b["enabled"] and b["tick_age"] is None),
        "open": bot_open,
        "open_r_display": open_r_display,
        "opened_24h": opened_24h,
        "closed_24h": n_closed,
        "winrate": round(wins / n_closed * 100) if n_closed else None,
        # `pnl_24h` and `pnl_24h_display` answer two different questions and
        # cover two different populations on purpose:
        #
        #   pnl_24h          every AssetBotTrade close in the window, the
        #                    operator's hand-taken ones included, because
        #                    `_panel_detail` adds this to the legacy book to
        #                    answer "what did today make" — and money made by
        #                    hand is money. Narrowing it would make a day on
        #                    which the operator closed three manual trades
        #                    report "nothing closed".
        #   pnl_24h_display  the fleet alone, because this is what the BOT
        #                    dropdown prints under "IS IT RUNNING?", next to
        #                    a fill count and a win rate that are the fleet's.
        #
        # They differ by exactly manual.pnl_24h, published below so the
        # arithmetic is checkable instead of mysterious. It is a raw float and
        # not the string for the older reason: re-parsing a formatted number
        # back into arithmetic is how a thousands separator becomes an error.
        "pnl_24h": pnl_24h_all,
        "pnl_24h_display": _signed(pnl_24h),
        "kill_at": kill_at,
        "kill_reason": kill_reason,
        "bots": bots[:6],
        "bots_hidden": max(0, len(bots) - 6),
        # The hand-taken book, kept beside the fleet's numbers rather than
        # folded into them. Nothing renders it yet — the BOT dropdown says it
        # in `reason` and the POSITIONS cell counts the trades — but the split
        # has to exist as numbers for the separation to be auditable, and for
        # whoever surfaces "+N by hand" in the strip next.
        "manual": {
            "configs": len(manual_configs),
            "open": manual_open,
            "opened_24h": opened_24h_manual,
            "closed_24h": n_closed_manual,
            "pnl_24h": pnl_24h_manual,
            "pnl_24h_display": _signed(pnl_24h_manual),
        },
    }

    # Names older surfaces and tests already read. `panel_bot_armed` stays
    # the raw config-level fact (something is enabled); the CELL renders
    # panel_bot.state, which is that fact AND the gates that decide whether
    # anything actually ticks.
    out["panel_bot_armed"] = bool(enabled)
    modes = sorted({c.mode for c in enabled})
    out["panel_bot_mode"] = (modes[0] if len(modes) == 1
                             else ("mixed" if modes else "—"))
    out["panel_bot_open"] = out["panel_bot"]["open"]
    # The CROSS-BOOK realised line counts closes, not automation, and reads
    # this name for its count exactly as it reads panel_bot["pnl_24h"] for
    # its money — so both halves of AssetBotTrade belong in it. The fleet's
    # own count is panel_bot["closed_24h"].
    out["panel_bot_trades_24h"] = n_closed + n_closed_manual
    out["panel_bot_winrate"] = out["panel_bot"]["winrate"]
    out["panel_bot_pnl_24h_display"] = out["panel_bot"]["pnl_24h_display"]
    out["panel_bot_last"] = ({
        "symbol": last_closed.symbol,
        "outcome": (last_closed.outcome or "closed").replace("_", " "),
        "r": last_closed.realized_r,
        "when": last_closed.closed_at,
    } if last_closed else None)
    out["panel_bot_currencies"] = sorted({(c.base_currency or "").upper()
                                          for c in configs if c.base_currency})
    return out


def _panel_detail(user):
    """The whole bottom headband — every cell AND every dropdown, one read.

    Two things were wrong with this strip, and they were the same thing. The
    cells were built from stored columns in `sauron_context` while the
    dropdowns were built here from the live book, so they could disagree; and
    the stored column behind the PORTFOLIO cell is written by a task that
    values only the legacy book on the shared portfolio, so it never moved
    off the seeded 10,000 no matter what the operator traded. Both cells and
    popups now come out of this one dict.

    Cached for PANEL_TTL_SECONDS per user AND per book fingerprint. The TTL
    alone would delay every fill by up to 20 seconds — the refresh would fire
    on the fill and be served the pre-fill payload — so the key carries a
    stamp that changes the moment the book does.
    """
    import sys
    from django.core.cache import cache

    # The cache is keyed on the user's primary key, which is stable and unique
    # in production. Under the test runner it is neither: every TestCase rolls
    # the database back, so primary keys restart and a payload cached by one
    # test is served to a different user in the next. That made assertions on
    # anything in the headband depend on how long the preceding test took.
    testing = "test" in sys.argv or any("pytest" in a for a in sys.argv)

    portfolio = None
    try:
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio(user=user)
    except Exception as e:
        logger.debug(f"Panel portfolio unavailable: {e}")

    key = f"sv:panel_detail:{user.pk}"
    if portfolio is not None:
        try:
            key = f"{key}:{_book_fingerprint(user, portfolio)}"
        except Exception as e:
            logger.debug(f"Panel fingerprint unavailable: {e}")
    if not testing:
        cached = cache.get(key)
        if cached is not None:
            return cached

    out = {}

    # ── The position book: value, exposure, P&L and R, from both books ───
    if portfolio is not None:
        try:
            out.update(_book_truth(user, portfolio))
        except Exception as e:
            logger.debug(f"Panel book detail unavailable: {e}")

    # ── The bot program: what it is actually doing right now ─────────────
    try:
        out.update(_bot_truth(user, out))
    except Exception as e:
        logger.debug(f"Panel bot detail unavailable: {e}")

    # ── Realised P&L over 24h, across both books ─────────────────────────
    # Distinguish "nothing closed" (em-dash) from "closed flat" (+0.00).
    try:
        bot_pnl = (out.get("panel_bot") or {}).get("pnl_24h")
        legacy_pnl = out.get("panel_legacy_pnl_24h")
        closes = (out.get("panel_bot_trades_24h") or 0) + (
            out.get("panel_legacy_closed_24h") or 0)
        if closes:
            total = (bot_pnl or 0.0) + (legacy_pnl or 0.0)
            out["panel_realised_24h_display"] = _signed(total)
            out["panel_realised_24h_n"] = closes
        else:
            out["panel_realised_24h_display"] = None
            out["panel_realised_24h_n"] = 0
    except Exception as e:
        logger.debug(f"Panel realised P&L unavailable: {e}")

    # ── The signals themselves, not just how many ────────────────────────
    try:
        from signals.models import Signal
        # SAME set and order as the signal rail (panel_recent_signals:
        # newest five active). This cell used to show the top four BY
        # SCORE, so the headband popup and the rail disagreed about what
        # "the current signals" were — two truths on one screen.
        out["panel_top_signals"] = [{
            "symbol": s.instrument.symbol,
            "direction": s.direction,
            "score_pct": int(round((s.score or 0) * 100)),
            "rule": s.rule_name or s.signal_type or "",
            "created_at": s.created_at,
            "entry": s.suggested_entry,
            "stop": s.suggested_stop,
        } for s in Signal.objects.filter(is_active=True)
            .select_related("instrument").order_by("-created_at")[:5]]
    except Exception as e:
        logger.debug(f"Panel signal detail unavailable: {e}")

    # ── Watchlist with prices, so the cell is a watchlist and not a count ─
    try:
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        # Starred instruments, NOT positions-on-starred-instruments: the old
        # expression counted open portfolio positions that happened to be
        # watchlisted, so the cell read 0 forever on a box with seven stars
        # and no positions — while its own dropdown listed the seven.
        starred = Instrument.objects.filter(is_watchlist=True, is_active=True)
        out["panel_watchlist"] = starred.count()
        wl = list(starred[:6])
        wq = {q.instrument_id: q for q in LiveQuote.objects.filter(
            instrument__in=wl)} if wl else {}
        out["panel_watchlist_rows"] = [{
            "symbol": i.symbol,
            "last": wq[i.id].last if i.id in wq else None,
            "change": _f(wq[i.id].change_pct) if i.id in wq else None,
        } for i in wl]
    except Exception as e:
        logger.debug(f"Panel watchlist detail unavailable: {e}")

    # ── Drawdown, with the peak it is measured from ──────────────────────
    try:
        from portfolio.models import PortfolioSnapshot
        if portfolio is not None:
            snaps = list(PortfolioSnapshot.objects.filter(portfolio=portfolio)
                         .order_by("-date")[:180])
            if snaps:
                peak = max(snaps, key=lambda s: s.total_value or 0)
                cur = snaps[0]
                out["panel_dd_peak"] = peak.total_value
                out["panel_dd_peak_date"] = peak.date
                out["panel_dd_current"] = cur.total_value
                out["panel_dd_snapshots"] = len(snaps)
                if cur.max_drawdown is not None:
                    # Already stored as a negative percentage by
                    # portfolio.tasks — do not multiply by 100, and show it
                    # as a magnitude.
                    out["panel_drawdown"] = f"{abs(float(cur.max_drawdown)):.1f}"
                # A snapshot from last week does not describe today's P&L.
                if (cur.date == timezone.localdate()
                        and cur.daily_pnl_pct is not None):
                    pct = float(cur.daily_pnl_pct)
                    out["panel_daily_pnl"] = pct
                    out["panel_daily_pnl_display"] = f"{pct:+.2f}%"
    except Exception as e:
        logger.debug(f"Panel drawdown detail unavailable: {e}")

    # ── Realised volatility. There is no VIX feed in this platform, and the
    #    cell was labelled "VIX index" while rendering a variable nobody set.
    #    This is what we can actually measure: 20-day annualised realised
    #    volatility of the instrument with the most price history.
    try:
        import statistics
        from market_data.models import PriceData

        # Periods per year, for annualising. Do NOT hardcode a timeframe: this
        # deployment holds 4h and 1h bars and no daily ones at all, so asking
        # for "1d" found nothing and the cell would have stayed blank forever
        # while looking like a missing feed.
        PERIODS = {"1d": 252, "4h": 252 * 6, "1h": 252 * 24}
        for tf, per_year in PERIODS.items():
            bars = list(PriceData.objects.filter(timeframe=tf)
                        .order_by("-timestamp")
                        .values_list("instrument__symbol", "close")[:600])
            by_symbol = {}
            for sym, close in bars:
                by_symbol.setdefault(sym, []).append(float(close))
            best = max(by_symbol.items(), key=lambda kv: len(kv[1]), default=None)
            if not best or len(best[1]) < 21:
                continue
            closes = best[1][:21]                     # newest first
            rets = [(closes[i] - closes[i + 1]) / closes[i + 1]
                    for i in range(20) if closes[i + 1]]
            if len(rets) >= 10:
                out["panel_vol_pct"] = round(
                    statistics.pstdev(rets) * (per_year ** 0.5) * 100, 1)
                out["panel_vol_symbol"] = best[0]
                out["panel_vol_days"] = len(rets)
                out["panel_vol_tf"] = tf
                break
    except Exception as e:
        logger.debug(f"Panel volatility unavailable: {e}")

    if not testing:
        cache.set(key, out, PANEL_TTL_SECONDS)
    return out


def _compact(value):
    """Money at a glance: 1.2B, 340M, 18K.

    The liquidation cells are 60px wide in the info panel. A raw
    1,238,904,551 does not fit and wraps into the cell below it, so the figure
    that gets read is whichever half survived.
    """
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= cut:
            return f"{n / cut:,.1f}{suffix}"
    return f"{n:,.0f}"


def sauron_context(request):
    """Inject all global data into every template."""

    # ── Timezone ──
    user_tz = "UTC"
    # ── Idle PIN lock ──
    # pin_locked mirrors the session flag core.idle_lock enforces, so the
    # shell can paint itself pre-locked instead of flashing data first.
    # idle_lock feeds the client timer its config; the related-object
    # accessor is cached on request.user, so this shares the timezone
    # lookup's query rather than adding one.
    pin_locked = False
    idle_lock = {"enabled": False, "minutes": 10, "has_pin": False}
    if hasattr(request, "user") and request.user.is_authenticated:
        try:
            pin_locked = bool(request.session.get("pin_locked"))
        except Exception:
            pass
        try:
            profile = request.user.trader_profile
            user_tz = profile.timezone_preference or "UTC"
            idle_lock = {
                "enabled": profile.idle_lock_enabled,
                "minutes": profile.idle_lock_minutes,
                "has_pin": profile.has_pin,
            }
        except Exception:
            pass

    # ── Exchange status ──
    try:
        exchange_data = get_exchange_status()
    except Exception:
        exchange_data = {"open_count": 0, "total": 14, "exchanges": []}

    # ── Enabled markets ──
    try:
        from core.market_config import MarketConfig
        enabled_markets = list(MarketConfig.objects.filter(is_enabled=True).values_list("market_key", flat=True))
    except Exception:
        enabled_markets = ["stock", "forex", "commodity"]

    # ── Defaults ──
    # None, never "0" and never "+0.00%". Every one of these is a
    # measurement, and until one has been taken the honest answer is an
    # em-dash. A confident red 0.0% drawdown reads as "no downside", not as
    # "we could not compute it" — which is the failure mode this platform
    # already has a whole test module about.
    ctx = {
        "user_timezone": user_tz,
        "pin_locked": pin_locked,
        "idle_lock": idle_lock,
        "exchanges_open_count": exchange_data["open_count"],
        "exchanges_total": exchange_data["total"],
        "exchanges_list": exchange_data["exchanges"],
        "enabled_markets": enabled_markets,
        "ticker_items": [],
        "notification_count": 0,
        "recent_notifications": [],
        "panel_currency": "",
        "panel_currency_symbol": "",
        "panel_portfolio_value": None,
        "panel_cash": None,
        "panel_deployed": None,
        "panel_cash_pct": None,
        "panel_pool": None,
        "panel_pool_used": None,
        "panel_pool_free": None,
        "panel_pool_free_neg": False,
        "panel_positions": 0,
        "panel_positions_priced": 0,
        # False and not None: before a book has been read there is no partial
        # total to warn about, and a warning that fires on "not measured yet"
        # is one an operator learns to ignore.
        "panel_positions_unpriced": 0,
        "panel_value_partial": False,
        "panel_exposure": None,
        "panel_book_coverage": "",
        "panel_open_pnl": None,
        "panel_open_pnl_display": None,
        "panel_n_long": 0,
        "panel_n_short": 0,
        "panel_open_r": None,
        "panel_open_r_display": None,
        "panel_open_r_n": 0,
        "panel_open_rows": [],
        "panel_open_rows_hidden": 0,
        "panel_realised_24h_display": None,
        "panel_realised_24h_n": 0,
        "panel_signals": 0,
        "panel_bullish": 0,
        "panel_bearish": 0,
        "panel_strategies": 0,
        "panel_news": 0,
        "panel_sentiment": "—",
        "panel_ai_cost": "0.00",
        "panel_ai_tasks": 0,
        "panel_drawdown": None,
        "panel_max_dd": None,
        "panel_daily_pnl": None,
        "panel_daily_pnl_display": None,
        # Fourteen of the thirty panel_* names below were rendered by
        # base.html and assigned by nothing at all, so the info panel showed a
        # fabricated constant on every page of the platform. The BOT cell was
        # the worst of them: panel_bot_armed was never set, so the header
        # permanently reported OFF / OFFLINE / 0 open even with the bot armed
        # and holding positions.
        "panel_signals_24h": 0,
        # None, not a fabricated OFF: a bot program whose state we failed to
        # read must never be drawn as "not running".
        "panel_bot": None,
        "panel_bot_armed": None,
        "panel_bot_mode": None,
        "panel_bot_open": None,
        "panel_bot_open_r_display": None,
        "panel_bot_pnl_24h_display": None,
        "panel_funding_display": None,
        "panel_funding_extreme_count": None,
        "panel_funding_flips": None,
        "panel_funding_samples": None,
        "panel_liq_24h_display": None,
        "panel_liq_count": None,
        "panel_liq_long_display": None,
        "panel_liq_short_display": None,
        "panel_vix": None,
        "panel_watchlist": 0,
        "panel_recent_signals": [],
        "panel_recent_positions": [],
        "panel_recent_news": [],
        "panel_recent_strategies": [],
    }

    if not hasattr(request, "user") or not request.user.is_authenticated:
        return ctx

    # ── Notifications ──
    try:
        from alerts.models import Notification
        ctx["notification_count"] = Notification.unread_count(request.user)
        ctx["recent_notifications"] = list(Notification.recent(request.user, limit=10))
    except Exception as e:
        logger.debug(f"Notifications unavailable: {e}")

    # ── Ticker + Panel ──
    try:
        from market_data.models import LiveQuote
        from signals.models import Signal
        from scraping.models import NewsArticle
        from django.utils import timezone as tz
        from datetime import timedelta

        now = tz.now()
        day_ago = now - timedelta(hours=24)
        ticker = []

        # No quotes here and no signals either, deliberately. The headband
        # directly above already shows live prices, and the signals rail on
        # the right is the signals' home — each carried in the ticker was a
        # duplicate crowding out the one thing with no other home: news.
        active_signals = Signal.objects.filter(is_active=True)

        # News
        for n in NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:18]:
            try:
                affected_list = list(n.ai_affected_instruments.all()[:6])
                affected_chips = [i.symbol for i in affected_list]
                affected_syms = ", ".join(affected_chips)
            except Exception:
                affected_syms = ""; affected_chips = []
            summary_txt = (n.ai_summary or n.content_summary or "").strip()
            import re as _re
            tokens = _re.findall(r"\b[A-Z][A-Za-z]{3,}\b", n.title or "")
            keywords = list(dict.fromkeys(tokens))[:5]
            sent = n.ai_sentiment_score
            if sent is None: implication = "Impact pending analysis"
            elif sent > 0.3: implication = "Bullish — risk-on setup"
            elif sent < -0.3: implication = "Bearish — risk-off setup"
            else: implication = "Neutral — mixed signal"
            ticker.append({
                "type": "news", "news_id": n.id, "title": n.title, "source": n.source,
                "summary": summary_txt[:400],
                "sentiment_score": sent,
                "urgency": n.ai_urgency or "",
                "affected": affected_syms,
                "affected_chips": affected_chips,
                "keywords": keywords,
                "implication": implication,
                "published_at": n.published_at.strftime("%H:%M") if n.published_at else "",
                "url": f"/news/{n.id}/",
            })

        ctx["ticker_items"] = ticker
        ctx["panel_signals"] = active_signals.count()
        # Rendered by base.html as "24H NEW" and assigned by nothing, so the
        # signals dropdown reported zero new signals in perpetuity.
        ctx["panel_signals_24h"] = Signal.objects.filter(created_at__gte=day_ago).count()
        ctx["panel_bullish"] = active_signals.filter(direction="bullish").count()
        ctx["panel_bearish"] = active_signals.filter(direction="bearish").count()
        # The STRATEGIES cell counts RuleControl rows — what the ENGINE runs.
        # It used to count strategies.Strategy, the wizard's hand-written
        # plans that nothing executes, so an install with twelve rules running
        # reported "STRATEGIES 0 active" in the headband of every page.
        #
        # The cell's sub-label is "active", and this is the population that
        # word names: the rules allowed to emit a signal right now. That is
        # deliberately NARROWER than the ladder count on /strategies/ ("IN THE
        # LADDER") and on the landing page ("on the ladder"), both of which are
        # every RuleControl row including the ones an admin has paused. Two
        # honest numbers, two labels — so the page this cell deep-links to
        # prints the running count next to the ladder count and the operator
        # can see the difference resolve instead of guessing at it.
        from signals.models_control import RuleControl
        ctx["panel_strategies"] = RuleControl.objects.filter(
            running_rules_q(now)).count()
        ctx["panel_news"] = NewsArticle.objects.filter(published_at__gte=day_ago).count()

    except Exception as e:
        logger.debug(f"Ticker/panel data unavailable: {e}")

    # Computed independently of the ticker block above: that one is wrapped in
    # its own try, and if it fails before assigning day_ago every panel below
    # would die on a NameError swallowed as "no data".
    day_ago = timezone.now() - timedelta(hours=24)

    # The whole headband — cells and dropdowns — behind one cache.
    try:
        ctx.update(_panel_detail(request.user))
    except Exception as e:
        logger.debug(f"Panel detail unavailable: {e}")

    # ── Funding and liquidations ──
    try:
        from market_data.models import FundingRate, LiquidationEvent

        rates = list(FundingRate.objects.filter(
            timestamp__gte=day_ago).values_list("symbol", "funding_rate"))
        if rates:
            values = [float(r) for _, r in rates if r is not None]
            if values:
                ctx["panel_funding_samples"] = len(values)
                ctx["panel_funding_display"] = f"{sum(values) / len(values) * 100:+.4f}%"
                ctx["panel_funding_extreme_count"] = sum(
                    1 for v in values if abs(v) >= 0.001)
                # A flip is the rate changing sign for a symbol: the moment
                # the crowd stops paying to be long and starts paying to be
                # short, which is the whole reason to watch this number.
                flips = 0
                by_symbol = {}
                for symbol, rate in rates:
                    if rate is None:
                        continue
                    by_symbol.setdefault(symbol, []).append(float(rate))
                for series in by_symbol.values():
                    flips += sum(1 for a, b in zip(series, series[1:])
                                 if (a >= 0) != (b >= 0))
                ctx["panel_funding_flips"] = flips

        liqs = LiquidationEvent.objects.filter(timestamp__gte=day_ago)
        agg = liqs.aggregate(total=Sum("notional_usd"), n=Count("id"))
        if agg["n"]:
            ctx["panel_liq_count"] = agg["n"]
            ctx["panel_liq_24h_display"] = _compact(agg["total"] or 0)
            longs = liqs.filter(side__iexact="long").aggregate(t=Sum("notional_usd"))["t"]
            shorts = liqs.filter(side__iexact="short").aggregate(t=Sum("notional_usd"))["t"]
            ctx["panel_liq_long_display"] = _compact(longs or 0)
            ctx["panel_liq_short_display"] = _compact(shorts or 0)
    except Exception as e:
        logger.debug(f"Funding/liquidation panel data unavailable: {e}")

    # Expanded panel signals + news
    try:
        from signals.models import Signal
        from scraping.models import NewsArticle
        # "-created_at", not "-score": this list is named RECENT and feeds the
        # signals rail top-down — ranking by score parked a strong old signal
        # at the top while new arrivals appeared buried mid-list. The score is
        # already visible on every card (gauge + number); the rail's job is
        # what just happened.
        ctx["panel_recent_signals"] = list(Signal.objects.filter(is_active=True).select_related("instrument").order_by("-created_at")[:5])
        ctx["panel_recent_news"] = list(NewsArticle.objects.order_by("-published_at")[:5])
        ctx["panel_news_sentiment"] = _news_sentiment_24h(NewsArticle)
        # Matching the count above filter for filter: the rules the engine
        # runs, newest stage movement first, each labelled with the stage it
        # sits at — the thing an operator wants from this dropdown ("what is
        # running, and how far has it earned its way up").
        #
        # Coalesced onto created_at, and not a bare "-stage_entered_at".
        # stage_entered_at is nullable with no default and neither seeder
        # writes it, so all twelve shipped rules carry NULL; Django emits a
        # bare ORDER BY … DESC and lets the backend decide where NULLs go.
        # PostgreSQL — production — sorts NULLs largest, so DESC put every
        # never-promoted rule ahead of every rule that had actually earned a
        # stage, and the five slots were permanently the alphabetically-first
        # seeds. SQLite, which dev and CI run, orders NULLs the other way, so
        # the bug is invisible locally. Coalescing rather than nulls_last
        # matches how dashboard.views and promotion_pipeline already read this
        # field (`stage_entered_at or created_at`) and gives a never-moved rule
        # a real recency instead of merely parking it at the back.
        from signals.models_control import RuleControl
        ctx["panel_recent_strategies"] = [
            {"name": r.rule_name, "status": r.promotion_stage.replace("_", " ")}
            for r in RuleControl.objects.filter(running_rules_q())
            .order_by(Coalesce("stage_entered_at", "created_at").desc(),
                      "rule_name")[:5]
        ]
    except Exception as e:
        logger.debug(f"Panel signals/news unavailable: {e}")

    return ctx
