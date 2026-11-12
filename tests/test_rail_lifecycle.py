"""A signal leaves the rail for a stated reason (2026-11-06).

The operator, 2026-11-06: "peut etre fait un vrai systeme pensé ou le
signal part si il n'est plus voter ou vu comme efficace et rentable ou
simplement passé quoi" (a real, thought-through system where a signal
leaves when it is no longer voted, no longer seen as effective and
profitable, or simply past).

The rail's lifecycle (dashboard/signal_rail.py) is computed BESIDE the
engine's, never in it. First match wins:

  1  yours            your own PASS or take                  (the pass view)
  2  recorded         a departure already written             (sticky)
  3  superseded       a newer signal from its own rule on its instrument
  4  aged             past the 24h the bots and the hand ticket count
  5  stop crossed     a fresh mark at or through the stop
  6  target reached   a fresh mark at or through the target
  7  chased           reward:risk from the mark under the ticket's 1.00
  8  rule paused
  9  rule demoted     after the signal
  10 rule losing      a measured loser on the promotion floor
  11 losing live      ten real-money closes in 180 days, expectancy <= 0

Every departure but age is written once, with its words, to the
display-only dashboard.RailDeparture. LEFT THE RAIL keeps the last 24h.

MONEY DIRECTION: none. No Signal field, nothing the engine, the bots, the
alerts or the take-trade path read is written; a retired signal stays
active in the engine and its ticket stays offered.

Run with:  python manage.py test tests.test_rail_lifecycle
"""
import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from tests.test_rail_every_signal import (
    HOST, _cards, _inst, _partial, _quote, _sig, _user)

#: A cache of its own for the tests that read the rule facts through it
#: (the rail bypasses its cache under the test runner otherwise).
FACTS_CACHE = {"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "sv-rail-rule-facts"}}


def _snap(user):
    from dashboard.signal_rail import rail_snapshot
    req = RequestFactory().get("/")
    req.user = user
    return rail_snapshot(req)


def _gone(user, signal):
    """The LEFT THE RAIL entry for `signal`, or None."""
    snap = _snap(user)
    return next((g for g in snap["gone"] if g.signal_id == signal.pk), None)


def _on_rail(user, signal):
    return signal.pk in [s.pk for s in _snap(user)["cards"]]


def _gone_rows(html):
    """The LEFT THE RAIL rows of a rendered rail, one chunk each."""
    section = html.split('<section class="sr-gone"', 1)[1].split("</section>")[0]
    return ['class="sr-gone-row"' + chunk
            for chunk in section.split('class="sr-gone-row"')[1:]]


def _departure(signal, user=None):
    from dashboard.models import RailDeparture
    return RailDeparture.objects.filter(signal=signal, user=user).first()


def _control(rule, *, stage="paper", status="active", paused_days=None):
    from signals.models import RuleControl
    return RuleControl.objects.create(
        rule_name=rule, promotion_stage=stage, status=status,
        paused_until=(timezone.now() + timedelta(days=paused_days)
                      if paused_days is not None else None))


def _graded(rule, n, r, *, outcome="stopped_out", inst=None, subs=None):
    """n closed, graded signals of `rule` at `r` each, long gone."""
    from signals.models import Signal
    inst = inst or _inst("RLGRD", "forex")
    rows = [Signal(instrument=inst, signal_type="technical",
                   direction="bullish", urgency="low", title="graded",
                   description="d", rule_name=rule, score=0.6,
                   sub_scores=(subs(i) if subs else {}),
                   price_at_signal=Decimal("1"), is_active=False,
                   outcome=outcome, realized_r=r,
                   expired_at=timezone.now() - timedelta(days=40))
            for i in range(n)]
    Signal.objects.bulk_create(rows)


def _cfg(user, asset_class="forex", name="RL fleet", mode="live"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=True,
        mode=mode, symbols=[], capital=Decimal("10000"))


def _closes(cfg, rule, n, r, *, paper=False, meta=None, symbol="RLLVA"):
    """n closed real-money trades of `rule`, graded at `r` each."""
    from bot_program.models import AssetBotTrade
    for _ in range(n):
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class=cfg.asset_class, symbol=symbol,
            side="BUY", qty=Decimal("1"), entry_price=Decimal("1.08"),
            stop_loss=Decimal("1.075"), take_profit=Decimal("1.09"),
            status="CLOSED", paper=paper, rule_name=rule,
            metadata=dict(meta or {}), outcome="stopped_out",
            realized_r=r)
        AssetBotTrade.objects.filter(pk=t.pk).update(
            closed_at=timezone.now() - timedelta(days=3))


class _Base(TestCase):
    def setUp(self):
        self.user = _user("rl_life")
        self.client.force_login(self.user)
        self.inst = _inst("RLFXA", "forex")


class ThePriceSaysItIsPastTests(_Base):
    def test_stop_crossed_leaves_with_its_words_and_is_recorded(self):
        s = _sig(self.inst)
        _quote(self.inst, "1.07400")
        self.assertFalse(_on_rail(self.user, s))
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "stop_crossed")
        self.assertEqual(g.tag, "STOP")
        self.assertIn("1.07400", g.words)
        self.assertIn("1.07500", g.words)
        row = _departure(s)
        self.assertIsNotNone(row, "the departure was not recorded")
        self.assertEqual(row.reason, "stop_crossed")
        self.assertEqual(row.mark, Decimal("1.07400"))
        self.assertEqual(row.words, g.words)

    def test_it_stays_gone_when_the_price_comes_back(self):
        """A plan whose stop was touched does not slide back in as new."""
        s = _sig(self.inst)
        _quote(self.inst, "1.07400")
        _snap(self.user)
        _quote(self.inst, "1.08000")
        self.assertFalse(_on_rail(self.user, s))
        self.assertEqual(_gone(self.user, s).reason, "stop_crossed")
        self.assertNotIn(s.pk, _cards(_partial(self.client)))

    def test_target_reached(self):
        s = _sig(self.inst)
        _quote(self.inst, "1.09100")
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "target_reached")
        self.assertIn("1.09100", g.words)
        self.assertIn("1.09000", g.words)

    def test_bearish_levels_mirror(self):
        short = _sig(self.inst, rule="rl_short", direction="bearish",
                     entry="1.08000", stop="1.08500", target="1.07000")
        _quote(self.inst, "1.08600")
        self.assertEqual(_gone(self.user, short).reason, "stop_crossed")
        other = _inst("RLFXB", "forex")
        short2 = _sig(other, rule="rl_short", direction="bearish",
                      entry="1.08000", stop="1.08500", target="1.07000")
        _quote(other, "1.06900")
        self.assertEqual(_gone(self.user, short2).reason, "target_reached")
        third = _inst("RLFXC", "forex")
        inside = _sig(third, rule="rl_short", direction="bearish",
                      entry="1.08000", stop="1.08500", target="1.07000")
        _quote(third, "1.07900")
        self.assertTrue(_on_rail(self.user, inside))

    def test_a_stale_quote_judges_nothing(self):
        """The engine's own bound: a quote older than 900s is no mark."""
        s = _sig(self.inst)
        _quote(self.inst, "1.07000", age_s=20 * 60)
        self.assertTrue(_on_rail(self.user, s))
        self.assertIsNone(_departure(s))

    def test_chased_uses_the_tickets_line(self):
        """Price ran 70% of the way to the target: from the mark the plan
        risks more than it can make, under the ticket's own 1.00 line."""
        s = _sig(self.inst)                       # 2.00 at the entry
        _quote(self.inst, "1.08700")
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "chased")
        self.assertIn("70%", g.words)
        self.assertIn("1.00", g.words)
        self.assertIn("2.00", g.words)
        self.assertIn("0.25", g.words)

    def test_a_plan_born_under_the_line_is_not_chased(self):
        s = _sig(self.inst, entry="1.08000", stop="1.07000",
                 target="1.08500")                # 0.50 at the entry
        _quote(self.inst, "1.08300")
        self.assertTrue(_on_rail(self.user, s))


class TheClockSaysItIsPastTests(_Base):
    def test_aged_after_24_hours(self):
        """Past the 24 hours in which the bots count its vote and a hand
        ticket counts it as backing; a clock, so nothing is written."""
        s = _sig(self.inst, minutes_ago=25 * 60)
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "aged")
        self.assertEqual(g.at, s.created_at + timedelta(hours=24))
        self.assertIn("25h old", g.words)
        self.assertIsNone(_departure(s))

    def test_a_scanner_rematch_keeps_it(self):
        """A composite signal is reused and re-flagged daily: the scanner
        matching it two hours ago affirms it."""
        from signals.models_opportunity import OpportunityFlag, OpportunitySetup
        s = _sig(self.inst, rule="rl_setup", signal_type="composite",
                 minutes_ago=72 * 60)
        setup = OpportunitySetup.objects.create(
            name="rl_setup", conditions=[], asset_classes=[])
        flag = OpportunityFlag.objects.create(
            setup=setup, instrument=self.inst, signal=s, score=0.7)
        OpportunityFlag.objects.filter(pk=flag.pk).update(
            scanned_at=timezone.now() - timedelta(hours=2))
        self.assertTrue(_on_rail(self.user, s))
        OpportunityFlag.objects.filter(pk=flag.pk).update(
            scanned_at=timezone.now() - timedelta(hours=26))
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "aged")
        self.assertIn("scanner last matched", g.words)


class TheRuleReplacedItTests(_Base):
    def test_superseded_by_the_same_rule(self):
        old = _sig(self.inst, rule="rl_same", minutes_ago=300)
        new = _sig(self.inst, rule="rl_same", minutes_ago=60)
        g = _gone(self.user, old)
        self.assertEqual(g.reason, "superseded")
        self.assertEqual(g.tag, "REPLACED")
        self.assertIn("Replaced by a newer LONG from the same rule (rl_same)",
                      g.words)
        self.assertEqual(g.at, new.created_at)
        self.assertTrue(_on_rail(self.user, new))
        self.assertEqual(_departure(old).reason, "superseded")

    def test_reversed_by_the_same_rule(self):
        old = _sig(self.inst, rule="rl_same", minutes_ago=300)
        _sig(self.inst, rule="rl_same", direction="bearish",
             entry="1.08000", stop="1.08500", target="1.07000",
             minutes_ago=60)
        self.assertIn("Reversed by a newer SHORT from the same rule",
                      _gone(self.user, old).words)

    def test_another_rule_disagreeing_is_a_badge_not_a_departure(self):
        """The bots net the two sides; the operator decides."""
        older = _sig(self.inst, rule="rl_left", minutes_ago=300)
        newer = _sig(self.inst, rule="rl_right", direction="bearish",
                     entry="1.08000", stop="1.08500", target="1.07000",
                     minutes_ago=60)
        self.assertTrue(_on_rail(self.user, older))
        self.assertTrue(_on_rail(self.user, newer))
        card = next(s for s in _snap(self.user)["cards"] if s.pk == older.pk)
        self.assertEqual(card.rail.contra["rule"], "rl_right")
        self.assertEqual(card.rail.contra["side"], "SHORT")
        html = _partial(self.client)
        older_card = html.split(f'data-signal-id="{older.pk}"', 1)[1].split(
            'class="sr-signal-wrap', 1)[0]
        self.assertIn("CONTRA", older_card)


class TheRuleNoLongerVotesTests(_Base):
    def test_a_paused_rule_retires_its_signals(self):
        _control("rl_paused", status="paused", paused_days=7)
        s = _sig(self.inst, rule="rl_paused")
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "rule_paused")
        self.assertIn("is paused", g.words)

    def test_an_expired_pause_is_no_pause(self):
        _control("rl_was_paused", status="paused", paused_days=-1)
        s = _sig(self.inst, rule="rl_was_paused")
        self.assertTrue(_on_rail(self.user, s))

    def test_a_research_rule_stays_with_its_badge(self):
        """Research rules never voted, so they cannot be 'no longer voted':
        they stay, with the WATCHED badge and the fact that they do not
        vote on the row."""
        _control("rl_research", stage="research")
        s = _sig(self.inst, rule="rl_research")
        self.assertTrue(_on_rail(self.user, s))
        html = _partial(self.client)
        card = html.split(f'data-signal-id="{s.pk}"', 1)[1].split(
            'class="sr-popup"', 1)[0]
        self.assertIn('data-votes="0"', card)
        self.assertIn("WATCHED", card)

    def test_a_demotion_after_the_signal_retires_it(self):
        from signals.models import PromotionEvent
        _control("rl_demoted", stage="paper")
        s = _sig(self.inst, rule="rl_demoted", minutes_ago=120)
        ev = PromotionEvent.objects.create(
            rule_name="rl_demoted", from_stage="live_small",
            to_stage="paper", reason="auto_demote")
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "rule_demoted")
        self.assertIn("demoted from live_small to paper", g.words)
        self.assertEqual(g.at, ev.created_at)

    def test_a_demotion_before_the_signal_does_not(self):
        from signals.models import PromotionEvent
        _control("rl_demoted_b", stage="paper")
        ev = PromotionEvent.objects.create(
            rule_name="rl_demoted_b", from_stage="live_small",
            to_stage="paper", reason="auto_demote")
        PromotionEvent.objects.filter(pk=ev.pk).update(
            created_at=timezone.now() - timedelta(hours=5))
        s = _sig(self.inst, rule="rl_demoted_b", minutes_ago=60)
        self.assertTrue(_on_rail(self.user, s))


class TheRuleIsNotEffectiveTests(_Base):
    def test_a_measured_loser_retires_its_signals(self):
        _graded("rl_loser", 20, -0.5)
        s = _sig(self.inst, rule="rl_loser")
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "rule_losing")
        self.assertIn("measured loser", g.words)
        self.assertIn("20 graded signals", g.words)

    def test_19_graded_is_not_judged(self):
        """Below the floor's 20 a record is not a measurement."""
        _graded("rl_young", 19, -0.5)
        s = _sig(self.inst, rule="rl_young")
        self.assertTrue(_on_rail(self.user, s))
        card = next(c for c in _snap(self.user)["cards"] if c.pk == s.pk)
        self.assertIn("not judged", card.rail.record_words)

    def test_the_grouped_record_is_the_floors(self):
        """The rail reads every rule's record in one grouped query; it must
        be the floor's own measure, rule by rule, the event-keyed rule
        counted by its events."""
        from dashboard.signal_rail import graded_records
        from signals.promotion_pipeline import measured_loser
        _graded("rl_g_loser", 22, -0.4)
        _graded("rl_g_thin", 15, 0.05, outcome="stopped_out")
        _graded("rl_g_thin", 7, 0.05, outcome="hit_target")
        _graded("rl_g_good", 25, 0.6, outcome="hit_target")
        _graded("rl_g_few", 5, -1.0)
        _graded("yield_curve_inversion_flip", 25, -0.3,
                subs=lambda i: {"paired_on": f"2026-10-{1 + i % 21:02d}"})
        rules = ["rl_g_loser", "rl_g_thin", "rl_g_good", "rl_g_few",
                 "rl_g_none", "yield_curve_inversion_flip"]
        grouped = graded_records(rules)
        verdicts = {}
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertEqual(measured_loser(rule, stats=grouped[rule]),
                                 measured_loser(rule))
                verdicts[rule] = bool(measured_loser(rule))
        self.assertEqual(verdicts, {
            "rl_g_loser": True, "rl_g_thin": True, "rl_g_good": False,
            "rl_g_few": False, "rl_g_none": False,
            "yield_curve_inversion_flip": True})


class TheRuleIsNotProfitableTests(_Base):
    def test_losing_real_money_retires_it(self):
        cfg = _cfg(self.user)
        _closes(cfg, "rl_live_loser", 10, -0.3)
        s = _sig(self.inst, rule="rl_live_loser")
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "rule_losing_live")
        self.assertIn("lost real money on forex", g.words)
        self.assertIn("10 closed real-money trades in 180 days", g.words)
        self.assertIn("-0.30R", g.words.replace("−", "-"))

    def test_9_closes_are_not_judged(self):
        cfg = _cfg(self.user)
        _closes(cfg, "rl_live_young", 9, -0.3)
        s = _sig(self.inst, rule="rl_live_young")
        self.assertTrue(_on_rail(self.user, s))

    def test_paper_and_demo_closes_do_not_count(self):
        cfg = _cfg(self.user)
        _closes(cfg, "rl_live_sim", 10, -0.3, paper=True)
        _closes(cfg, "rl_live_sim", 10, -0.3, meta={"broker_env": "paper"})
        s = _sig(self.inst, rule="rl_live_sim")
        self.assertTrue(_on_rail(self.user, s))

    def test_an_index_rides_the_stock_pool(self):
        """The pool class: an index signal is judged on the stock pool's
        real money, as the hand lane books it."""
        cfg = _cfg(self.user, asset_class="stock", name="RL stocks")
        _closes(cfg, "rl_idx", 10, -0.2, symbol="RLSTK")
        idx = _inst("RLIDX", "index")
        s = _sig(idx, rule="rl_idx", entry="100", stop="95", target="110")
        self.assertEqual(_gone(self.user, s).reason, "rule_losing_live")


class LeftTheRailTests(_Base):
    def test_engine_closes_are_in_the_left_list(self):
        from signals.models import Signal
        recent = _sig(self.inst, rule="rl_closed", active=False)
        Signal.objects.filter(pk=recent.pk).update(
            outcome="hit_target", realized_r=2.0,
            expired_at=timezone.now() - timedelta(hours=1))
        old = _sig(_inst("RLFXB"), rule="rl_closed_old", active=False)
        Signal.objects.filter(pk=old.pk).update(
            outcome="stopped_out", realized_r=-1.0,
            expired_at=timezone.now() - timedelta(hours=30))
        g = _gone(self.user, recent)
        self.assertEqual(g.reason, "closed_target")
        self.assertIn("The engine closed it: target reached (+2.00R).",
                      g.words)
        self.assertFalse(g.engine_active)
        self.assertFalse(g.takeable)
        self.assertIsNone(_gone(self.user, old))
        html = _partial(self.client)
        self.assertIn("The engine closed it: target reached (+2.00R).", html)

    def test_the_left_list_keeps_24_hours_and_counts_the_rest(self):
        """(2026-11-06, the review) Every departure the engine still holds
        is drawn in full, its ticket with it: a burst of departures must
        not take the operator's last way to act on the oldest of them. Only
        the engine's own closes, which no ticket can take, are drawn up to
        GONE_ROWS; the rest of them are counted. This test drew 60 of 65
        departures the engine still held, the cap the review found; it now
        draws all 65 and caps 65 engine closes at 60 instead."""
        from signals.models import Signal
        Signal.objects.bulk_create([Signal(
            instrument=self.inst, signal_type="technical",
            direction="bullish", urgency="low", title="old",
            description="d", rule_name=f"rl_aged_{i}", score=0.6,
            sub_scores={}, price_at_signal=Decimal("1.08"),
            is_active=True) for i in range(65)])
        Signal.objects.filter(rule_name__startswith="rl_aged_").update(
            created_at=timezone.now() - timedelta(hours=30))
        Signal.objects.bulk_create([Signal(
            instrument=self.inst, signal_type="technical",
            direction="bullish", urgency="low", title="closed",
            description="d", rule_name=f"rl_shut_{i}", score=0.6,
            sub_scores={}, price_at_signal=Decimal("1.08"),
            is_active=False, outcome="expired") for i in range(65)])
        Signal.objects.filter(rule_name__startswith="rl_shut_").update(
            created_at=timezone.now() - timedelta(hours=10),
            expired_at=timezone.now() - timedelta(hours=2))
        _sig(self.inst, rule="rl_way_old", minutes_ago=60 * 60)
        snap = _snap(self.user)
        self.assertEqual(snap["gone_n"], 130)
        self.assertEqual(len(snap["gone"]), 125)
        self.assertEqual(snap["older_n"], 1)
        self.assertIn(("AGED", 65), snap["gone_tags"])
        self.assertIn(("CLOSED", 65), snap["gone_tags"])
        html = _partial(self.client)
        self.assertIn("and 5 more engine closes in the last 24h", html)
        self.assertEqual(html.count('class="sr-gone-row"'), 125)
        self.assertEqual(html.count("window.svTakeTrade("), 65)

    def test_every_departure_the_engine_holds_keeps_its_ticket(self):
        """65 stops crossed at once: 65 rows, 65 tickets. The rows past the
        first 60 used to have none, and /signals/ offers no ticket."""
        ids = []
        for i in range(65):
            inst = _inst(f"RLTK{i:03d}", "forex")
            _quote(inst, "1.07000")
            ids.append(_sig(inst, rule=f"rl_tk_{i}").pk)
        html = _partial(self.client)
        rows = _gone_rows(html)
        self.assertEqual(len(rows), 65)
        missing = [i for i in ids if f"window.svTakeTrade({i})" not in html]
        self.assertEqual(missing, [])
        self.assertNotIn("more engine closes", html)

    def test_your_pass_on_a_setup_matched_again_can_be_brought_back(self):
        """A pass made more than a day ago on a reused composite the scanner
        has matched again: it would be on the rail but for the pass, so
        LEFT THE RAIL lists it, as of the re-match, with BRING BACK."""
        from dashboard.models import RailDeparture
        from signals.models_opportunity import OpportunityFlag, OpportunitySetup
        s = _sig(self.inst, rule="rl_setup_again", signal_type="composite",
                 minutes_ago=40 * 60)
        setup = OpportunitySetup.objects.create(
            name="rl_setup_again", conditions=[], asset_classes=[])
        flag = OpportunityFlag.objects.create(
            setup=setup, instrument=self.inst, signal=s, score=0.7)
        matched = timezone.now() - timedelta(hours=2)
        OpportunityFlag.objects.filter(pk=flag.pk).update(scanned_at=matched)
        RailDeparture.objects.create(
            signal=s, user=self.user, reason="passed",
            words="You passed it at 08:00 UTC.",
            departed_at=timezone.now() - timedelta(hours=30))
        self.assertFalse(_on_rail(self.user, s))
        g = _gone(self.user, s)
        self.assertIsNotNone(g, "the pass can no longer be undone anywhere")
        self.assertEqual(g.reason, "passed")
        self.assertTrue(g.yours)
        self.assertEqual(g.at, matched)
        self.assertIn("You passed it", g.words)
        self.assertIn("matched its setup again", g.words)
        self.assertIn(f'data-sv-unpass="{s.pk}"', _partial(self.client))

    def test_left_rows_cost_no_query_per_row(self):
        """LEFT THE RAIL rows whose signal is neither on the rail nor a
        recent close (a pass on an older signal) are batched like cards:
        their quote and their position are read with everyone else's."""
        from dashboard.models import RailDeparture
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def make(n, tag):
            for i in range(n):
                inst = _inst(f"RLX{tag}{i:02d}", "forex")
                _quote(inst, "1.08100")
                s = _sig(inst, rule="rl_x_old", minutes_ago=60 * 60)
                RailDeparture.objects.create(
                    signal=s, user=self.user, reason="passed",
                    words="You passed it at 08:00 UTC.",
                    departed_at=timezone.now() - timedelta(hours=1))
        make(2, "a")
        with CaptureQueriesContext(connection) as two:
            self.assertEqual(len(_snap(self.user)["gone"]), 2)
        make(10, "b")
        with CaptureQueriesContext(connection) as twelve:
            self.assertEqual(len(_snap(self.user)["gone"]), 12)
        self.assertEqual(len(two.captured_queries),
                         len(twelve.captured_queries),
                         "\n".join(q["sql"][:160] for q in
                                   twelve.captured_queries))

    def test_the_left_count_says_how_many_engine_closes_were_not_read(self):
        """The engine closes of the last day are read up to a bound; past
        it, the count and the words say how many more there were."""
        from signals.models import Signal
        Signal.objects.bulk_create([Signal(
            instrument=self.inst, signal_type="technical",
            direction="bullish", urgency="low", title="closed",
            description="d", rule_name=f"rl_unread_{i}", score=0.6,
            sub_scores={}, price_at_signal=Decimal("1.08"),
            is_active=False, outcome="stopped_out", realized_r=-1.0)
            for i in range(8)])
        Signal.objects.filter(rule_name__startswith="rl_unread_").update(
            created_at=timezone.now() - timedelta(hours=10),
            expired_at=timezone.now() - timedelta(hours=1))
        with mock.patch("dashboard.signal_rail.GONE_CLOSED_FETCH", 5):
            snap = _snap(self.user)
            html = _partial(self.client)
        self.assertEqual(snap["closed_unread"], 3)
        self.assertEqual(snap["gone_n"], 8)
        self.assertEqual(snap["meta"]["gone"], 8)
        self.assertIn("3 more engine closes of the last 24h were not read",
                      html)
        self.assertIn("3 more engine closes not read", snap["title"])

    def test_an_engine_close_after_a_departure_keeps_the_first_reason(self):
        from signals.models import Signal
        s = _sig(self.inst)
        _quote(self.inst, "1.07400")
        _snap(self.user)
        Signal.objects.filter(pk=s.pk).update(
            is_active=False, outcome="stopped_out", realized_r=-1.0,
            expired_at=timezone.now())
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "stop_crossed")
        self.assertIn("closed by the engine at", g.closed_words)
        self.assertIn("stopped out", g.closed_words)


class YourOwnChoiceTests(_Base):
    def _pass(self, signal, undo=False, client=None):
        return (client or self.client).post(
            "/api/signal-rail/pass/",
            data=json.dumps({"signal_id": signal.pk, "undo": undo}),
            content_type="application/json", HTTP_HOST=HOST)

    def test_a_pass_is_yours_on_every_device(self):
        """A PASS lives on the server: gone for this operator on every
        browser, present for another, and an undo brings it back."""
        from django.test import Client
        s = _sig(self.inst)
        resp = self._pass(s)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True, "reason": "passed"})
        second = Client()
        second.force_login(self.user)
        self.assertNotIn(s.pk, _cards(_partial(second)))
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "passed")
        self.assertTrue(g.yours)
        self.assertIn("You passed it at", g.words)
        self.assertIn(f'data-sv-unpass="{s.pk}"', _partial(second))
        other = _user("rl_other")
        self.assertTrue(_on_rail(other, s))
        resp = self._pass(s, undo=True)
        self.assertEqual(resp.json(), {"ok": True, "undone": True})
        self.assertIn(s.pk, _cards(_partial(second)))

    def test_the_pass_answers_bad_input_plainly(self):
        bad = self.client.post("/api/signal-rail/pass/", data="nope",
                               content_type="application/json", HTTP_HOST=HOST)
        self.assertEqual(bad.status_code, 400)
        missing = self.client.post(
            "/api/signal-rail/pass/", data=json.dumps({"signal_id": 999999}),
            content_type="application/json", HTTP_HOST=HOST)
        self.assertEqual(missing.status_code, 404)

    def test_passing_your_own_take_is_recorded_as_taken(self):
        """TAKE TRADE's success path retires the card through the same
        call; the server reads the book and says it was taken."""
        cfg = _cfg(self.user, mode="paper", name="manual")
        s = _sig(self.inst)
        from bot_program.models import AssetBotTrade
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol=self.inst.symbol,
            side="BUY", qty=Decimal("1"), entry_price=Decimal("1.08"),
            stop_loss=Decimal("1.075"), take_profit=Decimal("1.09"),
            status="OPEN", paper=True, rule_name="manual_take",
            metadata={"manual": True, "signal_id": s.pk})
        self.assertEqual(self._pass(s).json()["reason"], "taken")
        g = _gone(self.user, s)
        self.assertEqual(g.tag, "TAKEN")
        self.assertIn(f"position #{trade.pk} is open", g.words)

    def test_your_own_take_offers_no_second_ticket(self):
        """The server refuses a second position on one signal; the card no
        longer offers one, and says why."""
        cfg = _cfg(self.user, mode="paper", name="manual")
        s = _sig(self.inst)
        from bot_program.models import AssetBotTrade
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol=self.inst.symbol,
            side="BUY", qty=Decimal("1"), entry_price=Decimal("1.08"),
            stop_loss=Decimal("1.075"), take_profit=Decimal("1.09"),
            status="OPEN", paper=True, rule_name="manual_take",
            metadata={"manual": True, "signal_id": s.pk})
        html = _partial(self.client)
        card = html.split(f'data-signal-id="{s.pk}"', 1)[1].split(
            'class="sr-signal-wrap', 1)[0]
        self.assertIn("BY HAND", card)
        self.assertNotIn("ADD TO POSITION", card)
        self.assertIn(f"One position per signal: #{trade.pk} is open.", card)


class TheRuleFactsSpeakForTheirMomentTests(_Base):
    """(2026-11-06, the review) The rule facts are cached 300 seconds
    outside the test runner, and a departure is permanent: a fact read
    before a signal reached the rail must never judge it. A pause lifted, a
    record that recovered: a signal that arrives afterwards is read against
    the rule as it is."""

    def setUp(self):
        super().setUp()
        self.cached = mock.patch("dashboard.signal_rail._testing",
                                 return_value=False)
        self.cached.start()
        self.addCleanup(self.cached.stop)

    @override_settings(CACHES=FACTS_CACHE)
    def test_a_cached_pause_never_retires_a_signal_born_after_it(self):
        from django.core.cache import cache
        from signals.models import RuleControl
        cache.clear()
        self.addCleanup(cache.clear)
        _control("rl_cached_pause", status="paused", paused_days=7)
        before = _sig(self.inst, rule="rl_cached_pause")
        self.assertEqual(_gone(self.user, before).reason, "rule_paused")
        RuleControl.objects.filter(rule_name="rl_cached_pause").update(
            status="active", paused_until=None)
        after = _sig(_inst("RLFXB"), rule="rl_cached_pause")
        self.assertTrue(_on_rail(self.user, after),
                        "a signal born after the unpause was retired by the "
                        "cached pause")
        self.assertIsNone(_departure(after))
        # The one the pause met stays gone: a departure is permanent.
        self.assertEqual(_gone(self.user, before).reason, "rule_paused")

    @override_settings(CACHES=FACTS_CACHE)
    def test_a_cached_record_never_judges_a_newer_signal(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        _graded("rl_cached_loser", 20, -0.5)
        first = _sig(self.inst, rule="rl_cached_loser")
        self.assertEqual(_gone(self.user, first).reason, "rule_losing")
        _graded("rl_cached_loser", 30, 1.5, outcome="hit_target")
        later = _sig(_inst("RLFXB"), rule="rl_cached_loser")
        self.assertTrue(_on_rail(self.user, later),
                        "a signal born after the record recovered was retired "
                        "by the cached record")

    def test_the_facts_are_read_from_the_cache_in_one_call(self):
        """One cache read for every rule on the rail, not one per rule."""

        class Recorder:
            def __init__(self):
                self.store, self.calls = {}, []

            def get(self, key, default=None, **kw):
                self.calls.append(("get", key))
                return self.store.get(key, default)

            def get_many(self, keys, **kw):
                keys = list(keys)
                self.calls.append(("get_many", tuple(keys)))
                return {k: self.store[k] for k in keys if k in self.store}

            def set(self, key, value, timeout=None, **kw):
                self.calls.append(("set", key))
                self.store[key] = value

            def set_many(self, data, timeout=None, **kw):
                self.calls.append(("set_many", tuple(data)))
                self.store.update(data)
                return []

        for i in range(4):
            _sig(_inst(f"RLCG{i}"), rule=f"rl_cg_{i}", minutes_ago=30)
        rec = Recorder()
        with mock.patch("django.core.cache.cache", rec):
            self.assertEqual(len(_snap(self.user)["cards"]), 4)
            rec.calls.clear()
            self.assertEqual(len(_snap(self.user)["cards"]), 4)
        rule_calls = [c for c in rec.calls
                      if any(str(k).startswith("sv:rail:rule:")
                             for k in (c[1] if isinstance(c[1], tuple)
                                       else (c[1],)))]
        self.assertEqual([c[0] for c in rule_calls], ["get_many"], rec.calls)


class TheVoteFollowsTheBotsClockTests(_Base):
    """decide() counts a signal for max_signal_age_hours (24 by default)
    from when it FIRED, and the hand ticket's backing does too; the
    opportunity scanner reuses a composite signal and only re-flags it. A
    re-match keeps the card on the rail — the setup holds — but never brings
    its vote back."""

    def _rematched(self, inst, rule, *, fired_h, matched_h=2, **kw):
        from signals.models_opportunity import OpportunityFlag, OpportunitySetup
        s = _sig(inst, rule=rule, signal_type="composite",
                 minutes_ago=fired_h * 60, **kw)
        setup = OpportunitySetup.objects.create(name=rule, conditions=[],
                                                asset_classes=[])
        flag = OpportunityFlag.objects.create(setup=setup, instrument=inst,
                                              signal=s, score=0.7)
        OpportunityFlag.objects.filter(pk=flag.pk).update(
            scanned_at=timezone.now() - timedelta(hours=matched_h))
        return s

    def _card_html(self, s):
        html = _partial(self.client)
        return html.split(f'data-signal-id="{s.pk}"', 1)[1].split(
            'class="sr-signal-wrap', 1)[0]

    def test_a_rematched_composite_no_longer_votes_after_24_hours(self):
        from bot_program.asset_engine import StockBot
        from tests.test_evidence_honesty import _cfg as bot_cfg
        inst = _inst("RLVOTEA", "stock")
        _control("rl_setup_vote", stage="live_full")
        s = self._rematched(inst, "rl_setup_vote", fired_h=30, score=0.85,
                            entry="100", stop="95", target="110")
        _quote(inst, "100")
        snap = _snap(self.user)
        card = next(c for c in snap["cards"] if c.pk == s.pk)
        self.assertEqual(card.rail.stage_label, "TRADEABLE")
        self.assertFalse(card.rail.votes, "the rail says the bots count a "
                         "vote decide() no longer counts")
        self.assertFalse(card.rail.live)
        self.assertEqual(card.rail.vote_until,
                         s.created_at + timedelta(hours=24))
        self.assertEqual(snap["votes_n"], 0)
        self.assertEqual(snap["live_n"], 0)
        chunk = self._card_html(s)
        self.assertIn('data-votes="0"', chunk)
        self.assertIn('data-live="0"', chunk)
        self.assertNotIn("the bots count its vote", chunk)
        self.assertIn("stopped counting its vote", chunk)
        self.assertIn("matched it again", chunk)
        self.assertIn("24h after the scanner last matched its setup", chunk)
        cfg = bot_cfg(self.user, asset_class="stock", name="RL vote clock",
                      mode="paper", symbols=["RLVOTEA"],
                      capital=Decimal("10000"), min_signals_for_entry=1)
        self.assertEqual(StockBot(cfg).decide("RLVOTEA").direction, "HOLD")

    def test_a_fresh_signal_votes_until_24_hours_after_it_fired(self):
        _control("rl_fresh_vote", stage="live_full")
        s = _sig(self.inst, rule="rl_fresh_vote", minutes_ago=60)
        card = next(c for c in _snap(self.user)["cards"] if c.pk == s.pk)
        self.assertTrue(card.rail.votes)
        self.assertTrue(card.rail.live)
        self.assertEqual(card.rail.vote_until,
                         s.created_at + timedelta(hours=24))
        chunk = self._card_html(s)
        self.assertIn('data-votes="1"', chunk)
        self.assertIn("a default bot counts its vote until", chunk)

    def test_the_words_speak_for_a_default_bot(self):
        """A bot's own max_signal_age_hours can differ (a scalp persona
        counts 4 hours, a position persona 72): the words say "a default
        bot", never "the bots"."""
        aged = _sig(self.inst, rule="rl_words_age", minutes_ago=25 * 60)
        self.assertIn("a default bot", _gone(self.user, aged).words)
        self.assertNotIn("the bots count", _gone(self.user, aged).words)
        chips = (Path(settings.BASE_DIR) / "templates" / "_partials"
                 / "rail_sig_chips.html").read_text(encoding="utf-8")
        votes = re.search(r'data-f-val="votes"[^>]*title="([^"]*)"', chips)
        self.assertIsNotNone(votes)
        self.assertIn("default bot", votes.group(1))


class TheWordsStayTrueTests(_Base):
    """The words of a departure are written once and read for a day: each
    one says its moment, and a fact that can change after it — the rule's
    pause, the operator's position — is said as it is now, beside them."""

    def test_a_stop_departure_says_its_moment(self):
        s = _sig(self.inst)
        _quote(self.inst, "1.07400")
        g = _gone(self.user, s)
        self.assertRegex(g.words, r"^At \d\d:\d\d UTC the price")
        self.assertIn("was at or through its stop", g.words)
        self.assertNotIn("a ticket here is refused", g.words)
        self.assertTrue(g.takeable)

    def test_the_paused_words_are_true_for_a_scanner_setup(self):
        """The opportunity scanner never reads the pause: it keeps writing
        and re-matching a paused setup's signals. What a pause does stop is
        the bots' vote and their entries."""
        _control("rl_setup_paused", status="paused", paused_days=7)
        comp = _sig(self.inst, rule="rl_setup_paused", signal_type="composite")
        g = _gone(self.user, comp)
        self.assertEqual(g.reason, "rule_paused")
        self.assertNotIn("writes no new signal", g.words)
        self.assertIn("the bots no longer count its vote or open an entry on it",
                      g.words)
        _control("rl_rule_paused", status="paused", paused_days=7)
        tech = _sig(_inst("RLFXB"), rule="rl_rule_paused")
        self.assertIn("the rule engine writes no new signal for it",
                      _gone(self.user, tech).words)

    def test_a_paused_row_says_the_rule_state_now(self):
        from signals.models import RuleControl
        _control("rl_unpaused", status="paused", paused_days=7)
        s = _sig(self.inst, rule="rl_unpaused")
        g = _gone(self.user, s)
        self.assertRegex(g.words, r"^At \d\d:\d\d UTC its rule \(rl_unpaused\) "
                                  r"was paused")
        self.assertIn("Its rule is paused now.", g.words)
        RuleControl.objects.filter(rule_name="rl_unpaused").update(
            status="active", paused_until=None)
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "rule_paused")
        self.assertIn("Its rule is no longer paused.", g.words)
        self.assertNotIn("is paused now", g.words)

    def _hand_trade(self, s, status="OPEN"):
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, mode="paper", name="manual")
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol=self.inst.symbol,
            side="BUY", qty=Decimal("1"), entry_price=Decimal("1.08"),
            stop_loss=Decimal("1.075"), take_profit=Decimal("1.09"),
            status=status, paper=True, rule_name="manual_take",
            metadata={"manual": True, "signal_id": s.pk})

    def test_the_taken_words_follow_the_position(self):
        from bot_program.models import AssetBotTrade
        from dashboard.signal_rail import _hhmm
        s = _sig(self.inst, minutes_ago=60)
        trade = self._hand_trade(s)
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            opened_at=timezone.now() - timedelta(minutes=50))
        trade.refresh_from_db()
        resp = self.client.post(
            "/api/signal-rail/pass/", data=json.dumps({"signal_id": s.pk}),
            content_type="application/json", HTTP_HOST=HOST)
        self.assertEqual(resp.json()["reason"], "taken")
        self.assertIn(f"You took it at {_hhmm(trade.opened_at)}",
                      _departure(s, self.user).words)
        g = _gone(self.user, s)
        self.assertIn(f"position #{trade.pk} is open", g.words)
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            status="CLOSED", closed_at=timezone.now())
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "taken")
        self.assertNotIn(f"position #{trade.pk} is open", g.words)
        self.assertIn("you hold no position on it now", g.words)

    def test_a_closing_position_is_said_closing(self):
        """CLOSE_PENDING is still open at the broker, so the card keeps the
        ticket back; but the server's one-position check reads OPEN only,
        so the card must not say "is open"."""
        s = _sig(self.inst)
        trade = self._hand_trade(s, status="CLOSE_PENDING")
        html = _partial(self.client)
        card = html.split(f'data-signal-id="{s.pk}"', 1)[1].split(
            'class="sr-signal-wrap', 1)[0]
        self.assertNotIn(f"#{trade.pk} is open", card)
        self.assertIn(f"#{trade.pk} is closing (close pending)", card)
        self.assertNotIn(f"window.svTakeTrade({s.pk})", card)
        _quote(self.inst, "1.07000")
        g = _gone(self.user, s)
        self.assertIn(f"position #{trade.pk} is closing", g.position_words)
        self.assertFalse(g.takeable)

    def test_rounded_numbers_never_contradict_their_line(self):
        # Reward:risk 0.997 is under the ticket's 1.00 line: never "1.00".
        chased = _sig(self.inst)
        _quote(self.inst, "1.08251")
        g = _gone(self.user, chased)
        self.assertEqual(g.reason, "chased")
        self.assertIn("reward:risk 0.99, under the ticket's 1.00 line", g.words)
        # Half an hour past the 24 hours is never "24h old, past the 24h".
        aged = _sig(_inst("RLFXB"), rule="rl_half", minutes_ago=24 * 60 + 30)
        self.assertIn("24h 30m old", _gone(self.user, aged).words)
        # Ten real-money closes at exactly 0R lost nothing.
        _closes(_cfg(self.user), "rl_flat_live", 10, 0.0)
        flat = _sig(_inst("RLFXC"), rule="rl_flat_live")
        g = _gone(self.user, flat)
        self.assertEqual(g.reason, "rule_losing_live")
        self.assertNotIn("lost real money", g.words)
        self.assertIn("made nothing with real money on forex", g.words)

    def test_demotion_words_name_the_venues_and_the_day(self):
        """The words are read for a day after they are written: the
        demotion says its date, and the stages in the operator's words
        beside the ladder's own names."""
        from signals.models import PromotionEvent
        _control("rl_demoted_y", stage="paper")
        s = _sig(self.inst, rule="rl_demoted_y", minutes_ago=5 * 60)
        ev = PromotionEvent.objects.create(
            rule_name="rl_demoted_y", from_stage="live_small",
            to_stage="paper", reason="auto_demote")
        when = timezone.now() - timedelta(hours=2)
        PromotionEvent.objects.filter(pk=ev.pk).update(created_at=when)
        g = _gone(self.user, s)
        self.assertEqual(g.reason, "rule_demoted")
        self.assertIn("demoted from live_small to paper", g.words)
        self.assertIn("live at quarter size to the paper venue", g.words)
        from datetime import timezone as dt_timezone
        self.assertIn(when.astimezone(dt_timezone.utc).strftime("%b %d"),
                      g.words)

    def test_the_held_chips_say_which_books(self):
        """HELD counts every open position of the operator's — live, demo,
        paper and the legacy book — and the chips say so."""
        for name in ("rail_sig_chips.html", "rail_watch_chips.html"):
            src = (Path(settings.BASE_DIR) / "templates" / "_partials"
                   / name).read_text(encoding="utf-8")
            title = re.search(r'data-f-val="held"[^>]*title="([^"]*)"', src)
            with self.subTest(chips=name):
                self.assertIsNotNone(title)
                self.assertIn("live, demo, paper", title.group(1))


class TheCountsAreWholeTests(_Base):
    def test_signals_beyond_the_ceiling_are_not_called_left_earlier(self):
        for i in range(5):
            _sig(_inst(f"RLCE{i}"), rule=f"rl_ce_{i}", minutes_ago=10 + i)
        with mock.patch("dashboard.signal_rail.RAIL_SAFETY_CEILING", 3):
            snap = _snap(self.user)
        self.assertTrue(snap["ceiling_hit"])
        self.assertEqual(snap["n"], 3)
        self.assertEqual(snap["older_n"], 0, snap["title"])
        self.assertIn("showing the newest 3 of 5", snap["title"])

    def test_an_unread_rail_says_so_and_counts_nothing(self):
        """A snapshot that fails is an unknown, never a zero: the cell, its
        sub-line and the rail head say "—", and no sentence says the rail
        is empty."""
        from tests.test_rail_every_signal import _page
        _sig(self.inst)
        with mock.patch("dashboard.signal_rail._build",
                        side_effect=RuntimeError("db hiccup")):
            page = _page(self.client)
            swept = _page(self.client, HTTP_X_SV_SWEEP="1")
            partial = _partial(self.client)

        def text(html, pattern):
            from html import unescape
            m = re.search(pattern, html, re.S)
            self.assertIsNotNone(m, pattern)
            return unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        for html in (page, swept):
            self.assertEqual(text(html, r'data-sv-live="hb-signals" '
                                        r'data-sv-live-key="hb-signals">(.*?)'
                                        r'</span>\s*<span'), "—")
            self.assertEqual(text(html, r'data-sv-live="hb-signals-sub">(.*?)'
                                        r'</span>\s*<div'), "—")
        self.assertEqual(text(page, r'id="railSigCount"[^>]*>(.*?)</span>'), "—")
        self.assertIn("could not be read", partial)
        self.assertNotIn("No signal on the rail", partial)
        self.assertNotIn("Nothing left the rail", partial)


class PrimedActedTests(_Base):
    def test_prime_acted_matches_resolve_acted(self):
        """One query for the rail, the same join card by card."""
        from bot_program.models import AssetBotTrade
        from signals.models import Signal
        cfg = _cfg(self.user, mode="paper")
        other = _inst("RLFXB")

        def trade(symbol, rule, status="OPEN", meta=None):
            return AssetBotTrade.objects.create(
                config=cfg, asset_class="forex", symbol=symbol, side="BUY",
                qty=Decimal("1"), entry_price=Decimal("1.08"),
                stop_loss=Decimal("1.075"), take_profit=Decimal("1.09"),
                status=status, paper=True, rule_name=rule,
                metadata=meta or {})

        trade(self.inst.symbol, "rl_pa_before")     # before its signal
        exact = _sig(self.inst, rule="rl_pa_exact")
        by_rule = _sig(self.inst, rule="rl_pa_rule")
        closed = _sig(self.inst, rule="rl_pa_closed")
        before = _sig(self.inst, rule="rl_pa_before")
        elsewhere = _sig(other, rule="rl_pa_else")
        ruleless = _sig(self.inst, rule="")
        trade(self.inst.symbol, "manual_take",
              meta={"manual": True, "signal_id": exact.pk})
        trade(self.inst.symbol, "rl_pa_rule")
        trade(self.inst.symbol, "rl_pa_closed", status="CLOSED")
        trade(self.inst.symbol, "rl_pa_else")
        trade(self.inst.symbol, "")
        sigs = [exact, by_rule, closed, before, elsewhere, ruleless]
        one_by_one = [Signal.objects.get(pk=s.pk).acted for s in sigs]
        fresh = list(Signal.objects.filter(pk__in=[s.pk for s in sigs])
                     .select_related("instrument"))
        Signal.prime_acted(fresh)
        primed = {s.pk: s.acted for s in fresh}
        self.assertEqual([primed[s.pk] for s in sigs], one_by_one)
        self.assertEqual(one_by_one[0]["by"], "manual")
        self.assertEqual(one_by_one[1]["by"], "bot")
        self.assertEqual(one_by_one[2:], [None, None, None, None])


class MoneyDirectionTests(_Base):
    """Display only: what the engine, the bots and the take-trade path see
    is exactly what they saw."""

    def _world(self):
        """Every column of every row the engine, the bots and the ticket
        read — auto_now and auto_now_add columns included."""
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        from signals.models import PromotionEvent, RuleControl, Signal

        def row(obj):
            return json.dumps({f.attname: getattr(obj, f.attname)
                               for f in obj._meta.concrete_fields},
                              sort_keys=True, default=str)
        return {model.__name__: sorted(row(o) for o in model.objects.all())
                for model in (Signal, RuleControl, PromotionEvent,
                              AssetBotTrade, Instrument)}

    def _every_reason(self):
        from signals.models import PromotionEvent, Signal
        insts = [_inst(f"RLMD{i}", "forex") for i in range(10)]
        _sig(insts[0], rule="rl_md_same", minutes_ago=300)
        _sig(insts[0], rule="rl_md_same", minutes_ago=60)
        _sig(insts[1], rule="rl_md_age", minutes_ago=26 * 60)
        _sig(insts[2], rule="rl_md_stop")
        _quote(insts[2], "1.07000")
        _sig(insts[3], rule="rl_md_target")
        _quote(insts[3], "1.09500")
        _sig(insts[4], rule="rl_md_chase")
        _quote(insts[4], "1.08800")
        _control("rl_md_paused", status="paused", paused_days=7)
        _sig(insts[5], rule="rl_md_paused")
        _control("rl_md_demoted", stage="paper")
        _sig(insts[6], rule="rl_md_demoted", minutes_ago=30)
        PromotionEvent.objects.create(rule_name="rl_md_demoted",
                                      from_stage="live_full",
                                      to_stage="paper", reason="manual_demote")
        _graded("rl_md_loser", 20, -0.5)
        _sig(insts[7], rule="rl_md_loser")
        _closes(_cfg(self.user), "rl_md_live", 10, -0.4)
        _sig(insts[8], rule="rl_md_live")
        closed = _sig(insts[9], rule="rl_md_closed", active=False)
        Signal.objects.filter(pk=closed.pk).update(
            outcome="expired", expired_at=timezone.now() - timedelta(hours=2))
        return _sig(_inst("RLMDP"), rule="rl_md_pass")

    def test_the_rail_writes_no_engine_row(self):
        to_pass = self._every_reason()
        before = self._world()
        snap = _snap(self.user)
        reasons = {g.reason for g in snap["gone"]}
        self.assertTrue({"superseded", "aged", "stop_crossed",
                         "target_reached", "chased", "rule_paused",
                         "rule_demoted", "rule_losing", "rule_losing_live",
                         "closed_expired"} <= reasons, reasons)
        _partial(self.client)
        for undo in (False, True):
            self.client.post("/api/signal-rail/pass/", data=json.dumps(
                {"signal_id": to_pass.pk, "undo": undo}),
                content_type="application/json", HTTP_HOST=HOST)
        _partial(self.client)
        self.assertEqual(self._world(), before)

    #: The display modules that may name the rail, and nothing else
    #: (2026-11-06, the review: the guard used to read nine engine apps and
    #: skip trader_profile.py whole; it now reads EVERY Python file of the
    #: project, tests aside, against this list).
    RAIL_READERS = {
        "dashboard/signal_rail.py", "dashboard/rail_prefs.py",
        "dashboard/models.py", "dashboard/views.py", "dashboard/urls.py",
        "dashboard/migrations/0003_raildeparture.py",
        "core/context_processors.py", "core/context_ui.py",
        "portfolio/migrations/0019_traderprofile_rail_prefs.py",
    }
    RAIL_WORDS = ("RailDeparture", "signal_rail", "rail_prefs")
    #: A migration names the one before it in its dependencies: a file's
    #: name, not a read of the rail. Updated deliberately (2026-11-12):
    #: portfolio 0020, the Ambience field (display only), follows
    #: 0019_traderprofile_rail_prefs and must say so. That one line of a
    #: migration is let through, whole; anything else it says of the rail
    #: is still a hit.
    RAIL_DEPENDENCY = re.compile(r'\s*\("portfolio", "0019_traderprofile_rail_prefs"\),?\s*')

    def test_no_engine_module_reads_the_rail(self):
        """A guard, not a regression test: it passed before the rail existed,
        by construction. Every Python file of the project but the tests and
        the display modules above is read; trader_profile.py may carry the
        field's declaration and its comment, nothing more."""
        base = Path(settings.BASE_DIR)
        hits, read = [], 0
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(base).as_posix()
            top = rel.split("/", 1)[0]
            if (top in ("tests", "venv", ".venv", "node_modules", "staticfiles")
                    or "/site-packages/" in rel or rel in self.RAIL_READERS):
                continue
            read += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            for word in self.RAIL_WORDS:
                if word not in text:
                    continue
                lines = [ln for ln in text.splitlines() if word in ln]
                if rel == "portfolio/trader_profile.py" and all(
                        ln.strip().startswith("#")
                        or re.match(r"\s*rail_prefs = models\.JSONField\(", ln)
                        for ln in lines):
                    continue
                if "/migrations/" in rel and all(
                        self.RAIL_DEPENDENCY.fullmatch(ln) for ln in lines):
                    continue
                hits.append(f"{rel}: {word}")
        self.assertEqual(hits, [])
        self.assertGreater(read, 500, "the guard read almost nothing")

    def test_a_migration_s_dependency_is_a_file_name_and_nothing_else_is(self):
        """The one line the guard lets through in a migration is the
        dependency on the rail's own migration; a migration that reads or
        writes the field is still caught, on the same line or another."""
        ambience = (Path(settings.BASE_DIR) / "portfolio/migrations"
                    / "0020_traderprofile_ambience.py").read_text(encoding="utf-8")
        named = [ln for ln in ambience.splitlines()
                 if any(word in ln for word in self.RAIL_WORDS)]
        self.assertEqual(len(named), 1)
        self.assertTrue(self.RAIL_DEPENDENCY.fullmatch(named[0]), named[0])
        for line in ('    rail_prefs = models.JSONField(default=dict)',
                     '        profile.rail_prefs = {}',
                     '        ("portfolio", "0019_traderprofile_rail_prefs"), profile.rail_prefs',
                     '    from dashboard.signal_rail import rail_snapshot'):
            with self.subTest(line=line):
                self.assertIsNone(self.RAIL_DEPENDENCY.fullmatch(line))

    def test_the_take_trade_path_reads_nothing_of_the_rail(self):
        """The ticket's views live in dashboard/views.py beside the rail's
        own: none of them names the rail (a guard, as above)."""
        import inspect
        from dashboard import views
        for fn in (views.take_trade_preview, views.take_trade_execute,
                   views.asset_trade_preview, views.asset_trade_execute,
                   views.take_trade_arm, views.take_trade_lane_knobs):
            src = inspect.getsource(fn)
            for word in self.RAIL_WORDS:
                with self.subTest(view=fn.__name__, word=word):
                    self.assertNotIn(word, src)

    def test_a_retired_signal_stays_active_and_takeable(self):
        from signals.models import Signal
        s = _sig(self.inst)
        _quote(self.inst, "1.07000")
        html = _partial(self.client)
        self.assertNotIn(s.pk, _cards(html))
        self.assertTrue(Signal.objects.get(pk=s.pk).is_active)
        g = _gone(self.user, s)
        self.assertTrue(g.engine_active)
        self.assertTrue(g.takeable)
        rows = _gone_rows(html)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn(f'data-signal-id="{s.pk}"', rows[0])
        self.assertIn(f"window.svTakeTrade({s.pk})", rows[0])

    def test_decide_is_unchanged_by_the_rail(self):
        """The bots' vote reads the same Signal rows with the same filters:
        the rail retiring every signal on a symbol changes nothing in it."""
        from bot_program.asset_engine import StockBot
        from tests.test_evidence_honesty import _cfg as bot_cfg
        inst = _inst("RLVOTE", "stock")
        cfg = bot_cfg(self.user, asset_class="stock", name="RL vote",
                      mode="paper", symbols=["RLVOTE"],
                      capital=Decimal("10000"), min_signals_for_entry=2)
        for rule in ("golden_cross", "macd_cross"):
            _control(rule, stage="live_full")
            _sig(inst, rule=rule, score=0.85, entry="100", stop="95",
                 target="110")

        def decision():
            d = StockBot(cfg).decide("RLVOTE")
            return (d.direction, round(float(d.score or 0), 6), d.rule_name,
                    list(d.reasons))

        _quote(inst, "90")                      # every stop crossed
        before = decision()
        snap = _snap(self.user)
        self.assertEqual([c for c in snap["cards"]
                          if c.instrument_id == inst.pk], [])
        self.assertEqual(decision(), before)
        self.assertEqual(before[0], "BUY", before)
