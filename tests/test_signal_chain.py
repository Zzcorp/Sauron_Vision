"""The chain: bars -> rule engine -> Signal row -> decide() -> a trade.

This is the test whose absence let 81,000 lines ship with a dead rule layer.
Every link had unit tests. Nothing asserted that the links joined, and they
did not: rules emit `{symbol, rule, direction: "LONG", headline, thesis,
entry, stop, target}` while the persister read `result["instrument"]` and
`result["rule_name"]`, so 100% of rule output was dropped with a warning
nobody read.

Everything here runs the REAL objects — the real SignalEngine, the real
persister, the real decide(), the real sizing. No mocks in the chain itself,
because a mock at any join is exactly what would have hidden the defect.

Run with:  python manage.py test tests.test_signal_chain
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="chain_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_watchlist": True})
    return inst


def _crossover_closes(n_down=230, start=200.0, decline=0.5, rally=3.0):
    """Closes whose SMA50 crosses above SMA200 on the FINAL bar.

    GoldenCrossRule tests exactly one transition —
    `sma50[-2] <= sma200[-2] and sma50[-1] > sma200[-1]` — so a fixture that
    merely "contains an uptrend" fires nothing. Rather than hand-tuning
    numbers until they happen to line up, extend the rally until the cross
    occurs and stop on that bar.
    """
    import pandas as pd

    closes = [start - i * decline for i in range(n_down)]
    trough = closes[-1]
    for k in range(1, 400):
        closes.append(trough + k * rally)
        if len(closes) < 202:
            continue
        c = pd.Series(closes)
        s50 = c.rolling(50).mean()
        s200 = c.rolling(200).mean()
        if s50.iloc[-2] <= s200.iloc[-2] and s50.iloc[-1] > s200.iloc[-1]:
            return closes
    raise AssertionError("no SMA50/SMA200 crossover produced — fixture is wrong")


def _bars(inst, timeframe="4h", closes=None, n_down=230):
    """Persist a close series as OHLCV rows ending at the most recent bar."""
    from market_data.models import PriceData
    if closes is None:
        closes = _crossover_closes(n_down=n_down)
    now = timezone.now()
    total = len(closes)
    rows = []
    prev = closes[0]
    for i, close in enumerate(closes):
        rows.append(PriceData(
            instrument=inst, timeframe=timeframe,
            timestamp=now - timedelta(hours=4 * (total - i)),
            open=Decimal(str(round(prev, 4))),
            high=Decimal(str(round(max(prev, close) + 0.8, 4))),
            low=Decimal(str(round(min(prev, close) - 0.8, 4))),
            close=Decimal(str(round(close, 4))),
            volume=1000, source="test"))
        prev = close
    PriceData.objects.bulk_create(rows)


class AdapterTests(TestCase):
    """The translation itself, in isolation."""

    def setUp(self):
        self.inst = _instrument()

    def test_the_rule_shape_becomes_a_storable_signal(self):
        from signals.rule_adapter import normalise
        fields = normalise({
            "symbol": "BTCUSD", "rule": "rsi_bull_divergence",
            "direction": "LONG", "score": 0.7,
            "headline": "BTCUSD LONG - RSI bullish divergence",
            "thesis": "Momentum exhaustion.",
            "entry": 100.0, "stop": 98.5, "target": 103.0,
        })
        self.assertIsNotNone(fields, "the rule shape is still unstorable")
        self.assertEqual(fields["instrument"], self.inst)
        self.assertEqual(fields["rule_name"], "rsi_bull_divergence")
        self.assertEqual(fields["direction"], "bullish")
        self.assertEqual(fields["title"], "BTCUSD LONG - RSI bullish divergence")
        self.assertEqual(float(fields["suggested_stop"]), 98.5)

    def test_short_maps_to_bearish(self):
        from signals.rule_adapter import normalise
        f = normalise({"symbol": "BTCUSD", "rule": "r", "direction": "SHORT",
                       "score": 0.6, "entry": 100.0})
        self.assertEqual(f["direction"], "bearish")

    def test_risk_reward_is_derived_when_absent(self):
        from signals.rule_adapter import normalise
        f = normalise({"symbol": "BTCUSD", "rule": "r", "direction": "LONG",
                       "score": 0.6, "entry": 100.0, "stop": 98.0,
                       "target": 104.0})
        self.assertAlmostEqual(f["risk_reward_ratio"], 2.0, places=4)

    def test_a_priceless_rule_falls_back_to_the_last_close(self):
        """price_at_signal is NOT NULL and flow/fundamental rules emit no
        price — a naive adapter turns a skipped warning into an uncaught
        IntegrityError that kills the whole scan."""
        from signals.rule_adapter import normalise
        _bars(self.inst, closes=[100.0, 101.0, 102.0])
        f = normalise({"symbol": "BTCUSD", "rule": "flow_rule",
                       "direction": "LONG", "score": 0.6})
        self.assertIsNotNone(f)
        self.assertIsNotNone(f["price_at_signal"])

    def test_an_unknown_symbol_is_refused_not_guessed(self):
        from signals.rule_adapter import normalise
        self.assertIsNone(normalise({"symbol": "NOSUCHTHING", "rule": "r",
                                     "direction": "LONG", "score": 0.6,
                                     "entry": 1.0}))

    def test_the_storage_shape_still_works_untouched(self):
        """The opportunity scanner already emits the storage shape; the
        adapter must not break what was already correct."""
        from signals.rule_adapter import normalise
        f = normalise({"instrument": self.inst, "rule_name": "advanced_x",
                       "direction": "bullish", "score": 0.8,
                       "title": "t", "description": "d",
                       "price_at_signal": Decimal("100"),
                       "signal_type": "composite"})
        self.assertEqual(f["rule_name"], "advanced_x")
        self.assertEqual(f["signal_type"], "composite")

    def test_a_list_returning_rule_does_not_crash_the_scan(self):
        """SmcCompositeRule returns a LIST while every other rule returns a
        dict, and scan_instrument appends whichever it got — so .get() on the
        list raised AttributeError and killed the entire scan the first time
        any SMC setup was detected."""
        from signals.rule_adapter import flatten
        out = flatten([{"a": 1}, [{"b": 2}, {"c": 3}], None, "nonsense"])
        self.assertEqual(out, [{"a": 1}, {"b": 2}, {"c": 3}])


class ChainTests(TestCase):
    """bars -> engine -> Signal -> decide()."""

    def setUp(self):
        self.user = _user()
        self.inst = _instrument()
        _bars(self.inst)

    def _cfg(self, **kw):
        from bot_program.models import AssetBotConfig
        defaults = dict(user=self.user, asset_class="crypto", name="CH",
                        mode="paper", symbols=["BTCUSD"],
                        capital=Decimal("10000"), enabled=True,
                        entry_score_min=0.6, min_signals_for_entry=1)
        defaults.update(kw)
        return AssetBotConfig.objects.create(**defaults)

    def test_the_real_engine_produces_storable_signals(self):
        """The whole point: run the actual rules over actual bars and push
        the actual output through the actual persister."""
        from signals.engine import SignalEngine
        from signals.tasks import _create_signals_and_notify
        from signals.models import Signal

        results = SignalEngine().scan_instrument(self.inst)
        self.assertTrue(results, "no rule fired on a series ending in an SMA50/SMA200 crossover")

        created = _create_signals_and_notify(results)
        self.assertGreater(created, 0,
                           "rules fired but nothing was stored — the seam is "
                           "still broken")
        self.assertGreater(Signal.objects.count(), 0)

    def test_a_stored_signal_drives_decide_to_an_entry(self):
        from signals.engine import SignalEngine
        from signals.tasks import _create_signals_and_notify
        from bot_program.asset_engine import CryptoBot

        _create_signals_and_notify(SignalEngine().scan_instrument(self.inst))
        decision = CryptoBot(self._cfg()).decide("BTCUSD")
        self.assertIn(decision.direction, ("BUY", "SELL"),
                      msg=f"still HOLD: {decision.reasons}")
        self.assertTrue(decision.rule_name)

    def test_every_stored_signal_has_the_fields_decide_reads(self):
        from signals.engine import SignalEngine
        from signals.tasks import _create_signals_and_notify
        from signals.models import Signal

        _create_signals_and_notify(SignalEngine().scan_instrument(self.inst))
        for s in Signal.objects.all():
            self.assertIn(s.direction, ("bullish", "bearish", "neutral"))
            self.assertIsNotNone(s.price_at_signal)
            self.assertTrue(s.rule_name)
            self.assertGreater(s.score, 0)


class StaleSignalTests(TestCase):
    """`is_active` is cleared by a lifecycle pass that needs a fresh quote,
    so a signal on a no-longer-quoted instrument stays active forever and
    votes forever. Five fabricated April rows sit in the dev database at
    scores above the entry threshold."""

    def setUp(self):
        self.user = _user("stale_u")
        self.inst = _instrument()

    def _signal(self, age_hours):
        from signals.models import Signal
        s = Signal.objects.create(
            instrument=self.inst, signal_type="technical", direction="bullish",
            urgency="high", title="t", description="d", rule_name="old_rule",
            score=0.92, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), is_active=True)
        # created_at is auto_now_add, so it has to be written back.
        Signal.objects.filter(pk=s.pk).update(
            created_at=timezone.now() - timedelta(hours=age_hours))
        return s

    def _cfg(self, **kw):
        from bot_program.models import AssetBotConfig
        defaults = dict(user=self.user, asset_class="crypto", name="ST",
                        mode="paper", symbols=["BTCUSD"],
                        capital=Decimal("10000"), enabled=True,
                        entry_score_min=0.6, min_signals_for_entry=1)
        defaults.update(kw)
        return AssetBotConfig.objects.create(**defaults)

    def test_a_months_old_signal_cannot_open_a_trade(self):
        from bot_program.asset_engine import CryptoBot
        self._signal(age_hours=24 * 90)
        d = CryptoBot(self._cfg()).decide("BTCUSD")
        self.assertEqual(d.direction, "HOLD")
        self.assertIn("stale", d.reasons[0])

    def test_a_fresh_signal_still_votes(self):
        from bot_program.asset_engine import CryptoBot
        self._signal(age_hours=1)
        self.assertEqual(CryptoBot(self._cfg()).decide("BTCUSD").direction, "BUY")

    def test_the_window_is_configurable(self):
        from bot_program.asset_engine import CryptoBot
        self._signal(age_hours=48)
        cfg = self._cfg(extras={"max_signal_age_hours": 72})
        self.assertEqual(CryptoBot(cfg).decide("BTCUSD").direction, "BUY")
