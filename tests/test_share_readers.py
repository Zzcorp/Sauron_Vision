"""The share allocator's three readers — measured or blind, never zero.

Each reader answers a question the allocator multiplies into a share, so
each one has to be honest about NOT knowing: an unmeasured config scores
neutral, an idle news analyst is blind, an empty universe is no density.
These tests pin the semantics that keep a missing input from shrinking a
live pool:

  * config_evidence: paper and live are never pooled; a NULL realized_r
    is excluded, never counted as a zero-R trade; below MIN_EVIDENCE_N in
    every lane is score 1.0 with the reason.
  * opportunity_density: distinct instruments over the active universe;
    the scanner's own linked Signals are not counted twice; an empty
    universe or a switched-off scanner with no signals is unmeasured.
  * news_risk_by_class: blind when the analyst is idle; the sentiment is
    stated only above min_articles; the parser's fallback rows are
    excluded; one article on two stocks is one stock article.

Run with:  python manage.py test tests.test_share_readers
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="rd_u"):
    return User.objects.create_user(name, password="x")


def _cfg(user, *, name="bot", asset_class="stock", mode="live",
         symbols=("AAPL",)):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        enabled=True, symbols=list(symbols), capital=Decimal("1000"),
        extras={"capital_tracks_broker": True})


def _fill(cfg, r, *, paper=False, rule="r1", outcome="hit_target",
          days_ago=1, asset_class=None):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class,
        symbol="AAPL", side="BUY", qty=Decimal("1"),
        entry_price=Decimal("100"), exit_price=Decimal("101"),
        status="CLOSED", pnl=Decimal("1") if r is not None else None,
        rule_name=rule, paper=paper, realized_r=r, outcome=outcome)
    # auto_now_add ignores a value passed to create()
    AssetBotTrade.objects.filter(pk=t.pk).update(
        closed_at=timezone.now() - timedelta(days=days_ago))
    return t


def _inst(symbol, asset_class="stock", active=True):
    from instruments.models import Instrument
    return Instrument.objects.create(symbol=symbol, name=symbol,
                                     asset_class=asset_class,
                                     is_active=active)


class ConfigEvidenceTests(TestCase):

    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user)

    def test_ten_live_fills_measure_the_live_lane(self):
        from bot_program.evidence import config_evidence
        for i in range(10):
            _fill(self.cfg, 1.0 if i < 6 else -1.0)
        ev = config_evidence(self.cfg)
        self.assertEqual(ev["lane"], "live")
        self.assertTrue(ev["measured"])
        self.assertEqual(ev["n"], 10)
        self.assertAlmostEqual(ev["win_rate"], 0.6)
        self.assertAlmostEqual(ev["avg_r"], 0.2)
        # 1 + (0.6-0.5)*0.6 + 0.2*0.4 = 1.14
        self.assertAlmostEqual(ev["score"], 1.14)

    def test_null_realized_r_is_excluded_never_zero(self):
        from bot_program.evidence import config_evidence
        for _ in range(9):
            _fill(self.cfg, 1.0)
        _fill(self.cfg, None)                    # an unpriced exit
        ev = config_evidence(self.cfg)
        self.assertEqual(ev["lane"], "none")     # 9 < 10, the NULL is not a 10th
        self.assertFalse(ev["measured"])
        self.assertEqual(ev["score"], 1.0)
        self.assertIn("live n=9", ev["reason"])

    def test_paper_and_live_are_never_pooled(self):
        from bot_program.evidence import config_evidence
        for _ in range(6):
            _fill(self.cfg, 1.0)
        for _ in range(6):
            _fill(self.cfg, 1.0, paper=True)
        ev = config_evidence(self.cfg)
        self.assertFalse(ev["measured"])
        self.assertEqual(ev["lane"], "none")

    def test_the_paper_lane_answers_when_live_is_thin(self):
        from bot_program.evidence import config_evidence
        for i in range(12):
            _fill(self.cfg, 2.0 if i < 3 else -1.0, paper=True)
        ev = config_evidence(self.cfg)
        self.assertEqual(ev["lane"], "paper")
        self.assertEqual(ev["n"], 12)
        self.assertAlmostEqual(ev["win_rate"], 0.25)
        self.assertAlmostEqual(ev["avg_r"], (6.0 - 9.0) / 12)

    def test_the_fleet_live_lane_is_trade_weighted(self):
        from bot_program.evidence import config_evidence
        other = _cfg(_user("rd_other"), name="other")
        for _ in range(8):
            _fill(other, 1.0, rule="ra")           # wr 1.0, avg 1.0
        for _ in range(4):
            _fill(other, -1.0, rule="rb")          # wr 0.0, avg -1.0
        ev = config_evidence(self.cfg)
        self.assertEqual(ev["lane"], "fleet_live")
        self.assertEqual(ev["n"], 12)
        self.assertAlmostEqual(ev["win_rate"], 8 / 12)
        self.assertAlmostEqual(ev["avg_r"], (8.0 - 4.0) / 12)
        self.assertIn("own live n=0", ev["reason"])

    def test_the_fleet_lane_stays_in_its_asset_class(self):
        from bot_program.evidence import config_evidence
        fx = _cfg(_user("rd_fx"), name="fx", asset_class="forex")
        for _ in range(12):
            _fill(fx, 1.0)
        self.assertEqual(config_evidence(self.cfg)["lane"], "none")

    def test_manual_takes_and_blank_rules_are_not_evidence(self):
        from bot_program.evidence import config_evidence
        for _ in range(10):
            _fill(self.cfg, 1.0, rule="manual_take")
        for _ in range(10):
            _fill(self.cfg, 1.0, rule="")
        self.assertEqual(config_evidence(self.cfg)["lane"], "none")

    def test_fills_outside_the_window_do_not_count(self):
        from bot_program.evidence import config_evidence
        for _ in range(10):
            _fill(self.cfg, 1.0, days_ago=91)
        self.assertEqual(config_evidence(self.cfg, days=90)["lane"], "none")

    def test_the_score_is_bounded(self):
        from bot_program.evidence import evidence_score
        self.assertEqual(evidence_score(1.0, 5.0), 1.5)
        self.assertEqual(evidence_score(0.0, -5.0), 0.5)
        self.assertAlmostEqual(evidence_score(0.5, 0.0), 1.0)


class OpportunityDensityTests(TestCase):

    def _scanner(self, on):
        from core.platform_control import PlatformComponent
        c, _ = PlatformComponent.objects.get_or_create(
            key="pipeline_opportunity_scanner",
            defaults={"name": "Opportunity Scanner", "category": "pipeline"})
        c.is_enabled = on
        c.save()

    def _flag(self, inst, *, outcome="", hours_ago=1):
        from signals.models_opportunity import OpportunityFlag, OpportunitySetup
        setup, _ = OpportunitySetup.objects.get_or_create(
            name="setup_a", defaults={"direction": "bullish"})
        f = OpportunityFlag.objects.create(setup=setup, instrument=inst,
                                           score=0.8, outcome=outcome)
        OpportunityFlag.objects.filter(pk=f.pk).update(
            scanned_at=timezone.now() - timedelta(hours=hours_ago))
        return f

    def _signal(self, inst, *, score=0.7, sub_scores=None, hours_ago=1,
                active=True):
        from signals.models import Signal
        s = Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="medium", title="t", description="d", rule_name="r",
            score=score, sub_scores=sub_scores or {},
            price_at_signal=Decimal("1"), is_active=active)
        Signal.objects.filter(pk=s.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago))
        return s

    def test_distinct_instruments_over_the_active_universe(self):
        from signals.opportunity_density import opportunity_density
        self._scanner(True)
        a, b = _inst("AAA"), _inst("BBB")
        _inst("CCC"); _inst("DDD")
        _inst("ZZZ", active=False)               # not in the universe
        self._flag(a); self._flag(a)             # two flags, one instrument
        self._signal(b)
        self._signal(a)                          # a is already counted
        d = opportunity_density()["stock"]
        self.assertTrue(d["measured"])
        self.assertEqual(d["universe"], 4)
        self.assertEqual(d["n_flags"], 2)
        self.assertEqual(d["n_flag_instruments"], 1)
        self.assertEqual(d["n_signals"], 2)
        self.assertEqual(d["n_signal_instruments"], 2)
        self.assertAlmostEqual(d["share"], 0.5)

    def test_the_scanners_own_signals_are_not_counted_twice(self):
        from signals.opportunity_density import opportunity_density
        self._scanner(True)
        a = _inst("AAA"); _inst("BBB")
        self._signal(a, sub_scores={"opportunity_setup": "setup_a"})
        d = opportunity_density()["stock"]
        self.assertEqual(d["n_signals"], 0)
        self.assertEqual(d["share"], 0.0)

    def test_resolved_flags_weak_and_old_signals_do_not_count(self):
        from signals.opportunity_density import opportunity_density
        self._scanner(True)
        a = _inst("AAA")
        self._flag(a, outcome="hit")
        self._flag(a, hours_ago=49)
        self._signal(a, score=0.5)
        self._signal(a, hours_ago=25)
        self._signal(a, active=False)
        d = opportunity_density()["stock"]
        self.assertEqual(d["n_flags"], 0)
        self.assertEqual(d["n_signals"], 0)
        self.assertTrue(d["measured"])           # measured, and empty
        self.assertEqual(d["share"], 0.0)

    def test_an_empty_universe_is_unmeasured(self):
        from signals.opportunity_density import opportunity_density
        self._scanner(True)
        a = _inst("AAA", active=False)
        self._flag(a)
        d = opportunity_density()["stock"]
        self.assertFalse(d["measured"])
        self.assertIn("no active instruments", d["reason"])

    def test_scanner_off_with_no_signals_is_unmeasured(self):
        from signals.opportunity_density import opportunity_density
        self._scanner(False)
        _inst("AAA")
        d = opportunity_density()["stock"]
        self.assertFalse(d["measured"])
        self.assertIn("scanner off", d["reason"])

    def test_scanner_off_with_signals_is_still_measured(self):
        from signals.opportunity_density import opportunity_density
        self._scanner(False)
        a = _inst("AAA")
        self._signal(a)
        d = opportunity_density()["stock"]
        self.assertTrue(d["measured"])
        self.assertEqual(d["share"], 1.0)

    def test_classes_are_kept_apart(self):
        from signals.opportunity_density import opportunity_density
        self._scanner(True)
        _inst("AAA"); e = _inst("GLDM", asset_class="etf")
        self._flag(e)
        out = opportunity_density()
        self.assertEqual(out["etf"]["share"], 1.0)
        self.assertEqual(out["stock"]["share"], 0.0)


class NewsRiskTests(TestCase):

    def _article(self, *, sent, instruments=(), urgency="normal",
                 summary="ok", hours_ago=1, processed_hours_ago=0.5):
        from scraping.models import NewsArticle
        now = timezone.now()
        a = NewsArticle.objects.create(
            title="t", source="s", url=f"https://x/{now.timestamp()}"
            f"{sent}{hours_ago}{summary}{len(instruments)}",
            published_at=now - timedelta(hours=hours_ago),
            ai_sentiment_score=sent, ai_urgency=urgency, ai_summary=summary,
            ai_processed_at=(now - timedelta(hours=processed_hours_ago)
                             if processed_hours_ago is not None else None))
        a.ai_affected_instruments.set(instruments)
        return a

    def _event(self, ccy, *, hours_ahead=3, impact="High", source="fmp_macro"):
        from market_data.models import EconomicEvent
        return EconomicEvent.objects.create(
            title="CPI", country="US", impact=impact, source=source,
            currency_affected=ccy,
            datetime=timezone.now() + timedelta(hours=hours_ahead))

    def test_no_processed_article_is_blind(self):
        from bot_program.news_risk import news_risk_by_class
        out = news_risk_by_class()
        self.assertTrue(out["stock"]["blind"])
        self.assertIn("news analyst idle since ever", out["stock"]["reason"])

    def test_an_idle_analyst_is_blind_even_with_scores_on_file(self):
        from bot_program.news_risk import news_risk_by_class
        aapl = _inst("AAPL")
        for _ in range(3):
            self._article(sent=-0.9, instruments=[aapl],
                          processed_hours_ago=3)
        out = news_risk_by_class()
        self.assertTrue(out["stock"]["blind"])
        self.assertIn("news analyst idle since", out["stock"]["reason"])
        self.assertEqual(out["stock"]["n_graded"], 0)

    def test_graded_articles_state_the_sentiment_above_min(self):
        from bot_program.news_risk import news_risk_by_class
        aapl = _inst("AAPL")
        self._article(sent=-0.6, instruments=[aapl], urgency="high")
        self._article(sent=-0.2, instruments=[aapl])
        self._article(sent=0.2, instruments=[aapl], urgency="critical")
        s = news_risk_by_class()["stock"]
        self.assertFalse(s["blind"])
        self.assertEqual(s["n_graded"], 3)
        self.assertEqual(s["n_urgent"], 2)
        self.assertAlmostEqual(s["avg_sent"], -0.2)

    def test_below_min_articles_the_sentiment_is_not_stated(self):
        from bot_program.news_risk import news_risk_by_class
        aapl = _inst("AAPL")
        self._article(sent=-0.9, instruments=[aapl])
        self._article(sent=-0.9, instruments=[aapl])
        s = news_risk_by_class(min_articles=3)["stock"]
        self.assertEqual(s["n_graded"], 2)
        self.assertIsNone(s["avg_sent"])
        self.assertFalse(s["blind"])

    def test_one_article_on_two_stocks_is_one_stock_article(self):
        from bot_program.news_risk import news_risk_by_class
        aapl, msft = _inst("AAPL"), _inst("MSFT")
        self._article(sent=-1.0, instruments=[aapl, msft])
        self._article(sent=0.0, instruments=[aapl])
        self._article(sent=0.0, instruments=[msft])
        s = news_risk_by_class()["stock"]
        self.assertEqual(s["n_graded"], 3)
        self.assertAlmostEqual(s["avg_sent"], -1.0 / 3)

    def test_the_parsers_fallback_rows_are_excluded(self):
        from bot_program.news_risk import news_risk_by_class
        aapl = _inst("AAPL")
        for _ in range(3):
            self._article(sent=0.0, instruments=[aapl],
                          summary="Failed to parse AI response")
        self._article(sent=-0.8, instruments=[aapl])
        s = news_risk_by_class()["stock"]
        self.assertEqual(s["n_graded"], 1)

    def test_articles_outside_the_window_do_not_count(self):
        from bot_program.news_risk import news_risk_by_class
        aapl = _inst("AAPL")
        self._article(sent=-0.8, instruments=[aapl], hours_ago=25)
        self.assertEqual(news_risk_by_class()["stock"]["n_graded"], 0)

    def test_macro_events_map_usd_to_every_class_and_legs_to_forex(self):
        from bot_program.news_risk import news_risk_by_class
        _inst("EURUSD", asset_class="forex")
        self._event("USD")
        self._event("EUR")
        self._event("JPY")                       # no active JPY pair
        self._event("USD", impact="Medium")      # not high
        self._event("USD", hours_ahead=30)       # outside 24h
        self._event("USD", source="other")       # not the macro calendar
        out = news_risk_by_class()
        self.assertEqual(out["stock"]["events_24h"], 1)
        self.assertEqual(out["crypto"]["events_24h"], 1)
        self.assertEqual(out["forex"]["events_24h"], 2)
        self.assertIn("macro event", out["stock"]["reason"])

    def test_events_are_counted_even_when_leg_a_is_blind(self):
        from bot_program.news_risk import news_risk_by_class
        self._event("USD")
        s = news_risk_by_class()["stock"]
        self.assertTrue(s["blind"])
        self.assertEqual(s["events_24h"], 1)
