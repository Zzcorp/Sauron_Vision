"""Where a rule may fire, how often, and how loudly (2026-10-04).

The weekly review of 2026-10-02 read 151 signals in a week, 58 resolved,
13 hit (22%), and the RSI bullish divergence hitting 17% while labelling
every one of its signals HIGH, many on commodities and mining stocks. It
asked for signal cooldowns and for that detector paused on commodities
and miners.

Pinned: the code-default scope (the RSI divergence off the commodity
class and the miners), the miners' membership (Barrick, Newmont, the
bullion trust; never Goldman Sachs), the row's `scope` overriding the
default and an explicit empty list lifting it, the per-(rule, symbol)
cooldown anchored on the last signal's close, the record capping the
urgency word past the sample floor and saying so on the signal, the RSI
score reading the setup instead of a constant 0.7, the `rule_scope`
command, and the TAKE TRADE ticket naming the venue that had no price
instead of blaming the quote feeds.

Run with:  python manage.py test tests.test_signal_scope
"""
import io
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

RSI = "rsi_bull_divergence"


def _instrument(symbol, asset_class="stock", name="", sector=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": name or symbol,
                                 "asset_class": asset_class,
                                 "sector": sector, "is_active": True})
    return inst


def _payload(symbol, rule=RSI, score=0.7, **extra):
    return {"symbol": symbol, "rule": rule, "direction": "LONG",
            "score": score, "headline": f"{symbol} LONG", "thesis": "t",
            "entry": 100.0, "stop": 98.5, "target": 103.0, **extra}


def _create(payloads, records=None):
    from signals.tasks import _create_signals_and_notify
    with patch("signals.announce.announce_new_signal"), \
            patch("signals.rule_scope.rule_records",
                  return_value=records or {}):
        return _create_signals_and_notify(payloads)


def _close(signal, *, hours_ago, outcome="stopped_out", stamp=True):
    """Close a signal `hours_ago` hours back — with a close stamp, or as
    a row deactivated without one (then its birth is moved instead)."""
    from signals.models import Signal
    when = timezone.now() - timedelta(hours=hours_ago)
    fields = {"is_active": False, "outcome": outcome}
    if stamp:
        fields["expired_at"] = when
    else:
        fields["created_at"] = when
    Signal.objects.filter(pk=signal.pk).update(**fields)


class TheConstantsTests(SimpleTestCase):

    def test_the_cooldown_and_the_record_floors(self):
        from signals import rule_scope as rs
        self.assertEqual(rs.SIGNAL_COOLDOWN_HOURS, 24.0)
        self.assertEqual(rs.RECORD_MIN_RESOLVED, 20)
        self.assertEqual((rs.RECORD_LOW_HIT_RATE, rs.RECORD_MEDIUM_HIT_RATE),
                         (0.35, 0.50))
        self.assertEqual(rs.URGENCY_ORDER, ("low", "medium", "high", "critical"))

    def test_the_default_scope_is_the_review_s_ask(self):
        from signals.rule_scope import DEFAULT_RULE_SCOPE, GROUPS
        self.assertEqual(DEFAULT_RULE_SCOPE, {
            RSI: {"exclude": {"asset_classes": ["commodity"],
                              "groups": ["miners"]}}})
        self.assertEqual(GROUPS, ("miners",))

    def test_the_rsi_score_constants(self):
        from signals.rules import technical_rules as t
        self.assertEqual((t.RSI_THRESHOLD, t.RSI_DEEP), (35.0, 20.0))
        self.assertEqual((t.RSI_SCORE_FLOOR, t.RSI_SCORE_CEILING), (0.55, 0.70))


class TheMinersTests(SimpleTestCase):

    @staticmethod
    def _inst(symbol, name="", sector="", asset_class="stock"):
        return SimpleNamespace(symbol=symbol, name=name or symbol,
                               sector=sector, asset_class=asset_class)

    def test_the_catalogue_s_miners_and_metal_proxies(self):
        from signals.rule_scope import is_miner
        for symbol, name in (("GOLD", "Barrick Gold"), ("NEM", "Newmont Corp"),
                             ("RIO", "Rio Tinto"), ("BHP", "BHP Group"),
                             ("GLD", "SPDR Gold Shares")):
            self.assertTrue(is_miner(self._inst(symbol, name)), symbol)

    def test_goldman_sachs_is_not_a_miner(self):
        from signals.rule_scope import is_miner
        self.assertFalse(is_miner(self._inst("GS", "Goldman Sachs")))
        self.assertFalse(is_miner(self._inst("AAPL", "Apple")))
        self.assertFalse(is_miner(self._inst("XOM", "Exxon Mobil")))

    def test_a_sector_or_a_word_in_the_name_counts(self):
        from signals.rule_scope import is_miner
        self.assertTrue(is_miner(self._inst("XYZ", "Xyz Corp",
                                            sector="Basic Materials")))
        self.assertTrue(is_miner(self._inst("FCX", "Freeport-McMoRan Copper")))
        self.assertTrue(is_miner(self._inst("MP", "MP Materials")))
        self.assertTrue(is_miner(self._inst("CCJ", "Cameco uranium miner")))
        self.assertFalse(is_miner(self._inst("GLDMN", "Goldmine Software")))


class TheScopeTests(TestCase):

    def setUp(self):
        self.gold_metal = _instrument("XAUUSD", "commodity", "Gold Spot")
        self.barrick = _instrument("GOLD", "stock", "Barrick Gold")
        self.apple = _instrument("AAPL", "stock", "Apple")
        self.eurusd = _instrument("EURUSD", "forex", "EUR/USD")

    def test_the_default_keeps_the_rsi_divergence_off_commodities_and_miners(self):
        from signals.rule_scope import exclusion_reason
        self.assertIn("off commodity", exclusion_reason(RSI, self.gold_metal))
        self.assertIn("off the miners", exclusion_reason(RSI, self.barrick))
        self.assertIn("default scope", exclusion_reason(RSI, self.barrick))
        self.assertEqual(exclusion_reason(RSI, self.apple), "")
        self.assertEqual(exclusion_reason(RSI, self.eurusd), "")

    def test_a_rule_with_no_default_fires_everywhere(self):
        from signals.rule_scope import effective_scope, exclusion_reason
        self.assertEqual(exclusion_reason("golden_cross", self.gold_metal), "")
        self.assertEqual(effective_scope("golden_cross")["source"], "none")

    def test_the_row_overrides_the_default_and_an_empty_list_lifts_it(self):
        from signals.models_control import RuleControl
        from signals.rule_scope import effective_scope, exclusion_reason
        ctrl = RuleControl.objects.create(rule_name=RSI)
        self.assertEqual(ctrl.scope, {})
        self.assertEqual(effective_scope(RSI)["source"], "default")
        self.assertIn("off commodity", exclusion_reason(RSI, self.gold_metal))
        # A row that names only a cooldown keeps the default exclusions.
        ctrl.scope = {"cooldown_hours": 6}
        ctrl.save()
        self.assertEqual(effective_scope(RSI)["source"], "default")
        self.assertEqual(effective_scope(RSI)["cooldown_hours"], 6.0)
        self.assertIn("off commodity", exclusion_reason(RSI, self.gold_metal))
        # An explicit empty `exclude` lifts them.
        ctrl.scope = {"exclude": {}}
        ctrl.save()
        self.assertEqual(effective_scope(RSI)["source"], "row")
        self.assertEqual(exclusion_reason(RSI, self.gold_metal), "")
        ctrl.scope = {"exclude": {"asset_classes": [], "groups": []}}
        ctrl.save()
        self.assertEqual(effective_scope(RSI)["source"], "row")
        self.assertEqual(exclusion_reason(RSI, self.gold_metal), "")
        self.assertEqual(exclusion_reason(RSI, self.barrick), "")
        # The row decides entirely: naming one symbol lifts the class.
        ctrl.scope = {"exclude": {"symbols": ["aapl"]}}
        ctrl.save()
        self.assertIn("off AAPL", exclusion_reason(RSI, self.apple))
        self.assertIn("the row", exclusion_reason(RSI, self.apple))
        self.assertEqual(exclusion_reason(RSI, self.gold_metal), "")

    def test_a_sector_exclusion(self):
        from signals.models_control import RuleControl
        from signals.rule_scope import exclusion_reason
        inst = _instrument("MINER1", "stock", "Some Co", sector="Metals & Mining")
        RuleControl.objects.create(
            rule_name="golden_cross",
            scope={"exclude": {"sectors": ["Metals & Mining"]}})
        self.assertIn("off the metals & mining sector",
                      exclusion_reason("golden_cross", inst))
        self.assertEqual(exclusion_reason("golden_cross", self.apple), "")

    def test_the_cooldown_hours(self):
        from signals.models_control import RuleControl
        from signals.rule_scope import cooldown_hours
        self.assertEqual(cooldown_hours("golden_cross"), 24.0)
        ctrl = RuleControl.objects.create(rule_name="golden_cross",
                                          scope={"cooldown_hours": 6})
        self.assertEqual(cooldown_hours("golden_cross"), 6.0)
        for bad in (-1, "12", True, None):
            ctrl.scope = {"cooldown_hours": bad}
            ctrl.save()
            self.assertEqual(cooldown_hours("golden_cross"), 24.0, repr(bad))
        ctrl.scope = {"cooldown_hours": 0}
        ctrl.save()
        self.assertEqual(cooldown_hours("golden_cross"), 0.0)


class TheEngineTests(TestCase):

    def setUp(self):
        self.gold_metal = _instrument("XAUUSD", "commodity", "Gold Spot")
        self.apple = _instrument("AAPL", "stock", "Apple")

    def test_an_excluded_signal_is_not_stored(self):
        from signals.models import Signal
        self.assertEqual(_create([_payload("XAUUSD")]), 0)
        self.assertEqual(Signal.objects.filter(rule_name=RSI).count(), 0)
        self.assertEqual(_create([_payload("AAPL")]), 1)
        self.assertEqual(Signal.objects.filter(rule_name=RSI).count(), 1)

    def test_the_default_scope_lifted_by_the_row_lets_it_through(self):
        from signals.models_control import RuleControl
        RuleControl.objects.create(
            rule_name=RSI, scope={"exclude": {"asset_classes": [], "groups": []}})
        self.assertEqual(_create([_payload("XAUUSD")]), 1)

    def test_the_active_dedupe_still_holds(self):
        self.assertEqual(_create([_payload("AAPL", rule="r")]), 1)
        self.assertEqual(_create([_payload("AAPL", rule="r")]), 0)

    def test_no_second_signal_within_the_cooldown_of_the_last_close(self):
        from signals.models import Signal
        self.assertEqual(_create([_payload("AAPL", rule="r")]), 1)
        first = Signal.objects.get(rule_name="r")
        _close(first, hours_ago=2)
        self.assertEqual(_create([_payload("AAPL", rule="r")]), 0,
                         "re-fired two hours after the close")
        _close(first, hours_ago=25)
        self.assertEqual(_create([_payload("AAPL", rule="r")]), 1,
                         "blocked past the cooldown")
        self.assertEqual(Signal.objects.filter(rule_name="r").count(), 2)

    def test_a_row_deactivated_without_a_close_stamp_counts_from_its_birth(self):
        from signals.models import Signal
        _create([_payload("AAPL", rule="r")])
        first = Signal.objects.get(rule_name="r")
        _close(first, hours_ago=2, stamp=False)
        self.assertEqual(_create([_payload("AAPL", rule="r")]), 0)
        _close(first, hours_ago=30, stamp=False)
        self.assertEqual(_create([_payload("AAPL", rule="r")]), 1)

    def test_the_cooldown_is_per_rule_and_per_symbol(self):
        from signals.models import Signal
        _instrument("MSFT", "stock", "Microsoft")
        _create([_payload("AAPL", rule="r")])
        _close(Signal.objects.get(rule_name="r"), hours_ago=1)
        # another symbol, and another rule on the same symbol: free
        self.assertEqual(_create([_payload("MSFT", rule="r"),
                                  _payload("AAPL", rule="s")]), 2)

    def test_a_rule_may_switch_its_cooldown_off(self):
        from signals.models import Signal
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="r", scope={"cooldown_hours": 0})
        _create([_payload("AAPL", rule="r")])
        _close(Signal.objects.get(rule_name="r"), hours_ago=0.1)
        self.assertEqual(_create([_payload("AAPL", rule="r")]), 1)

    def test_the_cooldown_reason_names_the_last_signal(self):
        from signals.models import Signal
        from signals.rule_scope import cooldown_reason
        _create([_payload("AAPL", rule="r")])
        _close(Signal.objects.get(rule_name="r"), hours_ago=3)
        why = cooldown_reason("r", self.apple, hours=24)
        self.assertIn("closed stopped_out 3.0h ago", why)
        self.assertIn("cooldown 24h", why)
        self.assertEqual(cooldown_reason("r", self.apple, hours=0), "")
        self.assertEqual(cooldown_reason("never", self.apple, hours=24), "")

    def test_a_poor_record_caps_the_urgency_and_the_signal_says_so(self):
        from signals.models import Signal
        n = _create([_payload("AAPL", rule="r", score=0.7)],
                    records={"r": {"n": 58, "hit_rate": 13 / 58}})
        self.assertEqual(n, 1)
        sig = Signal.objects.get(rule_name="r")
        self.assertEqual(sig.urgency, "low")
        self.assertEqual(sig.sub_scores["urgency_uncapped"], "high")
        self.assertEqual(sig.sub_scores["rule_graded"], 58)
        self.assertEqual(sig.sub_scores["rule_hit_rate"], 0.224)
        self.assertIn("Rule record: 13 of 58 graded signals hit (22%), "
                      "all time — urgency capped at low.", sig.description)

    def test_a_middling_record_caps_at_medium_and_a_good_one_not_at_all(self):
        from signals.models import Signal
        _instrument("MSFT", "stock", "Microsoft")
        _create([_payload("AAPL", rule="r", score=0.9)],
                records={"r": {"n": 30, "hit_rate": 0.45}})
        self.assertEqual(Signal.objects.get(rule_name="r").urgency, "medium")
        _create([_payload("MSFT", rule="s", score=0.9)],
                records={"s": {"n": 30, "hit_rate": 0.6}})
        sig = Signal.objects.get(rule_name="s")
        self.assertEqual(sig.urgency, "critical")
        self.assertNotIn("urgency_uncapped", sig.sub_scores)
        self.assertNotIn("Rule record", sig.description)
        self.assertEqual(sig.sub_scores["rule_graded"], 30)

    def test_under_the_floor_the_record_is_not_a_number(self):
        from signals.models import Signal
        _create([_payload("AAPL", rule="r", score=0.7)],
                records={"r": {"n": 19, "hit_rate": 0.1}})
        sig = Signal.objects.get(rule_name="r")
        self.assertEqual(sig.urgency, "high")
        self.assertNotIn("urgency_uncapped", sig.sub_scores)

    def test_an_explicit_urgency_is_capped_too(self):
        from signals.models import Signal
        _create([_payload("AAPL", rule="r", score=0.9, urgency="critical")],
                records={"r": {"n": 40, "hit_rate": 0.2}})
        sig = Signal.objects.get(rule_name="r")
        self.assertEqual(sig.urgency, "low")
        self.assertEqual(sig.sub_scores["urgency_uncapped"], "critical")

    def test_the_records_come_off_the_evidence_ledger(self):
        from signals.rule_scope import rule_records
        rows = [{"rule": "r", "sig_n": 58, "sig_hit": 13 / 58},
                {"rule": "", "sig_n": 3}, {"rule": "s", "sig_n": 0}]
        with patch("bot_program.evidence.rule_rows", return_value=rows):
            recs = rule_records()
        self.assertEqual(recs["r"], {"n": 58, "hit_rate": 13 / 58})
        self.assertEqual(recs["s"], {"n": 0, "hit_rate": None})
        self.assertNotIn("", recs)
        with patch("bot_program.evidence.rule_rows",
                   side_effect=RuntimeError("down")):
            self.assertEqual(rule_records(), {})

    def test_the_cap_and_the_words(self):
        from signals.rule_scope import capped, record_sentence, urgency_cap
        self.assertEqual(urgency_cap({"n": 58, "hit_rate": 0.17}), "low")
        self.assertEqual(urgency_cap({"n": 58, "hit_rate": 0.45}), "medium")
        self.assertEqual(urgency_cap({"n": 58, "hit_rate": 0.5}), "")
        self.assertEqual(urgency_cap({"n": 19, "hit_rate": 0.0}), "")
        self.assertEqual(urgency_cap({"n": 58, "hit_rate": None}), "")
        self.assertEqual(urgency_cap({}), "")
        self.assertEqual(capped("high", "low"), "low")
        self.assertEqual(capped("low", "medium"), "low")
        self.assertEqual(capped("medium", ""), "medium")
        self.assertEqual(capped("odd", "low"), "odd")
        self.assertEqual(record_sentence({"n": 58, "hit_rate": 13 / 58}, "low"),
                         "Rule record: 13 of 58 graded signals hit (22%), "
                         "all time — urgency capped at low.")


class TheRsiScoreTests(SimpleTestCase):

    def test_the_score_reads_the_depth_of_the_reading(self):
        from signals.rule_adapter import _urgency_for
        from signals.rules.technical_rules import rsi_divergence_score
        self.assertEqual(rsi_divergence_score(35), 0.55)
        self.assertEqual(rsi_divergence_score(27.5), 0.625)
        self.assertEqual(rsi_divergence_score(20), 0.70)
        self.assertEqual(rsi_divergence_score(5), 0.70)
        self.assertAlmostEqual(rsi_divergence_score(34.9), 0.551, places=3)
        # A shallow divergence is medium; only a deep one reads high.
        self.assertEqual(_urgency_for(rsi_divergence_score(34)), "medium")
        self.assertEqual(_urgency_for(rsi_divergence_score(30)), "medium")
        self.assertEqual(_urgency_for(rsi_divergence_score(20)), "high")

    def test_the_rule_no_longer_scores_a_constant(self):
        import inspect
        from signals.rules.technical_rules import RSIDivergenceRule
        src = inspect.getsource(RSIDivergenceRule)
        self.assertNotIn('"score": 0.7', src)
        self.assertIn("rsi_divergence_score(last_rsi)", src)
        self.assertIn('"sub_scores": {"rsi"', src)


class TheRowTests(TestCase):

    def test_the_field_and_its_migration(self):
        from pathlib import Path
        from signals.models_control import RuleControl
        self.assertEqual(RuleControl(rule_name="x").scope, {})
        path = Path("signals/migrations/0019_rulecontrol_scope.py")
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("('signals', '0018_ruleaction_source_brain_report')", text)
        self.assertIn("name='scope'", text)


class TheCommandTests(TestCase):

    def setUp(self):
        self.gold_metal = _instrument("XAUUSD", "commodity", "Gold Spot")

    def _run(self, *args):
        out = io.StringIO()
        call_command("rule_scope", *args, stdout=out)
        return out.getvalue()

    def test_list_reads_the_defaults(self):
        text = self._run()
        self.assertIn(RSI, text)
        self.assertIn("off classes commodity", text)
        self.assertIn("off groups miners", text)
        self.assertIn("cooldown 24h", text)
        self.assertIn("code default", text)

    def test_set_creates_the_row_at_the_paper_stage(self):
        from signals.models_control import RuleControl
        text = self._run("set", RSI, "--cooldown", "12")
        ctrl = RuleControl.objects.get(rule_name=RSI)
        self.assertEqual(ctrl.promotion_stage, RuleControl.STAGE_PAPER)
        self.assertEqual(ctrl.scope, {"cooldown_hours": 12.0})
        self.assertIn("created", text)
        self.assertIn("cooldown 12h", text)
        # the exclusions still come from the default: the row names none
        from signals.rule_scope import cooldown_hours, exclusion_reason
        self.assertEqual(cooldown_hours(RSI), 12.0)
        self.assertIn("off commodity", exclusion_reason(RSI, self.gold_metal))

    def test_lift_then_clear(self):
        from signals.models_control import RuleControl
        from signals.rule_scope import exclusion_reason
        self._run("set", RSI, "--lift")
        self.assertEqual(RuleControl.objects.get(rule_name=RSI).scope["exclude"],
                         {"asset_classes": [], "sectors": [], "symbols": [],
                          "groups": []})
        self.assertEqual(exclusion_reason(RSI, self.gold_metal), "")
        self._run("clear", RSI)
        self.assertEqual(RuleControl.objects.get(rule_name=RSI).scope, {})
        self.assertIn("off commodity", exclusion_reason(RSI, self.gold_metal))

    def test_set_writes_the_lists_it_is_given(self):
        from signals.models_control import RuleControl
        self._run("set", "golden_cross", "--exclude-symbol", "tsla",
                  "--exclude-symbol", "NIO", "--exclude-class", "Crypto")
        scope = RuleControl.objects.get(rule_name="golden_cross").scope
        self.assertEqual(scope["exclude"],
                         {"asset_classes": ["crypto"], "sectors": [],
                          "symbols": ["NIO", "TSLA"], "groups": []})
        text = self._run("show", "golden_cross")
        self.assertIn("off symbols nio, tsla", text)
        self.assertIn("the row", text)

    def test_refusals(self):
        with self.assertRaises(CommandError):
            self._run("set", RSI, "--exclude-group", "banks")
        with self.assertRaises(CommandError):
            self._run("set", RSI)
        with self.assertRaises(CommandError):
            self._run("set")
        with self.assertRaises(CommandError):
            self._run("set", RSI, "--cooldown", "-1")

    def test_the_ops_entry(self):
        from core import ops_commands
        e = ops_commands.get("rule_scope")
        self.assertEqual(e["category"], "decide")
        self.assertFalse(e["read_only"])
        self.assertNotIn("rule_scope", ops_commands.runnable_names())


class TheTicketTests(TestCase):
    """The TAKE TRADE ticket names who had no price (2026-10-04)."""

    def test_the_detail_carries_the_venue_s_words(self):
        from bot_program.manual_trade import _mark_for, _mark_for_detail

        class Raising:
            def ticker(self, symbol):
                raise LookupError("eToro knows no instrument spelled 'ADAUSD'")

        class Mute:
            def ticker(self, symbol):
                return {"lastPrice": "0", "symbol": symbol}

        class Priced:
            def ticker(self, symbol):
                return {"lastPrice": "1.25", "symbol": symbol}

        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=Raising()):
            # the fifth element is the raw tick (2026-10-05, the quote
            # advisory): {} when the venue raised
            price, client, delayed, why, tick = _mark_for_detail(
                None, None, "ADAUSD")
            self.assertIsNone(price)
            self.assertEqual(tick, {})
            self.assertEqual(why, "eToro knows no instrument spelled 'ADAUSD'")
            self.assertEqual(len(_mark_for(None, None, "ADAUSD")), 3)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=Mute()):
            self.assertEqual(_mark_for_detail(None, None, "ADAUSD")[3],
                             "answered no rate")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=Priced()):
            price, _c, _d, why, tick = _mark_for_detail(None, None, "ADAUSD")
            self.assertEqual((price, why), (1.25, ""))
            self.assertEqual(tick["lastPrice"], "1.25")

    def test_a_live_ticket_names_the_venue_and_a_paper_one_the_feeds(self):
        from bot_program.manual_trade import _no_mark_message
        client = object()
        with patch("bot_program.engine.broker_router.broker_name_for_symbol",
                   return_value="etoro"):
            msg = _no_mark_message(None, None, "ADAUSD", client,
                                   "eToro knows no instrument spelled 'ADAUSD'")
        self.assertEqual(msg, "No price mark for ADAUSD from eToro: eToro knows "
                              "no instrument spelled 'ADAUSD'. A LIVE ticket is "
                              "priced by the venue that fills it, so the "
                              "platform's own quote cannot stand in — nothing "
                              "was sent")
        self.assertNotIn("quote feeds", msg)
        with patch("bot_program.asset_engine.base.AssetBot._is_paper_client",
                   return_value=True):
            msg = _no_mark_message(None, None, "ADAUSD", client, "answered no rate")
        self.assertEqual(msg, "No usable price mark for ADAUSD — the quote "
                              "feeds have nothing fresh")

    def test_the_preview_reads_the_detail(self):
        import inspect
        from bot_program import manual_trade
        src = inspect.getsource(manual_trade._preview)
        self.assertIn("_mark_for_detail(", src)
        self.assertIn("_no_mark_message(", src)
        self.assertNotIn('"quote feeds have nothing fresh"', src)
