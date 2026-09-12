"""The six questions every signal must answer, and the twelve filters.

Before 2026-09-12 /signals/ had ONE filter (`?active=1`) and its rows carried
no stage, no rule record, no conditions and no outcome. Twenty-six of the
platform's twenty-eight rules sit at `research`, where `stage_policy` returns
may_trade False and every bot drops the rule's votes from its consensus — so
almost every card on that page was an idea nothing could act on, rendered
identically to one a bot was about to trade live at full size.

These tests pin the repair, and above all its first rule: the badge is
DERIVED from `rule_actuator.stage_policy` and `is_rule_active`, the same two
functions the entry path calls. A second implementation of the gate would be
a page that can disagree with the gate, which is worse than no badge at all.

Run with:  python manage.py test tests.test_signal_surface
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone

User = get_user_model()


def _instrument(symbol, asset_class="forex"):
    from instruments.models import Instrument
    return Instrument.objects.create(symbol=symbol, name=symbol,
                                     asset_class=asset_class, is_active=True)


def _control(rule, *, stage="research", status="active", paused_until=None):
    from signals.models import RuleControl
    return RuleControl.objects.create(rule_name=rule, promotion_stage=stage,
                                      status=status, paused_until=paused_until)


def _signal(inst, rule, **kw):
    from signals.models import Signal
    fields = dict(instrument=inst, signal_type="composite", direction="bullish",
                  urgency="medium", title=f"{rule} on {inst.symbol}",
                  description="d", rule_name=rule, score=0.8,
                  price_at_signal=Decimal("1"), suggested_entry=Decimal("1"),
                  suggested_stop=Decimal("0.9"), suggested_target=Decimal("1.2"),
                  risk_reward_ratio=2.0, is_active=True)
    fields.update(kw)
    return Signal.objects.create(**fields)


class BadgeTests(TestCase):
    """(a) CAN ANYTHING ACT ON IT — all five states, from the real functions."""

    def test_the_badge_is_derived_from_stage_policy_for_every_state(self):
        from dashboard.signal_surface import stage_badge
        from signals.rule_actuator import stage_policy

        _control("r_live", stage="live_full")
        _control("r_paper", stage="paper")
        _control("r_research", stage="research")
        _control("r_paused", stage="live_full", status="paused")
        _control("r_reduced", stage="live_full", status="reduced")

        self.assertEqual(stage_badge("r_live")["label"], "TRADEABLE")
        self.assertEqual(stage_badge("r_paper")["label"], "PAPER ONLY")
        self.assertEqual(stage_badge("r_research")["label"], "WATCHED")
        self.assertEqual(stage_badge("r_paused")["label"], "PAUSED")
        self.assertEqual(stage_badge("r_reduced")["label"], "REDUCED")
        # THE no-RuleControl-row case, which is not "blocked": stage_policy
        # fails SAFE — paper venue, FULL nominal size.
        unreg = stage_badge("r_nobody_registered")
        self.assertEqual(unreg["label"], "PAPER ONLY")
        self.assertFalse(unreg["registered"])
        self.assertIn("unregistered - paper venue at full size", unreg["reason"])
        # And every one of them agrees with stage_policy itself, which is the
        # whole contract: the badge is that function's answer, not a copy.
        for rule in ("r_live", "r_paper", "r_research", "r_nobody_registered"):
            self.assertEqual(stage_badge(rule)["may_trade"],
                             stage_policy(rule)["may_trade"], rule)

    def test_a_junk_stage_reads_unregistered_exactly_as_the_gate_does(self):
        """`stage_policy` treats a MISSING row and a row whose stage is not in
        STAGE_ORDER identically — both are 'no promotion record': paper venue,
        full size. The badge has to branch on the same condition, not on a
        substring of that function's reason sentence, or a junk stage value
        renders as a promotion nobody granted.
        """
        from dashboard.signal_surface import stage_badge
        from signals.rule_actuator import stage_policy

        _control("r_junk", stage="banana")
        badge = stage_badge("r_junk")
        self.assertFalse(badge["registered"])
        self.assertEqual(badge["label"], "PAPER ONLY")
        self.assertIn("unregistered - paper venue at full size",
                      badge["reason"])
        policy = stage_policy("r_junk")
        self.assertEqual(badge["may_trade"], policy["may_trade"])
        self.assertTrue(policy["force_paper"])

    def test_a_research_signal_reads_watched_and_says_its_votes_are_dropped(self):
        inst = _instrument("EURUSD")
        _control("r_watch", stage="research")
        _signal(inst, "r_watch")
        user = User.objects.create_superuser("sig_su1", "a@b.c", "x")
        self.client.force_login(user)
        body = self.client.get("/signals/").content.decode()
        self.assertIn("WATCHED", body)
        self.assertIn("votes are dropped", body)
        self.assertIn("net evidence +0.00", body)


class RuleRecordTests(TestCase):
    """(b) WHAT IS THIS RULE WORTH — the ledger's numbers, at its own floor."""

    def setUp(self):
        self.inst = _instrument("GBPUSD")

    def _graded(self, rule, n, r=1.0):
        for _ in range(n):
            _signal(self.inst, rule, is_active=False, outcome="hit_target",
                    realized_r=r)

    def test_below_the_floor_it_reads_unmeasured_and_above_it_the_numbers(self):
        from bot_program.evidence import MIN_EVIDENCE_N
        from dashboard.signal_surface import rule_records

        self._graded("r_thin", MIN_EVIDENCE_N - 1)
        self._graded("r_thick", MIN_EVIDENCE_N)
        recs = rule_records(["r_thin", "r_thick"])
        self.assertFalse(recs["r_thin"]["measured"])
        self.assertIsNone(recs["r_thin"]["hit_rate"])
        self.assertIn("unmeasured", recs["r_thin"]["text"])
        self.assertTrue(recs["r_thick"]["measured"])
        self.assertEqual(recs["r_thick"]["hit_rate"], 100.0)
        self.assertEqual(recs["r_thick"]["avg_r"], 1.0)
        # The window is NAMED. A record with an unnamed window cannot be
        # compared to anything.
        self.assertEqual(recs["r_thick"]["window"], "all time")


class WhyBlockTests(TestCase):
    """(c) WHY DID IT FIRE — the flag's conditions, or sub_scores, NAMED."""

    def setUp(self):
        self.inst = _instrument("BTCUSD", "crypto")

    def test_it_renders_from_a_linked_flag_and_falls_back_to_sub_scores(self):
        from dashboard.signal_surface import why_block
        from signals.models import OpportunityFlag, OpportunitySetup

        s = _signal(self.inst, "r_scanner",
                    sub_scores={"opportunity_setup": "r_scanner"})
        setup = OpportunitySetup.objects.create(
            name="r_scanner", conditions=[], min_match_score=0.6)
        flag = OpportunityFlag.objects.create(
            setup=setup, instrument=self.inst, signal=s, score=0.8,
            conditions_evaluated=[
                {"kind": "price_pattern", "matched": True, "score": 1.0,
                 "details": {"last": 101.0, "ma": 100.0}},
                {"kind": "relative_volume", "matched": False, "score": 0.0,
                 "details": {"reason": "need 21 bars"}},
            ])
        block = why_block(s, flag)
        self.assertEqual(block["source"], "scanner flag")
        self.assertEqual([r["label"] for r in block["rows"]],
                         ["price_pattern", "relative_volume"])
        self.assertTrue(block["rows"][0]["matched"])
        self.assertIn("need 21 bars", block["rows"][1]["value"])
        self.assertIn(str(flag.pk), block["caption"])

        # No flag: the engine path, and the block says which source it is.
        e = _signal(self.inst, "r_engine",
                    sub_scores={"structure": 0.9, "momentum": 0.4})
        fallback = why_block(e, None)
        self.assertEqual(fallback["source"], "engine sub-scores")
        self.assertEqual(len(fallback["rows"]), 2)
        self.assertIn("sub_scores", fallback["caption"])


class ActedTests(TestCase):
    """(e) DID ANYONE ACT — the string join, captioned as an inference."""

    def setUp(self):
        from bot_program.models import AssetBotConfig
        self.user = User.objects.create_user("sig_acted", password="x")
        self.inst = _instrument("USDCAD")
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="p", mode="paper",
            enabled=True, symbols=["USDCAD"], capital=Decimal("1000"))

    def _trade(self, rule, symbol, **kw):
        from bot_program.models import AssetBotTrade
        fields = dict(config=self.cfg, asset_class="forex", symbol=symbol,
                      side="BUY", qty=Decimal("1"), entry_price=Decimal("1"),
                      status="OPEN", paper=True, rule_name=rule)
        fields.update(kw)
        return AssetBotTrade.objects.create(**fields)

    def test_it_finds_a_trade_by_rule_symbol_and_time_and_captions_the_doubt(self):
        from dashboard.signal_surface import ACTED_CAPTION, acted_index

        s = _signal(self.inst, "r_acted")
        self._trade("r_acted", "USDCAD")            # same rule, same symbol
        self._trade("r_other", "USDCAD")            # wrong rule
        self._trade("r_acted", "EURUSD")            # wrong symbol
        old = self._trade("r_acted", "USDCAD")
        # A position opened BEFORE the signal cannot have been opened because
        # of it, so the join must exclude it.
        type(old).objects.filter(pk=old.pk).update(
            opened_at=s.created_at - timedelta(hours=2))

        found = acted_index([s])
        self.assertEqual(len(found[s.pk]), 1)
        self.assertEqual(found[s.pk][0]["venue"], "PAPER")
        # The caption must say the join is not a foreign key, or the block
        # reads as certainty it has not earned.
        self.assertIn("NOT on a foreign key", ACTED_CAPTION)
        self.assertIn("not certainty", ACTED_CAPTION)


class FilterTests(TestCase):
    """Twelve filters, every one a real queryset narrowing."""

    def setUp(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        self.user = User.objects.create_user("sig_filt", password="x")
        self.fx = _instrument("EURUSD", "forex")
        self.btc = _instrument("BTCUSD", "crypto")
        _control("r_research", stage="research")
        _control("r_live", stage="live_full")

        self.a = _signal(self.fx, "r_research", score=0.9, direction="bullish",
                         urgency="critical", signal_type="composite")
        self.b = _signal(self.btc, "r_live", score=0.4, direction="bearish",
                         urgency="low", signal_type="technical")
        self.c = _signal(self.fx, "r_unregistered", score=0.6,
                         direction="bullish", urgency="medium",
                         is_active=False, outcome="hit_target", realized_r=1.2)
        self.d = _signal(self.btc, "r_unregistered", score=0.5,
                         direction="bearish", urgency="high",
                         is_active=False, outcome="", realized_r=None)
        # An old one, for --age-hours.
        self.old = _signal(self.fx, "r_live", score=0.7)
        type(self.old).objects.filter(pk=self.old.pk).update(
            created_at=timezone.now() - timedelta(days=9))

        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="p", mode="paper",
            enabled=True, symbols=["EURUSD"], capital=Decimal("1000"))
        AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("1"), status="OPEN",
            paper=True, rule_name="r_research")

    def _count(self, query):
        from dashboard.signal_surface import apply_filters
        from signals.models import Signal
        qs, _chips, active = apply_filters(
            Signal.objects.select_related("instrument"),
            QueryDict(query, mutable=True))
        return qs.count(), active

    def test_every_filter_narrows_the_queryset(self):
        total = 5
        self.assertEqual(self._count("")[0], total)
        for query, expected in (
                ("q=EUR", 3),
                ("rule=r_live", 2),
                ("stage=research", 1),
                ("stage=unregistered", 2),
                ("asset_class=crypto", 2),
                ("direction=bearish", 2),
                ("signal_type=technical", 1),
                ("urgency=critical", 1),
                ("score_min=0.7", 2),
                ("age_hours=48", 4),
                ("state=active", 3),
                ("state=closed", 2),
                ("state=graded", 1),
                ("state=ungraded", 1),
                ("acted=yes", 1),
                ("acted=no", 4),
                ("active=1", 3),
        ):
            with self.subTest(query=query):
                n, active = self._count(query)
                self.assertEqual(n, expected, query)
                self.assertTrue(active, f"{query} left no chip")
                # NARROWS, strictly. `assertLess(n, total + 1)` was here and
                # asserted nothing at all — every count on this fixture
                # satisfies it, including a filter that silently did no work.
                self.assertLess(n, total, f"{query} narrowed nothing")

    def test_two_filters_combine_as_and_not_or(self):
        """`bullish` alone is 3 and `crypto` alone is 2; ANDed they are 0.
        ORed they would be 5 — the whole table — which is the bug this pins."""
        self.assertEqual(self._count("direction=bullish")[0], 3)
        self.assertEqual(self._count("asset_class=crypto")[0], 2)
        self.assertEqual(self._count("direction=bullish&asset_class=crypto")[0], 0)
        self.assertEqual(
            self._count("direction=bearish&asset_class=crypto")[0], 2)

    def test_an_unknown_filter_value_is_ignored_rather_than_raising(self):
        """A value arrives from a typed URL or a bookmark that outlived a
        vocabulary change. Applying `direction=sideways` would empty the page
        and blame the platform; raising would lose the page entirely."""
        for query in ("direction=sideways", "urgency=screaming",
                      "signal_type=vibes", "state=quantum", "acted=maybe",
                      "stage=banana", "score_min=abc", "age_hours=soon",
                      "asset_class=unobtainium"):
            with self.subTest(query=query):
                n, active = self._count(query)
                self.assertEqual(n, 5, query)
                self.assertEqual(active, {}, query)


class PageTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_superuser("sig_page", "a@b.c", "x")
        self.client.force_login(self.user)
        self.fx = _instrument("EURUSD", "forex")
        _control("r_research", stage="research")
        for i in range(3):
            _signal(self.fx, "r_research", score=0.5 + i * 0.1)
        _signal(self.fx, "r_research", is_active=False, outcome="hit_target",
                realized_r=1.0)

    def test_the_n_of_m_header_is_right(self):
        body = self.client.get("/signals/").content.decode()
        self.assertIn("4 of 4 signals", body)
        narrowed = self.client.get("/signals/?state=graded").content.decode()
        self.assertIn("1 of 4 signals", narrowed)
        # A filter that matches nothing is visibly a FILTER, not an empty
        # platform — and it names the way out.
        none = self.client.get("/signals/?q=ZZZZ").content.decode()
        self.assertIn("0 of 4 signals", none)
        self.assertIn("NO SIGNAL MATCHES THESE FILTERS", none)

    def test_every_pre_existing_aggregate_still_renders(self):
        """This stage ADDS. Every aggregate the page had on 2026-09-11 has to
        survive it."""
        body = self.client.get("/signals/").content.decode()
        for marker in ("Score distribution", "Direction mix", "By asset class",
                       "Urgency mix", "Win rate by type", "ACTIVE SIGNALS",
                       "BULLISH", "BEARISH", "AVG SCORE", "HIGH URGENCY",
                       "TYPES TRACKED"):
            self.assertIn(marker, body, marker)

    def test_a_filter_chip_carries_the_querystring_that_removes_it(self):
        body = self.client.get("/signals/?direction=bullish&urgency=medium"
                               ).content.decode()
        self.assertIn("urgency=medium", body)
        self.assertIn("clear all", body.lower())


class CommandTests(TestCase):

    def setUp(self):
        self.fx = _instrument("EURUSD", "forex")
        _control("r_research", stage="research")
        self.sig = _signal(self.fx, "r_research", score=0.9)

    def _run(self, *args):
        out = StringIO()
        call_command("signals", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_list_prints_the_badge_and_the_n_of_m(self):
        out = self._run("list")
        self.assertIn("1 of 1 signals", out)
        self.assertIn("WATCHED", out)
        self.assertIn("r_research", out)
        self.assertIn("0 of 1 signals",
                      self._run("list", "--stage", "live_full"))

    def test_show_prints_all_six_blocks(self):
        out = self._run("show", str(self.sig.pk))
        for block in ("(a) CAN ANYTHING ACT ON IT?",
                      "(b) WHAT IS THIS RULE WORTH?",
                      "(c) WHY DID IT FIRE?",
                      "(d) WHAT WOULD IT COST?",
                      "(e) DID ANYONE ACT?",
                      "(f) ITS OWN GRADE"):
            self.assertIn(block, out)
        self.assertIn("WATCHED", out)
        self.assertIn("unmeasured", out)
        self.assertIn("NOT on a foreign key", out)

    def test_show_prices_the_levels_only_when_a_config_is_named(self):
        """(d) in the shell twin. Without --config the command REFUSES, in
        the same words the page uses when the viewer has no pool; with it,
        the verdict is `passes_cost_filter`'s, so the page and the command
        cannot disagree about whether a signal clears its costs."""
        from bot_program.models import AssetBotConfig

        user = User.objects.create_user("sig_cmd_cost", password="x")
        AssetBotConfig.objects.create(
            user=user, asset_class="forex", name="fx pool", mode="paper",
            enabled=True, symbols=["EURUSD"], capital=Decimal("1000"))

        bare = self._run("show", str(self.sig.pk))
        self.assertIn("no config context", bare)
        self.assertIn("--config", bare)

        priced = self._run("show", str(self.sig.pk), "--config", "fx pool")
        self.assertIn("CLEARS ITS COSTS", priced)
        self.assertIn("fx pool", priced)
        self.assertNotIn("no config context", priced)

    def test_an_unknown_config_name_is_refused_not_guessed(self):
        """Picking "the first enabled pool" for an operator who runs several
        would price the trade against a book that would never take it."""
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._run("show", str(self.sig.pk), "--config", "no such pool")


class CostBlockTests(TestCase):
    """(d) WHAT WOULD IT COST — the entry gate's own verdict, or a refusal.

    The round trip is NOT a property of a signal: it is a property of the
    pool that would take it, which is where `cost_bps`, `min_edge_ratio` and
    `min_net_rr` live. So this block either answers with
    `passes_cost_filter` — the gate `asset_engine/base.py`, `options_bot.py`
    and `manual_trade.validate_levels` all already call — or it says it
    cannot. What it must never do is compute a second round trip of its own:
    a page that told the operator a signal clears its costs while the entry
    path refused it for not clearing them would be the one that was wrong.
    """

    def setUp(self):
        self.user = User.objects.create_user("sig_cost", password="x")
        self.fx = _instrument("EURUSD", "forex")
        self.btc = _instrument("BTCUSD", "crypto")

    def _cfg(self, klass="forex", **kw):
        from bot_program.models import AssetBotConfig
        fields = dict(user=self.user, asset_class=klass, name=f"{klass} pool",
                      mode="paper", enabled=True, symbols=["EURUSD"],
                      capital=Decimal("1000"))
        fields.update(kw)
        return AssetBotConfig.objects.create(**fields)

    def test_with_no_context_it_refuses_instead_of_inventing_a_number(self):
        from dashboard.signal_surface import (COST_NO_CONTEXT, configs_for,
                                              cost_block)
        s = _signal(self.fx, "r_cost")
        block = cost_block(s, configs_for(self.user))   # no config at all
        self.assertFalse(block["answerable"])
        self.assertIsNone(block["ok"])
        self.assertEqual(block["reason"], COST_NO_CONTEXT)

        # A pool of ANOTHER asset class is not a context for this signal: its
        # cost table prices crypto, and this is a forex trade.
        self._cfg("crypto", symbols=["BTCUSD"])
        self.assertEqual(cost_block(s, configs_for(self.user))["reason"],
                         COST_NO_CONTEXT)

        # Nor is a DISABLED pool — it would not take the trade, so its cost
        # table is not the one that would be paid.
        self._cfg("forex", enabled=False)
        self.assertEqual(cost_block(s, configs_for(self.user))["reason"],
                         COST_NO_CONTEXT)

    def test_the_verdict_is_passes_cost_filter_itself_not_a_paraphrase(self):
        from bot_program.asset_engine.risk_levels import passes_cost_filter

        from dashboard.signal_surface import cost_block

        cfg = self._cfg()
        s = _signal(self.fx, "r_cost")
        block = cost_block(s, [cfg])
        ok, reason = passes_cost_filter(cfg, "EURUSD", 1.0, 1.2, stop=0.9)

        self.assertTrue(block["answerable"])
        self.assertEqual(block["ok"], ok)
        # The GATE'S OWN SENTENCE, verbatim. If this block ever paraphrased
        # it, the page could drift from the gate one release at a time.
        self.assertEqual(block["reason"], reason)
        self.assertIn("forex pool", block["config"])
        self.assertTrue(block["trades_symbol"])
        self.assertEqual(block["verdict"], "clears its costs")

    def test_levels_that_do_not_clear_their_costs_say_so(self):
        """A 0.5 gross reward:risk is not a marginal trade, it is one run for
        the broker: the winner pays the round trip out of a 5% target and the
        loser pays it on top of a 10% stop."""
        from dashboard.signal_surface import cost_block
        cfg = self._cfg()
        s = _signal(self.fx, "r_cost", suggested_entry=Decimal("1"),
                    suggested_stop=Decimal("0.9"),
                    suggested_target=Decimal("1.05"))
        block = cost_block(s, [cfg])
        self.assertTrue(block["answerable"])
        self.assertFalse(block["ok"])
        self.assertIn("does NOT clear", block["verdict"])
        self.assertIn("reward:risk falls to", block["reason"])
        self.assertIsNotNone(block["cost_pct"])

    def test_an_unpriced_signal_is_not_reported_as_a_missing_config(self):
        """Two different silences. A signal with no target is UNPRICED — that
        is a fact about the signal, and blaming the reader's missing config
        for it would send them to configure a pool that would not help."""
        from dashboard.signal_surface import COST_NO_LEVELS, cost_block
        cfg = self._cfg()
        s = _signal(self.fx, "r_cost", suggested_entry=None,
                    suggested_target=None, suggested_stop=None)
        block = cost_block(s, [cfg])
        self.assertFalse(block["answerable"])
        self.assertEqual(block["reason"], COST_NO_LEVELS)

    def test_a_pool_that_does_not_list_the_symbol_carries_the_caveat(self):
        from dashboard.signal_surface import COST_SYMBOL_CAVEAT, cost_block
        cfg = self._cfg(symbols=["GBPUSD"])
        s = _signal(self.fx, "r_cost")
        block = cost_block(s, [cfg])
        self.assertTrue(block["answerable"])
        self.assertFalse(block["trades_symbol"])
        self.assertIn("would not itself take", COST_SYMBOL_CAVEAT)

    def test_the_page_prices_the_levels_for_a_viewer_who_runs_a_pool(self):
        su = User.objects.create_superuser("sig_cost_su", "a@b.c", "x")
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.create(
            user=su, asset_class="forex", name="fx pool", mode="paper",
            enabled=True, symbols=["EURUSD"], capital=Decimal("1000"))
        _control("r_cost", stage="research")
        _signal(self.fx, "r_cost")

        self.client.force_login(su)
        body = self.client.get("/signals/").content.decode()
        self.assertIn("clears its costs", body)
        self.assertIn("fx pool", body)
        self.assertNotIn("no config context", body)

        # And a viewer with NO pool gets the refusal on the same row, not a
        # number borrowed from somebody else's book.
        other = User.objects.create_superuser("sig_cost_su2", "b@b.c", "x")
        self.client.force_login(other)
        bare = self.client.get("/signals/").content.decode()
        self.assertIn("no config context", bare)


# ══ Adversarial review, 2026-09-12 ═════════════════════════════════════════
#
# The badge answers the page's single most load-bearing question — CAN
# ANYTHING ACT ON IT — and it was answering it with a lane the entry path does
# not read.


class PauseIsNotAVenueGateTests(TestCase):
    """A PAUSED badge must not claim protection the gate does not give.

    `is_rule_active` is consulted in exactly two places on this platform: the
    rule engine's signal WRITE path (`signals/tasks.py:47`) and the fast-rule
    runner (`signals/fast_rules.py:164`). It is not consulted by
    `scan_all_setups`, not by `stage_policy`, and — the one that matters
    here — not by the bot ENTRY path, which reads `stage_policy` alone
    (`bot_program/asset_engine/base.py:2268`, `options_bot.py:400`).
    `dashboard/views.py:866` already spells that asymmetry out for
    /strategies/.

    So a pause stops NEW signals from a rule-engine rule. It does not stop the
    opportunity scanner publishing, and it does not stop a bot acting on a
    signal that already exists. The badge used to answer `may_trade: False`
    for every paused rule whatever its stage — telling an operator that
    nothing could act on a live_full signal a bot was about to trade at full
    size on a real venue.
    """

    def setUp(self):
        self.inst = _instrument("EURUSD")

    def test_a_paused_live_rule_still_reports_the_gates_own_answer(self):
        from dashboard.signal_surface import stage_badge
        from signals.rule_actuator import stage_policy

        _control("r_paused_live", stage="live_full", status="paused")
        badge = stage_badge("r_paused_live")
        policy = stage_policy("r_paused_live")
        # The label is still PAUSED — the pause is real and an operator needs
        # to see it — but may_trade is the ENTRY PATH's answer, not the
        # admin lane's.
        self.assertEqual(badge["label"], "PAUSED")
        self.assertTrue(policy["may_trade"])
        self.assertEqual(badge["may_trade"], policy["may_trade"])
        self.assertIn("does not stop a bot", badge["reason"])
        self.assertIn("live_full", badge["reason"])

    def test_a_paused_live_rule_is_toned_like_the_live_row_it_is(self):
        from dashboard.signal_surface import stage_badge

        _control("r_tone_live", stage="live_full")
        _control("r_tone_paused", stage="live_full", status="paused")
        self.assertEqual(stage_badge("r_tone_paused")["tone"],
                         stage_badge("r_tone_live")["tone"])

    def test_a_paused_research_rule_is_still_shut_by_its_stage(self):
        """The other half: where the STAGE also refuses, the badge says so,
        and may_trade stays False because the gate says False."""
        from dashboard.signal_surface import stage_badge

        _control("r_paused_research", stage="research", status="paused")
        badge = stage_badge("r_paused_research")
        self.assertEqual(badge["label"], "PAUSED")
        self.assertFalse(badge["may_trade"])
        self.assertIn("permits no order either", badge["reason"])

    def test_the_page_warns_on_a_paused_live_signal(self):
        user = User.objects.create_superuser("sig_pause_su", "a@b.c", "x")
        self.client.force_login(user)
        _control("r_page_paused", stage="live_full", status="paused")
        _signal(self.inst, "r_page_paused")
        body = self.client.get("/signals/").content.decode()
        self.assertIn("PAUSED", body)
        self.assertIn("does not stop a bot", body)


class PaginationTests(TestCase):
    """The list is never unbounded: 50 a page, and the header counts the
    whole filtered set rather than the page."""

    def setUp(self):
        self.user = User.objects.create_superuser("sig_page2", "a@b.c", "x")
        self.client.force_login(self.user)
        self.inst = _instrument("EURUSD")
        _control("r_many", stage="research")
        from signals.models import Signal
        rows = []
        for i in range(55):
            rows.append(Signal(instrument=self.inst, signal_type="composite",
                               direction="bullish", urgency="medium",
                               title=f"s{i}", description="d",
                               rule_name="r_many", score=0.5,
                               price_at_signal=Decimal("1"), is_active=True))
        Signal.objects.bulk_create(rows)

    def test_a_page_holds_fifty_rows_and_the_header_counts_all_of_them(self):
        body = self.client.get("/signals/").content.decode()
        self.assertIn("55 of 55 signals", body)
        self.assertIn("page 1 of 2", body)
        self.assertEqual(body.count("six answers"), 50)
        second = self.client.get("/signals/?page=2").content.decode()
        self.assertIn("page 2 of 2", second)
        self.assertEqual(second.count("six answers"), 5)
