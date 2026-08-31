"""Real counts for the public landing page (templates/landing/the_wall.html).

The Wall advertised "Fully Auditable" a few hundred pixels above a hardcoded
"667 tests green" and a ticker of invented late-2024 quotes (SPX 5,842.31,
BTC 97,234.00). Those were never placeholders in any useful sense: a made-up
price on the one page whose entire pitch is auditability is the single lie
that costs the pitch. This module is the source of the numbers that page
renders, so there is exactly one place to check them against reality.

What ships here — and what deliberately does not
------------------------------------------------

Every value is an aggregate COUNT. Never a symbol, a price, a P&L, a
username, a broker in use, or anything else tied to one account. This page is
the login gateway: its context is readable by anyone on the internet, so the
rule is enforced here at the source rather than left to whoever edits the
template next.

Fencing
-------

`wall_facts()` cannot raise. A dead cache, an unreachable database, or a
table that does not exist yet mid-migration must all degrade to a number,
because a 500 on the front door locks every user out of a platform that is
otherwise perfectly healthy. Each counter carries its own fence, so one bad
query zeroes its own key and leaves the other ten alone.

A degraded counter reports 0 — never a remembered figure, never an estimate.
0 reads as "nothing measured", which is true; anything else would smuggle
back exactly the fabrication this module exists to remove.
"""
import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Build-time constants ────────────────────────────────────────────────────

# UPDATE THIS WITH THE SUITE. `python manage.py test` ends with "Ran N tests";
# put N here when it changes. This is the ONLY place the number lives — the
# template renders {{ wall.tests_green }} and must never carry a literal
# again, which is how the old "667" survived roughly 1,250 new tests.
# tests/test_wall_facts.py counts the suite and fails when this drifts: the
# first version of this module shipped a number its own commit had already
# invalidated, which is exactly the failure it was written to prevent.
TESTS_GREEN = 5427

# Broker adapters implemented under bot_program/engine/ — one module and one
# client class each, all reachable from broker_router.client_for_symbol().
# Named rather than globbed off the directory: a glob would silently promote
# the next helper someone drops in there into a "broker we support".
BROKER_ADAPTERS = (
    "alpaca",           # engine/alpaca_client.py           AlpacaTrader
    "binance",          # engine/binance_client.py          BinanceClient
    "binance_futures",  # engine/binance_futures_client.py  BinanceFuturesClient
    "ibkr",             # engine/ibkr_client.py             IBKRTrader
    "oanda",            # engine/oanda_client.py            OANDATrader
    "paper",            # engine/paper_trader.py            PaperTrader
)

CACHE_KEY = "sv:wall_facts:v1"
CACHE_TTL = 300  # seconds
DEGRADED_TTL = 15  # a payload built while the DB was down expires fast

# The shape every caller can rely on, and the answer of last resort if even
# the fenced builder cannot be reached. Keys are the public contract; the
# template indexes this dict and nothing else.
FALLBACK_FACTS = {
    "tests_green": TESTS_GREEN,
    "asset_classes": 0,
    "broker_adapters": len(BROKER_ADAPTERS),
    "evaluators": 0,
    "instruments": 0,
    "signals_graded": 0,
    "trades_graded": 0,
    "strategies": 0,
    "chain_length": 0,
    "news_24h": 0,
    "bots": 0,
}


# ── Individual counters ─────────────────────────────────────────────────────
#
# Each one is a module-level function so a single counter can be failed in
# isolation (both by a real outage and by a test), and so the fence in
# `_safe` stays one line per key rather than eleven nested try blocks.

def _count_asset_classes() -> int:
    """Distinct asset classes we actually hold live instruments in.

    Not len(AssetClass.CHOICES): the enum lists nine classes the schema can
    express, which is a claim about the code, not about the deployment. The
    page says "asset classes" next to instruments and bots, so it has to mean
    the ones with something in them.
    """
    from instruments.models import Instrument
    return (Instrument.objects
            .filter(is_active=True)
            .values("asset_class")
            .distinct()
            .count())


def _count_instruments() -> int:
    """Active instruments tracked. Retired rows keep their history but stop
    being something we can honestly say we watch."""
    from instruments.models import Instrument
    return Instrument.objects.filter(is_active=True).count()


def _count_evaluators() -> int:
    """Registered opportunity evaluators — the `kind` handlers an
    OpportunitySetup's JSON can name.

    Read off the live registry, not a hand-maintained list: importing the
    scanner is what registers the built-ins, and the Phase 34-36 advanced
    families register by side-effect at the bottom of that same module. A
    literal here would rot the same way "667" did.
    """
    from signals.opportunity_scanner import EVALUATOR_REGISTRY
    return len(EVALUATOR_REGISTRY)


def _count_signals_graded() -> int:
    """Signals that reached an outcome (hit_target / stopped_out / expired /
    manual_close) — i.e. the ones the system has graded itself on.

    Written as an IN over the four outcome values rather than `exclude(
    outcome="")`: `<> ''` on the leading column of signals_sig_outcome_idx is
    not a sargable range, so the exclusion form walks the table while this one
    can ride the index.
    """
    from signals.models import Signal
    graded = [value for value, _label in Signal.OUTCOME_CHOICES]
    return Signal.objects.filter(outcome__in=graded).count()


def _count_trades_graded() -> int:
    """Closed bot trades carrying a realized R-multiple.

    R, not P&L: R normalises by initial risk, so this is the count of trades
    that can actually feed the promotion ladder. Honest about cost: `status`
    is never a leading column on this table's indexes and `realized_r` is
    unindexed, so this one IS a scan. It stays acceptable only because the
    cache runs it at most once every five minutes; if the table grows past
    comfort the fix is an index, not a smaller-looking query.
    """
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.filter(
        status="CLOSED", realized_r__isnull=False).count()


def _count_strategies() -> int:
    """Rules sitting in the Phase-8 promotion ladder.

    Every RuleControl row carries a promotion_stage (research → paper →
    live_small → live_full), so the row count IS the ladder population. The
    `strategies.Strategy` model is a different thing — user-authored trade
    plans — and counting it here would answer a question nobody asked.
    """
    from signals.models_control import RuleControl
    return RuleControl.objects.count()


def _count_chain_length() -> int:
    """Entries in the Phase-28 hash-chained audit log.

    This is the number that backs the page's "AUDIT CHAIN" claim: every row
    is append-only and hashes its predecessor, so the count is the length of
    a chain that can be verified, not a log line count.
    """
    from bot_program.audit_models import AuditLogEntry
    return AuditLogEntry.objects.count()


def _count_news_24h() -> int:
    """News articles published into the platform in the last 24 hours.

    `published_at` carries no index today, so this is a scan — acceptable
    only because the 300s cache caps it at twelve scans an hour, and because
    adding the index needs a migration this change deliberately does not
    ship. If the news table ever gets large, index published_at and revisit.
    """
    from scraping.models import NewsArticle
    cutoff = timezone.now() - timedelta(hours=24)
    return NewsArticle.objects.filter(published_at__gte=cutoff).count()


def _count_bots() -> int:
    """Configured asset bots across the platform.

    Configured, not enabled: the page is describing what the platform is set
    up to run, and an enabled-only count would flip to 0 every time the kill
    switch fired — which is the opposite of the story the number tells.
    """
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.count()


# ── Assembly ────────────────────────────────────────────────────────────────

def _safe(name: str, builder, fallback: int) -> int:
    """Run one counter inside its own fence.

    Deliberately catches everything, including OperationalError from a table
    that a half-applied migration has not created yet. The alternative — let
    it propagate — takes down the login page for a schema detail that has
    nothing to do with logging in.
    """
    try:
        return int(builder())
    except Exception as exc:
        logger.debug("wall_facts: %s unavailable (%s) — reporting %d",
                     name, exc, fallback)
        return fallback


def _is_degraded(facts: dict) -> bool:
    """True when a counter that should have data reported its fallback.

    A brand-new install genuinely has zeros everywhere, so this cannot mean
    "any zero". It means the two counters that exist the moment the schema
    does — instruments and the evaluator registry — came back empty, which in
    practice is a database or import failure rather than an empty platform.
    """
    return not facts.get("instruments") or not facts.get("evaluators")


def _build_facts() -> dict:
    """Compute every contract key. Never raises — see `_safe`.

    Builders are looked up through module globals at call time (rather than
    captured in a table at import) so a test can fail exactly one counter and
    assert the other ten survived it.
    """
    return {
        # Build-time constants: no query, so nothing can degrade them.
        "tests_green": TESTS_GREEN,
        "broker_adapters": len(BROKER_ADAPTERS),
        # In-process registry: no query either, but the import can fail.
        "evaluators": _safe("evaluators", _count_evaluators, 0),
        # Database counts, one fence each.
        "asset_classes": _safe("asset_classes", _count_asset_classes, 0),
        "instruments": _safe("instruments", _count_instruments, 0),
        "signals_graded": _safe("signals_graded", _count_signals_graded, 0),
        "trades_graded": _safe("trades_graded", _count_trades_graded, 0),
        "strategies": _safe("strategies", _count_strategies, 0),
        "chain_length": _safe("chain_length", _count_chain_length, 0),
        "news_24h": _safe("news_24h", _count_news_24h, 0),
        "bots": _safe("bots", _count_bots, 0),
    }


def market_sessions(now=None) -> list:
    """The four trading sessions with their REAL state right now.

    Deliberately outside the cached facts and outside the database: it is
    pure clock arithmetic, so it costs nothing and is never five minutes
    stale. The wall used to paint London and New York as open in hardcoded
    markup, which meant a visitor at 03:00 UTC read two blinking, false
    market states on the page that advertises "Fully Auditable" — the same
    species of fabrication as the invented ticker prices this module removed.
    """
    from core.constants import MARKET_SESSIONS

    now = now or timezone.now()
    minutes = now.hour * 60 + now.minute
    out = []
    for key, window in MARKET_SESSIONS.items():
        try:
            oh, om = (int(p) for p in window["open"].split(":"))
            ch, cm = (int(p) for p in window["close"].split(":"))
        except Exception:  # noqa: BLE001 — a malformed window is not a 500
            continue
        start, end = oh * 60 + om, ch * 60 + cm
        # Sydney runs 21:00→05:00, i.e. across midnight.
        is_open = (start <= minutes < end) if start < end else (
            minutes >= start or minutes < end)
        out.append({
            "name": key.replace("_", " ").upper(),
            "window": f"{window['open']}–{window['close']}",
            "is_open": is_open,
        })
    return out


def wall_facts() -> dict:
    """Public counts for The Wall. Cached for `CACHE_TTL`, and never raises.

    Two independent failure modes are fenced here rather than at the call
    site, because the call site is a view an anonymous visitor hits:

      - the cache itself is unreachable → compute the facts directly, so a
        Redis outage costs latency instead of the front door;
      - the cache returns something that is not our dict (a stale payload
        from an older key shape) → fall through to a fresh build.
    """
    try:
        facts = cache.get(CACHE_KEY)
    except Exception as exc:
        logger.warning("wall_facts: cache unavailable (%s) — computing live", exc)
        facts = None

    if not isinstance(facts, dict):
        try:
            facts = _build_facts()
        except Exception as exc:  # noqa: BLE001 — the front door stays open
            logger.error("wall_facts: build failed (%s) — serving fallbacks", exc)
            return dict(FALLBACK_FACTS)
        try:
            # A payload built during a database blip is all fallbacks, and
            # caching THAT for the full window would leave the front door
            # advertising zeros for five minutes after the DB came back. A
            # degraded build gets a short leash instead.
            cache.set(CACHE_KEY, facts,
                      DEGRADED_TTL if _is_degraded(facts) else CACHE_TTL)
        except Exception:  # noqa: BLE001 — a dead cache costs latency, not the page
            pass

    # Any key a future cached payload predates is filled from the fallbacks,
    # so the template never hits a missing-variable hole after a deploy.
    return {**FALLBACK_FACTS, **facts}
