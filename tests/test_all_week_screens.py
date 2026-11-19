"""eToro's ALL-WEEK INSTRUMENTS, SCREEN BY SCREEN (2026-11-19). Display
only; money direction none.

The operator, 2026-11-19: yes, the screens say "open 24/7 at eToro" at the
weekend for eToro's all-week instruments; the bots keep no new entry at
the weekend, for now. Every surface of the build map
(scratchpad/display247/map.md) that said their market was shut, closed or
opening, asked at Saturday 21 November 2026, 15:00 UTC (and in a break):

  A. ONE PRICE (market_data/one_quote.py, the browser's mirror pinned by
     tests/one_quote_words.json): "open · eToro 24/7 · eToro bid · 4 min";
     a stand-in keeps its own market's time (its age says how old it is);
     "pause · eToro bid 22:00 · eToro reopens 22:30 UTC" in a break.
  B. THE MARKET BADGE on the instrument page and the instruments list:
     eToro's own, "24/7" or "PAUSE", under its own session code, and the
     badge poller's rows (/api/exchange-status/ "all_week").
  C. THE SIGNALS: the rail's card and popup, the headband's dropdown,
     /signals/, the new-signal banner, Telegram and its copies, the bell.
  D. THE POSITIONS: the position page's note, /positions/' mark hover,
     the Horde's Market line, the close advice.
  E. THE TICKET: its own display key and its words.
  F. THE ORCS' next wake, and Telegram's /why.

Every other instrument (forex, copper, platinum, palladium, EURUSD,
stocks, crypto) reads exactly as before, and so do the indices' weekday
nights. Every instant is fixed; fakes only; no network, no broker, no
model. Every price is invented. The oil platform symbol is read from its
pin (eToro id 17), never written here.

Run with:  python manage.py test tests.test_all_week_screens
"""
import json
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from tests.one_quote_fixture import stamp

UTC = dt_tz.utc
FRI_2205 = datetime(2026, 11, 20, 22, 5, tzinfo=UTC)
FRI_2210 = datetime(2026, 11, 20, 22, 10, tzinfo=UTC)
SAT_1456 = datetime(2026, 11, 21, 14, 56, tzinfo=UTC)
SAT_1500 = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
SAT_2205 = datetime(2026, 11, 21, 22, 5, tzinfo=UTC)
TUE_1500 = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
TUE_2230 = datetime(2026, 11, 24, 22, 30, tzinfo=UTC)

ROWS = {"XAUUSD": ("Gold", "commodity", "COMEX"),
        "XAGUSD": ("Silver", "commodity", "COMEX"),
        "NGUSD": ("Natural Gas", "commodity", "NYMEX"),
        "SPX500": ("S&P 500", "index", "CME"),
        "NSDQ100": ("Nasdaq 100", "index", "CME"),
        "EURUSD": ("Euro / US Dollar", "forex", "FOREX"),
        "GBPUSD": ("British Pound / US Dollar", "forex", "FOREX"),
        "HGUSD": ("Copper", "commodity", "COMEX"),
        "BTCUSD": ("Bitcoin", "crypto", "CRYPTO")}
PRICES = {"XAUUSD": ("2640.10", "2640.60"), "XAGUSD": ("31.200", "31.240"),
          "NGUSD": ("3.2150", "3.2190"), "SPX500": ("6010.5", "6011.0"),
          "NSDQ100": ("21010.5", "21012.0"),
          "EURUSD": ("1.08447", "1.08457"), "HGUSD": ("4.5100", "4.5140"),
          "BTCUSD": ("65000.00", "65010.00")}


def oil():
    from bot_program.engine.etoro_client import PINNED_SYMBOL
    return PINNED_SYMBOL[17]


def gates(test, *, display=True):
    """The suite's switched-off clocks back on for one test
    (tests/__init__.py): the screens' all-week words, the rail's market
    clock and the bots' entry clock (on the branch's base, before the
    words existed, the two clocks alone: these tests then read its words)."""
    targets = [("signals.market_hold.GATE", True),
               ("bot_program.entry_timing.GATE", True)]
    try:
        import market_data.all_week_display  # noqa: F401
        targets.append(("market_data.all_week_display.GATE", display))
    except ImportError:
        pass
    for target, on in targets:
        p = mock.patch(target, on)
        p.start()
        test.addCleanup(p.stop)


def hold(test, at):
    """Every clock the server reads held at `at` (B0's hold), for one test."""
    from tests.old_design.measure import _ClockSwap
    for p in (_ClockSwap(at.timestamp, over=True),
              mock.patch("django.utils.timezone.now", return_value=at),
              mock.patch("market_data.one_quote.now", return_value=at)):
        p.start()
        test.addCleanup(p.stop)


def inst(symbol):
    from instruments.models import Instrument
    name, cls, exch = ROWS.get(symbol, ("Oil", "commodity", "NYMEX"))
    obj, _ = Instrument.objects.update_or_create(
        symbol=symbol, defaults={"name": name, "asset_class": cls,
                                 "exchange": exch, "currency": "USD",
                                 "is_active": True, "is_watchlist": True})
    return obj


def lane(user, cls, *, mode="live", name=None):
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=cls, name=name or f"aw {cls} {mode}",
        defaults={"enabled": True, "mode": mode, "symbols": [],
                  "capital": Decimal("10000"), "base_currency": "USD"})
    return cfg


def held(user, symbol, at, *, side="BUY", paper=False, read_at=None):
    """An open eToro row of `symbol` (real money; a paper row with
    paper=True), its venue stamp read at `read_at` (4 min before `at`)."""
    from bot_program.models import AssetBotTrade
    i = inst(symbol)
    bid, ask = PRICES.get(symbol, ("80.10", "80.14"))
    read = read_at or at - timedelta(minutes=4)
    meta = ({} if paper else
            {"broker": "etoro", "broker_env": "live",
             "venue_mark": stamp(bid if side == "BUY" else ask, bid, ask,
                                 at=read)})
    entry = Decimal(bid)
    t = AssetBotTrade.objects.create(
        config=lane(user, i.asset_class, mode="paper" if paper else "live"),
        asset_class=i.asset_class, symbol=symbol, side=side,
        qty=Decimal("1"), entry_price=entry, stop_loss=entry * Decimal("0.98"),
        take_profit=entry * Decimal("1.04"), status="OPEN", paper=paper,
        rule_name="trend_break_4h", metadata=meta)
    AssetBotTrade.objects.filter(pk=t.pk).update(opened_at=at - timedelta(
        hours=26))
    t.refresh_from_db()
    return t


def quote(symbol, last, source, written_at, *, bid=None, ask=None):
    from market_data.models import LiveQuote
    i = inst(symbol)
    LiveQuote.objects.update_or_create(
        instrument=i, defaults={"last": Decimal(last), "source": source,
                                "bid": None if bid is None else Decimal(bid),
                                "ask": None if ask is None else Decimal(ask),
                                "change_pct": Decimal("0.10"), "volume": 0,
                                "change_source": source})
    LiveQuote.objects.filter(instrument=i).update(updated_at=written_at)
    return i


def _text(html):
    """The page's words without its tags (one space between)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _tag(html, attr, value):
    """The first element whose `attr` is `value`: its whole markup, its
    nested elements of the same tag included."""
    m = re.search(r'<(\w+)\b[^>]*\b%s="%s"[^>]*>' % (
        re.escape(attr), re.escape(value)), html, re.S)
    if not m:
        return ""
    name, depth, at = m.group(1), 1, m.end()
    for t in re.finditer(r"<(/?)%s\b[^>]*>" % name, html[at:]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return html[m.start():at + t.end()]
    return html[m.start():]


class _Case(TestCase):
    username = "aw_screens"

    def setUp(self):
        gates(self)
        self.user = get_user_model().objects.create_user(
            self.username, password="x", is_staff=True, is_superuser=True)
        from tests.old_design.measure import tour_done
        tour_done(self.user)

    def shown(self, symbol, at, user=None):
        from market_data.one_quote import shown
        return shown(symbol, user=self.user if user is None else user,
                     now=at)


# ══════════════════════════════════════════════════════════════════════════
# A. One price
# ══════════════════════════════════════════════════════════════════════════

class OnePriceTests(_Case):
    username = "aw_one_price"

    def test_a_held_gold_price_on_saturday_reads_open_at_etoro(self):
        held(self.user, "XAUUSD", SAT_1500)
        s = self.shown("XAUUSD", SAT_1500)
        self.assertEqual(s.state, "delayed", "open at eToro: its age tiers")
        self.assertIsNone(s.shut)
        self.assertEqual(s.words(SAT_1500),
                         "open · eToro 24/7 · eToro bid · 4 min")
        self.assertEqual(s.age_text(SAT_1500), "4 min")
        p = s.payload()
        self.assertEqual(p["wk"]["open"], "open · eToro 24/7")
        self.assertIn("eToro 24/7: breaks 22:00-23:00 UTC daily",
                      s.title(SAT_1500))

    def test_a_stand_in_keeps_its_own_markets_time(self):
        """Nobody holds gold: its number is Yahoo's front-month future, and
        that market really is shut. eToro is said open; the number is said
        Yahoo's, aged from its own market's close, never an eToro price."""
        quote("XAUUSD", "2641.30", "yfinance", SAT_1500 - timedelta(
            minutes=1))
        s = self.shown("XAUUSD", SAT_1500)
        self.assertEqual(s.at, datetime(2026, 11, 20, 22, 0, tzinfo=UTC))
        self.assertEqual(
            s.words(SAT_1500),
            "open · eToro 24/7 · Yahoo GC=F, the front-month future · 17 h")
        self.assertNotIn("eToro bid", s.words(SAT_1500))

    def test_a_break_reads_pause_with_its_reopening(self):
        held(self.user, "XAUUSD", FRI_2210, read_at=FRI_2205)
        s = self.shown("XAUUSD", FRI_2210)
        self.assertEqual(s.state, "shut")
        self.assertEqual(s.words(FRI_2210),
                         "pause · eToro bid 22:00 · eToro reopens 22:30 UTC")
        self.assertEqual(s.age_text(FRI_2210),
                         "pause · eToro reopens 22:30 UTC")
        self.assertEqual(s.payload()["shut"]["word"], "pause")

    def test_natural_gas_pauses_on_saturday_night_and_gold_does_not(self):
        held(self.user, "NGUSD", SAT_2205, read_at=SAT_2205 - timedelta(
            minutes=2))
        held(self.user, "XAUUSD", SAT_2205)
        self.assertEqual(self.shown("NGUSD", SAT_2205).words(SAT_2205),
                         "pause · eToro bid 22:00 · eToro reopens 22:15 UTC")
        self.assertEqual(self.shown("XAUUSD", SAT_2205).words(SAT_2205),
                         "open · eToro 24/7 · eToro bid · 4 min")

    def test_every_other_instrument_reads_as_before(self):
        held(self.user, "EURUSD", SAT_1500,
             read_at=datetime(2026, 11, 20, 21, 58, tzinfo=UTC))
        held(self.user, "HGUSD", SAT_1500,
             read_at=datetime(2026, 11, 20, 21, 58, tzinfo=UTC))
        fx = self.shown("EURUSD", SAT_1500)
        self.assertEqual(fx.words(SAT_1500), "closed · eToro bid Fri 20 Nov "
                                             "21:58 · opens Sun 22:00 UTC")
        self.assertNotIn("wk", fx.payload())
        cu = self.shown("HGUSD", SAT_1500)
        self.assertEqual(cu.words(SAT_1500), "closed · eToro bid Fri 20 Nov "
                                             "21:58 · opens Sun 23:00 UTC")
        self.assertNotIn("wk", cu.payload())

    def test_a_weekday_reads_as_before(self):
        held(self.user, "XAUUSD", TUE_1500)
        s = self.shown("XAUUSD", TUE_1500)
        self.assertEqual(s.words(TUE_1500), "eToro bid · 4 min")
        self.assertNotIn("wk", s.payload())

    def test_with_the_words_off_gold_reads_as_before(self):
        with mock.patch("market_data.all_week_display.GATE", False):
            held(self.user, "XAUUSD", SAT_1500)
            s = self.shown("XAUUSD", SAT_1500)
            self.assertEqual(s.state, "shut")
            self.assertTrue(s.words(SAT_1500).startswith("closed · "))


# ══════════════════════════════════════════════════════════════════════════
# B. The market badge
# ══════════════════════════════════════════════════════════════════════════

class TheBadgeOnThePagesTests(_Case):
    username = "aw_badge"

    def page(self, url, at):
        hold(self, at)
        self.client.force_login(self.user)
        r = self.client.get(url, HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 200, url)
        return r.content.decode("utf-8")

    def test_the_instrument_page_on_saturday(self):
        held(self.user, "XAUUSD", SAT_1500)
        html = self.page("/instruments/XAUUSD/", SAT_1500)
        badge = _tag(html, "data-market-session", "ETORO247_18")
        self.assertTrue(badge, "eToro's own badge, under its own code")
        self.assertIn("mk-open", badge)
        self.assertIn(">24/7<", badge)
        self.assertIn('title="open · eToro 24/7 (breaks 22:00-23:00 UTC '
                      'daily, Fri 22:00-22:30)"', badge)
        self.assertNotIn('data-market-session="CME"', html)
        words = _text(_tag(html, "data-hero", "src"))
        self.assertEqual(words, "open · eToro 24/7 · eToro bid · 4 min")

    def test_the_instrument_page_in_a_break(self):
        held(self.user, "XAUUSD", FRI_2210, read_at=FRI_2205)
        html = self.page("/instruments/XAUUSD/", FRI_2210)
        badge = _tag(html, "data-market-session", "ETORO247_18")
        self.assertIn("mk-pause", badge)
        self.assertIn(">PAUSE<", badge)
        self.assertIn('title="pause · eToro reopens 22:30 UTC"', badge)
        self.assertEqual(_text(_tag(html, "data-hero", "src")),
                         "pause · eToro bid 22:00 · eToro reopens 22:30 UTC")

    def test_every_other_instruments_badge_is_as_before(self):
        held(self.user, "EURUSD", SAT_1500)
        html = self.page("/instruments/EURUSD/", SAT_1500)
        badge = _tag(html, "data-market-session", "FOREX")
        self.assertIn("mk-closed", badge)
        self.assertIn(">CLOSED<", badge)
        self.assertNotIn("ETORO247", html)

    def test_the_instruments_list(self):
        for sym in ("XAUUSD", "SPX500", "EURUSD", "HGUSD"):
            quote(sym, PRICES[sym][0], "yfinance", SAT_1500 - timedelta(
                minutes=1))
        html = self.page("/instruments/", SAT_1500)
        gold = _tag(html, "data-market-session", "ETORO247_18")
        self.assertIn(">24/7<", gold)
        self.assertIn("mk-open", gold)
        spx = _tag(html, "data-market-session", "ETORO247_27")
        self.assertIn('title="open · eToro 24/7 (short breaks; times not '
                      'published)"', spx)
        fx = _tag(html, "data-market-session", "FOREX")
        self.assertIn(">CLOSED<", fx)
        cu = re.findall(r'data-market-session="CME"', html)
        self.assertTrue(cu, "copper keeps CME's badge")

    def test_the_pollers_rows(self):
        hold(self, SAT_2205)
        self.client.force_login(self.user)
        got = self.client.get("/api/exchange-status/").json()
        rows = {r["code"]: r for r in got["all_week"]}
        self.assertEqual(rows["ETORO247_18"]["word"], "24/7")
        self.assertEqual(rows["ETORO247_22"]["word"], "PAUSE")
        self.assertEqual(rows["ETORO247_17"]["title"],
                         "pause · eToro reopens 22:15 UTC")
        codes = {r["code"] for r in got["exchanges"]}
        self.assertNotIn("ETORO247_18", codes, "never in the strip's count")
        with mock.patch("market_data.all_week_display.GATE", False):
            off = self.client.get("/api/exchange-status/").json()
        self.assertEqual((off["open_count"], off["total"]),
                         (got["open_count"], got["total"]))
        self.assertNotIn("all_week", off)


# ══════════════════════════════════════════════════════════════════════════
# C. The signals
# ══════════════════════════════════════════════════════════════════════════

def _signal(symbol, born, *, direction="bearish"):
    from signals.models import Signal
    i = inst(symbol)
    bid, _ask = PRICES.get(symbol, ("80.10", "80.14"))
    px = Decimal(bid)
    s = Signal.objects.create(
        instrument=i, signal_type="technical", direction=direction,
        urgency="medium", title=f"Lower high on {symbol}", description="d",
        rule_name="trend_break_4h", score=0.70, sub_scores={},
        price_at_signal=px, suggested_entry=px,
        suggested_stop=px * Decimal("1.01"),
        suggested_target=px * Decimal("0.98"), risk_reward_ratio=2.0,
        is_active=True)
    Signal.objects.filter(pk=s.pk).update(created_at=born)
    s.refresh_from_db()
    return s


def _card(html, signal_id):
    m = re.search(r'<div class="sr-signal-wrap[^"]*" data-signal-id="%d"'
                  % signal_id, html)
    if not m:
        return ""
    return _tag(html[m.start():], "data-signal-id", str(signal_id))


class TheSignalsTests(_Case):
    username = "aw_signals"

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)

    def partial(self, at):
        hold(self, at)
        self.client.force_login(self.user)
        r = self.client.get("/partials/signal-rail/", HTTP_HOST="127.0.0.1")
        self.assertEqual(r.status_code, 200)
        return r.content.decode("utf-8")

    def test_the_rail_card_and_its_popup_on_saturday(self):
        gold = _signal("XAUUSD", SAT_1500 - timedelta(hours=2))
        copper = _signal("HGUSD", SAT_1500 - timedelta(hours=2))
        html = self.partial(SAT_1500)
        card = _card(html, gold.pk)
        self.assertTrue(card)
        self.assertNotIn("MARKET SHUT", card)
        self.assertNotIn('data-market="shut"', card)
        self.assertIn('<span class="sr-week-tag">OPEN 24/7</span> '
                      '<span class="sr-week-note">at eToro</span>', card)
        self.assertIn("Open at eToro, which trades GOLD all week (breaks "
                      "22:00-23:00 UTC daily, Fri 22:00-22:30). Bots: no "
                      "weekend entries, by your choice. Paper: waits for "
                      "CME&#x27;s open, Sun 23:00 UTC; a live ticket fills "
                      "at eToro.", card)
        self.assertIn('<span class="sr-pop-k">market</span> open · eToro '
                      '24/7 · bots: no weekend entries, by your choice · '
                      'paper: waits for CME&#x27;s open, Sun 23:00 UTC; a '
                      'live ticket fills at eToro</div>', card)
        cu = _card(html, copper.pk)
        self.assertIn("MARKET SHUT", cu)
        self.assertIn('data-market="shut"', cu)
        self.assertNotIn("sr-week", cu)
        meta = json.loads(re.search(
            r'<div data-sv-rail-meta hidden><script type="application/json">'
            r'(.*?)</script>', html, re.S).group(1))
        self.assertEqual(meta["shut"], 1, "the SHUT chip counts copper alone")

    def test_the_indices_card_never_says_the_bots_choice(self):
        spx = _signal("SPX500", SAT_1500 - timedelta(hours=2))
        card = _card(self.partial(SAT_1500), spx.pk)
        self.assertIn("OPEN 24/7", card)
        self.assertIn("short breaks; times not published", card)
        self.assertNotIn("bots:", card)
        self.assertNotIn("Bots:", card)

    def test_a_break_on_the_card(self):
        gold = _signal("XAUUSD", FRI_2210 - timedelta(hours=1))
        card = _card(self.partial(FRI_2210), gold.pk)
        self.assertIn('class="sr-week sr-week--pause"', card)
        self.assertIn('<span class="sr-week-tag">PAUSE</span> <span '
                      'class="sr-week-note">eToro reopens 22:30 UTC</span>',
                      card)
        self.assertIn("pause · eToro reopens 22:30 UTC · bots: no weekend "
                      "entries, by your choice", card)
        self.assertIn("a live order waits for eToro&#x27;s reopening", card)

    def test_the_headband_dropdown_row(self):
        gold = _signal("XAUUSD", SAT_1500 - timedelta(hours=2))
        hold(self, SAT_1500)
        self.client.force_login(self.user)
        html = self.client.get("/instruments/", HTTP_HOST="127.0.0.1"
                               ).content.decode("utf-8")
        row = _tag(html, "data-signal-id", str(gold.pk))
        m = re.search(r'<div class="ip-dd-row sv-sig-row"[^>]*data-signal-id='
                      r'"%d".*?</div>' % gold.pk, html, re.S)
        self.assertTrue(m, "the headband's row")
        row = m.group(0)
        self.assertNotIn('data-market="shut"', row)
        self.assertIn(">OPEN 24/7 · at eToro</span>", row)
        self.assertNotIn("MARKET SHUT", row)

    def test_the_signals_page(self):
        gold = _signal("XAUUSD", SAT_1500 - timedelta(hours=2))
        _signal("HGUSD", SAT_1500 - timedelta(hours=2))
        hold(self, SAT_1500)
        self.client.force_login(self.user)
        html = self.client.get("/signals/", HTTP_HOST="127.0.0.1"
                               ).content.decode("utf-8")
        self.assertIn('<span class="sig-week" title="Open at eToro, which '
                      'trades GOLD all week', html)
        self.assertIn('<span class="sig-week-note">at eToro</span>', html)
        self.assertEqual(html.count('class="badge badge-high sig-shut"'), 1,
                         "copper's MARKET SHUT, never gold's")
        from dashboard.signal_surface import market_block
        block = market_block(gold, now=SAT_1500)
        self.assertFalse(block["shut"])
        self.assertEqual(block["week"]["tag"], "OPEN 24/7")

    def test_the_announcements(self):
        from alerts.dispatch import signal_telegram
        from alerts.models import Notification
        from alerts.notify import notify_new_signal
        from signals.announce import banner_payload
        hold(self, SAT_1500)
        gold = _signal("XAUUSD", SAT_1500)
        spx = _signal("SPX500", SAT_1500)
        cu = _signal("HGUSD", SAT_1500)
        words = "open · eToro 24/7 · bots: no weekend entries, by your choice"
        self.assertEqual(banner_payload(gold)["market"], words)
        self.assertEqual(banner_payload(spx)["market"], "open · eToro 24/7")
        self.assertEqual(banner_payload(cu)["market"],
                         "market shut · opens Sun 23:00 UTC")
        _title, lines, _mark = signal_telegram(gold)
        self.assertEqual(lines[0], "Open · eToro 24/7 · bots: no weekend "
                                   "entries, by your choice")
        _t2, cu_lines, _m2 = signal_telegram(cu)
        self.assertEqual(cu_lines[0], "Market shut · opens Sun 23:00 UTC")
        notify_new_signal(gold)
        bell = Notification.objects.filter(title__endswith="XAUUSD").first()
        self.assertTrue(bell.body.endswith(" · " + words), bell.body)

    def test_announcements_in_a_break_and_on_a_weekday(self):
        from signals.announce import banner_payload
        gas = _signal("NGUSD", SAT_2205)
        gold = _signal("XAUUSD", SAT_2205)
        hold(self, SAT_2205)
        self.assertEqual(banner_payload(gas)["market"],
                         "pause · eToro reopens 22:15 UTC · bots: no weekend "
                         "entries, by your choice")
        self.assertEqual(banner_payload(gold)["market"],
                         "open · eToro 24/7 · bots: no weekend entries, "
                         "by your choice")

    def test_an_open_markets_announcement_keeps_its_bytes(self):
        from signals.announce import banner_payload
        hold(self, TUE_1500)
        gold = _signal("XAUUSD", TUE_1500)
        self.assertNotIn("market", banner_payload(gold))


# ══════════════════════════════════════════════════════════════════════════
# D. The positions
# ══════════════════════════════════════════════════════════════════════════

class ThePositionsTests(_Case):
    username = "aw_positions"

    def notes(self, trade, at):
        from dashboard.position_summary import build_summary
        return [n["text"] for n in build_summary(trade, now=at)["notes"]]

    def test_the_position_page_note_of_a_gold_row_held_at_etoro(self):
        hold(self, SAT_1500)
        t = held(self.user, "XAUUSD", SAT_1500)
        said = self.notes(t, SAT_1500)
        self.assertIn("eToro trades XAUUSD 24/7: its price moves at the "
                      "weekend. Bots: no weekend entries, by your choice.",
                      said)
        self.assertFalse([n for n in said if "shut right now" in n], said)
        self.assertFalse([n for n in said if "normal while the market is "
                          "shut" in n], said)

    def test_the_position_page_in_a_break(self):
        hold(self, FRI_2210)
        t = held(self.user, "XAUUSD", FRI_2210, read_at=FRI_2205)
        self.assertIn("eToro pauses XAUUSD until 22:30 UTC, one of its "
                      "published breaks: the price does not move until "
                      "then.", self.notes(t, FRI_2210))

    def test_a_paper_row_and_every_other_instrument_keep_the_shut_note(self):
        hold(self, SAT_1500)
        paper = held(self.user, "XAUUSD", SAT_1500, paper=True)
        self.assertTrue([n for n in self.notes(paper, SAT_1500)
                         if n.startswith("The market for XAUUSD is shut "
                                         "right now")])
        fx = held(self.user, "EURUSD", SAT_1500)
        self.assertTrue([n for n in self.notes(fx, SAT_1500)
                         if n.startswith("The market for EURUSD is shut "
                                         "right now")])

    def test_the_positions_mark_hover(self):
        from dashboard.views import _mark_words
        hold(self, SAT_1500)
        row = SimpleNamespace(mark_source="venue_stale", mark_age_s=1500,
                              mark_via="tick", paper=False, symbol="XAUUSD",
                              asset_class="commodity")
        title = _mark_words(row)["mark_title"]
        self.assertIn("Nothing newer has come in from the venue — eToro "
                      "trades it 24/7, so it is out of date.", title)
        self.assertNotIn("normal while its market is shut", title)
        fx = _mark_words(SimpleNamespace(
            mark_source="venue_stale", mark_age_s=1500, mark_via="tick",
            paper=False, symbol="EURUSD", asset_class="forex"))["mark_title"]
        self.assertIn("normal while its market is shut", fx)

    def test_the_hordes_market_line(self):
        from dashboard.horde import _market_words
        hold(self, SAT_1500)
        up = SimpleNamespace(instrument=SimpleNamespace(exchange="COMEX"))
        real = held(self.user, "XAUUSD", SAT_1500)
        self.assertEqual(
            _market_words(real, "live", "commodity", up, None, SAT_1500),
            "eToro: trades GOLD 24/7 (breaks 22:00-23:00 UTC daily, Fri "
            "22:00-22:30). Open. Bots: no weekend entries, by your choice.")
        spx = held(self.user, "SPX500", SAT_1500)
        self.assertEqual(
            _market_words(spx, "live", "index", SimpleNamespace(
                instrument=SimpleNamespace(exchange="CME")), None, SAT_1500),
            "eToro: trades SPX500 24/7 (short breaks; times not "
            "published). Open.")
        paper = held(self.user, "XAUUSD", SAT_1500, paper=True)
        self.assertTrue(_market_words(paper, "paper", "commodity", up, None,
                                      SAT_1500).startswith(
            "Paper venue, on the CME Futures clock. Shut · opens in"))

    def test_the_hordes_market_line_in_a_break(self):
        from dashboard.horde import _market_words
        hold(self, FRI_2210)
        real = held(self.user, "XAUUSD", FRI_2210)
        self.assertEqual(
            _market_words(real, "live", "commodity", SimpleNamespace(
                instrument=SimpleNamespace(exchange="COMEX")), None,
                FRI_2210),
            "eToro: trades GOLD 24/7 (breaks 22:00-23:00 UTC daily, Fri "
            "22:00-22:30). Pause · eToro reopens 22:30 UTC. Bots: no weekend "
            "entries, by your choice.")

    def test_the_close_advice(self):
        from brain.close_advice import advise
        hold(self, SAT_1500)
        live = held(self.user, "XAUUSD", SAT_1500)
        paper = held(self.user, "XAUUSD", SAT_1500, paper=True)
        got = advise(self.user, [live.id, paper.id])
        by_id = {p["trade_id"]: p for p in got["positions"]}
        live_reasons = " | ".join(by_id[live.id]["reasons"])
        self.assertIn("eToro trades XAUUSD 24/7: a close now fills at "
                      "eToro's weekend price, where spreads may be wider.",
                      live_reasons)
        self.assertNotIn("is shut", live_reasons)
        self.assertIn("The market for XAUUSD is shut: a close now would wait "
                      "for the open (Sunday 23:00 UTC); a paper close is "
                      "refused until then.",
                      " | ".join(by_id[paper.id]["reasons"]))


# ══════════════════════════════════════════════════════════════════════════
# E. The ticket
# ══════════════════════════════════════════════════════════════════════════

class TheTicketTests(_Case):
    username = "aw_ticket"

    def preview(self, symbol, at, venue="live"):
        from bot_program.manual_trade import timing_advisory
        from dashboard.views import _ticket_week
        hold(self, at)
        i = inst(symbol)
        return _ticket_week({"venue": venue, "symbol": symbol,
                             "timing_advisory": timing_advisory(i)}, i)

    def test_a_live_gold_ticket_on_saturday(self):
        p = self.preview("XAUUSD", SAT_1500)
        self.assertEqual(p["timing_advisory"]["code"], "SHUT",
                         "the advisory the booking records is untouched")
        self.assertEqual(p["week"]["head"], "OPEN · eToro 24/7")
        self.assertEqual(p["week"]["lines"], [
            "eToro trades GOLD all week; at the weekend only market orders, "
            "and spreads may be wider (eToro's note)",
            "bots: no weekend entries, by your choice",
            "Sauron's clock (CME) is shut: a booking now is one Morgul G1 "
            "would flag"])

    def test_a_break_and_a_paper_ticket(self):
        p = self.preview("XAUUSD", FRI_2210)
        self.assertEqual(p["week"]["head"], "PAUSE · eToro reopens 22:30 UTC")
        self.assertEqual(p["week"]["lines"][0], "an order now waits for "
                                                "eToro's reopening (eToro's "
                                                "note)")
        paper = self.preview("XAUUSD", SAT_1500, venue="paper")
        self.assertEqual(paper["week"]["paper"],
                         "paper: waits for CME's open, Sun 23:00 UTC; eToro "
                         "itself trades GOLD 24/7")

    def test_every_other_ticket_is_as_before(self):
        for sym in ("EURUSD", "HGUSD", "SPX500"):
            with self.subTest(sym):
                self.assertNotIn("week", self.preview(sym, SAT_1500))
        self.assertNotIn("week", self.preview("XAUUSD", TUE_1500))

    def test_the_popup_says_it_without_the_warning_and_stays_pressable(self):
        from pathlib import Path

        from django.conf import settings
        html = (Path(settings.BASE_DIR) / "templates" / "base.html"
                ).read_text(encoding="utf-8")
        self.assertIn("if (timingAdv.code === 'SHUT' && wk && wk.head && "
                      "live) {", html)
        self.assertIn("'<div class=\"sz-note sz-note--week\"><b>' + "
                      "esc(wk.head) + '</b> '", html)
        expr = html.split("okBtn.disabled = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("wk", expr)
        self.assertNotIn("week", expr)
        manual = (Path(settings.BASE_DIR) / "bot_program" / "manual_trade.py"
                  ).read_text(encoding="utf-8")
        self.assertNotIn("all_week", manual, "the preview's own facts")


# ══════════════════════════════════════════════════════════════════════════
# F. The Orcs, and Telegram's /why
# ══════════════════════════════════════════════════════════════════════════

class TheOrcsAndWhyTests(_Case):
    username = "aw_orcs"

    def test_the_metronome_rests_on_saurons_clock(self):
        from bot_program.orcs.notes import _wake_rests
        gold = SimpleNamespace(symbol="XAUUSD", asset_class="commodity")
        due = datetime(2026, 11, 20, 21, 0, tzinfo=UTC)
        self.assertEqual(
            _wake_rests(gold, due, SAT_1500),
            "Next wake: the metronome rests on Sauron's CME clock until Sun "
            "22 Nov 23:00 UTC; eToro trades GOLD 24/7.")
        self.assertTrue(_wake_rests(gold, due, SAT_1500, minds=False)
                        .endswith("Detected and recorded only, no model."))
        self.assertEqual(_wake_rests(gold, SAT_1500 + timedelta(hours=1),
                                     SAT_1500), "", "not overdue")
        fx = SimpleNamespace(symbol="EURUSD", asset_class="forex")
        self.assertEqual(_wake_rests(fx, due, SAT_1500), "")

    def test_the_slot_says_it(self):
        from bot_program.orcs import notes
        from bot_program.orcs.models import Orc
        from tests.orcs.helpers import _config, _on, _row, born
        _on()
        cfg = _config(self.user, "commodity")
        row = _row(cfg, symbol="XAUUSD", cls="commodity", paper=False,
                   meta={"broker": "etoro", "broker_env": "live"},
                   entry="2640", stop="2600", target="2720")
        orc = born(self, row)
        Orc.objects.filter(pk=orc.pk).update(next_wake_due=datetime(
            2026, 11, 20, 21, 0, tzinfo=UTC))
        orc.refresh_from_db()
        sl = notes.slot(orc, trade=row, now=SAT_1500)
        self.assertEqual(sl["next_wake_t"],
                         "Next wake: the metronome rests on Sauron's CME "
                         "clock until Sun 22 Nov 23:00 UTC; eToro trades "
                         "GOLD 24/7.")
        with mock.patch("market_data.all_week_display.GATE", False):
            self.assertEqual(notes.slot(orc, trade=row, now=SAT_1500)[
                "next_wake_t"], "Next wake overdue since Fri 20 Nov 21:00 "
                                "UTC.")

    def test_why_says_the_bots_weekend_rule(self):
        from bot_program.telegram_eye import _skip_line
        live = SimpleNamespace(asset_class="commodity", mode="live")
        last = {"code": "market_shut", "at": SAT_1500.isoformat(),
                "detail": "the commodity market is shut until Sunday 23:00 "
                          "UTC"}
        self.assertEqual(_skip_line(live, "XAUUSD", last),
                         "Last reason: bots: no weekend entries, by your "
                         "choice (eToro trades GOLD 24/7)")
        paper = SimpleNamespace(asset_class="commodity", mode="paper")
        self.assertEqual(_skip_line(paper, "XAUUSD", last),
                         "Last reason: paper: waits for CME's open, Sun 23:00 "
                         "UTC (eToro trades GOLD 24/7)")
        fx = SimpleNamespace(asset_class="forex", mode="live")
        self.assertEqual(_skip_line(fx, "EURUSD", last),
                         "Last reason: The market was shut: no paper fill, "
                         "no live entry")
        other = dict(last, code="cooldown")
        self.assertEqual(_skip_line(live, "XAUUSD", other),
                         "Last reason: This symbol traded too recently")
        weekday = dict(last, at=TUE_2230.isoformat())
        self.assertEqual(_skip_line(live, "XAUUSD", weekday),
                         "Last reason: The market was shut: no paper fill, "
                         "no live entry")
