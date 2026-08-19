"""The Wall's numbers must be real, cheap, fenced, and anonymous.

The public landing page hardcoded "667 tests green" while the suite sat at
1,923, and scrolled a ticker of invented late-2024 quotes (SPX 5,842.31,
BTC 97,234.00) directly under the words "Fully Auditable". A fabricated
figure on the one page whose pitch is auditability is not a placeholder —
it is the claim disproving itself, in the same viewport.

`core.wall_facts` replaces those literals. This module pins the four
properties that make it safe to point the login gateway at a database:

  1. The contract holds. Eleven keys, every one an int, every one a count —
     the template and the other half of this wave both index that shape.

  2. The counts are real. Create rows, and the numbers move with them. A
     "real" number that ignores the database is just a slower literal.

  3. It cannot 500. This is the LOGIN page: if a counter dies, the honest
     outcome is a 0 next to a label, not a locked front door for every user
     of an otherwise healthy platform. Each counter is fenced on its own, so
     one dead query must not zero the other ten.

  4. Nothing personal escapes. Anonymous visitors read this context. Counts
     only — no username, no symbol, no P&L, no broker in use.

Run with:  python manage.py test tests.test_wall_facts
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.utils import OperationalError
from django.test import TestCase
from django.utils import timezone

from core.wall_facts import (
    CACHE_KEY,
    FALLBACK_FACTS,
    TESTS_GREEN,
    wall_facts,
)


CONTRACT_KEYS = (
    "tests_green", "asset_classes", "broker_adapters", "evaluators",
    "instruments", "signals_graded", "trades_graded", "strategies",
    "chain_length", "news_24h", "bots",
)


def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _graded_signal(inst, outcome="hit_target"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction="bullish",
        urgency="high", title="t", description="d", rule_name="wf_rule",
        score=0.9, sub_scores={}, price_at_signal=Decimal("100"),
        outcome=outcome, realized_r=1.5, is_active=False)


def _cfg(user, asset_class="crypto", name="WF"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode="paper",
        symbols=["ZZTESTPAIR"], capital=Decimal("10000"))


def _graded_trade(cfg, symbol="ZZTESTPAIR"):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("110"),
        status="CLOSED", outcome="hit_target", realized_r=2.0,
        closed_at=timezone.now())


class WallFactsContractTests(TestCase):
    """The shape both the view and the template are written against."""

    def setUp(self):
        # LocMemCache survives the per-test transaction rollback, so a payload
        # built from another test's fixtures would otherwise be served here.
        cache.clear()

    def test_every_contract_key_is_present_and_an_int(self):
        """The template indexes these names directly. A missing key renders
        as an empty string in Django, which on this page would read as a
        deleted capability rather than a bug — so absence must fail here."""
        facts = wall_facts()
        for key in CONTRACT_KEYS:
            self.assertIn(key, facts, f"contract key {key!r} missing")
            self.assertIsInstance(
                facts[key], int, f"{key} must be an int, got {type(facts[key])}")
            self.assertNotIsInstance(
                facts[key], bool, f"{key} must be a count, not a bool")

    def test_no_extra_keys_leak_into_the_public_context(self):
        """The contract is closed on purpose. Anything extra reaching this
        dict reaches an anonymous visitor, and the review that catches it is
        this one."""
        self.assertEqual(set(wall_facts()), set(CONTRACT_KEYS))

    def test_tests_green_is_the_named_constant_and_not_the_stale_literal(self):
        """667 was true once and then quietly was not, for ~1,250 tests. The
        number now lives in exactly one place; the template renders
        {{ wall.tests_green }} and carries no literal to go stale."""
        self.assertEqual(wall_facts()["tests_green"], TESTS_GREEN)
        self.assertNotEqual(TESTS_GREEN, 667)

    def test_tests_green_still_matches_the_actual_suite(self):
        """The real guard. Comparing the constant to the retired 667 passes
        for ANY wrong number — which is how the first version of this module
        shipped a count that its own commit had already invalidated. This
        counts the suite instead, so the public figure cannot drift again:
        if it fails, run the suite and put the new "Ran N" in TESTS_GREEN.
        """
        import unittest

        from django.conf import settings

        suite = unittest.defaultTestLoader.discover(
            start_dir=str(settings.BASE_DIR / "tests"),
            pattern="test*.py",
            top_level_dir=str(settings.BASE_DIR),
        )
        self.assertEqual(
            TESTS_GREEN, suite.countTestCases(),
            "core/wall_facts.TESTS_GREEN is stale — the wall publishes it")

    def test_counts_are_never_negative(self):
        """A count is a count. Guards against a future counter switching to
        an aggregate that can return None and being coerced to -1."""
        for key, value in wall_facts().items():
            self.assertGreaterEqual(value, 0, f"{key} went negative")


class KillSwitchNeedsThePinTests(TestCase):
    """The wall now tells the public the kill switch is behind the PIN. It
    was true of the HQ button and false of /api/kill-switch/, which reached
    the same function with @login_required and nothing else — a stolen
    session could flatten the book. The copy and the code now agree."""

    def setUp(self):
        from django.contrib.auth.models import User

        from portfolio.trader_profile import get_or_create_profile
        self.user = User.objects.create_user("ks_u", password="x")
        prof = get_or_create_profile(self.user)
        prof.set_pin("4321")
        prof.save()
        self.client.force_login(self.user)

    def test_without_a_pin_the_book_stays_open(self):
        import json
        from unittest.mock import patch

        with patch("bot_program.engine.kill_switch.execute_kill_switch") as ks:
            r = self.client.post("/api/kill-switch/",
                                 data=json.dumps({"reason": "test"}),
                                 content_type="application/json")
        self.assertEqual(r.status_code, 403)
        ks.assert_not_called()

    def test_a_wrong_pin_is_refused(self):
        import json
        from unittest.mock import patch

        with patch("bot_program.engine.kill_switch.execute_kill_switch") as ks:
            r = self.client.post("/api/kill-switch/",
                                 data=json.dumps({"pin": "0000"}),
                                 content_type="application/json")
        self.assertEqual(r.status_code, 403)
        ks.assert_not_called()

    def test_the_right_pin_flattens(self):
        import json
        from unittest.mock import patch

        with patch("bot_program.engine.kill_switch.execute_kill_switch",
                   return_value={"ok": True}) as ks:
            r = self.client.post("/api/kill-switch/",
                                 data=json.dumps({"pin": "4321"}),
                                 content_type="application/json")
        self.assertEqual(r.status_code, 200)
        ks.assert_called_once()


class WallCopyIsTrueTests(TestCase):
    """Claims on the public page must match what the platform does. These
    pin the three the review caught as fiction."""

    def setUp(self):
        self.body = self.client.get("/wall/").content.decode("utf-8", "replace")

    def test_take_trade_does_not_claim_the_orchestrator_gate(self):
        # bot_program/manual_trade.py never calls gate_new_entry.
        self.assertNotIn("passed through the same orchestrator gate", self.body)

    def test_take_trade_does_not_promise_a_live_manual_path(self):
        # manual_trade refuses any config that is not paper.
        self.assertNotIn("Paper venue until you arm live", self.body)

    def test_the_evaluator_count_is_not_spelled_out_in_prose(self):
        """The stat cell counts the registry; prose saying "twelve" beside it
        is the same stale-literal failure as 667, just in words."""
        self.assertNotIn("Twelve evaluators", self.body)
        self.assertNotIn("twelve evaluator kinds", self.body)


class MarketSessionTests(TestCase):
    """The wall used to paint LONDON and NEW YORK open in static markup, so
    a visitor at 03:00 UTC read two blinking, false market states on a page
    whose badge says "Fully Auditable"."""

    def _at(self, hour, minute=0):
        from datetime import datetime, timezone as dt_timezone

        from core.wall_facts import market_sessions
        return {s["name"]: s["is_open"] for s in market_sessions(
            datetime(2026, 8, 19, hour, minute, tzinfo=dt_timezone.utc))}

    def test_london_and_new_york_are_closed_in_the_middle_of_the_night(self):
        state = self._at(3)
        self.assertFalse(state["LONDON"])
        self.assertFalse(state["NEW YORK"])

    def test_tokyo_is_open_in_the_middle_of_the_night(self):
        self.assertTrue(self._at(3)["TOKYO"])

    def test_london_is_open_during_its_window(self):
        self.assertTrue(self._at(9)["LONDON"])

    def test_a_session_that_crosses_midnight_is_handled(self):
        """Sydney runs 21:00→05:00; naive start<=now<end reads it as always
        closed."""
        self.assertTrue(self._at(23)["SYDNEY"])
        self.assertTrue(self._at(2)["SYDNEY"])
        self.assertFalse(self._at(12)["SYDNEY"])

    def test_the_wall_renders_session_state_from_the_server(self):
        r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("sessions", r.context)

    def test_no_session_pill_carries_a_hardcoded_state(self):
        """Asserting on the RENDERED page would pass or fail with the clock
        — London really is open for eight hours a day, and the loop then
        emits the very markup a naive assertion reads as hardcoded. The
        template source is the honest place to check."""
        with open("templates/landing/the_wall.html", encoding="utf-8") as fh:
            src = fh.read()
        row = src.split('class="sess-row"')[1].split("</div>")[0]
        self.assertIn("{% for s in sessions %}", row)
        self.assertNotIn('sess-pill open"', row,
                         "the open state must come from the server clock")


class DegradedCacheTests(TestCase):
    """A payload built during a database blip used to be cached for the full
    five minutes, so the front door advertised zeros long after the database
    came back."""

    def setUp(self):
        cache.clear()

    def test_a_degraded_build_gets_a_short_leash(self):
        from unittest.mock import patch

        from core import wall_facts as wf
        with patch.object(wf, "_count_instruments", side_effect=OSError("db")), \
             patch.object(wf, "cache") as fake_cache:
            fake_cache.get.return_value = None
            wf.wall_facts()
            ttl = fake_cache.set.call_args.args[2]
        self.assertEqual(ttl, wf.DEGRADED_TTL)

    def test_a_healthy_build_is_cached_for_the_full_window(self):
        from unittest.mock import patch

        from instruments.models import Instrument
        from core import wall_facts as wf
        Instrument.objects.create(
            symbol="WALLTTL", name="ttl", asset_class="forex", is_active=True)
        with patch.object(wf, "cache") as fake_cache:
            fake_cache.get.return_value = None
            wf.wall_facts()
            ttl = fake_cache.set.call_args.args[2]
        self.assertEqual(ttl, wf.CACHE_TTL)


class WallFactsRealDataTests(TestCase):
    """Numbers that do not move with the database are literals in disguise."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="wall_facts_fixture_user", password="x")

    def test_instruments_and_asset_classes_track_the_instrument_table(self):
        """Two asset classes, three instruments — and the retired one counts
        for neither, because "tracked" has to mean currently watched."""
        from instruments.models import Instrument
        _instrument("ZZAAA", "crypto")
        _instrument("ZZBBB", "crypto")
        _instrument("ZZCCC", "forex")
        Instrument.objects.create(
            symbol="ZZDEAD", name="ZZDEAD", asset_class="stock", is_active=False)

        facts = wall_facts()
        self.assertEqual(facts["instruments"], 3)
        self.assertEqual(facts["asset_classes"], 2)

    def test_signals_graded_counts_resolved_signals_only(self):
        """Grading is the whole self-improvement claim. An open signal has
        not been graded, so it must not inflate the number."""
        inst = _instrument("ZZAAA")
        _graded_signal(inst, outcome="hit_target")
        _graded_signal(inst, outcome="stopped_out")
        from signals.models import Signal
        Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="low", title="open", description="d", rule_name="wf_rule",
            score=0.5, sub_scores={}, price_at_signal=Decimal("100"))

        self.assertEqual(wall_facts()["signals_graded"], 2)

    def test_trades_graded_counts_closed_trades_with_an_r_multiple(self):
        """R-multiple, not P&L: only trades carrying R can feed the promotion
        ladder, so only those are what the page is claiming to have."""
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user)
        _graded_trade(cfg)
        AssetBotTrade.objects.create(  # still open — ungraded
            config=cfg, asset_class="crypto", symbol="ZZTESTPAIR", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN")

        self.assertEqual(wall_facts()["trades_graded"], 1)

    def test_strategies_counts_the_promotion_ladder(self):
        """Every RuleControl row sits at a promotion_stage, so the ladder's
        population is the row count."""
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="wf_rule_a")
        RuleControl.objects.create(rule_name="wf_rule_b")

        self.assertEqual(wall_facts()["strategies"], 2)

    def test_chain_length_counts_audit_chain_entries(self):
        """This is the number backing the page's "AUDIT CHAIN" section — the
        length of a hash-chain that can be verified, not a log line count."""
        from bot_program.audit_models import AuditLogEntry, GENESIS_HASH
        AuditLogEntry.objects.create(
            kind="system", data={"n": 1}, prev_hash=GENESIS_HASH,
            payload_hash="a" * 64)
        AuditLogEntry.objects.create(
            kind="system", data={"n": 2}, prev_hash="a" * 64,
            payload_hash="b" * 64)

        self.assertEqual(wall_facts()["chain_length"], 2)

    def test_news_24h_excludes_older_articles(self):
        """"in the last 24h" is the claim; a week-old article answering it
        would be the same species of lie as a hardcoded price."""
        from scraping.models import NewsArticle
        now = timezone.now()
        NewsArticle.objects.create(
            title="fresh", source="s", url="https://example.test/zz-fresh",
            published_at=now - timedelta(hours=2))
        NewsArticle.objects.create(
            title="stale", source="s", url="https://example.test/zz-stale",
            published_at=now - timedelta(days=7))

        self.assertEqual(wall_facts()["news_24h"], 1)

    def test_bots_counts_configured_bots_regardless_of_enabled_state(self):
        """Configured, not enabled: an enabled-only count would drop to 0 the
        moment the kill switch fires, which tells the opposite story."""
        _cfg(self.user, asset_class="crypto", name="WF-A")
        _cfg(self.user, asset_class="forex", name="WF-B")

        self.assertEqual(wall_facts()["bots"], 2)

    def test_evaluators_reads_the_live_registry(self):
        """The registry is populated by import side-effects (the Phase 34-36
        families register at the bottom of the scanner module), so the count
        must come from it rather than from a hand-kept list."""
        from signals.opportunity_scanner import EVALUATOR_REGISTRY
        self.assertEqual(wall_facts()["evaluators"], len(EVALUATOR_REGISTRY))
        self.assertGreater(wall_facts()["evaluators"], 0)

    def test_broker_adapters_matches_the_named_adapter_list(self):
        """Named, not globbed off bot_program/engine/ — otherwise the next
        helper module dropped in there becomes a "broker we support"."""
        from core.wall_facts import BROKER_ADAPTERS
        self.assertEqual(wall_facts()["broker_adapters"], len(BROKER_ADAPTERS))

    def test_the_wall_renders_with_the_real_numbers_in_context(self):
        """End to end: the view hands the template the live counts, not a
        constant. Asserted on the context rather than the rendered HTML so
        this test pins the wiring and not somebody's markup."""
        _instrument("ZZAAA", "crypto")
        _instrument("ZZCCC", "forex")
        cfg = _cfg(self.user)
        _graded_trade(cfg)

        r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 200)
        wall = r.context["wall"]
        self.assertEqual(wall["instruments"], 2)
        self.assertEqual(wall["asset_classes"], 2)
        self.assertEqual(wall["trades_graded"], 1)
        self.assertEqual(wall["bots"], 1)
        self.assertEqual(wall["tests_green"], TESTS_GREEN)

    def test_authenticated_users_still_bounce_to_the_dashboard(self):
        """The counts are additive to the view, not a replacement for it —
        logged-in users must never land on the marketing page."""
        self.client.force_login(self.user)
        r = self.client.get("/wall/")
        self.assertEqual(r.status_code, 302)


class WallFactsFencingTests(TestCase):
    """The login gateway stays open through a database or cache failure."""

    def setUp(self):
        cache.clear()

    def test_one_dead_counter_does_not_zero_the_others(self):
        """The whole point of fencing each counter separately: a table that a
        half-applied migration has not created yet must cost one number, not
        eleven."""
        _instrument("ZZAAA", "crypto")

        with patch("core.wall_facts._count_instruments",
                   side_effect=OperationalError("no such table")):
            facts = wall_facts()

        self.assertEqual(facts["instruments"], 0)          # the fenced one
        self.assertEqual(facts["asset_classes"], 1)        # still real
        self.assertEqual(facts["tests_green"], TESTS_GREEN)

    def test_a_dead_counter_still_renders_the_page(self):
        """A 500 here locks every user out of a healthy platform over a stat
        nobody logs in to read."""
        with patch("core.wall_facts._count_chain_length",
                   side_effect=OperationalError("relation does not exist")):
            r = self.client.get("/wall/")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["wall"]["chain_length"], 0)

    def test_a_total_database_outage_still_renders_the_page(self):
        """Every DB-backed counter fails at once — the constants survive and
        the page serves."""
        with patch("django.db.models.query.QuerySet.count",
                   side_effect=OperationalError("could not connect")):
            r = self.client.get("/wall/")

        self.assertEqual(r.status_code, 200)
        wall = r.context["wall"]
        self.assertEqual(wall["tests_green"], TESTS_GREEN)
        self.assertGreater(wall["broker_adapters"], 0)
        self.assertEqual(wall["instruments"], 0)
        self.assertEqual(wall["news_24h"], 0)

    def test_a_dead_cache_degrades_to_a_live_computation(self):
        """Redis going down should cost latency, not the front door."""
        _instrument("ZZAAA", "crypto")

        with patch("core.wall_facts.cache.get_or_set",
                   side_effect=RuntimeError("connection refused")):
            facts = wall_facts()

        self.assertEqual(facts["instruments"], 1)

    def test_a_stale_cached_payload_is_backfilled_from_the_contract(self):
        """A deploy that adds a key must not render a hole for the 5 minutes
        the previous payload still lives in Redis."""
        cache.set(CACHE_KEY, {"instruments": 7}, 300)
        facts = wall_facts()

        self.assertEqual(facts["instruments"], 7)
        self.assertEqual(set(facts), set(CONTRACT_KEYS))
        self.assertEqual(facts["tests_green"], FALLBACK_FACTS["tests_green"])

    def test_wall_facts_never_raises_even_when_the_builder_explodes(self):
        """Last line of defence: whatever happens, the view gets a dict."""
        with patch("core.wall_facts.cache.get_or_set",
                   side_effect=RuntimeError("cache down")), \
             patch("core.wall_facts._build_facts",
                   side_effect=RuntimeError("everything is on fire")):
            facts = wall_facts()

        self.assertEqual(facts, FALLBACK_FACTS)


class WallFactsCachingTests(TestCase):
    """Eleven aggregates on an unauthenticated page is a free DoS surface."""

    def setUp(self):
        cache.clear()

    def test_a_warm_call_issues_no_queries(self):
        """The Wall is the most-hit URL on the box and needs no per-visitor
        freshness: one build per five minutes, then pure cache reads."""
        wall_facts()  # warm

        with self.assertNumQueries(0):
            wall_facts()

    def test_repeated_page_loads_do_not_rebuild_the_facts(self):
        """Same guarantee through the view, where it actually matters."""
        self.client.get("/wall/")
        first = cache.get(CACHE_KEY)
        self.assertIsInstance(first, dict)

        _instrument("ZZAAA", "crypto")  # a change the cache should hide
        r = self.client.get("/wall/")

        self.assertEqual(r.context["wall"]["instruments"], first["instruments"])

    def test_clearing_the_cache_picks_up_new_data(self):
        """The flip side — cached, not frozen."""
        wall_facts()
        _instrument("ZZAAA", "crypto")
        cache.clear()

        self.assertEqual(wall_facts()["instruments"], 1)


class WallFactsPrivacyTests(TestCase):
    """Anonymous visitors read this page. Counts only."""

    def setUp(self):
        cache.clear()

    def test_no_username_of_a_user_with_data_reaches_the_page(self):
        """A bot config stringifies as "<username> · CRYPTO · <name>". If any
        counter ever switches from .count() to a list of objects, the
        username lands in the HTML of a page served to the whole internet —
        this test is what stops that landing silently."""
        user = User.objects.create_user(
            username="zz_wall_private_operator", password="x")
        cfg = _cfg(user)
        _graded_trade(cfg)
        _graded_signal(_instrument("ZZAAA"))

        body = self.client.get("/wall/").content.decode("utf-8", errors="ignore")

        self.assertNotIn("zz_wall_private_operator", body)
        # Nor the instrument the operator is actually trading.
        self.assertNotIn("ZZTESTPAIR", body)
        self.assertNotIn("ZZAAA", body)

    def test_every_public_value_is_a_bare_integer(self):
        """No strings means no symbol, no broker name, and no P&L can ride
        along in the payload, whatever a future counter is tempted to add."""
        user = User.objects.create_user(username="zz_wall_private_two", password="x")
        _graded_trade(_cfg(user))

        for key, value in wall_facts().items():
            self.assertIs(type(value), int, f"{key} is {type(value)}, not int")
