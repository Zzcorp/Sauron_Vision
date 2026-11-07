"""THE OCULUS, O0 — cost and truth in today's look (2026-11-06).

The page read 81 queries per call, walked the source tree on every staff
GET, and printed a handful of numbers that read as something they were
not: a REAL MONEY column that counted the broker's demo rows, "unresolved"
and "never graded" counts that included what was simply not due yet, a
probe count with no date, lifetime totals with no window, money cut to an
integer. These tests pin the fixes. They change what the page SAYS, never
what the desk, the engine or any switch does: the world split is a display
helper over the same rows, with the desk's own formula, and a test below
holds it to the desk's sum.

Every symbol and amount here is synthetic and round.

Run with:  python manage.py test tests.test_oculus_truth
"""
import html as _html
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from dashboard.oculus import oculus


def _cycle(data, key):
    return next(c for c in data["cycles"] if c["key"] == key)


def _facts(cycle):
    return {f["label"]: f for f in cycle["facts"]}


def _every_fact(data):
    """(place, fact) for every fact on the page, the book's included."""
    for cycle in data["cycles"]:
        for fact in cycle.get("facts", []):
            yield cycle["key"], fact
        for venue in cycle.get("venues", []):
            for fact in venue.get("facts", []):
                yield f"book.{venue['venue']}", fact
        for world in cycle.get("worlds", []):
            for fact in world.get("facts", []):
                yield f"book.{world['world']}", fact


def _content(body):
    """The Oculus's own part of the page: the shell around it (headband,
    rail, ticket) is not the Oculus and carries its own forms."""
    start = body.index('class="page-content')
    return body[start:body.index("</main>", start)]


def _config(user, name, mode, capital, currency="USD"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="forex", name=name, enabled=True, mode=mode,
        symbols=[], capital=Decimal(capital), base_currency=currency)


def _open(config, symbol, qty, entry, stop, *, paper, stamps,
          status="OPEN"):
    from bot_program.models import AssetBotTrade
    meta = dict(stamps)
    if stop is not None:
        meta["initial_stop_loss"] = float(stop)
    return AssetBotTrade.objects.create(
        config=config, asset_class=config.asset_class, symbol=symbol,
        side="BUY", qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=Decimal(stop) if stop is not None else None,
        status=status, paper=paper, metadata=meta)


REAL = {"broker": "etoro", "broker_env": "live"}
DEMO = {"broker": "etoro", "broker_env": "paper"}
PAPER = {"broker": "paper"}


def _seed_three_worlds(user, *, demo=True):
    """One REAL row (10.00 at its stop), one eToro DEMO row (100.00) and
    one PAPER row (10.00). The demo row is paper=False, exactly as the
    broker's demo segment books it."""
    live = _config(user, "o0 live pool", "live", "1000")
    paper = _config(user, "o0 paper pool", "paper", "4000")
    _open(live, "EURUSD", "1000", "1.10", "1.09", paper=False, stamps=REAL)
    if demo:
        _open(live, "XAUUSD", "1", "2000", "1900", paper=False, stamps=DEMO)
    _open(paper, "BTCUSD", "0.01", "60000", "59000", paper=True,
          stamps=PAPER)
    return live, paper


def _keyed_etoro(user, *, read_ago=timedelta(minutes=1), equity="10000"):
    """A keyed eToro account carrying a class, with an equity cell the sync
    stored `read_ago`: the operator's own shape, where the desk's governor
    reads the withdrawals and the equity history."""
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(
        user=user, is_primary_for_forex=True, last_equity=Decimal(equity),
        last_equity_currency="USD", last_equity_at=timezone.now() - read_ago)
    acct.set_credentials("o0-api-key", "o0-user-key")
    acct.save()
    return acct


def _row_of(body, label):
    """The page's table row that carries `label`."""
    row = body[:body.index(label)]
    row = body[row.rindex("<tr"):]
    return row[:row.index("</tr>")]


class TheBookSplitsTheWorldsTests(TestCase):
    """REAL, DEMO and PAPER, side by side and never summed (B3.1).

    The desk's live venue is `paper=False`, which is real money AND the
    broker's demo rows. The REAL MONEY column follows the platform's one
    world rule (dashboard.position_summary.world_of) instead, and the
    desk's own numbers stay on the page, labelled as the desk's, with how
    many demo rows they still count."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_book", password="x")

    def _book(self):
        return _cycle(oculus(user=self.user), "book")

    def test_real_leaves_the_demo_row_out(self):
        _seed_three_worlds(self.user)
        worlds = {w["world"]: w for w in self._book()["worlds"]}
        self.assertEqual(list(worlds), ["live", "demo", "paper"])
        self.assertEqual(worlds["live"]["word"], "REAL MONEY")

        def cents(world):   # the desk's float arithmetic, read to the cent
            return {k: round(v, 2) for k, v in world["risk"].items()}

        self.assertEqual(worlds["live"]["n_open"], 1)
        self.assertEqual(cents(worlds["live"]), {"USD": 10.0})
        self.assertEqual(worlds["demo"]["n_open"], 1)
        self.assertEqual(cents(worlds["demo"]), {"USD": 100.0})
        self.assertEqual(worlds["paper"]["n_open"], 1)
        self.assertEqual(cents(worlds["paper"]), {"USD": 10.0})
        risk = {f["label"]: f for f in worlds["live"]["facts"]}[
            "risk at the stops"]
        self.assertEqual(risk["display"], "10.00")

    def test_the_three_worlds_are_the_desks_own_sum_over_the_same_rows(self):
        """A display helper may never drift from the desk: the same rows,
        book_risk's formula, and the split adds back to the desk's two
        venues to the cent."""
        from bot_program.capital_desk import book_risk
        live, _paper = _seed_three_worlds(self.user)
        # a row with no readable stop, and a closing one: both on the book
        _open(live, "AAPL", "10", "200", None, paper=False, stamps=REAL)
        _open(live, "BTCUSD", "0.02", "60000", "59500", paper=False,
              stamps=REAL, status="CLOSE_PENDING")
        book = self._book()
        split = sum(sum(w["risk"].values()) for w in book["worlds"])
        desk = (book_risk(self.user, "live")["risk"]
                + book_risk(self.user, "paper")["risk"])
        self.assertAlmostEqual(split, desk, places=9)
        n_split = sum(w["n_open"] for w in book["worlds"])
        n_desk = (book_risk(self.user, "live")["n_open"]
                  + book_risk(self.user, "paper")["n_open"])
        self.assertEqual(n_split, n_desk)
        real = next(w for w in book["worlds"] if w["world"] == "live")
        self.assertEqual(real["unmeasured"], 1)
        self.assertEqual(real["n_close_pending"], 1)

    def test_there_is_no_total(self):
        """REAL, DEMO and PAPER are never added, anywhere on the page."""
        _seed_three_worlds(self.user)
        book = self._book()
        self.assertEqual(len(book["worlds"]), 3)
        for world in book["worlds"]:
            for fact in world["facts"]:
                self.assertNotIn("total", fact["label"].lower())
        self.assertNotIn("total", " ".join(book.keys()))
        self.client.force_login(self.user)
        body = _html.unescape(_content(
            self.client.get(reverse("oculus_dashboard")).content.decode()))
        start = body.index("THE OPEN BOOK, BY MONEY WORLD")
        worlds = body[start:body.index("WHAT THE DESK SIZES WITH", start)]
        self.assertIn("never summed", worlds)
        # REAL + DEMO is 110.00 and all three 120.00: the worlds print
        # neither. (110.00 does appear below, as the desk's own live venue,
        # labelled as the desk's and with how many demo rows it counts.)
        self.assertNotIn("110.00", worlds)
        self.assertNotIn("120.00", body)

    def test_the_desk_says_how_many_demo_rows_it_still_counts(self):
        _seed_three_worlds(self.user)
        desk = self._book()["desk"]
        self.assertEqual(desk["demo_counted"]["n"], 1)
        self.assertAlmostEqual(desk["demo_counted"]["risk"], 100.0)
        self.assertIn("1 eToro DEMO row", desk["sentence"])
        self.assertIn("100.00", desk["sentence"])

    def test_with_no_demo_row_the_desk_counts_real_rows_only(self):
        """The sentence prints a measured count. When the desk stops
        counting demo, or there is none, it says so by itself."""
        _seed_three_worlds(self.user, demo=False)
        desk = self._book()["desk"]
        self.assertEqual(desk["demo_counted"]["n"], 0)
        self.assertIn("REAL rows only", desk["sentence"])

    def test_the_desk_venues_carry_their_reason_currency_and_aside(self):
        """The governor's "100" meant TWO things and budget_for already
        knew which: its reason, currency and asides reach the page."""
        _seed_three_worlds(self.user)
        venues = {v["venue"]: v for v in self._book()["venues"]}
        self.assertEqual(list(venues), ["live", "paper"])
        self.assertEqual(venues["live"]["reason"],
                         "no equity reading — governor 1.00")
        self.assertEqual(venues["paper"]["reason"],
                         "paper venue — no drawdown governor")
        for venue in venues.values():
            self.assertEqual(venue["currency"], "USD")
            self.assertEqual(venue["not_summed"], {})
            self.assertEqual(venue["n_other_currency"], 0)

    def test_the_paper_pool_says_it_holds_the_live_pools_too(self):
        """5,000.00 = 4,000.00 paper + 1,000.00 live: the paper venue
        divides by both, which the bare number never said (B3.2)."""
        _seed_three_worlds(self.user)
        sentence = self._book()["desk"]["paper_sentence"]
        self.assertIn("5,000.00", sentence)
        self.assertIn("4,000.00 paper", sentence)
        self.assertIn("1,000.00 live", sentence)

    def test_the_page_prints_the_worlds_and_the_desk_labelled_as_the_desks(self):
        _seed_three_worlds(self.user)
        self.client.force_login(self.user)
        body = _html.unescape(_content(
            self.client.get(reverse("oculus_dashboard")).content.decode()))
        self.assertIn("REAL MONEY", body)
        self.assertIn("DEMO", body)
        self.assertIn("PAPER", body)
        self.assertIn("1 eToro DEMO row", body)
        self.assertIn("no equity reading — governor 1.00", body)
        # the desk's live venue is not called real money any more
        self.assertNotIn("LIVE · REAL MONEY", body)


class MoneyKeepsItsCentsTests(TestCase):
    """`int()` cut 473.8 to 473 and -0.6 to 0 (B1.5): a breached budget
    could print as an exact zero."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_money", password="x")

    def test_a_money_fact_keeps_two_decimals(self):
        from dashboard.oculus import _fact
        up = _fact("risk", lambda: 473.8, kind="money")
        down = _fact("budget", lambda: -0.6, kind="money")
        self.assertEqual(up["value"], 473.8)
        self.assertEqual(up["display"], "473.80")
        self.assertEqual(down["value"], -0.6)
        self.assertEqual(down["display"], "-0.60")

    def test_the_page_prints_the_cents_never_a_zero(self):
        def _budget(user, venue, **kwargs):
            return {"budget": -0.6, "gross": 70.0, "capital": 3500.0,
                    "currency": "USD", "not_summed": {}, "book_risk": 473.8,
                    "unmeasured_open": 0, "n_other_currency": 0,
                    "n_open": 5, "entries": [], "governor": 1.0,
                    "drawdown_pct": None,
                    "reason": "no equity reading — governor 1.00"}

        self.client.force_login(self.user)
        with mock.patch("bot_program.capital_desk.budget_for",
                        side_effect=_budget):
            body = _html.unescape(_content(self.client.get(
                reverse("oculus_dashboard")).content.decode()))

        def _value(label):
            row = body[:body.index(label)]
            row = row[row.rindex("<tr"):]
            return re.sub(r"<[^>]+>", "", row[row.index("ocu-v"):]
                          .split("</td>")[0].split(">", 1)[1]).strip()

        self.assertEqual(_value("risk to stop committed"), "473.80")
        self.assertEqual(_value("budget left"), "-0.60")


class EveryCountNamesItsWindowTests(TestCase):
    """A lifetime total with no window reads as current state (B3.5)."""

    WINDOWS = ("now", "today", "24 h", "7 d", "30 d", "all time")

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("o0_win", password="x",
                                              is_staff=True)

    def test_every_fact_carries_a_window_or_says_it_is_a_constant(self):
        from dashboard.oculus import WINDOWS
        self.assertEqual(tuple(WINDOWS), self.WINDOWS)
        _seed_three_worlds(self.staff)
        for place, fact in _every_fact(oculus(user=self.staff)):
            with self.subTest(place=place, label=fact["label"]):
                if fact["kind"] == "constant":
                    self.assertEqual(fact["window"], "constant")
                else:
                    self.assertIn(fact["window"], self.WINDOWS)

    def test_the_lifetime_counts_say_all_time(self):
        data = oculus(user=self.staff)
        for key, label in (
                ("signals", "graded: target hit"),
                ("signals", "graded: stopped out"),
                ("signals", "closed with no grade"),
                ("evolution", "proposals approved"),
                ("evolution", "mutations actually backtested"),
                ("allocation", "share plans actually applied"),
                ("allocation", "desk passes in shadow"),
                ("allocation", "desk passes live"),
                ("backtests", "engine v1 runs"),
                ("backtests", "bot runs"),
                ("trust", "direction calls graded right"),
                ("trust", "direction calls graded wrong"),
                ("scan", 'detections graded "no price"')):
            with self.subTest(cycle=key, label=label):
                self.assertEqual(_facts(_cycle(data, key))[label]["window"],
                                 "all time")

    def test_the_constants_say_constant(self):
        data = oculus(user=self.staff)
        for key, label in (("personas", "personalities defined"),
                           ("forge", "tests published on the wall")):
            with self.subTest(cycle=key, label=label):
                fact = _facts(_cycle(data, key))[label]
                self.assertEqual(fact["kind"], "constant")
                self.assertEqual(fact["window"], "constant")

    def test_the_page_prints_the_windows(self):
        self.client.force_login(self.staff)
        body = _html.unescape(_content(
            self.client.get(reverse("oculus_dashboard")).content.decode()))
        for word in ("all time", "constant", "30 d", "7 d"):
            self.assertIn(word, body)

    def test_the_scan_caveat_reads_its_schedule_and_its_setups(self):
        """'about 179 instruments, 09:00 UTC' was typed prose: the time
        now comes from the beat entry and the count from the setups."""
        from signals.models_opportunity import OpportunitySetup
        for i in range(3):
            OpportunitySetup.objects.create(name=f"o0 setup {i}",
                                            direction="bullish",
                                            is_active=True)
        from core.day_of_sauron import read_schedule, schedule_words
        beat, _routes = read_schedule()
        when = schedule_words(beat["scan-opportunities"]["schedule"])[0]
        caveat = _cycle(oculus(user=self.staff), "scan")["caveat"]
        self.assertNotIn("179", caveat)
        self.assertIn(f"{when} UTC", caveat)
        self.assertIn("3 armed setups", caveat)


class NotDueIsNotLateTests(TestCase):
    """The resolver calls a flag whose horizon has not passed `not_due`,
    "the healthiest thing a flag can be". The page counted it as
    unresolved, in amber (B3.6); the same for live signals and for calls
    whose due date is ahead.

    Late is what fell due before the resolver's last pass, so these tests
    fix that pass half an hour ago: a real nightly pass would make them
    depend on the time of day (LateMeansPastTheResolversLastPassTests
    holds the pass itself)."""

    def setUp(self):
        cache.clear()
        self.now = timezone.now()
        last_pass = mock.patch("dashboard.oculus._last_pass",
                               return_value=self.now - timedelta(minutes=30))
        last_pass.start()
        self.addCleanup(last_pass.stop)

    def _instrument(self, symbol="EURUSD"):
        from instruments.models import Instrument
        return Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "forex"})[0]

    def test_a_flag_inside_its_horizon_is_not_due_and_past_it_is_late(self):
        from signals.models_opportunity import OpportunityFlag, OpportunitySetup
        setup = OpportunitySetup.objects.create(name="o0 flags",
                                                direction="bullish")
        inst = self._instrument()
        # (days ago, horizon days): inside, inside, past, past, resolved
        for ago, horizon, outcome in ((2, 5, ""), (0, 1, ""), (6, 5, ""),
                                      (3, 1, ""), (40, 5, "hit")):
            flag = OpportunityFlag.objects.create(
                setup=setup, instrument=inst, score=0.5, outcome=outcome,
                horizon_days=horizon)
            OpportunityFlag.objects.filter(pk=flag.pk).update(
                scanned_at=self.now - timedelta(days=ago, minutes=1))
        facts = _facts(_cycle(oculus(), "scan"))
        self.assertEqual(facts["detections not due yet"]["value"], 2)
        self.assertEqual(facts["detections not due yet"]["tone"], "inert")
        late = facts["detections past due, unresolved"]
        self.assertEqual(late["value"], 2)
        self.assertTrue(late["alert"])
        self.assertIn("the resolver is late", late["alert_words"])

    def test_a_live_signal_is_not_an_ungraded_one(self):
        from signals.models import Signal
        inst = self._instrument()
        Signal.objects.bulk_create([
            Signal(instrument=inst, signal_type="technical",
                   direction="bullish", urgency="low", title="o0",
                   description="o0", rule_name="o0_rule", score=0.5,
                   price_at_signal=Decimal("1"), outcome=outcome,
                   is_active=active)
            for outcome, active in (("", True), ("", True), ("", False),
                                    ("hit_target", False))])
        facts = _facts(_cycle(oculus(), "signals"))
        self.assertEqual(facts["still live, not graded yet"]["value"], 2)
        self.assertEqual(facts["still live, not graded yet"]["tone"], "inert")
        closed = facts["closed with no grade"]
        self.assertEqual(closed["value"], 1)
        self.assertTrue(closed["alert"])
        self.assertEqual(facts["graded: target hit"]["value"], 1)

    def test_a_call_before_its_due_date_is_not_due_and_after_it_is_late(self):
        from ai_agents.models import AgentPrediction
        for due in (self.now + timedelta(days=1), self.now + timedelta(hours=1),
                    self.now - timedelta(hours=1), None):
            AgentPrediction.objects.create(
                agent="o0_agent", prediction_type="direction",
                predicted_value="up", expected_resolution_at=due)
        AgentPrediction.objects.create(
            agent="o0_agent", prediction_type="direction",
            predicted_value="up", was_correct=True, evaluated_at=self.now,
            expected_resolution_at=self.now - timedelta(days=2))
        facts = _facts(_cycle(oculus(), "trust"))
        self.assertEqual(facts["calls not due yet"]["value"], 2)
        self.assertEqual(facts["calls not due yet"]["tone"], "inert")
        late = facts["calls past due, ungraded"]
        # past its due date, and the one with none: no grader reaches it
        self.assertEqual(late["value"], 2)
        self.assertTrue(late["alert"])
        self.assertIn("nobody is grading", late["alert_words"])
        self.assertEqual(facts["direction calls graded right"]["value"], 1)


class AmberNeedsAThresholdTests(TestCase):
    """Colour means state (§5.3): amber or coral only when a stated
    threshold is crossed, with its glyph and its words, and never on a
    dash."""

    def setUp(self):
        cache.clear()

    def test_alert_when_holds_only_past_its_threshold(self):
        from dashboard.oculus import _fact

        def flag(value, rule, kind="count"):
            return _fact("x", lambda: value, kind=kind, alert_when=rule,
                         alert_words="past it")["alert"]

        self.assertEqual([flag(v, ("<", 0), "money") for v in (-0.01, 0, 5)],
                         [True, False, False])
        self.assertEqual([flag(v, (">", 0)) for v in (0, 1)], [False, True])
        self.assertEqual([flag(v, (">", 45), "days") for v in (45, 46)],
                         [False, True])
        plain = _fact("x", lambda: 7)
        self.assertFalse(plain["alert"])
        self.assertEqual(plain["alert_words"], "")

    def test_a_dash_never_raises_the_flag(self):
        from dashboard.oculus import _fact

        def _boom():
            raise RuntimeError("no such table")

        for builder in (_boom, lambda: None):
            fact = _fact("x", builder, alert_when=(">", 0), alert_words="w")
            self.assertIsNone(fact["value"])
            self.assertFalse(fact["alert"])

    def test_the_facts_the_spec_names_declare_their_threshold(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="o0_broken", defaults={"is_enabled": True,
                                       "last_status": "error"})
        PlatformComponent.objects.update_or_create(
            key="o0_never", defaults={"is_enabled": True,
                                      "last_run_at": None})
        gates = _facts(_cycle(oculus(), "gates"))
        self.assertTrue(gates["last pass in error"]["alert"])
        self.assertEqual(gates["last pass in error"]["alert_level"], "danger")
        self.assertTrue(gates["on but never run"]["alert"])
        self.assertEqual(gates["on but never run"]["alert_level"], "warn")
        self.assertFalse(gates["components on"]["alert"])

    def test_the_page_never_paints_a_dash_in_alert(self):
        staff = User.objects.create_user("o0_dash", password="x",
                                         is_staff=True)
        cache.delete("forge:route_probe")   # the probe's two dashes
        self.client.force_login(staff)
        body = _content(self.client.get(
            reverse("oculus_dashboard")).content.decode())
        dash_cells = re.findall(r'<td class="([^"]*\bdash\b[^"]*)"', body)
        self.assertTrue(dash_cells, "the probe's dashes are not on the page")
        for classes in dash_cells:
            self.assertNotIn("alert", classes.split())

    def test_an_alert_prints_its_glyph_and_its_words(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="o0_broken", defaults={"is_enabled": True,
                                       "last_status": "error"})
        staff = User.objects.create_user("o0_alert", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        body = _html.unescape(_content(self.client.get(
            reverse("oculus_dashboard")).content.decode()))
        row = body[body.index("last pass in error"):]
        row = row[:row.index("</tr>")]
        self.assertIn("⨯", row)


class EveryDashIsNamedTests(TestCase):
    """The footer promised every dash and missed the book's (B3.8)."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_named", password="x")
        _seed_three_worlds(self.user)

    def test_a_book_fact_dash_is_named_with_its_reason(self):
        from bot_program import capital_desk
        real = capital_desk.budget_for

        def _no_budget(user, venue, **kwargs):
            out = real(user, venue, **kwargs)
            if venue == "live":
                out["budget"] = None
            return out

        with mock.patch("bot_program.capital_desk.budget_for",
                        side_effect=_no_budget):
            data = oculus(user=self.user)
        self.assertIn("book.live.budget left", data["degraded"])
        row = next(r for r in data["not_measured"]
                   if r["name"] == "book.live.budget left")
        self.assertEqual(row["place"], "book · live · budget left")
        self.assertTrue(row["why"])

    def test_an_unreadable_venue_and_gap_are_named_by_type_only(self):
        from dashboard import oculus as mod
        original = mod._venue_facts

        def _half(user, venue):
            if venue == "live":
                raise RuntimeError("secret detail of the failure")
            return original(user, venue)

        with mock.patch.object(mod, "_venue_facts", side_effect=_half), \
                mock.patch("bot_program.bot_grading.paper_live_expectancy_gap",
                           side_effect=ValueError("another detail")):
            data = oculus(user=self.user)
            self.client.force_login(self.user)
            body = _html.unescape(_content(self.client.get(
                reverse("oculus_dashboard")).content.decode()))
        self.assertIn("book.live", data["degraded"])
        self.assertIn("book.expectancy gap", data["degraded"])
        why = {r["name"]: r["why"] for r in data["not_measured"]}
        self.assertIn("RuntimeError", why["book.live"])
        self.assertIn("ValueError", why["book.expectancy gap"])
        # in the footer, by name and reason, never by message
        self.assertIn("book · live", body)
        self.assertIn("book · expectancy gap", body)
        self.assertIn("RuntimeError", body)
        self.assertNotIn("secret detail", body)
        self.assertNotIn("another detail", body)

    def test_failures_log_at_warning_once_per_fact(self):
        from dashboard import oculus as mod
        mod._WARNED.clear()

        def _boom():
            raise RuntimeError("table mid-migration")

        with self.assertLogs("dashboard.oculus", level="WARNING") as logs:
            mod._fact("o0 once", _boom)
            mod._fact("o0 once", _boom)
            mod._fact("o0 twice", _boom)
        warned = [r for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warned), 2, [r.getMessage() for r in warned])


class TheForgeIsReadOncePerBuildTests(TestCase):
    """The forge read 1,297 files and built a migration plan on every
    staff GET (B4.1). The answer changes per build, so it is read once per
    build, and the page prints how old the reading is."""

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("o0_forge", password="x",
                                              is_staff=True)

    def _patched(self):
        scan = mock.patch("pathlib.Path.rglob",
                          side_effect=lambda *a, **k: iter(()))
        plan = mock.patch("django.db.migrations.executor.MigrationExecutor")
        return scan, plan

    def test_cold_reads_warm_does_not_and_a_new_build_reads_again(self):
        scan_p, plan_p = self._patched()
        with mock.patch.dict("os.environ", {"SAURON_GIT_SHA": "aaaaaaa"}), \
                scan_p as scan, plan_p as plan:
            plan.return_value.migration_plan.return_value = []
            oculus(user=self.staff)                       # cold
            self.assertEqual((scan.call_count, plan.call_count), (1, 1))
            forge = _facts(_cycle(oculus(user=self.staff), "forge"))  # warm
            self.assertEqual((scan.call_count, plan.call_count), (1, 1))
        self.assertEqual(forge["guarded tasks with no switch"]["value"], 0)
        self.assertEqual(forge["migrations pending"]["value"], 0)
        self.assertRegex(forge["migrations pending"]["age"]["words"],
                         r"^plan checked (just now|\d+ (min|h|d) ago)$")
        self.assertIn("this build",
                      forge["guarded tasks with no switch"]["age"]["words"])

        scan_p, plan_p = self._patched()
        with mock.patch.dict("os.environ", {"SAURON_GIT_SHA": "bbbbbbb"}), \
                scan_p as scan, plan_p as plan:
            plan.return_value.migration_plan.return_value = []
            oculus(user=self.staff)                       # a new image
            self.assertEqual((scan.call_count, plan.call_count), (1, 1))

    def test_how_long_each_reading_is_kept(self):
        """With a stamped image the scan cannot change until the next one;
        the migration plan can (migrate runs on the same image): ten
        minutes. Without a stamp the scan is a dev checkout's: ten minutes
        too."""
        from dashboard import oculus as mod
        seen = {}
        real_set = cache.set

        def _set(key, value, timeout=None, *a, **k):
            seen[key] = timeout
            return real_set(key, value, timeout, *a, **k)

        stamped = {"SAURON_GIT_SHA": "ccccccc",
                   "SAURON_BUILT_AT": "2026-01-07T10:00:00Z"}
        with mock.patch.object(cache, "set", side_effect=_set):
            with mock.patch.dict("os.environ", stamped):
                oculus(user=self.staff)
                build = mod._build_id()
            env = {k: v for k, v in __import__("os").environ.items()
                   if k not in stamped}
            with mock.patch.dict("os.environ", env, clear=True):
                oculus(user=self.staff)
        self.assertEqual(build, "ccccccc@2026-01-07T10:00:00Z")
        self.assertIsNone(seen[mod.FORGE_GUARDS_KEY.format(build=build)])
        self.assertEqual(seen[mod.FORGE_MIGRATIONS_KEY.format(build=build)],
                         600)
        self.assertEqual(seen[mod.FORGE_GUARDS_KEY.format(build="unstamped")],
                         600)

    def test_a_missing_probe_is_a_named_dash_and_a_stored_one_its_age(self):
        cache.delete("forge:route_probe")
        data = oculus(user=self.staff)
        raising = _facts(_cycle(data, "forge"))[
            "pages that raise, at the last probe"]
        self.assertIsNone(raising["value"])
        row = next(r for r in data["not_measured"]
                   if r["name"] == "forge.pages that raise, at the last probe")
        self.assertEqual(row["why"], "no probe stored: never run, cleared, "
                                     "or older than 7 days")
        self.assertIn("probe_routes", row["fix"])

        cache.set("forge:route_probe", {
            "state": "ran", "at": time.time() - 3 * 3600,
            "counts": {"broken": 0, "missing": 1}}, 60)
        forge = _facts(_cycle(oculus(user=self.staff), "forge"))
        self.assertEqual(forge["pages that raise, at the last probe"]["value"], 0)
        self.assertEqual(
            forge["pages that raise, at the last probe"]["age"]["words"],
            "probed 3 h ago")

    def test_a_broken_cache_never_takes_the_page(self):
        """Compute, or show a named dash: never a 500."""
        with mock.patch.object(cache, "get", side_effect=ConnectionError("x")), \
                mock.patch.object(cache, "set", side_effect=ConnectionError("x")):
            data = oculus(user=self.staff)
        forge = _facts(_cycle(data, "forge"))
        self.assertIsNotNone(forge["guarded tasks with no switch"]["value"])
        self.assertIsNotNone(forge["migrations pending"]["value"])
        self.assertIsNone(forge["pages that raise, at the last probe"]["value"])


class TheBacktestsReadTheirMarkerInTheDatabaseTests(TestCase):
    """"Computed before the 09-14 fix" was a Python loop over every run's
    stats. `has_key` asks the database the same question; the four shapes
    a stats column has held must give the loop's answer."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_bt", password="x")

    def test_has_key_counts_what_the_loop_counted_on_every_shape(self):
        from django.db.models import JSONField, Value

        from bot_program.models import BotBacktestRun
        from dashboard.oculus import _bot_runs_before_the_fix
        for stats in ({"unmeasured": {"signals_without_bars": 2}},
                      {"n": 3},
                      [1, 2],
                      "legacy text"):
            BotBacktestRun.objects.create(user=self.user, status="complete",
                                          stats=stats)
        null = BotBacktestRun.objects.create(user=self.user,
                                             status="complete", stats={})
        BotBacktestRun.objects.filter(pk=null.pk).update(
            stats=Value(None, JSONField()))
        BotBacktestRun.objects.create(user=self.user, status="error",
                                      stats={"n": 1})

        loop = sum(1 for s in BotBacktestRun.objects.filter(
            status="complete").values_list("stats", flat=True)
            if not isinstance(s, dict) or "unmeasured" not in s)
        self.assertEqual(loop, 4)
        self.assertEqual(_bot_runs_before_the_fix(), loop)
        facts = _facts(_cycle(oculus(), "backtests"))
        self.assertEqual(facts["… computed before the 09-14 fix"]["value"], 4)

    def test_the_unsimulated_sum_is_stored_ten_minutes_and_dated(self):
        from bot_program.models import BotBacktestRun
        BotBacktestRun.objects.create(
            user=self.user, status="complete",
            stats={"unmeasured": {"signals_without_bars": 3}})
        fact = _facts(_cycle(oculus(), "backtests"))[
            "signals a run could not simulate"]
        self.assertEqual(fact["value"], 3)
        self.assertRegex(fact["age"]["words"],
                         r"^counted (just now|\d+ (min|h|d) ago)$")
        # a new complete run is a new answer, not a ten-minute-old one
        BotBacktestRun.objects.create(
            user=self.user, status="complete",
            stats={"unmeasured": {"signals_without_bars": 4}})
        fact = _facts(_cycle(oculus(), "backtests"))[
            "signals a run could not simulate"]
        self.assertEqual(fact["value"], 7)


class TheTwoLifetimeAggregatesAreKeptTenMinutesTests(TestCase):
    """§7.2 point 6: measured at the six-month scale the page missed its
    budget, so the next two reads named there are stored ten minutes —
    the predictions' and the desk passes' all-time counts, whole-table
    reads with no index for their filter — and each prints its age."""

    def setUp(self):
        cache.clear()

    def test_they_are_stored_ten_minutes_and_print_their_age(self):
        from dashboard import oculus as mod
        seen = {}
        real_set = cache.set

        def _set(key, value, timeout=None, *a, **k):
            seen[key] = timeout
            return real_set(key, value, timeout, *a, **k)

        with mock.patch.object(cache, "set", side_effect=_set):
            data = oculus()
        build = mod._build_id()
        self.assertEqual(seen[mod.PREDICTIONS_KEY.format(build=build)], 600)
        self.assertEqual(seen[mod.DESK_PASSES_KEY.format(build=build)], 600)
        trust = _facts(_cycle(data, "trust"))
        for label in ("direction calls graded right", "calls not due yet",
                      "calls past due, ungraded"):
            self.assertRegex(trust[label]["age"]["words"],
                             r"counted (just now|\d+ (min|h|d) ago)$")
        passes = _facts(_cycle(data, "allocation"))["desk passes in shadow"]
        self.assertRegex(passes["age"]["words"],
                         r"counted (just now|\d+ (min|h|d) ago)$")

    def test_a_stored_count_is_served_from_the_store_until_it_expires(self):
        from ai_agents.models import AgentPrediction
        AgentPrediction.objects.create(agent="o0", prediction_type="direction",
                                       predicted_value="up", was_correct=True,
                                       evaluated_at=timezone.now())
        first = _facts(_cycle(oculus(), "trust"))
        AgentPrediction.objects.create(agent="o0", prediction_type="direction",
                                       predicted_value="up", was_correct=True,
                                       evaluated_at=timezone.now())
        again = _facts(_cycle(oculus(), "trust"))
        label = "direction calls graded right"
        self.assertEqual(first[label]["value"], 1)
        self.assertEqual(again[label]["value"], 1)   # stored, and dated
        cache.clear()
        self.assertEqual(_facts(_cycle(oculus(), "trust"))[label]["value"], 2)

    def test_the_proposals_tally_buckets_on_creation_too(self):
        """The small table's one grouped read keeps the strips' rule."""
        src = (Path(settings.BASE_DIR) / "dashboard" / "oculus.py").read_text(
            encoding="utf-8")
        fields = re.findall(r"_tally\([A-Za-z_]+,\s*\"([a-z_]+)\"", src)
        self.assertTrue(fields)
        for field in fields:
            self.assertIn(field, ("created_at", "scanned_at"))


class TheQueryBudgetTests(TestCase):
    """81 queries per call for staff, 74 for a viewer (B4.2). One component
    read per render and one aggregate per table bring them to the budgets
    of §7.3. Measured on a request's own user object (nothing cached on
    it), in both states a GET meets:

    WARM — the stored readings in place: every GET but the ones below.
    COLD — none in place: the first GET of a build, and one GET every ten
    minutes after it, when the migration plan, the two lifetime
    aggregates and the unsimulated sum expire (the guard scan does not).
    Cold reads them again: three more for a viewer, five more for staff
    (the plan is two). §7.3's 30 / 26 hold warm; cold is pinned here at its
    measured count, so a regression on either path fails.

    The staff login carries a keyed eToro account with an equity reading,
    the operator's own shape: the desk's governor then reads the
    withdrawals and the equity history, two queries of the desk's own."""

    WARM = {"staff": 30, "viewer": 26}
    COLD = {"staff": 34, "viewer": 29}

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("o0_q_staff", password="x",
                                              is_staff=True)
        self.viewer = User.objects.create_user("o0_q_viewer", password="x")
        for user in (self.staff, self.viewer):
            _seed_three_worlds(user)
        _keyed_etoro(self.staff)

    def _queries(self, user, *, warm=True):
        cache.clear()
        if warm:
            oculus(user=user)
        fresh = User.objects.get(pk=user.pk)
        with CaptureQueriesContext(connection) as q:
            data = oculus(user=fresh)
        self.assertEqual([c["key"] for c in data["cycles"] if c["dead"]], [])
        return [x["sql"] for x in q.captured_queries]

    def test_the_staff_book_reads_the_operators_governor(self):
        """The keyed account is read by the desk: its two reads are in."""
        sql = self._queries(self.staff)
        self.assertTrue(any("bot_program_brokerequityreading" in s
                            for s in sql))

    def test_staff_reads_at_most_thirty_warm(self):
        sql = self._queries(self.staff)
        self.assertLessEqual(len(sql), self.WARM["staff"],
                             "\n".join(s[:120] for s in sql))

    def test_a_viewer_reads_at_most_twenty_six_warm(self):
        sql = self._queries(self.viewer)
        self.assertLessEqual(len(sql), self.WARM["viewer"],
                             "\n".join(s[:120] for s in sql))

    def test_cold_reads_are_pinned_too(self):
        for who, user in (("staff", self.staff), ("viewer", self.viewer)):
            with self.subTest(who=who):
                sql = self._queries(user, warm=False)
                self.assertLessEqual(len(sql), self.COLD[who],
                                     "\n".join(s[:120] for s in sql))

    def test_the_switches_are_one_read(self):
        sql = self._queries(self.staff)
        components = [s for s in sql if "core_platformcomponent" in s]
        self.assertEqual(len(components), 1, components)


class TheGapIsJudgedOnlyPastItsFloorTests(TestCase):
    """A 4-trade gap of -1.13 was drawn in red (B3.9) while the caveat
    called negative the normal direction. Below the desk's evidence floor
    the gap is printed, uncoloured, with the floor in words."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_gap", password="x")

    def _row(self, body, rule):
        row = body[body.index(rule):]
        return row[:row.index("</tr>")]

    def test_a_thin_gap_is_printed_and_not_judged(self):
        from bot_program.capital_desk import DESK_MIN_N
        gaps = [{"rule_name": "o0_thin", "asset_class": "forex",
                 "n_paper": 30, "n_live": DESK_MIN_N - 6,
                 "paper_expectancy": 0.2, "live_expectancy": -0.93,
                 "gap": -1.13},
                {"rule_name": "o0_thick", "asset_class": "forex",
                 "n_paper": 30, "n_live": DESK_MIN_N,
                 "paper_expectancy": 0.3, "live_expectancy": -0.06,
                 "gap": -0.36}]
        self.client.force_login(self.user)
        with mock.patch("bot_program.bot_grading.paper_live_expectancy_gap",
                        return_value=gaps):
            body = _html.unescape(_content(self.client.get(
                reverse("oculus_dashboard")).content.decode()))
        thin = self._row(body, "o0_thin")
        self.assertIn("-1.13", thin)
        self.assertIn("not judged", thin)
        self.assertNotIn('class="neg"', thin)
        thick = self._row(body, "o0_thick")
        self.assertIn('class="neg"', thick)
        self.assertNotIn("not judged", thick)


class NoBrokerAndNoModelIsCalledTests(TestCase):
    """§6: no broker call and no model call to draw the page. The source of
    the Oculus's own modules names no adapter and no model client, and a
    render with every one of them patched to raise succeeds without
    touching any."""

    BANNED = ("client_for_symbol", "broker_router", "etoro_client",
              "EtoroTrader", "bot_program.engine", "ai_agents.providers",
              "anthropic", "openai", "ollama", "http.client", "urllib",
              "requests.", "httpx")

    def test_the_oculus_modules_import_no_broker_and_no_model(self):
        for name in ("oculus.py", "views_oculus.py"):
            src = (Path(settings.BASE_DIR) / "dashboard" / name).read_text(
                encoding="utf-8")
            for banned in self.BANNED:
                with self.subTest(module=name, banned=banned):
                    self.assertNotIn(banned, src)

    def test_the_page_renders_with_every_door_out_shut(self):
        cache.clear()
        staff = User.objects.create_user("o0_doors", password="x",
                                         is_staff=True, is_superuser=True)
        _seed_three_worlds(staff)
        refuse = RuntimeError("the Oculus must not call out")
        doors = [
            mock.patch("bot_program.engine.broker_router.client_for_symbol",
                       side_effect=refuse),
            mock.patch("bot_program.engine.etoro_client.EtoroTrader.__init__",
                       side_effect=refuse),
            mock.patch("http.client.HTTPConnection.connect",
                       side_effect=refuse),
            mock.patch("urllib3.connectionpool.HTTPConnectionPool.urlopen",
                       side_effect=refuse),
            mock.patch("ai_agents.providers.claude_provider.ClaudeProvider"
                       ".complete", side_effect=refuse),
        ]
        mocks = [door.start() for door in doors]
        try:
            data = oculus(user=staff)
            self.client.force_login(staff)
            resp = self.client.get(reverse("oculus_dashboard"))
        finally:
            for door in doors:
                door.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([c["key"] for c in data["cycles"] if c["dead"]], [])
        for m in mocks:
            m.assert_not_called()


class TheOculusActsOnNothingTests(TestCase):
    """The display-only contract (§6): no form, no POST, no button that
    acts, in the page the Oculus renders. Every action is a link to the
    page that holds it, behind its own PIN."""

    BANNED = ("<form", 'method="post"', "hx-post", "data-sv-close-trade",
              "svTakeTrade(", "svCloseTrade(")

    def test_the_template_carries_no_action(self):
        src = (Path(settings.BASE_DIR) / "templates" / "dashboard"
               / "oculus.html").read_text(encoding="utf-8").lower()
        for banned in self.BANNED:
            self.assertNotIn(banned.lower(), src)

    def test_the_staff_page_with_every_region_populated_carries_no_action(self):
        from bot_program.models import BotBacktestRun
        from core.platform_control import PlatformComponent
        cache.clear()
        staff = User.objects.create_user("o0_acts", password="x",
                                         is_staff=True, is_superuser=True)
        _seed_three_worlds(staff)
        PlatformComponent.objects.update_or_create(
            key="platform_master", defaults={"is_enabled": True})
        BotBacktestRun.objects.create(user=staff, status="complete",
                                      stats={"n": 1})
        cache.set("forge:route_probe", {"state": "ran", "at": time.time(),
                                        "counts": {"broken": 1,
                                                   "missing": 0}}, 60)
        gaps = [{"rule_name": "o0_rule", "asset_class": "forex",
                 "n_paper": 30, "n_live": 12, "paper_expectancy": 0.3,
                 "live_expectancy": -0.1, "gap": -0.4}]
        self.client.force_login(staff)
        with mock.patch("bot_program.bot_grading.paper_live_expectancy_gap",
                        return_value=gaps):
            body = _content(self.client.get(
                reverse("oculus_dashboard")).content.decode())
        self.assertIn("REAL MONEY", body)
        self.assertIn("o0_rule", body)
        lower = body.lower()
        for banned in self.BANNED:
            self.assertNotIn(banned.lower(), lower)


# ── the review of O0 (2026-11-07) ───────────────────────────────────────

class TheDemoSentenceKeepsTheDesksCurrencyRuleTests(TestCase):
    """The sentence that says what the desk's live venue counts as live,
    and the REAL column does not, reads the DEMO world's own risk under
    the currency rule the desk itself applied.

    With no live config enabled (the kill switch, the brake and `bot off`
    disable them all and leave the rows open) the desk's currency is ""
    and book_risk adds every row, REAL and DEMO together: subtracting a
    lookup on "" from that total printed the REAL row's risk as demo. With
    the desk in one currency, a demo row in another is counted by the desk
    and left out of its budget: it printed as 0.00 in the desk's currency.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_demo_ccy", password="x")

    def _desk(self):
        return _cycle(oculus(user=self.user), "book")["desk"]

    def test_with_every_live_config_off_the_real_risk_is_never_demo(self):
        from bot_program.models import AssetBotConfig
        _seed_three_worlds(self.user)
        AssetBotConfig.objects.filter(user=self.user, mode="live").update(
            enabled=False)
        desk = self._desk()
        self.assertNotIn("110.00", desk["sentence"])
        self.assertIn("1 eToro DEMO row", desk["sentence"])
        self.assertIn("100.00 USD", desk["sentence"])
        self.assertEqual(desk["demo_counted"]["n"], 1)
        self.assertEqual(desk["demo_counted"]["currency"], "")
        self.assertEqual(desk["demo_counted"]["risk_by_currency"],
                         {"USD": 100.0})

    def test_with_every_live_config_off_each_currency_stays_apart(self):
        from bot_program.models import AssetBotConfig
        _seed_three_worlds(self.user)
        eur = _config(self.user, "o0 live eur", "live", "1000",
                      currency="EUR")
        _open(eur, "EURUSD", "500", "1.10", "1.00", paper=False,
              stamps=DEMO)
        AssetBotConfig.objects.filter(user=self.user, mode="live").update(
            enabled=False)
        desk = self._desk()
        self.assertIn("2 eToro DEMO rows", desk["sentence"])
        self.assertIn("100.00 USD", desk["sentence"])
        self.assertIn("50.00 EUR", desk["sentence"])
        self.assertNotIn("150.00", desk["sentence"])
        self.assertEqual(desk["demo_counted"]["risk_by_currency"],
                         {"USD": 100.0, "EUR": 50.0})

    def test_a_demo_row_in_another_currency_is_named_never_a_zero(self):
        usd = _config(self.user, "a o0 live usd", "live", "1000")
        eur = _config(self.user, "b o0 live eur", "live", "1000",
                      currency="EUR")
        _open(usd, "EURUSD", "1000", "1.10", "1.09", paper=False,
              stamps=REAL)
        _open(eur, "XAUUSD", "1", "2000", "1900", paper=False, stamps=DEMO)
        desk = self._desk()
        counted = desk["demo_counted"]
        self.assertEqual((counted["n"], counted["currency"]), (1, "USD"))
        self.assertEqual(counted["risk_by_currency"], {})
        self.assertEqual(counted["risk"], 0.0)   # no demo row in USD at all
        self.assertEqual(counted["aside"],
                         {"EUR": {"n": 1, "risk": 100.0, "unmeasured": 0}})
        self.assertNotIn("0.00 USD", desk["sentence"])
        self.assertIn("100.00 EUR", desk["sentence"])
        self.assertIn("USD budget", desk["sentence"])

    def test_a_demo_row_with_no_readable_stop_is_counted_never_priced(self):
        live = _config(self.user, "o0 live pool", "live", "1000")
        _open(live, "XAUUSD", "1", "2000", None, paper=False, stamps=DEMO)
        desk = self._desk()
        self.assertIn("1 eToro DEMO row", desk["sentence"])
        self.assertIn("no readable stop", desk["sentence"])
        self.assertNotIn("0.00", desk["sentence"])


class AWorldOpenWithNoMeasuredStopIsADashTests(TestCase):
    """A world holding open rows none of which has a readable opening stop
    printed "risk at the stops 0.00": a sum over no measured row, read as
    a measured zero in the REAL column. It is a named dash; a world with
    nothing open keeps its measured 0.00."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_unstopped", password="x")

    def test_the_risk_line_is_a_named_dash(self):
        live = _config(self.user, "o0 live pool", "live", "1000")
        _open(live, "EURUSD", "1000", "1.10", None, paper=False, stamps=REAL)
        _open(live, "AAPL", "10", "200", None, paper=False, stamps=REAL)
        data = oculus(user=self.user)
        worlds = {w["world"]: w for w in _cycle(data, "book")["worlds"]}
        risk = _facts(worlds["live"])["risk at the stops"]
        self.assertIsNone(risk["value"])
        self.assertIn("readable opening stop", risk["why"])
        self.assertEqual(_facts(worlds["live"])[
            "positions with no measured stop"]["value"], 2)
        name = "book.REAL MONEY.risk at the stops"
        self.assertIn(name, data["degraded"])
        row = next(r for r in data["not_measured"] if r["name"] == name)
        self.assertEqual(row["place"], "book · REAL MONEY · risk at the stops")
        # nothing open is a measured zero, not a dash
        self.assertEqual(_facts(worlds["demo"])["risk at the stops"][
            "display"], "0.00")

    def test_the_page_prints_the_dash_and_names_it(self):
        live = _config(self.user, "o0 live pool", "live", "1000")
        _open(live, "EURUSD", "1000", "1.10", None, paper=False, stamps=REAL)
        self.client.force_login(self.user)
        body = _html.unescape(_content(self.client.get(
            reverse("oculus_dashboard")).content.decode()))
        start = body.index("THE OPEN BOOK, BY MONEY WORLD")
        worlds = body[start:body.index("WHAT THE DESK SIZES WITH", start)]
        self.assertIn("ocu-v dash", _row_of(worlds, "risk at the stops"))
        self.assertIn("book · REAL MONEY · risk at the stops", body)


class TheThresholdReadsTheUnroundedValueTests(TestCase):
    """alert_when was checked on the rounded value: a budget of -0.004
    printed "-0.00" with no amber, and a governor of 0.998 printed "100"
    with no amber, under a qualifier saying 100 means no drawdown or no
    reading. The threshold reads the value the desk computed; the cell
    keeps the sign the threshold saw."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_unrounded", password="x")

    def test_a_budget_just_under_zero_keeps_its_sign_and_its_amber(self):
        from dashboard.oculus import _fact

        def budget(raw):
            return _fact("budget left", lambda: raw, kind="money",
                         alert_when=("<", 0), alert_words="past the ceiling")

        for raw in (-0.004, -1.4e-14):
            with self.subTest(raw=raw):
                fact = budget(raw)
                self.assertTrue(fact["alert"])
                self.assertEqual(fact["display"], "-0.00")
        for raw in (-0.0, 0.0, 0.004):
            with self.subTest(raw=raw):
                fact = budget(raw)
                self.assertFalse(fact["alert"])
                self.assertEqual(fact["display"], "0.00")

    def test_a_governor_just_under_one_reads_under_100_with_its_amber(self):
        def _budget(user, venue, **kwargs):
            return {"budget": 10.0, "gross": 20.0, "capital": 1000.0,
                    "currency": "USD", "not_summed": {}, "book_risk": 10.0,
                    "unmeasured_open": 0, "n_other_currency": 0,
                    "n_open": 1, "entries": [], "governor": 0.998,
                    "drawdown_pct": 0.0505,
                    "reason": "governor 1.00 — 5.0% under the high-water mark"}

        with mock.patch("bot_program.capital_desk.budget_for",
                        side_effect=_budget):
            book = _cycle(oculus(user=self.user), "book")
        live = next(v for v in book["venues"] if v["venue"] == "live")
        gov = next(f for f in live["facts"]
                   if "drawdown governor" in f["label"])
        self.assertLess(gov["value"], 100)
        self.assertTrue(gov["alert"])
        self.assertIn("under the high-water mark", gov["alert_words"])
        self.assertIn("TWO", gov["qualifier"])


class LateMeansPastTheResolversLastPassTests(TestCase):
    """The flag resolver runs nightly at 23:15 UTC and the grader of the
    calls at 03:30. A flag that fell due at 09:05 is not late at noon: it
    waits for the 23:15 pass. Counting it late lit "the resolver is late"
    about fourteen hours a day with the resolver on time, and "nobody is
    grading" nearly all day. Late is what fell due before the resolver's
    last scheduled pass and is still unresolved; what fell due after it is
    due and waiting, inert, with no amber."""

    def setUp(self):
        cache.clear()
        self.now = timezone.now()
        self.last_pass = self.now - timedelta(hours=6)

    def _instrument(self, symbol="EURUSD"):
        from instruments.models import Instrument
        return Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "forex"})[0]

    def test_the_last_pass_of_a_crontab(self):
        from celery.schedules import crontab

        from dashboard.oculus import _last_fire
        utc = dt_timezone.utc
        nightly = crontab(hour=23, minute=15)
        self.assertEqual(
            _last_fire(nightly, datetime(2026, 1, 7, 10, 0, tzinfo=utc)),
            datetime(2026, 1, 6, 23, 15, tzinfo=utc))
        self.assertEqual(
            _last_fire(nightly, datetime(2026, 1, 7, 23, 15, 30, tzinfo=utc)),
            datetime(2026, 1, 7, 23, 15, tzinfo=utc))
        # Sundays at 04:00: on a Wednesday the last one was three days back
        weekly = crontab(hour=4, minute=0, day_of_week="sunday")
        self.assertEqual(
            _last_fire(weekly, datetime(2026, 1, 7, 10, 0, tzinfo=utc)),
            datetime(2026, 1, 4, 4, 0, tzinfo=utc))
        # every fifteen minutes
        quarter = crontab(minute="*/15")
        self.assertEqual(
            _last_fire(quarter, datetime(2026, 1, 7, 10, 59, tzinfo=utc)),
            datetime(2026, 1, 7, 10, 45, tzinfo=utc))

    def test_the_last_pass_gives_a_pass_its_floor_to_finish(self):
        """The pass at 23:15 is judged five minutes later (the floor the
        system map gives every row), never while it may still run."""
        from celery.schedules import crontab

        from dashboard import oculus as mod
        utc = dt_timezone.utc
        beat = {"resolve-opportunity-flags":
                {"schedule": crontab(hour=23, minute=15)}}
        with mock.patch("core.day_of_sauron.read_schedule",
                        return_value=(beat, {})):
            self.assertEqual(
                mod._last_pass("resolve-opportunity-flags",
                               datetime(2026, 1, 7, 23, 17, tzinfo=utc)),
                datetime(2026, 1, 6, 23, 15, tzinfo=utc))
            self.assertEqual(
                mod._last_pass("resolve-opportunity-flags",
                               datetime(2026, 1, 7, 23, 21, tzinfo=utc)),
                datetime(2026, 1, 7, 23, 15, tzinfo=utc))
            # no beat entry: no pass will come, so what is due is late now
            now = datetime(2026, 1, 7, 12, 0, tzinfo=utc)
            self.assertEqual(mod._last_pass("no-such-entry", now), now)

    def test_a_flag_due_since_the_last_pass_waits_and_one_due_before_is_late(self):
        from signals.models_opportunity import OpportunityFlag, OpportunitySetup
        setup = OpportunitySetup.objects.create(name="o0 pass",
                                                direction="bullish")
        inst = self._instrument()
        # (scanned this long ago, horizon in days, outcome)
        for ago, horizon, outcome in (
                (timedelta(days=2), 5, ""),               # due in 3 days
                (timedelta(days=1, hours=3), 1, ""),      # due 3 h ago: waits
                (timedelta(days=1, hours=9), 1, ""),      # due 9 h ago: late
                (timedelta(days=40), 5, "hit")):          # resolved
            flag = OpportunityFlag.objects.create(
                setup=setup, instrument=inst, score=0.5, outcome=outcome,
                horizon_days=horizon)
            OpportunityFlag.objects.filter(pk=flag.pk).update(
                scanned_at=self.now - ago)
        with mock.patch("dashboard.oculus._last_pass",
                        return_value=self.last_pass):
            facts = _facts(_cycle(oculus(), "scan"))
        self.assertEqual(facts["detections not due yet"]["value"], 1)
        waiting = facts["detections due, waiting for the resolver"]
        self.assertEqual(waiting["value"], 1)
        self.assertEqual(waiting["tone"], "inert")
        self.assertFalse(waiting["alert"])
        late = facts["detections past due, unresolved"]
        self.assertEqual(late["value"], 1)
        self.assertTrue(late["alert"])
        self.assertIn("the resolver is late", late["alert_words"])

    def test_nothing_is_late_while_every_due_flag_waits_for_its_pass(self):
        from signals.models_opportunity import OpportunityFlag, OpportunitySetup
        setup = OpportunitySetup.objects.create(name="o0 waits",
                                                direction="bullish")
        flag = OpportunityFlag.objects.create(
            setup=setup, instrument=self._instrument(), score=0.5,
            outcome="", horizon_days=1)
        OpportunityFlag.objects.filter(pk=flag.pk).update(
            scanned_at=self.now - timedelta(days=1, hours=3))
        with mock.patch("dashboard.oculus._last_pass",
                        return_value=self.last_pass):
            facts = _facts(_cycle(oculus(), "scan"))
        self.assertEqual(facts["detections past due, unresolved"]["value"], 0)
        self.assertFalse(facts["detections past due, unresolved"]["alert"])

    def test_a_call_due_since_the_last_pass_waits_and_one_before_is_late(self):
        from ai_agents.models import AgentPrediction
        for due in (self.now + timedelta(days=1),     # not due
                    self.now - timedelta(hours=1),    # due since the pass
                    self.now - timedelta(hours=9),    # due before it: late
                    None):                            # no due date: late
            AgentPrediction.objects.create(
                agent="o0_agent", prediction_type="direction",
                predicted_value="up", expected_resolution_at=due)
        with mock.patch("dashboard.oculus._last_pass",
                        return_value=self.last_pass):
            facts = _facts(_cycle(oculus(), "trust"))
        self.assertEqual(facts["calls not due yet"]["value"], 1)
        waiting = facts["calls due, waiting for the grader"]
        self.assertEqual(waiting["value"], 1)
        self.assertEqual(waiting["tone"], "inert")
        self.assertFalse(waiting["alert"])
        late = facts["calls past due, ungraded"]
        self.assertEqual(late["value"], 2)
        self.assertTrue(late["alert"])
        self.assertIn("nobody is grading", late["alert_words"])


class AStoredReadingPrintsItsAgeInPlaceOfNowTests(TestCase):
    """A stored figure printed "· now" above "probed 6 d ago". A fact read
    from a stored reading prints its age where its window would read
    "now"; a count over a longer window keeps the window and prints its
    age beneath."""

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("o0_when", password="x",
                                              is_staff=True)

    def test_the_probe_and_the_forge_print_their_age_not_now(self):
        cache.set("forge:route_probe", {
            "state": "ran", "at": time.time() - 3 * 3600,
            "counts": {"broken": 0, "missing": 0}}, 60)
        forge = _facts(_cycle(oculus(user=self.staff), "forge"))
        self.assertEqual(forge["pages that raise, at the last probe"]["when"],
                         "probed 3 h ago")
        self.assertRegex(forge["migrations pending"]["when"],
                         r"^plan checked (just now|\d+ (min|h|d) ago)$")
        self.assertEqual(forge["tests published on the wall"]["when"],
                         "constant")
        self.client.force_login(self.staff)
        body = _html.unescape(_content(self.client.get(
            reverse("oculus_dashboard")).content.decode()))
        row = _row_of(body, "pages that raise, at the last probe")
        self.assertIn("· probed 3 h ago", row)
        self.assertNotIn("· now", row)

    def test_a_count_over_a_window_keeps_its_window(self):
        trust = _facts(_cycle(oculus(user=self.staff), "trust"))
        right = trust["direction calls graded right"]
        self.assertEqual(right["when"], "all time")
        self.assertRegex(right["age"]["words"], r"counted")


class TheProbeIsDatedAgainstTheBuildTests(TestCase):
    """Redis keeps its data across a deploy (an appendonly volume) and the
    probe keeps its tally seven days, so after a deploy the forge printed
    the previous image's tally as current. A tally older than this build
    is a dash; a missing one says what can remove it."""

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("o0_probe", password="x",
                                              is_staff=True)

    def _forge(self, built_ago):
        built = datetime.now(dt_timezone.utc) - built_ago
        env = {"SAURON_GIT_SHA": "ddddddd",
               "SAURON_BUILT_AT": built.strftime("%Y-%m-%dT%H:%M:%SZ")}
        with mock.patch.dict("os.environ", env), \
                mock.patch("pathlib.Path.rglob",
                           side_effect=lambda *a, **k: iter(())):
            return oculus(user=self.staff)

    def test_a_tally_older_than_this_build_is_a_dash(self):
        cache.set("forge:route_probe", {
            "state": "ran", "at": time.time() - 2 * 86400,
            "counts": {"broken": 0, "missing": 0}}, 60)
        data = self._forge(timedelta(hours=1))
        forge = _facts(_cycle(data, "forge"))
        for label in ("pages that raise, at the last probe",
                      "pages answering 404, at the last probe"):
            self.assertIsNone(forge[label]["value"])
        row = next(r for r in data["not_measured"]
                   if r["name"] == "forge.pages that raise, at the last probe")
        self.assertEqual(row["why"], "no probe since this build")
        self.assertIn("probe_routes", row["fix"])

    def test_a_tally_newer_than_this_build_is_read_with_its_age(self):
        cache.set("forge:route_probe", {
            "state": "ran", "at": time.time() - 3 * 3600,
            "counts": {"broken": 1, "missing": 0}}, 60)
        forge = _facts(_cycle(self._forge(timedelta(hours=5)), "forge"))
        raising = forge["pages that raise, at the last probe"]
        self.assertEqual(raising["value"], 1)
        self.assertTrue(raising["alert"])
        self.assertEqual(raising["when"], "probed 3 h ago")

    def test_a_missing_tally_names_every_way_it_goes(self):
        cache.delete("forge:route_probe")
        data = oculus(user=self.staff)
        row = next(r for r in data["not_measured"]
                   if r["name"] == "forge.pages that raise, at the last probe")
        self.assertEqual(row["why"], "no probe stored: never run, cleared, "
                                     "or older than 7 days")


class TheGovernorPrintsTheAgeOfItsEquityTests(TestCase):
    """The governor is computed from the broker's equity cell, which the
    sync stores. It printed "· now" whatever that cell's age. It prints the
    cell's age, and says when the cell is past the freshness bound."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_equity", password="x")
        _seed_three_worlds(self.user)

    def _live(self):
        book = _cycle(oculus(user=self.user), "book")
        return next(v for v in book["venues"] if v["venue"] == "live")

    def test_a_three_day_old_cell_prints_its_age_and_says_stale(self):
        _keyed_etoro(self.user, read_ago=timedelta(days=3))
        live = self._live()
        gov = next(f for f in live["facts"]
                   if "drawdown governor" in f["label"])
        self.assertEqual(gov["value"], 100)
        self.assertTrue(gov["when"].startswith("equity read 3 d ago"))
        self.assertIn("stale", gov["when"])
        self.assertTrue(gov["age"]["stale"])
        self.assertTrue(live["equity"]["words"].startswith(
            "equity read 3 d ago"))
        self.client.force_login(self.user)
        body = _html.unescape(_content(self.client.get(
            reverse("oculus_dashboard")).content.decode()))
        row = _row_of(body, "drawdown governor")
        self.assertIn("equity read 3 d ago", row)
        self.assertNotIn("· now", row)

    def test_a_fresh_cell_prints_its_age_without_stale(self):
        _keyed_etoro(self.user, read_ago=timedelta(minutes=2))
        gov = next(f for f in self._live()["facts"]
                   if "drawdown governor" in f["label"])
        self.assertEqual(gov["when"], "equity read 2 min ago")
        self.assertFalse(gov["age"]["stale"])

    def test_with_no_reading_the_governor_reads_now_and_two_meanings(self):
        live = self._live()
        gov = next(f for f in live["facts"]
                   if "drawdown governor" in f["label"])
        self.assertEqual(gov["when"], "now")
        self.assertIn("TWO", gov["qualifier"])
        self.assertIsNone(live["equity"])
        self.assertEqual(live["reason"], "no equity reading — governor 1.00")


class TheStoredReadingsAreKeyedByTheBuildTests(TestCase):
    """Redis survives a deploy. A reading stored by the previous image's
    code was read by the next one: a dict without a key the new code asks
    for became four dashes, and a changed counting rule printed the old
    number under the new label. Every stored reading is keyed by the
    build (its sha and its build time: a same-sha rebuild is a new
    image), and a stored dict that lacks what the code asks for is
    counted again."""

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("o0_keys", password="x",
                                              is_staff=True)

    def _env(self, sha, built):
        return mock.patch.dict("os.environ", {"SAURON_GIT_SHA": sha,
                                              "SAURON_BUILT_AT": built})

    def test_every_stored_reading_carries_the_build(self):
        from dashboard import oculus as mod
        seen = []
        real_set = cache.set

        def _set(key, value, timeout=None, *a, **k):
            seen.append(key)
            return real_set(key, value, timeout, *a, **k)

        with self._env("eeeeeee", "2026-01-07T10:00:00Z"), \
                mock.patch.object(cache, "set", side_effect=_set), \
                mock.patch("pathlib.Path.rglob",
                           side_effect=lambda *a, **k: iter(())):
            oculus(user=self.staff)
            build = mod._build_id()
        self.assertEqual(build, "eeeeeee@2026-01-07T10:00:00Z")
        ours = [k for k in seen if k.startswith("oculus:")]
        self.assertEqual(len(ours), 5, ours)
        for key in ours:
            self.assertTrue(key.endswith(":" + build), key)

    def test_an_older_codes_dict_is_counted_again_never_a_dash(self):
        from dashboard import oculus as mod
        with self._env("eeeeeee", "2026-01-07T10:00:00Z"):
            key = mod.PREDICTIONS_KEY.format(build=mod._build_id())
            cache.set(key, {"value": {"right": 5, "wrong": 1}, "at": time.time(),
                            "fp": None}, 600)
            data = oculus(user=self.staff)
        trust = _facts(_cycle(data, "trust"))
        for fact in trust.values():
            self.assertIsNotNone(fact["value"], fact["label"])
        self.assertEqual([d for d in data["degraded"] if d.startswith("trust")],
                         [])

    def test_a_same_sha_rebuild_scans_again(self):
        with mock.patch("pathlib.Path.rglob",
                        side_effect=lambda *a, **k: iter(())) as scan:
            with self._env("fffffff", "2026-01-07T10:00:00Z"):
                oculus(user=self.staff)
                forge = _facts(_cycle(oculus(user=self.staff), "forge"))
            self.assertEqual(scan.call_count, 1)
            self.assertIn("this build", forge["guarded tasks with no switch"][
                "when"])
            with self._env("fffffff", "2026-01-08T10:00:00Z"):
                oculus(user=self.staff)
            self.assertEqual(scan.call_count, 2)


class TheDesksReasonCarriesNoExceptionMessageTests(TestCase):
    """budget_for writes an unreadable governor's exception message into
    its reason ("governor unreadable (<message>) — 1.00"), and O0 prints
    the reason. The page names a failure's kind, never its message: a
    database error carries SQL text."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("o0_reason", password="x")
        _seed_three_worlds(self.user)
        # after the USD pool in the configs' order: the desk works in USD
        # and sets this one aside, which its reason line says
        _config(self.user, "z o0 live eur", "live", "500", currency="EUR")

    def test_the_cause_stays_in_the_desks_log(self):
        boom = RuntimeError('column "secret_col" does not exist '
                            'LINE 1: SELECT x')
        with mock.patch("bot_program.capital_truth.equity_drawdown",
                        side_effect=boom):
            live = next(v for v in _cycle(oculus(user=self.user), "book")[
                "venues"] if v["venue"] == "live")
            self.client.force_login(self.user)
            body = _html.unescape(_content(self.client.get(
                reverse("oculus_dashboard")).content.decode()))
        self.assertTrue(live["reason"].startswith(
            "governor unreadable — 1.00 (the cause is in the desk's log)"))
        # the desk's own aside survives, after the cause
        self.assertIn("1 config in EUR not summed", live["reason"])
        self.assertNotIn("secret_col", live["reason"])
        self.assertNotIn("secret_col", body)
        self.assertNotIn("SELECT x", body)
