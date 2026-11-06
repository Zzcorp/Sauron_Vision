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

from django.conf import settings
from django.test import RequestFactory, TestCase
from django.utils import timezone

from tests.test_rail_every_signal import (
    HOST, _cards, _inst, _partial, _quote, _sig, _user)


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
        from signals.models import Signal
        Signal.objects.bulk_create([Signal(
            instrument=self.inst, signal_type="technical",
            direction="bullish", urgency="low", title="old",
            description="d", rule_name=f"rl_aged_{i}", score=0.6,
            sub_scores={}, price_at_signal=Decimal("1.08"),
            is_active=True) for i in range(65)])
        Signal.objects.filter(rule_name__startswith="rl_aged_").update(
            created_at=timezone.now() - timedelta(hours=30))
        _sig(self.inst, rule="rl_way_old", minutes_ago=60 * 60)
        snap = _snap(self.user)
        self.assertEqual(snap["gone_n"], 65)
        self.assertEqual(len(snap["gone"]), 60)
        self.assertEqual(snap["older_n"], 1)
        self.assertIn(("AGED", 65), snap["gone_tags"])
        html = _partial(self.client)
        self.assertIn("and 5 more in the last 24h", html)
        self.assertEqual(html.count('class="sr-gone-row"'), 60)

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

    def test_no_engine_module_reads_the_rail(self):
        base = Path(settings.BASE_DIR)
        hits = []
        for top in ("signals", "bot_program", "alerts", "portfolio",
                    "ai_agents", "brain", "backtester", "market_data",
                    "scraping"):
            for path in (base / top).rglob("*.py"):
                rel = path.relative_to(base).as_posix()
                if (rel == "portfolio/trader_profile.py"
                        or re.match(r"portfolio/migrations/\d+_traderprofile"
                                    r"_rail_prefs\.py$", rel)):
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for word in ("RailDeparture", "signal_rail", "rail_prefs"):
                    if word in text:
                        hits.append(f"{rel}: {word}")
        self.assertEqual(hits, [])

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
