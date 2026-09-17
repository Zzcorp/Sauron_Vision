"""One number, two opposite diagnoses (2026-09-15).

`preflight_live` printed:

    GLDM         newest 4h bar 5.7h ago

Read at 01:40 UTC that is CORRECT — NYSE shut 5.7 hours earlier and the bar
writer is working perfectly. The identical line at 15:00 UTC would mean the
feed is 34 refresh cycles behind, because `refresh-bot-bars` runs every 600
seconds. Nothing on the line separated the two, and the operator asked
whether the feed was broken.

It nearly cost a wrong repair: the age was read as a stale feed, a cause was
drafted against `market_data/bot_bars.py`, and only reading the mute path
line by line showed that a muted venue still writes from the public feed. A
number with no unit of comparison beside it does not merely fail to inform —
it actively invites a conclusion.

THE SIX HOURS ARE NOT DECORATION

`MAX_BAR_AGE_SECONDS = 6 * 3600` is enforced in three places:

    signals/performance.py    _bar_close_fallback  -> no price, no outcome
    signals/lifecycle.py      the SMC pass         -> no resolution
    engine/paper_trader.py    ticker()             -> cannot mark a position

Past it a symbol produces no evidence whatsoever: no outcome, no
`realized_r`, and therefore nothing for the promotion ladder, whose gates
(`PROMO_PAPER_TO_LIVE_SMALL_MIN_N = 20`) count exactly those rows. For a shut
market that is correct and temporary. For an open market it is a dead feed.
For crypto, which never shuts, it is always a dead feed.

WHAT THESE TESTS CONFRONT

Not the number 6. The preflight must not RESTATE it — a fourth copy is the
copy that drifts — so one test reads the constant out of all three enforcing
modules and demands they agree with what the preflight imports. The rest fix
the branching: an open market and a shut one must not produce the same
finding from the same age.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program.management.commands import preflight_live as pf

OPEN_MARKET = {"session": "NYSE", "code": "NYSE", "is_open": True}
SHUT_MARKET = {"session": "NYSE", "code": "NYSE", "is_open": False}
CRYPTO_MARKET = {"session": "CRYPTO", "code": "CRYPTO", "is_open": True}

#: The shape `_market_note` / `_bar_findings` receive from the .values() query.
def _row(asset_class="etf", exchange="ARCA"):
    return {"timestamp": None, "close": Decimal("1"),
            "instrument__asset_class": asset_class,
            "instrument__exchange": exchange}


def _at(hours_old):
    now = timezone.now()
    return now - timedelta(hours=hours_old), now


class TheSixHoursAreOneNumberTests(SimpleTestCase):
    """The preflight may report the limit. It may not own it."""

    def test_the_preflight_imports_the_limit_it_reports(self):
        from signals.performance import MAX_BAR_AGE_SECONDS
        self.assertEqual(pf.BAR_DEAD_HOURS, MAX_BAR_AGE_SECONDS / 3600.0)

    def test_all_three_enforcers_agree(self):
        """If any of them moves alone, a symbol is dead for the paper venue
        and alive for the signal lifecycle, or the reverse — and the
        preflight's line names a threshold that governs only one of them."""
        from bot_program.engine.paper_trader import PaperTrader
        from signals.lifecycle import DEFAULT_MAX_BAR_AGE_SECONDS
        from signals.performance import MAX_BAR_AGE_SECONDS
        self.assertEqual(
            {MAX_BAR_AGE_SECONDS,
             DEFAULT_MAX_BAR_AGE_SECONDS,
             PaperTrader.MAX_BAR_AGE_SECONDS},
            {MAX_BAR_AGE_SECONDS},
            "the three modules that decide whether a bar can price anything "
            "no longer agree; the preflight reports one of them and the "
            "operator will read it as all three")

    def test_the_preflight_does_not_restate_the_number(self):
        """A literal 6 here is the copy that drifts."""
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "management"
               / "commands" / "preflight_live.py").read_text(encoding="utf-8")
        self.assertIn("from signals.performance import MAX_BAR_AGE_SECONDS",
                      src)
        self.assertNotIn("BAR_DEAD_HOURS = 6", src)

    def test_the_late_threshold_clears_one_whole_bar_period(self):
        """4h candles: an age below one period proves nothing about the
        writer, so a lower bar would flag every healthy feed."""
        self.assertGreaterEqual(pf.BAR_LATE_HOURS_WHILE_OPEN, 4.0)
        self.assertLess(pf.BAR_LATE_HOURS_WHILE_OPEN, pf.BAR_DEAD_HOURS)


class TheSameAgeMeansTwoDifferentThingsTests(SimpleTestCase):
    """5.7 hours, twice, with opposite verdicts."""

    def _findings(self, market, hours_old):
        newest, now = _at(hours_old)
        blockers, warnings = [], []
        with mock.patch("core.exchange_status.market_status_for",
                        return_value=market):
            note = pf._market_note(_row(), newest, now)
            pf._bar_findings("GLDM", _row(), newest, now, blockers, warnings)
        return note, blockers, warnings

    def test_a_shut_market_at_five_point_seven_hours_is_not_a_failure(self):
        note, blockers, warnings = self._findings(SHUT_MARKET, 5.7)
        self.assertIn("shut", note)
        self.assertEqual(blockers, [])
        self.assertEqual(warnings, [])

    def test_an_open_market_at_five_point_seven_hours_is_a_failure(self):
        note, blockers, warnings = self._findings(OPEN_MARKET, 5.7)
        self.assertIn("OPEN", note)
        self.assertEqual(len(blockers), 1, blockers)
        self.assertIn("10 minutes", blockers[0],
                      "the blocker does not say what the expected cadence is, "
                      "so the reader cannot tell 5.7h from normal")
        self.assertIn("GLDM", blockers[0])

    def test_an_open_market_with_a_fresh_bar_says_so_and_stays_quiet(self):
        note, blockers, warnings = self._findings(OPEN_MARKET, 1.0)
        self.assertIn("open", note)
        self.assertEqual(blockers, [])
        self.assertEqual(warnings, [])

    def test_a_shut_market_past_the_limit_warns_without_blocking(self):
        """Correct, temporary, and the reason a paper campaign accrues
        evidence only inside sessions. Worth reading once; not a reason to
        refuse to arm."""
        note, blockers, warnings = self._findings(SHUT_MARKET, 6.5)
        self.assertEqual(blockers, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("reopens", warnings[0])
        self.assertIn("resolves nothing", note)

    def test_crypto_never_shuts_so_a_stale_bar_is_always_a_failure(self):
        """The case the market clock gets right for free: a 24/7 venue has no
        closed state to excuse the gap."""
        note, blockers, warnings = self._findings(CRYPTO_MARKET, 7.0)
        self.assertIn("OPEN", note)
        self.assertEqual(len(blockers), 1, blockers)

    def test_an_unknown_clock_says_unknown_rather_than_guessing(self):
        newest, now = _at(9.0)
        blockers, warnings = [], []
        with mock.patch("core.exchange_status.market_status_for",
                        side_effect=RuntimeError("no clock")):
            note = pf._market_note(_row(), newest, now)
            pf._bar_findings("GLDM", _row(), newest, now, blockers, warnings)
        self.assertIn("unknown", note)
        self.assertEqual(blockers, [],
                         "a market it cannot place was reported as a feed "
                         "failure; an unknown clock is not evidence of one")

    def test_a_missing_clock_never_takes_the_page(self):
        """The preflight runs with a finger over the arming button. A helper
        that raises must cost the clause, never the command."""
        newest, now = _at(1.0)
        with mock.patch("core.exchange_status.market_status_for",
                        side_effect=Exception("boom")):
            self.assertIsInstance(pf._market_note(_row(), newest, now), str)


class TheLineCarriesBothTests(TestCase):
    """End to end, through the command, with the real market clock."""

    def setUp(self):
        self.user = User.objects.create_user("bar_age_u", password="x")
        from bot_program.models import AssetBotConfig, IBKRAccount
        acct = IBKRAccount.objects.create(user=self.user, port=4004)
        acct.set_credentials("DU1234567")
        acct.username_enc, acct.password_enc = "x", "y"
        acct.last_equity = Decimal("10000")
        acct.last_equity_currency = "EUR"
        acct.last_equity_at = timezone.now()
        acct.save()
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="etf_pack", mode="live",
            symbols=["GLDM"], capital=Decimal("10000"),
            base_currency="EUR", enabled=True)

    def _seed(self, age_hours):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst, _ = Instrument.objects.get_or_create(
            symbol="GLDM", defaults={"name": "GLDM", "asset_class": "etf",
                                     "exchange": "ARCA"})
        PriceData.objects.update_or_create(
            instrument=inst, timeframe="4h",
            timestamp=timezone.now() - timedelta(hours=age_hours),
            defaults={"open": 1, "high": 2, "low": 1, "close": Decimal("60"),
                      "volume": 10, "source": "test"})

    def _run(self):
        out = StringIO()
        call_command("preflight_live", stdout=out)
        return out.getvalue()

    def test_the_age_never_appears_without_a_market_beside_it(self):
        self._seed(5.7)
        body = self._run()
        self.assertIn("newest 4h bar", body)
        line = next(ln for ln in body.splitlines() if "newest 4h bar" in ln)
        self.assertRegex(
            line, r"newest 4h bar .*(?i:open|shut|unknown)",
            f"the bar age is printed bare: {line!r}. That is the line that "
            f"was read as a broken feed on a correctly shut market.")

    def test_the_real_clock_is_the_one_consulted(self):
        """Not a schedule restated here. If the helper is bypassed, this
        mock is never touched and the test fails."""
        self._seed(5.7)
        with mock.patch("core.exchange_status.market_status_for",
                        return_value=SHUT_MARKET) as spy:
            self._run()
        self.assertTrue(spy.called,
                        "preflight_live no longer asks core.exchange_status "
                        "which market a symbol keeps")
