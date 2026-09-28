"""IS IT A GOOD IDEA TO CLOSE? — and closing only what was ticked.

On /positions/ and /portfolio/ the operator (or Gandalf, logged in as the
operator) ticks open positions and asks Sauron whether closing them now is a
good idea. Sauron answers per position and for the selection, in words, and
closes NOTHING by itself; the human may then close exactly the ticked rows
through a PIN-confirmed "Close selected".

What this file pins, in order:

  * THE RULES. Each path to each of the four verdicts — close, trim or
    tighten, hold, unknown — from the watcher's own trigger codes plus the
    facts it never had: the stop the VENUE holds (eToro kept 9.98% where 5%
    was sent), the world a row lives in (a demo row is never "live"), an
    unfilled order (withdraw or keep, no R), the time stop, a shut market,
    fresh signals for and against, a close already being retried, and the
    watcher's latest model verdict.
  * NO VERDICT ON A STALE PRICE: "unknown", said out loud.
  * OWNERSHIP: another user's row, a closed one and a made-up id are all
    "not found" — in one sentence that does not say which.
  * THE MODEL HALF: one call for the whole selection, clamped to the four
    words, and every way it can be missing (no key, no budget, an error, an
    unreadable answer) returns the rule-based answer with a sentence why.
    No Notification, no PositionReview row, no hypothesis.
  * THE ENDPOINTS: CSRF enforced, owner-scoped, 405/400/login like their
    siblings. Close-selected closes the ticked rows and nothing else,
    reports a row that vanished instead of replacing it, and refuses the
    WHOLE batch on a wrong PIN rather than closing half of it.
  * THE PAGES: a tick only on a bot row, the script and the sheet loaded,
    the row click that no longer navigates on a tick, and the live region
    that says when it rebuilt the table so the ticks can come back.
  * THE SOURCE: brain/close_advice.py has no path to the engine.

Run with:  python manage.py test tests.test_close_advice
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from unittest import mock
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone

HOST = "127.0.0.1"
NODE = shutil.which("node")
PIN = "4321"

ADVICE = "/positions/close-advice/"
PREVIEW = "/positions/close-selected/preview/"
CLOSE = "/positions/close-selected/"


# ── fixtures ─────────────────────────────────────────────────────────────

def _read(*parts):
    return (pathlib.Path(settings.BASE_DIR).joinpath(*parts)
            .read_text(encoding="utf-8"))


def _instrument(symbol, asset_class="crypto", exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange, "is_active": True})
    return inst


def _quote(symbol, last, asset_class="crypto", age_seconds=None):
    """A LiveQuote; `age_seconds` ages it past the platform's freshness."""
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    q, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    if age_seconds is not None:
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(seconds=age_seconds))
    return q


def _config(user, *, asset_class="crypto", mode="paper", name=None, **kw):
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=asset_class,
        name=name or "ca_%s_%s" % (asset_class, mode),
        defaults=dict(enabled=True, mode=mode, symbols=[],
                      capital=Decimal("10000"), base_currency="USD", **kw))
    return cfg


def _trade(user, *, symbol="BTCUSD", asset_class="crypto", side="BUY",
           qty="0.5", entry=60000, stop=58800, target=63000,
           initial_stop=None, paper=True, status="OPEN", metadata=None,
           opened_hours_ago=2, rule="", config=None):
    from bot_program.models import AssetBotTrade
    _instrument(symbol, asset_class)
    meta = {"initial_stop_loss": float(initial_stop if initial_stop
                                       is not None else stop)
            if (initial_stop is not None or stop is not None) else None}
    meta.update(metadata or {})
    t = AssetBotTrade.objects.create(
        config=config or _config(user, asset_class=asset_class,
                                 mode="paper" if paper else "live"),
        asset_class=asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)) if stop is not None else None,
        take_profit=Decimal(str(target)) if target is not None else None,
        status=status, paper=paper, rule_name=rule,
        reason="breakout above the prior high", metadata=meta)
    AssetBotTrade.objects.filter(pk=t.pk).update(
        opened_at=timezone.now() - timedelta(hours=opened_hours_ago))
    t.refresh_from_db()
    return t


def _signal(symbol, direction, score, *, rule="rsi_reversal_4h",
            hours_ago=1, active=True):
    from signals.models import Signal
    s = Signal.objects.create(
        instrument=_instrument(symbol), signal_type="technical",
        direction=direction, urgency="medium", title="%s %s" % (rule, symbol),
        description="d", rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal("1"), is_active=active)
    Signal.objects.filter(pk=s.pk).update(
        created_at=timezone.now() - timedelta(hours=hours_ago))
    return s


def _pin(user, pin=PIN):
    from django.contrib.auth.hashers import make_password
    from portfolio.trader_profile import TraderProfile
    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.access_pin_hash = make_password(pin)
    prof.save(update_fields=["access_pin_hash"])


def _legacy(user, symbol="AAPL"):
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    return Position.objects.create(
        portfolio=get_or_create_default_portfolio(user=user),
        instrument=_instrument(symbol, "stock"), direction="long",
        quantity=Decimal("2"), entry_price=Decimal("100"),
        current_price=Decimal("100"), opened_at=timezone.now())


def _one(answer, trade):
    for p in answer["positions"]:
        if p["trade_id"] == trade.id:
            return p
    raise AssertionError("trade #%s not in the answer: %r"
                         % (trade.id, answer["not_found"]))


class _Case(TestCase):
    username = "ca_user"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            self.username, password="x")

    def advise(self, *trades, **kw):
        from brain.close_advice import advise
        return advise(self.user, [t.id for t in trades], **kw)


# ══════════════════════════════════════════════════════════════════════════
# The rules
# ══════════════════════════════════════════════════════════════════════════

class VerdictRuleTests(_Case):
    username = "ca_rules"

    def test_hold_when_nothing_fires(self):
        _quote("BTCUSD", 60600)
        t = _trade(self.user)
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "hold")
        self.assertEqual(p["verdict_words"],
                         "Hold — the reason it was opened still stands")
        self.assertIn("Nothing the watcher measures has fired: the stop and "
                      "the target are doing their job.", p["reasons"])
        n = p["numbers"]
        self.assertEqual(n["r_now"], 0.5)
        self.assertEqual(n["r_now_text"], "+0.50R")
        self.assertEqual(n["r_to_stop_text"], "1.50R")
        self.assertEqual(n["r_to_target_text"], "2.00R")
        self.assertEqual(n["pnl"], 300.0)
        self.assertEqual(n["pnl_text"], "+300.00 USD")
        # Cash cost at entry for an unlevered class: qty x entry.
        self.assertEqual(n["committed_text"], "30,000.00 USD")
        self.assertEqual(n["committed_kind"], "cost")
        self.assertEqual(n["age_text"], "2 hours")

    def test_close_when_the_mark_is_through_the_stop(self):
        """C1: the exit the trade was sized around has already passed."""
        _quote("BTCUSD", 58000)
        t = _trade(self.user)
        a = self.advise(t)
        p = _one(a, t)
        self.assertEqual(p["verdict"], "close")
        self.assertEqual(p["verdict_words"], "Closing looks right")
        # One row: its own verdict is the read of the selection.
        self.assertEqual(a["summary"]["overall"], "Closing looks right.")
        self.assertTrue(any("BEYOND the stop" in r for r in p["reasons"]))
        self.assertEqual(p["numbers"]["r_to_stop_text"], "past it by 0.67R")

    def test_close_when_signals_oppose_and_it_is_not_paying(self):
        """C3: a thesis reason and nothing left to wait for."""
        _quote("BTCUSD", 59900)
        _signal("BTCUSD", "bearish", 0.9)
        _signal("BTCUSD", "bullish", 0.4, rule="golden_cross")
        t = _trade(self.user)
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "close")
        self.assertTrue(p["facts"]["signals"]["opposing_dominates"])
        self.assertIn("1 fresh signal in the last 24h points the other way "
                      "(strongest: RSI reversal 4h, score 0.90), against 1 "
                      "agreeing (strongest 0.40).", p["reasons"])

    def test_trim_when_signals_oppose_but_it_is_still_paying(self):
        """T2: protect what it made rather than hand it back."""
        _quote("BTCUSD", 60600)
        _signal("BTCUSD", "bearish", 0.9)
        t = _trade(self.user)
        self.assertEqual(_one(self.advise(t), t)["verdict"],
                         "trim_or_tighten")

    def test_a_stale_or_neutral_or_agreeing_signal_is_no_reason_to_close(self):
        _quote("BTCUSD", 59900)
        _signal("BTCUSD", "bearish", 0.9, hours_ago=30)      # not fresh
        _signal("BTCUSD", "bearish", 0.9, active=False)      # not active
        _signal("BTCUSD", "neutral", 0.9)                    # no direction
        _signal("BTCUSD", "bullish", 0.7)                    # agrees
        t = _trade(self.user)
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "hold")
        self.assertEqual(p["facts"]["signals"]["oppose"], 0)
        self.assertEqual(p["facts"]["signals"]["agree"], 1)

    def test_a_short_reads_the_signals_the_other_way_round(self):
        _quote("BTCUSD", 60100)
        _signal("BTCUSD", "bullish", 0.8)
        t = _trade(self.user, side="SELL", stop=61200, target=57000)
        p = _one(self.advise(t), t)
        self.assertEqual(p["side"], "SELL")
        self.assertEqual(p["headline"], "Short BTCUSD")
        self.assertTrue(p["facts"]["signals"]["opposing_dominates"])
        self.assertEqual(p["verdict"], "close")        # losing, thesis against

    def test_trim_when_the_stop_is_close_but_not_through(self):
        """T1 near_stop: a trailed stop 0.17R under the mark, trade in
        profit — watch it, the bracket is about to decide."""
        _quote("BTCUSD", 60200)
        t = _trade(self.user, stop=59700, initial_stop=57000)
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "trim_or_tighten")
        self.assertIn("near_stop", [x["code"] for x in p["triggers"]])

    def test_close_when_the_time_stop_is_reached(self):
        """C2: the platform's own ceiling for this position has run out."""
        _quote("BTCUSD", 60600)
        cfg = _config(self.user, name="ca_short_clock", max_hold_hours=1.0)
        t = _trade(self.user, config=cfg, opened_hours_ago=3)
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "close")
        self.assertTrue(any(r.startswith("Its time limit is reached")
                            for r in p["reasons"]))

    def test_trim_when_the_time_stop_is_approaching(self):
        _quote("BTCUSD", 60600)
        cfg = _config(self.user, name="ca_near_clock", max_hold_hours=10.0)
        t = _trade(self.user, config=cfg, opened_hours_ago=9)
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "trim_or_tighten")
        self.assertTrue(any("of its time limit" in r for r in p["reasons"]))

    def test_unknown_without_a_fresh_price(self):
        """No verdict on a stale mark: the price is two hours old and no
        bar backs it, so nothing is judged and nothing is invented."""
        _quote("BTCUSD", 60600, age_seconds=7200)
        _signal("BTCUSD", "bearish", 0.9)
        t = _trade(self.user)
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "unknown")
        self.assertEqual(p["verdict_words"], "Can't judge — no fresh price")
        self.assertTrue(p["reasons"][0].startswith("No fresh price for BTCUSD"))
        n = p["numbers"]
        for key in ("mark", "pnl", "r_now", "r_to_stop", "r_to_target"):
            self.assertIsNone(n[key], key)
        for key in ("mark_text", "pnl_text", "r_now_text", "r_to_stop_text"):
            self.assertEqual(n[key], "—", key)
        self.assertEqual(p["triggers"], [])

    def test_an_options_row_has_no_price_to_judge(self):
        _quote("AAPL", 190, asset_class="stock")
        t = _trade(self.user, symbol="AAPL", asset_class="options", qty="1",
                   entry=5, stop=2.5, target=10,
                   metadata={"multiplier": 100})
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "unknown")
        self.assertIsNone(p["numbers"]["pnl"])
        self.assertIn("No option-price feed exists", p["reasons"][0])

    def test_a_close_already_being_retried_comes_first(self):
        _quote("BTCUSD", 60600)
        t = _trade(self.user, status="CLOSE_PENDING",
                   metadata={"close_retry_attempts": 3})
        p = _one(self.advise(t), t)
        self.assertEqual(p["reasons"][0],
                         "A close is already being retried: the broker "
                         "refused it 3 times, so the position is still open "
                         "there and Sauron tries again every 5 minutes.")

    def test_a_shut_market_says_the_close_would_wait(self):
        _quote("BTCUSD", 60600)
        t = _trade(self.user)
        shut = {"is_open": False, "session": "NYSE", "modelled": True,
                "reopens": None, "reopens_words": "Monday 13:30 UTC",
                "opened": None}
        with patch("core.exchange_status.market_clock", return_value=shut):
            p = _one(self.advise(t), t)
        self.assertIn("The market for BTCUSD is shut: a close now would wait "
                      "for the open (Monday 13:30 UTC); a paper close is "
                      "refused until then.", p["reasons"])
        self.assertFalse(p["facts"]["market"]["is_open"])

    def test_the_watchers_latest_model_verdict_is_reported(self):
        from brain.position_review_models import PositionReview
        _quote("BTCUSD", 60600)
        t = _trade(self.user)
        PositionReview.objects.create(
            book="bot", position_id=t.id, symbol="BTCUSD", side="BUY",
            user=self.user, verdict="exit", confidence=0.72,
            reasoning_md="The breakout failed and the level is lost.")
        p = _one(self.advise(t), t)
        self.assertTrue(any(r.startswith("Sauron's position watcher said "
                                         "\"exit\"") and "(confidence 0.72)"
                            in r and "The breakout failed" in r
                            for r in p["reasons"]), p["reasons"])
        # Reported, never obeyed: the rules still read a healthy position.
        self.assertEqual(p["verdict"], "hold")

    def test_at_most_six_reasons_most_important_first(self):
        """Seven things to say; the least important one is the one cut."""
        from brain.close_advice import MAX_REASONS
        from brain.position_review_models import PositionReview
        _quote("BTCUSD", 58000)
        for i in range(4):
            _signal("BTCUSD", "bearish", 0.5 + i / 10, rule="r%d" % i)
        cfg = _config(self.user, name="ca_many", max_hold_hours=1.0)
        t = _trade(self.user, config=cfg, opened_hours_ago=3,
                   status="CLOSE_PENDING")
        PositionReview.objects.create(
            book="bot", position_id=t.id, symbol="BTCUSD", side="BUY",
            user=self.user, verdict="hold", confidence=0.5)
        shut = {"is_open": False, "session": "X", "modelled": True,
                "reopens": None, "reopens_words": "", "opened": None}
        with patch("core.exchange_status.market_clock", return_value=shut):
            p = _one(self.advise(t), t)
        self.assertEqual(len(p["reasons"]), MAX_REASONS)
        self.assertFalse(any("position watcher" in r for r in p["reasons"]))
        self.assertTrue(any("is shut" in r for r in p["reasons"]))
        self.assertTrue(p["reasons"][0].startswith("A close is already"))
        # The two severity-1.0 triggers next, in the watcher's own order.
        self.assertTrue(any("BEYOND the stop" in r for r in p["reasons"][1:3]),
                        p["reasons"])
        # The fresh-signal line is below the stop and the clock.
        self.assertGreater(
            [i for i, r in enumerate(p["reasons"]) if "fresh signal" in r][0],
            [i for i, r in enumerate(p["reasons"])
             if r.startswith("Its time limit")][0])


class LevelsTests(_Case):
    """"Hold" says what the levels are doing — only the levels the row has.

    A target can be cleared from the positions page, and older rows carry
    no stop at all. The hold sentence used to praise "the stop and the
    target" on a row with neither, and a row with no stop has no R, so
    every R-based warning was silent and the only possible answer was
    "hold" — whatever it was losing.
    """
    username = "ca_levels"

    def test_a_row_without_a_target_is_not_told_its_target_works(self):
        _quote("BTCUSD", 60600)
        t = _trade(self.user, target=None)
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "hold")
        self.assertIn("Nothing the watcher measures has fired: the stop is "
                      "doing its job; no target is set.", p["reasons"])
        self.assertFalse(any("the target are doing" in r
                             for r in p["reasons"]))
        self.assertEqual(p["numbers"]["r_to_target_text"], "—")

    def test_a_row_without_a_stop_is_never_a_hold(self):
        """T5 — the reviewer's case: no stop, no target, 1,500 USD down."""
        _quote("BTCUSD", 57000)
        t = _trade(self.user, stop=None, target=None)
        a = self.advise(t)
        p = _one(a, t)
        self.assertEqual(p["numbers"]["pnl"], -1500.0)
        self.assertEqual(p["verdict"], "trim_or_tighten")
        self.assertEqual(p["reasons"][0],
                         "No stop is set: nothing limits the loss, and with "
                         "no stop to measure against there is no R, so the "
                         "warnings that read R (near the stop, adverse "
                         "excursion, give-back, risk against reward) cannot "
                         "fire.")
        self.assertFalse(any("doing its job" in r or "doing their job" in r
                             for r in p["reasons"]))
        # No R was invented to fill the gap.
        self.assertIsNone(p["numbers"]["r_now"])
        self.assertEqual(p["numbers"]["r_to_stop_text"], "—")
        self.assertNotIn("hold", a["summary"]["overall"].lower())

    def test_a_zero_stop_is_no_stop(self):
        """An older row spells "none" as 0. The watcher measures it as a
        level at price zero — "50R still at risk to the stop" on a long,
        and on a short a mark THROUGH it, which would read as close."""
        _quote("BTCUSD", 60600)
        long_ = _trade(self.user, stop=0, initial_stop=58800)
        short = _trade(self.user, side="SELL", stop=0, initial_stop=61200,
                       target=57000)
        a = self.advise(long_, short)
        for t in (long_, short):
            p = _one(a, t)
            self.assertEqual(p["verdict"], "trim_or_tighten", p["reasons"])
            self.assertEqual(p["reasons"][0],
                             "No stop is set: nothing limits the loss.")
            self.assertFalse(any("to the stop" in r or "BEYOND the stop" in r
                                 for r in p["reasons"]), p["reasons"])
            self.assertEqual(p["numbers"]["r_to_stop_text"], "—")
            # R itself is still measured: the stop it OPENED with is known.
            self.assertIsNotNone(p["numbers"]["r_now"])

    def test_the_hold_sentence_names_the_levels_it_has(self):
        from brain.close_advice import _hold_words
        self.assertEqual(
            [_hold_words(True, True), _hold_words(True, False),
             _hold_words(False, True), _hold_words(False, False)],
            ["Nothing the watcher measures has fired: the stop and the "
             "target are doing their job.",
             "Nothing the watcher measures has fired: the stop is doing its "
             "job; no target is set.",
             "Nothing the watcher measures has fired; a target is set, but "
             "no stop is.",
             "Nothing the watcher measures has fired; neither a stop nor a "
             "target is set."])


class PendingTests(_Case):
    """A CLOSE_PENDING row is already being closed — the retry task sends
    it every five minutes. Its facts are still judged, but nothing on the
    card or in the selection's line may read as "this stays open"."""
    username = "ca_pending"

    def _pending(self, **kw):
        return _trade(self.user, status="CLOSE_PENDING",
                      metadata={"close_retry_attempts": 2}, **kw)

    def test_a_pending_row_is_never_labelled_hold(self):
        _quote("BTCUSD", 60600)
        t = self._pending()
        a = self.advise(t)
        p = _one(a, t)
        # The facts' reading is kept: if the retries are abandoned, whoever
        # closes it at the broker wants to know what they said.
        self.assertEqual(p["verdict"], "hold")
        self.assertTrue(p["pending"])
        self.assertEqual(p["verdict_words"],
                         "Already being closed — on its facts alone Sauron "
                         "would not have closed it")
        self.assertNotIn("still stands", p["verdict_words"])
        s = a["summary"]
        self.assertEqual((s["hold"], s["pending"]), (0, 1))
        self.assertEqual(s["overall"], p["verdict_words"] + ".")
        self.assertTrue(p["reasons"][0].startswith(
            "A close is already being retried"))

    def test_every_verdict_has_pending_words(self):
        from brain.close_advice import PENDING_WORDS, VERDICTS
        self.assertEqual(set(PENDING_WORDS), set(VERDICTS))
        for words in PENDING_WORDS.values():
            self.assertTrue(words.startswith("Already being closed"), words)

    def test_the_selection_line_counts_pending_rows_apart(self):
        _quote("BTCUSD", 60600)
        _quote("ETHUSD", 3030)
        pending = self._pending()
        eth = _trade(self.user, symbol="ETHUSD", qty="2", entry=3000,
                     stop=2940, target=3150)
        s = self.advise(pending, eth)["summary"]
        self.assertEqual((s["hold"], s["pending"], s["count"]), (1, 1, 2))
        self.assertEqual(
            s["overall"],
            "1 is already being closed (Sauron retries it every 5 minutes). "
            "The other one, ETHUSD: hold — the reason it was opened still "
            "stands.")
        self.assertNotIn("Nothing here needs closing", s["overall"])

    def test_the_rest_of_a_larger_selection_is_read_on_its_own(self):
        _quote("BTCUSD", 60600)
        _quote("ETHUSD", 3030)
        _quote("SOLUSD", 150)
        pending = self._pending()
        eth = _trade(self.user, symbol="ETHUSD", qty="2", entry=3000,
                     stop=2940, target=3150)
        sol = _trade(self.user, symbol="SOLUSD", qty="10", entry=150,
                     stop=147, target=156)
        # Three crypto longs in one book is concentration, which the
        # watcher rightly flags; silenced here so the line under test is
        # the "all hold" one.
        with patch("brain.position_review.evaluate_triggers",
                   return_value=[]):
            s = self.advise(pending, eth, sol)["summary"]
        self.assertEqual(
            s["overall"],
            "1 is already being closed (Sauron retries it every 5 minutes). "
            "Of the other 2: nothing here needs closing — hold all 2.")

    def test_a_selection_that_is_all_pending_says_so(self):
        _quote("BTCUSD", 60600)
        _quote("ETHUSD", 3030)
        a = self._pending()
        b = self._pending(symbol="ETHUSD", qty="2", entry=3000, stop=2940,
                          target=3150)
        s = self.advise(a, b)["summary"]
        self.assertEqual(s["overall"],
                         "All 2 are already being closed: the broker refused "
                         "each close and Sauron retries them every 5 "
                         "minutes.")

    def test_the_models_verdict_on_a_pending_row_wears_the_same_words(self):
        _quote("BTCUSD", 60600)
        t = self._pending()
        raw = json.dumps({"positions": [
            {"trade_id": t.id, "verdict": "hold", "reasoning": "Fine.",
             "confidence": 0.6}], "overall": "Leave it."})
        rec = []
        with _stub(raw, recorder=rec), patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")):
            a = self.advise(t, use_model=True)
        m = _one(a, t)["model"]
        self.assertEqual(m["verdict"], "hold")
        self.assertTrue(m["verdict_words"].startswith("Already being closed"))
        # The model is told the row is being closed.
        self.assertIn('"pending": true',
                      rec[0].provider.complete.call_args.kwargs[
                          "user_message"])


class VenueHeldStopTests(_Case):
    """eToro clamps a stop on fill rather than refuse it: on the real
    account, 5% was sent and 9.98% held. The distance that matters is to
    the stop the broker HOLDS."""
    username = "ca_venue"

    def _etoro(self, **meta):
        base = {"broker": "etoro", "broker_env": "real", "protected": True,
                "stop_rewritten_by_venue": {"sent": 57000.0,
                                            "held": 54012.0}}
        base.update(meta)
        return _trade(self.user, paper=False, stop=57000, target=66000,
                      metadata=base)

    def test_past_the_sent_stop_but_not_the_held_one_is_a_close(self):
        _quote("BTCUSD", 56500)
        t = self._etoro()
        a = self.advise(t)
        self.assertEqual(a["summary"]["overall"],
                         "Closing looks right. It is real money.")
        p = _one(a, t)
        self.assertEqual(p["verdict"], "close")
        self.assertEqual(p["world"], "live")
        self.assertEqual(p["world_words"], "Real money · eToro")
        n = p["numbers"]
        # Against the HELD stop, the one in force at the broker...
        self.assertAlmostEqual(n["r_to_stop"], (56500 - 54012) / 3000, 3)
        # ...with the planned one beside it, already passed.
        self.assertAlmostEqual(n["r_to_planned_stop"], -500 / 3000, 3)
        self.assertTrue(any("past the stop Sauron sent (57000.00)" in r
                            and "holds its stop at 54012.00" in r
                            for r in p["reasons"]), p["reasons"])
        self.assertTrue(any("that stop risks 1.997R, not 1R" in r
                            or "that stop risks 2.00R, not 1R" in r
                            for r in p["reasons"]), p["reasons"])

    def test_a_wider_held_stop_on_a_healthy_position_says_tighten(self):
        """T4: the trade is fine, the stop at the broker is twice the risk
        it was sized for."""
        _quote("BTCUSD", 60900)
        t = self._etoro()
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "trim_or_tighten")
        self.assertEqual(p["facts"]["venue_risk_r"], 2.0)

    def test_a_held_stop_under_the_sentinel_is_no_stop_at_all(self):
        _quote("BTCUSD", 60900)
        t = self._etoro(stop_rewritten_by_venue={"sent": 57000.0,
                                                 "held": 0.0001})
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "trim_or_tighten")
        self.assertTrue(p["facts"]["venue_stop"]["none"])
        self.assertTrue(any(r.startswith("The broker holds NO stop")
                            for r in p["reasons"]))
        # No distance to a stop that does not exist at the broker is
        # invented: the R to stop stays the one Sauron's own stop gives.
        self.assertIsNone(p["numbers"]["r_to_planned_stop"])

    def test_a_stop_moved_since_the_fill_does_not_quote_the_old_echo(self):
        _quote("BTCUSD", 60900)
        t = self._etoro()
        type(t).objects.filter(pk=t.pk).update(stop_loss=Decimal("59000"))
        p = _one(self.advise(t), t)
        self.assertFalse(p["facts"]["venue_stop"]["applies"])
        self.assertTrue(any("the stop has been moved since" in r
                            for r in p["reasons"]))


class WorldTests(_Case):
    username = "ca_world"

    def test_an_etoro_demo_row_is_never_called_live(self):
        _quote("BTCUSD", 60600)
        t = _trade(self.user, paper=False,
                   metadata={"broker": "etoro", "broker_env": "paper"})
        a = self.advise(t)
        p = _one(a, t)
        self.assertEqual(p["world"], "demo")
        self.assertEqual(p["world_words"], "eToro demo")
        self.assertTrue(p["requires_pin"])
        self.assertEqual((a["summary"]["live"], a["summary"]["demo"],
                          a["summary"]["paper"]), (0, 1, 0))
        self.assertNotIn("real money", a["summary"]["overall"].lower())
        self.assertNotIn("live", json.dumps(p["world_words"]).lower())

    def test_paper_is_paper(self):
        _quote("BTCUSD", 60600)
        t = _trade(self.user)
        p = _one(self.advise(t), t)
        self.assertEqual((p["world"], p["world_words"], p["requires_pin"]),
                         ("paper", "Paper trading", False))


class OrderTests(_Case):
    """A working entry is an ORDER: withdraw or keep, never R."""
    username = "ca_order"

    def test_a_working_entry_is_judged_as_an_order(self):
        _quote("BTCUSD", 60600)
        t = _trade(self.user, metadata={"entry_working": True})
        p = _one(self.advise(t), t)
        self.assertEqual(p["kind"], "order")
        self.assertEqual(p["verdict"], "hold")
        self.assertEqual(p["verdict_words"], "Keep the order working")
        self.assertIn("This is an ORDER waiting at the broker", p["reasons"][0])
        for key in ("mark", "pnl", "r_now", "r_to_stop", "r_to_target"):
            self.assertIsNone(p["numbers"][key], key)
        self.assertEqual(p["triggers"], [])

    def test_opposing_signals_say_withdraw_it(self):
        _quote("BTCUSD", 60600)
        _signal("BTCUSD", "bearish", 0.8)
        t = _trade(self.user, metadata={"entry_working": True})
        p = _one(self.advise(t), t)
        self.assertEqual(p["verdict"], "close")
        self.assertEqual(p["verdict_words"],
                         "Withdrawing the order looks right")

    def test_an_order_is_not_added_into_the_money(self):
        _quote("BTCUSD", 60600)
        a_trade = _trade(self.user)
        order = _trade(self.user, metadata={"entry_working": True})
        s = self.advise(a_trade, order)["summary"]
        self.assertEqual((s["count"], s["positions"], s["orders"]), (2, 1, 1))
        self.assertEqual(s["pnl"], 300.0)


class SelectionTests(_Case):
    username = "ca_sel"

    def test_another_users_rows_and_closed_rows_are_not_found(self):
        _quote("BTCUSD", 60600)
        mine = _trade(self.user)
        theirs = _trade(get_user_model().objects.create_user("ca_other"))
        closed = _trade(self.user, status="CLOSED")
        from brain.close_advice import advise
        a = advise(self.user, [mine.id, theirs.id, closed.id, 999999, "x"])
        self.assertEqual([p["trade_id"] for p in a["positions"]], [mine.id])
        self.assertEqual(a["not_found"], [theirs.id, closed.id, 999999, "x"])
        # One sentence for all of them: "not yours" would confirm the row.
        self.assertEqual(a["not_found_words"],
                         "4 of the ticked rows were not found, not yours, or "
                         "no longer open, and were left out.")
        self.assertNotIn(theirs.id, [p["trade_id"] for p in a["positions"]])

    def test_the_summary_adds_up_only_what_it_can(self):
        _quote("BTCUSD", 60600)
        _quote("ETHUSD", 3030)
        a1 = _trade(self.user)
        a2 = _trade(self.user, symbol="ETHUSD", qty="2", entry=3000,
                    stop=2940, target=3150)
        s = self.advise(a1, a2)["summary"]
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["pnl"], 360.0)
        self.assertEqual(s["pnl_text"], "+360.00 USD")
        self.assertEqual(s["capital_freed_text"], "36,000.00 USD")
        self.assertEqual(s["paper"], 2)
        self.assertEqual(s["overall"], "Nothing here needs closing — hold "
                                       "all 2.")

    def test_one_unmeasured_row_makes_the_total_unmeasured(self):
        _quote("BTCUSD", 60600)
        _quote("ETHUSD", 3030, age_seconds=7200)
        a1 = _trade(self.user)
        a2 = _trade(self.user, symbol="ETHUSD", qty="2", entry=3000,
                    stop=2940, target=3150)
        s = self.advise(a1, a2)["summary"]
        self.assertIsNone(s["pnl"])
        self.assertEqual(s["pnl_text"], "—")
        self.assertIn("1 of the 2 positions have no measured profit or loss",
                      s["pnl_note"])
        self.assertIn("close 0", s["overall"] + " close 0")  # no crash
        self.assertIn("1 can't be judged (no fresh price)", s["overall"])

    def test_a_mixed_read_names_what_to_close(self):
        _quote("BTCUSD", 58000)
        _quote("ETHUSD", 3030)
        a1 = _trade(self.user)
        a2 = _trade(self.user, symbol="ETHUSD", qty="2", entry=3000,
                    stop=2940, target=3150)
        s = self.advise(a1, a2)["summary"]
        self.assertEqual(s["overall"], "Sauron's read: close 1 (BTCUSD); "
                                       "hold 1.")

    def test_another_users_book_does_not_count_as_concentration(self):
        """The watcher's overlap audit is platform-wide; this answer is one
        person's, and must neither count nor name another book's rules."""
        _quote("BTCUSD", 60600)
        other = get_user_model().objects.create_user("ca_sel_other")
        _trade(other, rule="their_rule_a")
        _trade(other, rule="their_rule_b")
        t = _trade(self.user, rule="my_rule")
        p = _one(self.advise(t), t)
        self.assertNotIn("concentration", [x["code"] for x in p["triggers"]])
        self.assertNotIn("their_rule", json.dumps(p))
        self.assertEqual(p["verdict"], "hold")

    def test_the_users_own_doubling_up_is_concentration(self):
        _quote("BTCUSD", 60600)
        _trade(self.user, rule="rule_a")
        t = _trade(self.user, rule="rule_b")
        p = _one(self.advise(t), t)
        self.assertIn("concentration", [x["code"] for x in p["triggers"]])
        self.assertEqual(p["verdict"], "trim_or_tighten")

    def test_bot_position_is_the_passes_own_normalisation(self):
        """One dict for one row, whether the beat or a person asks."""
        from brain.position_review import bot_position, open_positions
        _quote("BTCUSD", 60600)
        t = _trade(self.user)
        from_pass = [p for p in open_positions()
                     if p["book"] == "bot" and p["position_id"] == t.id][0]
        self.assertEqual(bot_position(t), from_pass)

    def test_asking_changes_nothing(self):
        from alerts.models import Notification
        from brain.position_review_models import PositionReview
        _quote("BTCUSD", 58000)
        t = _trade(self.user)
        self.advise(t)
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(PositionReview.objects.count(), 0)


# ══════════════════════════════════════════════════════════════════════════
# The model half
# ══════════════════════════════════════════════════════════════════════════

def _stub(raw, *, recorder=None, raises=None, usage=None):
    """Patch the agent so no network call is made and the call is countable."""
    usage = usage or {"input_tokens": 2400, "output_tokens": 500,
                      "cost_usd": 0.014}

    def patched_init(self, *a, **kw):
        self.agent_name = "close_advisor"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        if raises is not None:
            self.provider.complete = MagicMock(side_effect=raises)
        else:
            self.provider.complete = MagicMock(return_value=(raw, usage))
        if recorder is not None:
            recorder.append(self)
    return patch("brain.close_advice.CloseAdvisorAgent.__init__",
                 patched_init)


KEY = {"ANTHROPIC_API_KEY": "sk-test"}


class ModelPassTests(_Case):
    username = "ca_model"

    def setUp(self):
        super().setUp()
        _quote("BTCUSD", 58000)
        _quote("ETHUSD", 3030)
        self.t1 = _trade(self.user)                               # close
        self.t2 = _trade(self.user, symbol="ETHUSD", qty="2", entry=3000,
                         stop=2940, target=3150)                  # hold

    def _answer(self, parsed):
        return json.dumps(parsed)

    def test_one_call_for_the_whole_selection_folded_in_and_clamped(self):
        rec = []
        raw = self._answer({
            "positions": [
                {"trade_id": self.t1.id, "verdict": "close",
                 "reasoning": "It is through its stop.", "confidence": 1.7},
                {"trade_id": self.t2.id, "verdict": "trim_or_tighten",
                 "reasoning": "Momentum is fading.", "confidence": "high"},
                {"trade_id": 999999, "verdict": "close", "reasoning": "x"},
            ],
            "overall": "Close BTC, keep an eye on ETH."})
        with _stub(raw, recorder=rec), \
                patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend",
                      return_value=(True, "ok")):
            a = self.advise(self.t1, self.t2, use_model=True)
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0].provider.complete.call_count, 1)
        kwargs = rec[0].provider.complete.call_args.kwargs
        self.assertEqual(kwargs["agent_name"], "close_advisor")
        self.assertIn("close_advice:user=%d" % self.user.pk,
                      kwargs["source_ref"])
        # The snapshot never calls a demo row live and carries the rules.
        self.assertIn('"rule_based_verdict": "close"', kwargs["user_message"])

        m = a["model"]
        self.assertTrue(m["used"])
        self.assertEqual(m["overall"], "Close BTC, keep an eye on ETH.")
        self.assertEqual(m["note"], "")
        p1, p2 = _one(a, self.t1), _one(a, self.t2)
        self.assertEqual(p1["model"]["verdict"], "close")
        self.assertEqual(p1["model"]["confidence"], 1.0)
        self.assertTrue(p1["model"]["agrees"])
        self.assertEqual(p2["model"]["verdict"], "trim_or_tighten")
        self.assertIsNone(p2["model"]["confidence"])
        self.assertFalse(p2["model"]["agrees"])
        # The rule-based answer is never overwritten by the model's.
        self.assertEqual((p1["verdict"], p2["verdict"]), ("close", "hold"))

    def test_a_garbled_verdict_falls_back_to_the_rules(self):
        raw = self._answer({"positions": [
            {"trade_id": self.t2.id, "verdict": "SELL EVERYTHING NOW",
             "reasoning": "!!!", "confidence": 0.9}], "overall": ""})
        with _stub(raw), patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")):
            a = self.advise(self.t1, self.t2, use_model=True)
        p2 = _one(a, self.t2)
        self.assertEqual(p2["model"]["verdict"], "hold")
        self.assertIn("The AI said nothing about BTCUSD", a["model"]["note"])

    def test_an_unknown_position_stays_unknown_whatever_the_model_says(self):
        _quote("ETHUSD", 3030, age_seconds=7200)
        raw = self._answer({"positions": [
            {"trade_id": self.t2.id, "verdict": "close",
             "reasoning": "Looks weak.", "confidence": 0.8}]})
        with _stub(raw), patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")):
            a = self.advise(self.t2, use_model=True)
        self.assertEqual(_one(a, self.t2)["model"]["verdict"], "unknown")

    def test_an_unreadable_answer_leaves_the_rules_alone(self):
        with _stub("I think you should close it."), \
                patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")):
            a = self.advise(self.t1, self.t2, use_model=True)
        self.assertFalse(a["model"]["used"])
        self.assertEqual(a["model"]["note"],
                         "The AI part is missing: its answer could not be "
                         "read. This is Sauron's rule-based answer only.")
        self.assertNotIn("model", _one(a, self.t1))
        self.assertEqual(_one(a, self.t1)["verdict"], "close")

    def test_keyless_says_so_and_calls_nothing(self):
        rec = []
        env = {k: v for k, v in os.environ.items()
               if k != "ANTHROPIC_API_KEY"}
        with _stub("{}", recorder=rec), patch.dict(os.environ, env,
                                                   clear=True):
            a = self.advise(self.t1, use_model=True)
        self.assertEqual(rec, [])
        self.assertFalse(a["model"]["used"])
        self.assertEqual(a["model"]["note"],
                         "The AI part is missing: no Anthropic API key is "
                         "configured on this server. This is Sauron's "
                         "rule-based answer only.")
        self.assertEqual(_one(a, self.t1)["verdict"], "close")

    def test_a_refused_budget_says_so_and_calls_nothing(self):
        rec = []
        with _stub("{}", recorder=rec), patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend",
                      return_value=(False, "daily AI budget spent "
                                           "($15.00 of $15.00)")) as cs:
            a = self.advise(self.t1, use_model=True)
        self.assertEqual(rec, [])
        self.assertEqual(cs.call_args.kwargs["tier"], "balanced")
        self.assertIn("today's AI budget refused the call (daily AI budget "
                      "spent", a["model"]["note"])

    def test_the_budget_is_asked_for_what_this_selection_costs(self):
        """One call covers one row or fifty; the estimate handed to the
        guard grows with what is sent instead of a flat $0.08."""
        seen = []
        for trades in ((self.t1,), (self.t1, self.t2)):
            with _stub("{}"), patch.dict(os.environ, KEY), \
                    patch("ai_agents.spend.can_spend",
                          return_value=(False, "no")) as cs:
                self.advise(*trades, use_model=True)
            seen.append(cs.call_args.kwargs["estimated_usd"])
        self.assertGreater(seen[1], seen[0])
        self.assertGreaterEqual(seen[0], 0.02)

    def test_fifty_rows_are_priced_as_fifty(self):
        """The reviewer's arithmetic: fifty rows of pretty-printed facts is
        tens of thousands of tokens in, several thousand out — around
        $0.25-0.35 on the balanced tier. The estimate must not sit below
        that, or the guard waves the day's last call through."""
        from brain.close_advice import (build_snapshot, context_for,
                                        estimated_usd)
        a = self.advise(self.t1)
        snap = build_snapshot(a)
        one = estimated_usd(context_for(snap), 1, model="claude-sonnet-5")
        snap["positions"] = snap["positions"] * 50
        fifty = estimated_usd(context_for(snap), 50, model="claude-sonnet-5")
        self.assertGreaterEqual(fifty, 0.30)
        self.assertGreater(fifty, 5 * one)
        # And the text the estimate priced is the text that is sent.
        import brain.close_advice as ca
        rec = []
        with _stub("{}", recorder=rec), patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")), \
                patch.object(ca, "estimated_usd",
                             wraps=ca.estimated_usd) as est:
            self.advise(self.t1, use_model=True)
        self.assertEqual(
            est.call_args.args[0],
            rec[0].provider.complete.call_args.kwargs["user_message"])
        self.assertEqual(est.call_args.args[1], 1)

    def test_a_failed_call_says_so(self):
        with _stub(None, raises=RuntimeError("overloaded")), \
                patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")):
            a = self.advise(self.t1, use_model=True)
        self.assertEqual(a["model"]["note"],
                         "The AI part is missing: the model call failed "
                         "(overloaded). This is Sauron's rule-based answer "
                         "only.")

    def test_no_side_effects_beyond_the_ledger(self):
        from alerts.models import Notification
        from brain.knowledge_models import Hypothesis
        from brain.position_review_models import PositionReview
        raw = self._answer({"positions": [
            {"trade_id": self.t1.id, "verdict": "close",
             "reasoning": "Through its stop.", "confidence": 0.9}],
            "overall": "Close it."})
        with _stub(raw), patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")):
            self.advise(self.t1, use_model=True)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(PositionReview.objects.count(), 0)
        self.assertEqual(Hypothesis.objects.count(), 0)
        self.t1.refresh_from_db()
        self.assertEqual(self.t1.status, "OPEN")

    def test_the_agent_resolves_on_the_balanced_tier_and_is_pickable(self):
        from ai_agents.catalog import resolve_agent
        from brain.close_advice import CloseAdvisorAgent
        from dashboard.views_ai_models import AGENT_GROUPS
        self.assertEqual(CloseAdvisorAgent.agent_name, "close_advisor")
        self.assertEqual(CloseAdvisorAgent.default_tier, "balanced")
        self.assertTrue(resolve_agent("close_advisor", "balanced"))
        rows = {name: tier for _, rs in AGENT_GROUPS for name, _, tier in rs}
        self.assertEqual(rows.get("close_advisor"), "balanced")


class NoCloseMachineryIsReachableTests(SimpleTestCase):
    """The adviser PROPOSES; the operator acts through views_close.py.
    The same guard the position watcher carries
    (tests/test_position_review.NoCloseMachineryIsReachableTests)."""

    FORBIDDEN = ("execute_close", "_close_trade", "retry_trade_close",
                 "kill_switch", "market_order", "_submit_close_order")

    def test_the_adviser_cannot_close_anything(self):
        src = _read("brain", "close_advice.py")
        for token in self.FORBIDDEN:
            self.assertNotIn(f"{token}(", src,
                             f"brain/close_advice.py calls {token}()")


# ══════════════════════════════════════════════════════════════════════════
# The endpoints
# ══════════════════════════════════════════════════════════════════════════

class _Endpoint(_Case):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def post(self, url, payload, raw=None):
        return self.client.post(
            url, data=raw if raw is not None else json.dumps(payload),
            content_type="application/json", HTTP_HOST=HOST)


class AdviceEndpointTests(_Endpoint):
    username = "ca_ep"

    def test_it_answers_for_the_users_own_open_rows(self):
        _quote("BTCUSD", 60600)
        mine = _trade(self.user)
        theirs = _trade(get_user_model().objects.create_user("ca_ep_other"))
        resp = self.post(ADVICE, {"ids": [mine.id, theirs.id]})
        self.assertEqual(resp.status_code, 200)
        a = resp.json()
        self.assertEqual([p["trade_id"] for p in a["positions"]], [mine.id])
        self.assertEqual(a["not_found"], [theirs.id])
        self.assertFalse(a["model"]["requested"])

    def test_a_get_is_refused(self):
        self.assertEqual(self.client.get(ADVICE, HTTP_HOST=HOST).status_code,
                         405)

    def test_a_bad_body_is_a_400(self):
        for raw in ("not json", "[1, 2]", json.dumps({"ids": "1"}),
                    json.dumps({"ids": []}), json.dumps({"ids": ["abc"]}),
                    json.dumps({"ids": [True]}), json.dumps({"ids": [-3]}),
                    json.dumps({"ids": [1.5]}),
                    json.dumps({"ids": list(range(1, 52))}),
                    json.dumps({"ids": [1], "model": "yes"})):
            resp = self.post(ADVICE, None, raw=raw)
            self.assertEqual(resp.status_code, 400, raw)
            self.assertIn("error", resp.json())

    def test_fifty_is_allowed(self):
        resp = self.post(ADVICE, {"ids": list(range(1, 51))})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["not_found"]), 50)

    def test_the_model_flag_reaches_the_adviser(self):
        _quote("BTCUSD", 60600)
        t = _trade(self.user)
        with patch("brain.close_advice.advise",
                   return_value={"ok": 1}) as adv:
            self.post(ADVICE, {"ids": [t.id, str(t.id)], "model": True})
        adv.assert_called_once_with(self.user, [t.id], use_model=True)

    def test_it_needs_a_login(self):
        """Redirected to the door like every sibling — the answer never
        reaches an anonymous caller, and nothing is closed."""
        _quote("BTCUSD", 60600)
        t = _trade(self.user)
        self.client.logout()
        with mock.patch("bot_program.manual_close.execute_close") as ex:
            for url in (ADVICE, PREVIEW, CLOSE):
                resp = self.post(url, {"ids": [t.id]})
                self.assertEqual(resp.status_code, 302, url)
                self.assertIn("next=" + url, resp["Location"])
        self.assertFalse(ex.called)

    def test_csrf_is_enforced(self):
        """No csrf_exempt: the page's token is the one the endpoint takes."""
        _quote("BTCUSD", 60600)
        t = _trade(self.user)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        strict.get("/positions/", HTTP_HOST=HOST)
        token = strict.cookies["csrftoken"].value
        body = json.dumps({"ids": [t.id]})
        for url in (ADVICE, PREVIEW, CLOSE):
            refused = strict.post(url, data=body,
                                  content_type="application/json",
                                  HTTP_HOST=HOST)
            self.assertEqual(refused.status_code, 403, url)
        with mock.patch("bot_program.manual_close.execute_close") as ex:
            ok = strict.post(ADVICE, data=body,
                             content_type="application/json",
                             HTTP_HOST=HOST, HTTP_X_CSRFTOKEN=token)
            self.assertFalse(ex.called)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["positions"][0]["trade_id"], t.id)


def _closed_ok(user, trade, *, pin_ok):
    """What execute_close answers on success — and the row really closes,
    so the re-read after the loop sees it gone."""
    type(trade).objects.filter(pk=trade.pk).update(
        status="CLOSED", closed_at=timezone.now())
    return {"ok": True, "trade_id": trade.id, "symbol": trade.symbol,
            "side": trade.side, "qty": float(trade.qty), "exit": 60600.0,
            "pnl": 12.5, "r": 0.4, "outcome": "manual_close"}


class CloseSelectedTests(_Endpoint):
    username = "ca_cs"

    def setUp(self):
        super().setUp()
        _quote("BTCUSD", 60600)
        _quote("ETHUSD", 3030)
        _quote("SOLUSD", 150)
        self.a = _trade(self.user)
        self.b = _trade(self.user, symbol="ETHUSD", qty="2", entry=3000,
                        stop=2940, target=3150)
        self.other = _trade(self.user, symbol="SOLUSD", qty="10", entry=150,
                            stop=147, target=156)

    def test_preview_counts_only_the_ticked_rows(self):
        resp = self.post(PREVIEW, {"ids": [self.a.id, self.b.id, 999999]})
        self.assertEqual(resp.status_code, 200)
        p = resp.json()
        self.assertEqual(p["count"], 2)
        self.assertEqual(p["ids"], [self.a.id, self.b.id])
        self.assertEqual(p["missing"], [999999])
        self.assertEqual(p["worlds"], {"live": 0, "demo": 0, "paper": 2})
        self.assertFalse(p["needs_pin"])
        # Money as the house prints it, from the preview's own P&L.
        self.assertRegex(p["pnl_text"], r"^[+-][\d,]+\.\d\d USD$")
        self.assertNotIn("SOLUSD", json.dumps(p))

    def test_preview_counts_a_demo_row_apart_from_real_money(self):
        demo = _trade(self.user, paper=False, symbol="BTCUSD",
                      metadata={"broker": "etoro", "broker_env": "paper"})
        with patch("bot_program.manual_close.preview_close",
                   return_value={"venue": "live", "pnl": 1.0}):
            p = self.post(PREVIEW, {"ids": [demo.id]}).json()
        self.assertEqual(p["worlds"], {"live": 0, "demo": 1, "paper": 0})
        # The top-level counts too — not only the page script's `worlds`.
        # preview_close says "live" for any paper=False row; any other
        # reader of this JSON must not be told a demo row is real money.
        self.assertEqual((p["live"], p["demo"], p["paper"]), (0, 1, 0))
        self.assertEqual([r["world"] for r in p["rows"]], ["demo"])
        self.assertNotIn('"live"', json.dumps(p["rows"]))
        self.assertTrue(p["needs_pin"])

    def test_only_the_selected_rows_are_closed(self):
        with patch("bot_program.manual_close.execute_close",
                   side_effect=_closed_ok) as ex:
            resp = self.post(CLOSE, {"ids": [self.a.id, self.b.id]})
        self.assertEqual(resp.status_code, 200)
        out = resp.json()
        closed_ids = [c.args[1].id for c in ex.call_args_list]
        self.assertEqual(closed_ids, [self.a.id, self.b.id])
        self.assertEqual(out["n_closed"], 2)
        self.assertEqual([c["id"] for c in out["closed"]],
                         [self.a.id, self.b.id])
        self.assertEqual(out["closed"][0]["pnl_text"], "+12.50 USD")
        self.assertEqual(out["still_open"], 0)
        self.assertTrue(out["flat"])
        self.other.refresh_from_db()
        self.assertEqual(self.other.status, "OPEN")

    def test_a_vanished_row_is_reported_never_replaced(self):
        type(self.b).objects.filter(pk=self.b.pk).update(status="CLOSED")
        with patch("bot_program.manual_close.execute_close",
                   side_effect=_closed_ok) as ex:
            out = self.post(CLOSE, {"ids": [self.a.id, self.b.id]}).json()
        self.assertEqual([c.args[1].id for c in ex.call_args_list],
                         [self.a.id])
        self.assertEqual(out["missing"], [self.b.id])
        self.assertEqual(out["n_closed"], 1)
        self.other.refresh_from_db()
        self.assertEqual(self.other.status, "OPEN")

    def test_another_users_row_is_not_closed(self):
        theirs = _trade(get_user_model().objects.create_user("ca_cs_other"))
        with patch("bot_program.manual_close.execute_close",
                   side_effect=_closed_ok) as ex:
            out = self.post(CLOSE, {"ids": [theirs.id]}).json()
        self.assertFalse(ex.called)
        self.assertEqual(out["missing"], [theirs.id])
        self.assertEqual(out["n_closed"], 0)

    def test_a_wrong_or_missing_pin_closes_nothing_at_all(self):
        """All or nothing: the paper row does NOT close because the live
        one is refused — close-all's half-a-book outcome, ruled out."""
        live = _trade(self.user, paper=False, symbol="BTCUSD",
                      metadata={"broker": "etoro", "broker_env": "real"})
        _pin(self.user)
        for payload in ({"ids": [self.a.id, live.id]},
                        {"ids": [self.a.id, live.id], "pin": "0000"}):
            with patch("bot_program.manual_close.execute_close",
                       side_effect=_closed_ok) as ex:
                resp = self.post(CLOSE, payload)
            self.assertEqual(resp.status_code, 403, payload)
            self.assertFalse(ex.called, payload)
            out = resp.json()
            self.assertTrue(out["pin_required"])
            self.assertIn("Nothing was closed.", out["error"])
            self.assertEqual(out["n_closed"], 0)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, "OPEN")

    def test_the_right_pin_closes_the_whole_batch(self):
        live = _trade(self.user, paper=False, symbol="BTCUSD",
                      metadata={"broker": "etoro", "broker_env": "real"})
        _pin(self.user)
        with patch("bot_program.manual_close.execute_close",
                   side_effect=_closed_ok) as ex:
            out = self.post(CLOSE, {"ids": [self.a.id, live.id],
                                    "pin": PIN}).json()
        self.assertEqual([c.args[1].id for c in ex.call_args_list],
                         [self.a.id, live.id])
        self.assertTrue(all(c.kwargs["pin_ok"] for c in ex.call_args_list))
        self.assertEqual(out["n_closed"], 2)

    def test_a_paper_only_selection_needs_no_pin(self):
        with patch("bot_program.manual_close.execute_close",
                   side_effect=_closed_ok) as ex:
            out = self.post(CLOSE, {"ids": [self.a.id]}).json()
        self.assertEqual(ex.call_count, 1)
        self.assertEqual(out["n_closed"], 1)

    def test_a_refused_close_is_reported_and_the_selection_is_not_flat(self):
        def refuse(user, trade, *, pin_ok):
            return {"error": "broker unreachable", "still_open": True}
        with patch("bot_program.manual_close.execute_close",
                   side_effect=refuse):
            out = self.post(CLOSE, {"ids": [self.a.id]}).json()
        self.assertEqual(out["n_failed"], 1)
        self.assertEqual(out["failed"][0]["error"], "broker unreachable")
        self.assertEqual(out["still_open"], 1)
        self.assertFalse(out["flat"])

    def test_get_and_bad_bodies_are_refused(self):
        for url in (PREVIEW, CLOSE):
            self.assertEqual(self.client.get(url, HTTP_HOST=HOST).status_code,
                             405)
            self.assertEqual(self.post(url, None, raw="nope").status_code,
                             400)
            self.assertEqual(self.post(url, {"ids": []}).status_code, 400)
            self.assertEqual(self.post(url, {"pin": PIN}).status_code, 400)


# ══════════════════════════════════════════════════════════════════════════
# The pages
# ══════════════════════════════════════════════════════════════════════════

class PageTests(_Endpoint):
    username = "ca_page"

    def setUp(self):
        super().setUp()
        _quote("BTCUSD", 60600)
        self.t = _trade(self.user)
        _legacy(self.user)

    def _page(self, url):
        resp = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8")

    def _check(self, page):
        ticks = re.findall(r'data-sv-select-trade="(\d+)"', page)
        # Exactly one tick: the bot row. The legacy row has no close path.
        self.assertEqual(ticks, [str(self.t.id)])
        self.assertEqual(page.count("data-sv-select-cell"), 2)
        self.assertIn('data-sv-select-all aria-label="Select every '
                      'position shown" title="Select all visible"', page)
        self.assertIn("js/sv-close-advice.js", page)
        self.assertIn("css/sv-close-advice.css", page)
        self.assertIn("data-sv-select-bar", page)
        self.assertIn(">Should I close?</button>", page)
        self.assertIn(">Close selected…</button>", page)

    def test_the_positions_page(self):
        self._check(self._page("/positions/"))

    def test_every_positions_cell_names_its_own_column(self):
        """Below 640px the table stacks into cards. Its labels used to come
        from nth-child rules in sauron.css, and the tick column shifted
        every one of them: the checkbox read SYMBOL, BTCUSD read DIRECTION.
        A data-label on the cell cannot drift from the column it names."""
        page = self._page("/positions/")
        table = re.search(r'<table class="sv-perf-table sv-stack">(.*?)'
                          r'</table>', page, flags=re.S)
        self.assertIsNotNone(table, "the open table no longer stacks")
        heads = re.findall(r"<th\b[^>]*>(.*?)</th>",
                           table.group(1).split("</thead>")[0], flags=re.S)
        for row in re.findall(r"<tr data-sv-position-row.*?</tr>",
                              table.group(1), flags=re.S):
            labels = re.findall(r'<td\b[^>]*\bdata-label="([^"]*)"', row)
            self.assertEqual(len(labels), len(re.findall(r"<td\b", row)),
                             "a cell has no data-label")
            self.assertEqual(labels[0], "Select")
            # Every other label is its own header's text, in order.
            self.assertEqual(
                [lb.replace("&amp;", "&") for lb in labels[1:]],
                [re.sub(r"<[^>]+>", "", h).replace("&amp;", "&").strip()
                 for h in heads[1:]])

    def test_a_phone_can_still_select_all(self):
        """The header row is visually hidden when the table stacks, and
        its "select all" with it; the phone gets its own, in the card the
        ticks live in and outside the live region."""
        page = self._page("/positions/")
        card = page.split("data-sv-select-scope", 1)[1]
        self.assertIn('<label class="sv-sel-all-phone" '
                      'data-sv-select-all-wrap hidden><input type="checkbox" '
                      'class="sv-sel-box" data-sv-select-all', card)
        self.assertLess(card.index("data-sv-select-all-wrap"),
                        card.index('data-sv-live="pos-open"'))
        frag = self._page("/positions/live/")
        self.assertNotIn("data-sv-select-all-wrap", frag)

    def test_the_portfolio_page(self):
        self._check(self._page("/portfolio/"))

    def test_the_live_fragments_carry_the_ticks_but_not_the_bar(self):
        for url in ("/positions/live/", "/portfolio/live/"):
            frag = self._page(url)
            self.assertIn('data-sv-select-trade="%d"' % self.t.id, frag, url)
            self.assertNotIn("data-sv-select-bar", frag, url)

    def test_the_fathers_page_asks_about_its_one_position(self):
        page = self._page("/forensics/%d/" % self.t.id)
        self.assertIn('data-sv-advice-ids="%d" data-sv-advice-no-close="1"'
                      % self.t.id, page)
        self.assertIn(">Should I close?</button>", page)
        self.assertIn("js/sv-close-advice.js", page)
        self.assertIn("css/sv-close-advice.css", page)
        # Beside the close button, above it.
        self.assertLess(page.index("data-sv-advice-ids"),
                        page.index('id="pdCloseBtn"'))

    def test_a_closed_positions_page_offers_no_question(self):
        closed = _trade(self.user, status="CLOSED")
        page = self._page("/forensics/%d/" % closed.id)
        self.assertNotIn("data-sv-advice-ids", page)


class ScriptTests(SimpleTestCase):
    def setUp(self):
        self.js = _read("static", "js", "sv-close-advice.js")
        self.css = _read("static", "css", "sv-close-advice.css")

    def test_closing_from_the_advice_keeps_the_failed_rows_ticked(self):
        """closeSelected unticks exactly the rows that closed. The advice
        dialog's own onClosed used to clear EVERY advised id on top of
        that, so after "PARTIALLY closed — 1 STILL OPEN" the row still
        open had lost the tick needed to retry it."""
        block = self.js.split("closeThese.onclick = function () {", 1)[1] \
            .split("\n                };", 1)[0]
        self.assertIn("closeSelected(open,", block)
        self.assertNotIn("clearIds(", block)
        self.assertIn("clearIds((res.closed || []).map(function (c) "
                      "{ return c.id; }));", self.js)

    def test_a_pending_row_does_not_wear_the_hold_colour(self):
        self.assertIn('return p.pending ? "is-pending" : verdictClass(p.verdict);',
                      self.js)
        self.assertIn(".sv-adv-chip.is-pending", self.css)
        self.assertIn('if (s.pending) reads.push(s.pending + " already being '
                      'closed");', self.js)

    def test_the_phone_box_selects_its_card(self):
        self.assertIn('all.closest("table") || '
                      'all.closest("[data-sv-select-scope]") || d', self.js)
        self.assertIn("each(boxes(scopeOf(t)), function (b) {", self.js)
        phone = self.css.split("@media (max-width: 640px)", 1)[1]
        self.assertIn(".sv-sel-all-phone:not([hidden])", phone)
        self.assertIn(".sv-sel-all-phone { display: none; }",
                      self.css.split("@media", 1)[0])

    def test_a_tick_is_not_a_click_on_the_row(self):
        card = _read("static", "js", "sv-position-card.js")
        block = card.split("function rowNav(", 1)[1].split("\n    }", 1)[0]
        self.assertIn("e.target.closest(NOT_THE_ROW)", block)
        guard = card.split("var NOT_THE_ROW = ", 1)[1].split(";", 1)[0]
        for part in ("input", "label", "[data-sv-select-cell]"):
            self.assertIn(part, guard)

    def test_the_live_region_says_when_it_rebuilt_a_region(self):
        live = _read("templates", "_partials", "live_region.html")
        self.assertIn("new CustomEvent('sv:live-swapped'", live)
        self.assertEqual(live.count("announce(name, node);"), 2)
        self.assertIn('d.addEventListener("sv:live-swapped", reapply);',
                      self.js)

    def test_the_script_talks_to_the_three_endpoints_only(self):
        for url in (ADVICE, PREVIEW, CLOSE):
            self.assertIn('"%s"' % url, self.js)
        self.assertNotIn("/close-all/", self.js)
        self.assertIn('secretLabel: p.needs_pin ? "Trading PIN" : undefined',
                      self.js)
        self.assertIn("{ ids: p.ids, pin:", self.js)
        self.assertIn("if (w.svLiveRefresh) w.svLiveRefresh();", self.js)
        self.assertIn("if (w.refreshPanelCounts) w.refreshPanelCounts();",
                      self.js)
        self.assertIn("Ask Sauron to reason about it (AI)", self.js)

    def test_server_text_is_never_parsed_as_markup(self):
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("insertAdjacentHTML", self.js)

    def test_no_selection_state_is_written_into_the_regions_markup(self):
        """The refresher swaps a region when its markup changed; a class or
        attribute stamped on a ticked row would rebuild it every sweep."""
        self.assertNotIn("classList", self.js.split("function reapply(", 1)[1]
                         .split("function tick(", 1)[0])
        self.assertNotIn(".disabled", self.js.split("function paint(", 1)[1]
                         .split("function tick(", 1)[0])
        self.assertIn(":has(> td > .sv-sel-box:checked)", self.css)

    def test_the_sheet_uses_tokens_and_the_ladder(self):
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", self.css), [])
        for z in re.findall(r"z-index\s*:\s*([^;]+);", self.css):
            self.assertRegex(z.strip(), r"^(calc\()?var\(--z-", z)
        self.assertIn("@media (max-width: 640px)", self.css)


@unittest.skipUnless(NODE, "node is not installed")
class ScriptUnderNodeTests(SimpleTestCase):
    """The selection record and the world words, run as shipped."""

    def _run(self, expr):
        src = _read("static", "js", "sv-close-advice.js")
        prelude = (
            "var listeners = {};\n"
            "var document = {readyState: 'complete', cookie: '',\n"
            "  addEventListener: function (n, f) { listeners[n] = f; },\n"
            "  querySelectorAll: function () { return []; }};\n"
            "var window = {};\n")
        prog = (prelude + src.replace("(window, document);",
                                      "(window, document);", 1)
                + "\nprocess.stdout.write(JSON.stringify(" + expr + "));\n")
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="ca-js-"))
        (tmp / "t.js").write_text(prog, encoding="utf-8")
        out = subprocess.run([NODE, str(tmp / "t.js")], capture_output=True,
                             text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_rows_that_left_the_page_leave_the_selection(self):
        self.assertEqual(
            self._run('window.SVCloseAdvice.prune(["7", "3", "9"], ["9", "7"])'),
            ["7", "9"])

    def test_a_demo_row_is_never_counted_as_real_money(self):
        self.assertEqual(
            self._run('[window.SVCloseAdvice.worldWords({live: 1, demo: 2, '
                      'paper: 1}), window.SVCloseAdvice.worldWords({demo: 1}),'
                      ' window.SVCloseAdvice.worldWords({})]'),
            ["1 real money · 2 broker demo · 1 paper", "1 broker demo", "—"])

    def test_the_listeners_are_wired(self):
        self.assertEqual(
            self._run('Object.keys(listeners).sort()'),
            ["change", "click", "sv:live-swapped"])
