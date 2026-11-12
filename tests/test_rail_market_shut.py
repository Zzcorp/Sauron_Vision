"""A signal whose market is shut says so on its card (2026-11-12).

The operator, 2026-11-11: signals shown while their market is shut, as if
they could be traded ("please fix it"). Told they would be moved out of
the way until the open, he answered on 2026-11-12: "non, faites que l'on
reçoive quand même les signaux live, c'est plus intéressant". So nothing
is hidden: a signal whose market is shut stays a card on the rail, a row
in the headband list and a row on /signals/, and each carries a visible
MARKET SHUT badge with the hour the market opens, the hour its
announcement gave (signals/market_hold.market_state, the bots' own
clock). One chip on the rail, SHUT, shows or hides those cards: shown by
default, kept per user with the rail's other choices.

Pinned here, at fixed instants, the market clock's gate on:
  * the badge and the hour on the rail card, in its popup, on the headband
    row, on /signals/ and in `signals show`; the card keeps its TAKE TRADE
    ticket (the ticket says the market is shut itself);
  * the rail's counts are unchanged and count the badged cards apart
    (the chip's number); the badge follows the clock and is gone once the
    market opens;
  * an open market's card, row and /signals/ row are the ones drawn with
    the gate off, byte for byte, and a shut market's differ by the badge
    alone;
  * the chip: pressed by default, the choice stored per user and cleaned
    by the whitelist, the stylesheet hiding exactly the badged rows on both
    lists, "show all" bringing them back, the script writing the state on
    both hosts and saving it;
  * display only: no query per card, no engine row written.

THE OPTIONAL HOLD ON THE RAIL (the switch signal_market_hold, OFF on
arrival), the spec's cases 1 to 11: a signal whose market cannot trade
waits in a MARKET SHUT section with the hour the market opens and its
ticket, off the cards, the counts and the headband list; it is a card
again once the market has opened and settled; the price rules judge
nothing while a market is shut; the counts add up; no query per row and
no engine row; and with the switch off none of it is drawn. Then the
section's chip and filter row, and /signals/ saying a signal was held.

Run with:  python manage.py test tests.test_rail_market_shut
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tests.test_rail_every_signal import (HOST, _cards, _page, _partial,
                                          _user)
from tests.test_signal_market_hold import (MON_1000, SAT_0005, SAT_NOON,
                                           SUN_0900, SUN_2130, SUN_2205,
                                           SUN_2217, SUN_2220, _at, _db_inst,
                                           _quote, _sig, _switch, _t)

NODE = shutil.which("node")
SAT_1100 = _t(2026, 11, 7, 11, 0)
OPENS = "opens Sun 22:00 UTC"
TICKET_WORDS = ("a paper ticket is refused until it opens; a live ticket "
                "warns and is yours to send")
ROW_ANY = re.compile(r'<div class="ip-dd-row sv-sig-row"[^>]*?'
                     r'data-signal-id="(\d+)".*?</div>', re.S)


_AGE = re.compile(r"\d+\xa0(?:minute|hour|day|week|month|year)s?"
                  r"(?:, \d+\xa0(?:minute|hour|day|week|month|year)s?)?")


def _ageless(html):
    """A render with its ages masked: the timesince filter reads the wall
    clock, not the fixed one, and two renders of one test can straddle a
    minute."""
    return _AGE.sub("AGE", html)


def _snap(user):
    from django.test import RequestFactory

    from dashboard.signal_rail import rail_snapshot
    req = RequestFactory().get("/")
    req.user = user
    return rail_snapshot(req)


def _card(html, signal):
    """The whole card of `signal` in a rendered rail: its wrapper, the
    card and its popup, up to the next card or the end of the list."""
    chunks = re.split(r'(?=<div class="sr-signal-wrap)',
                      html.split('<div class="sr-list"', 1)[1])
    for chunk in chunks:
        if re.match(r'<div class="sr-signal-wrap[^"]*" data-signal-id="%d"'
                    % signal.pk, chunk):
            return chunk.split('<div data-sv-rail-meta', 1)[0]
    return ""


def _row(html, signal):
    """The headband list's row of `signal` (the rail answer carries the
    list in its <template>)."""
    mirror = html.split('<template data-sv-mirror="hbSignalRows">', 1)[1]
    for m in ROW_ANY.finditer(mirror):
        if int(m.group(1)) == signal.pk:
            return m.group(0)
    return ""


def _signals_rows(html):
    """The body of the /signals/ table (the page's third table: two
    summaries stand above it)."""
    table = html.split('<table class="sv-perf-table sv-stack">', 1)[1]
    return table.split("<tbody>", 1)[1].split("</tbody>", 1)[0]


def _signals_row(html, signal):
    """The /signals/ table row of `signal`."""
    for tr in _signals_rows(html).split("<tr>")[1:]:
        if f">{signal.title}<" in tr:
            return tr
    return ""


def _meta(html):
    block = html.split("data-sv-rail-meta hidden>", 1)[1]
    return json.loads(re.search(r"<script[^>]*>(.*?)</script>", block,
                                re.S).group(1))


class _Base(TestCase):
    def setUp(self):
        self.user = _user("rms_u")
        self.client.force_login(self.user)
        self.fx = _db_inst("EURUSD")
        self.btc = _db_inst("BTCUSD", "crypto")

    def _rail(self, when, gate=True):
        with _at(when, gate):
            return _partial(self.client)

    def _two(self, born=SAT_1100):
        shut = _sig(self.fx, born, rule="rms_fx")
        always = _sig(self.btc, born, rule="rms_btc", direction="bullish",
                      entry="60000", stop="58000", target="64000")
        return shut, always


class TheBadgeTests(_Base):
    def test_the_rail_card_carries_the_badge_and_the_hour(self):
        shut, always = self._two()
        html = self._rail(SAT_NOON)
        # nothing is hidden: both are cards, newest first
        self.assertEqual(set(_cards(html)), {shut.pk, always.pk})
        card = _card(html, shut)
        self.assertIn(' data-market="shut"', card)
        self.assertRegex(card, r'<div class="sr-shut" title="[^"]*">'
                               r'<span class="sr-shut-tag">MARKET SHUT</span> '
                               r'<span class="sr-shut-opens">%s</span></div>'
                               % re.escape(OPENS))
        title = re.search(r'<div class="sr-shut" title="([^"]*)"', card)
        self.assertEqual(title.group(1),
                         "The forex market is shut: it opens Sunday 22:00 "
                         "UTC. " + TICKET_WORDS[0].upper() + TICKET_WORDS[1:]
                         + ".")
        # the popup says it beside the ticket, which is still offered
        self.assertIn(f'<span class="sr-pop-k">market</span> shut · {OPENS}'
                      f' · {TICKET_WORDS}</div>', card)
        self.assertIn("▶ TAKE TRADE", card)
        self.assertIn(f"window.svTakeTrade({shut.pk})", card)
        # crypto never shuts
        other = _card(html, always)
        self.assertNotIn("MARKET SHUT", other)
        self.assertNotIn("data-market", other)

    def test_the_headband_row_carries_the_badge_and_the_hour(self):
        shut, always = self._two()
        html = self._rail(SAT_NOON)
        row = _row(html, shut)
        self.assertIn(' data-market="shut"', row)
        self.assertRegex(row, r'<span class="ipr-shut" title="[^"]*">MARKET '
                              r'SHUT · %s</span>' % re.escape(OPENS))
        self.assertNotIn("MARKET SHUT", _row(html, always))
        self.assertNotIn("data-market", _row(html, always))

    def test_the_signals_page_row_carries_the_badge_and_the_hour(self):
        from signals.models import Signal
        shut, always = self._two()
        closed = _sig(self.fx, SAT_1100, rule="rms_closed", active=False)
        Signal.objects.filter(pk=closed.pk).update(
            title="A closed one", outcome="expired", expired_at=SAT_1100)
        closed.refresh_from_db()
        with _at(SAT_NOON):
            html = _page(self.client, "/signals/")
        row = _signals_row(html, shut)
        self.assertRegex(row, r'<span class="badge badge-high sig-shut" '
                              r'title="[^"]*">MARKET SHUT</span> '
                              r'<span class="sig-shut-opens">%s</span>'
                         % re.escape(OPENS))
        self.assertNotIn("MARKET SHUT", _signals_row(html, always))
        # a signal the engine closed is no longer something to act on
        self.assertTrue(_signals_row(html, closed))
        self.assertNotIn("MARKET SHUT", _signals_row(html, closed))

    def test_the_signals_command_says_it_too(self):
        from io import StringIO

        from django.core.management import call_command
        shut, always = self._two()
        out = StringIO()
        with _at(SAT_NOON):
            call_command("signals", "show", str(shut.pk), stdout=out)
        self.assertIn(f"MARKET SHUT · {OPENS} — The forex market is shut: "
                      f"it opens Sunday 22:00 UTC.", out.getvalue())
        out = StringIO()
        with _at(SAT_NOON):
            call_command("signals", "show", str(always.pk), stdout=out)
        self.assertNotIn("MARKET SHUT", out.getvalue())
        # an open market: the command's words are the ones the gate off prints
        on, off = StringIO(), StringIO()
        with _at(MON_1000):
            call_command("signals", "show", str(shut.pk), stdout=on)
        with _at(MON_1000, gate=False):
            call_command("signals", "show", str(shut.pk), stdout=off)
        self.assertEqual(on.getvalue(), off.getvalue())

    def test_an_unknown_reopening_says_only_market_shut(self):
        from unittest.mock import patch
        shut, _always = self._two()
        clock = {"is_open": False, "session": "FOREX", "modelled": True,
                 "reopens": None, "reopens_words": "", "opened": None,
                 "closed": None}
        with patch("signals.market_hold.market_clock", return_value=clock):
            html = self._rail(SAT_NOON)
        card = _card(html, shut)
        self.assertIn('<span class="sr-shut-tag">MARKET SHUT</span></div>',
                      card)
        self.assertNotIn("sr-shut-opens", card)
        self.assertRegex(_row(html, shut),
                         r'<span class="ipr-shut" title="[^"]*">MARKET SHUT'
                         r'</span>')

    def test_the_counts_are_unchanged_and_the_badged_cards_are_counted(self):
        shut, always = self._two()
        with _at(SAT_NOON):
            snap = _snap(self.user)
        self.assertEqual((snap["n"], snap["shut_n"]), (2, 1))
        self.assertEqual([r["id"] for r in snap["rows"]],
                         [s.pk for s in snap["cards"]])
        self.assertEqual(snap["title"],
                         "2 on the rail · 2 active in the engine · 0 left in "
                         "the last 24h · 0 left earlier")
        meta = _meta(self._rail(SAT_NOON))
        self.assertEqual((meta["n"], meta["shut"]), (2, 1))
        with _at(SAT_NOON):
            page = _page(self.client)
        self.assertRegex(page, r'<b data-sv-rail-n="shut">1</b>')
        # the facts the card carries
        facts = {s.pk: s.rail for s in snap["cards"]}
        self.assertEqual(facts[shut.pk].market, "shut")
        self.assertEqual(facts[shut.pk].opens, OPENS)
        self.assertEqual(facts[shut.pk].opens_at, _t(2026, 11, 8, 22, 0))
        self.assertEqual(facts[always.pk].market, "")

    def test_the_badge_follows_the_clock(self):
        shut = _sig(self.fx, _t(2026, 11, 8, 9, 0), rule="rms_fx")
        self.assertIn("MARKET SHUT", _card(self._rail(_t(2026, 11, 8, 21, 30)),
                                           shut))
        # the first quarter hour is an open market: no badge
        self.assertNotIn("MARKET SHUT", _card(self._rail(SUN_2205), shut))
        self.assertNotIn("MARKET SHUT", _card(self._rail(SUN_2220), shut))
        with _at(SUN_2220):
            self.assertEqual(_snap(self.user)["shut_n"], 0)


class OnlyTheBadgeDiffersTests(_Base):
    """An open market's card is main's card; a shut market's is main's
    card and its badge. The gate off is the path main draws (the suite's
    default): no market is read at all."""

    def _three(self, when):
        self._two(born=when - timedelta(hours=1))
        with _at(when, gate=True):
            on = (_partial(self.client), _page(self.client, "/signals/"))
        with _at(when, gate=False):
            off = (_partial(self.client), _page(self.client, "/signals/"))
        return tuple(map(_ageless, on)), tuple(map(_ageless, off))

    def test_an_open_market_draws_what_the_gate_off_draws(self):
        on, off = self._three(MON_1000)
        self.assertEqual(on[0], off[0])            # the whole rail answer
        self.assertNotIn("MARKET SHUT", on[0])
        self.assertNotIn("data-market", on[0])
        self.assertNotIn("MARKET SHUT", _signals_rows(on[1]))
        self.assertEqual(_signals_rows(on[1]), _signals_rows(off[1]))
        self.assertEqual(_signals_rows(on[1]).count("<tr>"), 2)

    def test_a_shut_market_differs_by_the_badge_alone(self):
        on, off = self._three(SAT_NOON)
        rail = on[0]
        self.assertIn("MARKET SHUT", rail)
        # take the badge's four fragments out: what is left is the rail
        # the gate off draws
        rail = rail.replace(' data-market="shut"', "")
        rail, cards = re.subn(
            r'\n\s*<div class="sr-shut" title="[^"]*"><span class="sr-shut-'
            r'tag">MARKET SHUT</span> <span class="sr-shut-opens">[^<]*'
            r'</span></div>', "", rail)
        rail, facts = re.subn(
            r'<div class="sr-pop-fact sr-pop-fact-shut">.*?</div>', "", rail)
        rail, rows = re.subn(
            r'<span class="ipr-shut" title="[^"]*">[^<]*</span>', "", rail)
        self.assertEqual((cards, facts, rows), (1, 1, 1))
        rail = rail.replace('"shut": 1', '"shut": 0')
        self.assertEqual(rail, off[0])
        # /signals/: the same, one badge
        page, n = re.subn(
            r' <span class="badge badge-high sig-shut" title="[^"]*">MARKET '
            r'SHUT</span> <span class="sig-shut-opens">[^<]*</span>', "",
            _signals_rows(on[1]))
        self.assertEqual(n, 1)
        self.assertEqual(page, _signals_rows(off[1]))


class DisplayOnlyTests(_Base):
    def test_no_query_is_added_per_card(self):
        insts = [_db_inst(f"RMSQ{i:02d}") for i in range(30)]
        for inst in insts[:3]:
            _sig(inst, SAT_1100, rule="rms_qc")
        self._rail(SAT_NOON)                       # warm the session
        with _at(SAT_NOON), CaptureQueriesContext(connection) as three:
            self.assertEqual(len(_cards(_partial(self.client))), 3)
        for inst in insts[3:]:
            _sig(inst, SAT_1100, rule="rms_qc")
        with _at(SAT_NOON), CaptureQueriesContext(connection) as thirty:
            html = _partial(self.client)
        self.assertEqual(len(_cards(html)), 30)
        self.assertEqual(html.count('<span class="sr-shut-tag">'), 30)
        self.assertEqual(len(three.captured_queries),
                         len(thirty.captured_queries),
                         "\n".join(q["sql"][:160]
                                   for q in thirty.captured_queries))

    def test_the_rail_writes_no_engine_row_with_shut_cards(self):
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        from signals.models import PromotionEvent, RuleControl, Signal

        def world():
            def row(obj):
                return json.dumps({f.attname: getattr(obj, f.attname)
                                   for f in obj._meta.concrete_fields},
                                  sort_keys=True, default=str)
            return {m.__name__: sorted(row(o) for o in m.objects.all())
                    for m in (Signal, RuleControl, PromotionEvent,
                              AssetBotTrade, Instrument)}

        self._two()
        before = world()
        html = self._rail(SAT_NOON)
        self.assertIn("MARKET SHUT", html)
        with _at(SAT_NOON):
            _page(self.client, "/signals/")
            _page(self.client)
        self.assertEqual(world(), before)


# ── the chip: show or hide the cards whose market is shut ────────────────

class TheChipTests(_Base):
    def test_the_chip_is_on_the_rail_bar_shown_by_default(self):
        self._two()
        with _at(SAT_NOON):
            page = _page(self.client)
        chip = re.search(r'<button type="button" class="rf-chip rf-shut"'
                         r'[^>]*>SHUT <b data-sv-rail-n="shut">1</b></button>',
                         page)
        self.assertIsNotNone(chip, "the SHUT chip is not on the rail bar")
        tag = chip.group(0)
        self.assertIn('data-f-key="shut_off"', tag)
        self.assertIn('data-f-val="0"', tag)
        self.assertIn("data-f-toggle", tag)
        self.assertIn('aria-pressed="true"', tag)
        self.assertIn('title="Show or hide the cards whose market is shut '
                      'now', tag)
        # once, on the rail's bar; the headband's compact bar has none
        self.assertEqual(page.count('class="rf-chip rf-shut"'), 1)
        bar = page.split('id="railSigFacets"', 1)[1].split("</div>", 1)[0]
        self.assertIn('class="rf-chip rf-shut"', bar)
        # both hosts carry the state, not hiding
        self.assertEqual(page.count('data-f-shutoff="0"'), 2)
        self.assertNotIn('data-f-shutoff="1"', page)

    def test_the_choice_is_kept_per_user_and_cleaned(self):
        from dashboard import rail_prefs
        self.assertIs(rail_prefs.SIG_DEFAULT["shut_off"], False)
        self.assertIs(rail_prefs.clean({})["sig"]["shut_off"], False)
        self.assertIs(rail_prefs.clean(
            {"sig": {"shut_off": "<script>"}})["sig"]["shut_off"], False)
        self.assertIs(rail_prefs.clean(
            {"sig": {"shut_off": 1}})["sig"]["shut_off"], True)
        resp = self.client.post(
            "/api/rail-prefs/", data=json.dumps(
                {"prefs": {"sig": {"shut_off": True, "side": "long"}}}),
            content_type="application/json", HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertIs(resp.json()["prefs"]["sig"]["shut_off"], True)
        self._two()
        with _at(SAT_NOON):
            page = _page(self.client)
        self.assertEqual(page.count('data-f-shutoff="1"'), 2)
        chip = re.search(r'<button type="button" class="rf-chip rf-shut"'
                         r'[^>]*>', page).group(0)
        self.assertIn('aria-pressed="false"', chip)
        # the cards are still rendered (the stylesheet hides them) and the
        # chip still counts them, so they can be brought back
        self.assertRegex(page, r'<b data-sv-rail-n="shut">1</b>')
        self.assertIn('<span class="sr-shut-tag">MARKET SHUT</span>', page)
        # another user draws them
        other = _user("rms_other")
        self.client.force_login(other)
        with _at(SAT_NOON):
            page = _page(self.client)
        self.assertEqual(page.count('data-f-shutoff="0"'), 2)

    def test_the_stylesheet_hides_exactly_the_badged_rows(self):
        from bs4 import BeautifulSoup

        from tests.test_rail_filters_css import (CSS, _set_state, drawn,
                                                 hidden, parse_rules)
        shut, always = self._two()
        with _at(SAT_NOON):
            soup = BeautifulSoup(_page(self.client), "html.parser")
        rail = soup.find(id="signalsRail")
        rail["class"] = rail.get("class", []) + ["open"]
        rules = parse_rules(CSS.read_text(encoding="utf-8"))

        def shown(host_id, list_class, **state):
            host = soup.find(id=host_id)
            _set_state(host, **state)
            lst = host.find(class_=list_class)
            return {k.get("data-signal-id") for k in drawn(lst, rules, host)
                    if k.has_attr("data-sv-row")}

        both, only_open = {str(shut.pk), str(always.pk)}, {str(always.pk)}
        for host_id, list_class in (("railSignals", "sr-list"),
                                    ("hbSignalsDD", "sv-sig-rows")):
            with self.subTest(host=host_id):
                self.assertEqual(shown(host_id, list_class), both)
                self.assertEqual(shown(host_id, list_class, shutoff="0"),
                                 both)
                self.assertEqual(shown(host_id, list_class, shutoff="1"),
                                 only_open)
                # "show all" pauses it with every other filter
                self.assertEqual(shown(host_id, list_class, shutoff="1",
                                       peek="1"), both)
        # the badge itself is never hidden by density
        host = soup.find(id="railSignals")
        _set_state(host, dense="1")
        badge = host.find(class_="sr-shut")
        self.assertFalse(hidden(badge, rules, host))


RUN_TAIL = r"""
async function shutChip() {
  const W = boot();
  const out = {};
  const chip = W.chip('#railSigFacets', 'shut_off', '0');
  out.found = !!chip;
  out.before = [W.attr('railSignals', 'data-f-shutoff'), W.attr('hbSignalsDD', 'data-f-shutoff'),
                chip && chip.getAttribute('aria-pressed')];
  W.click(chip); await W.advance(100);
  out.hidden = [W.attr('railSignals', 'data-f-shutoff'), W.attr('hbSignalsDD', 'data-f-shutoff'),
                chip.getAttribute('aria-pressed')];
  await W.advance(700);
  out.posts = W.posts.length;
  out.body = W.posts.length ? JSON.parse(W.posts[0].body) : null;
  W.click(chip); await W.advance(800);
  out.shown = [W.attr('railSignals', 'data-f-shutoff'), W.attr('hbSignalsDD', 'data-f-shutoff'),
               chip.getAttribute('aria-pressed')];
  out.last = W.posts.length ? JSON.parse(W.posts[W.posts.length - 1].body) : null;
  /* a rail refresh repaints the chip's number from the answer's meta */
  W.wsSend({ type: 'signal' }); await W.advance(1500);
  out.count_after_refresh = W.doc.querySelectorAll('[data-sv-rail-n="shut"]').map(e => e.textContent);
  out.errors = W.errors();
  return out;
}

(async () => {
  process.stdout.write(JSON.stringify({ shut_chip: await shutChip() }));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(NODE, "node is not installed on this machine")
class TheChipInTheBrowserTests(_Base):
    """static/js/sv-rail-filters.js on the page as rendered, under node
    (the harness of tests/test_rail_filters.py)."""

    def _report(self, tail=None):
        from django.template import engines
        from django.test import RequestFactory

        from core.context_ui import ui_extras
        from tests import test_rail_filters as rf
        from tests.test_headband_hover_lives import DOM_JS
        from tests.test_rail_every_signal import (BAR_FROM, BAR_TO, _ctx,
                                                  _shell, _upgrade3)
        self._two()
        raw = _shell()
        eng = engines["django"]
        with _at(SAT_NOON):
            req = RequestFactory().get("/")
            req.user = self.user
            ctx = dict(_ctx(self.user))
            ctx.update(ui_extras(req))
            ctx.update({"user": self.user, "sv_sweep": False})
            load = "{% load sauron_tags static %}"
            style = re.search(r'<style id="svRuleOff".*?</style>', raw,
                              re.S).group(0)
            bar = raw[raw.index(BAR_FROM):raw.index(BAR_TO)]
            start = raw.index("<!-- Signals Rail (right sidebar)")
            rail = raw[start:raw.index("{# The activity drawer", start)]
            page = (eng.from_string(load + style).render(ctx)
                    + eng.from_string(load + bar).render(ctx)
                    + '<main id="elsewhere"><p>The page</p></main>'
                    + eng.from_string(load + rail).render(ctx))
            # the answer of the next refresh: a second shut-market card
            _sig(_db_inst("RMSND"), SAT_1100, rule="rms_node")
            answer = _partial(self.client)
        rail_js = raw[raw.index("/* ── Phase 62.1"):raw.index("/* ── TAKE TRADE")]
        filters = (Path(settings.BASE_DIR) / "static" / "js"
                   / "sv-rail-filters.js").read_text(encoding="utf-8")
        scripts = [{"label": "base.html Phase 62.1-64.4", "source": rail_js},
                   {"label": "base.html UPGRADE-3", "source": _upgrade3()},
                   {"label": "static/js/sv-rail-filters.js",
                    "source": filters}]
        boot = rf.RUN_JS.split("async function chipsAndSave()", 1)[0]
        tmp = Path(tempfile.mkdtemp(prefix="sv-rms-"))
        try:
            (tmp / "dom.js").write_text(DOM_JS, encoding="utf-8")
            (tmp / "run.js").write_text(boot + (tail or RUN_TAIL),
                                        encoding="utf-8")
            (tmp / "input.json").write_text(json.dumps(
                {"page": page, "answer": answer, "scripts": scripts}),
                encoding="utf-8")
            proc = subprocess.run(
                [NODE, str(tmp / "run.js"), str(tmp / "input.json")],
                capture_output=True, text=True, timeout=300, encoding="utf-8")
            if proc.returncode != 0:
                raise AssertionError("the runner failed: %s"
                                     % proc.stderr[:3000])
            return json.loads(proc.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_chip_hides_and_shows_on_both_hosts_and_saves(self):
        r = self._report()["shut_chip"]
        dump = json.dumps(r, indent=1)[:4000]
        self.assertTrue(r["found"], dump)
        self.assertEqual(r["before"], ["0", "0", "true"], dump)
        self.assertEqual(r["hidden"], ["1", "1", "false"], dump)
        self.assertEqual(r["posts"], 1, dump)
        self.assertIs(r["body"]["prefs"]["sig"]["shut_off"], True, dump)
        self.assertEqual(r["shown"], ["0", "0", "true"], dump)
        self.assertIs(r["last"]["prefs"]["sig"]["shut_off"], False, dump)
        self.assertEqual(r["count_after_refresh"], ["2"], dump)
        self.assertEqual(r["errors"], [], dump)


# ═════════════════════════════════════════════════════════════════════════
# THE OPTIONAL HOLD ON THE RAIL (the switch signal_market_hold, OFF on
# arrival). On, the rail lists what can be traded now: a candidate whose
# market is shut, or opened less than a quarter hour ago, leaves the cards
# for a MARKET SHUT section (hidden until its chip or its filter row is
# pressed) with the hour the market opens and its ticket, and comes back
# as a card by itself once the market has opened and settled. Off, none of
# it is drawn: the rail is the one above.
# ═════════════════════════════════════════════════════════════════════════

WAIT_TITLE = ("The market is shut: a paper ticket is refused until it opens;"
              " a live ticket warns and is yours to send")
# A market in its first quarter hour is open: its row never says "shut".
SETTLE_TITLE = ("The market has just opened: a paper ticket is refused in "
                "its first quarter hour; a live ticket is yours to send")


def _waiting_rows(html):
    """The MARKET SHUT rows of a rendered rail, one chunk each."""
    section = html.split('<section class="sr-shut-sec"', 1)[1].split(
        "</section>")[0]
    return ['class="sr-wait-row"' + chunk
            for chunk in section.split('class="sr-wait-row"')[1:]]


def _gone_rows(html):
    section = html.split('<section class="sr-gone"', 1)[1].split(
        "</section>")[0]
    return ['class="sr-gone-row"' + chunk
            for chunk in section.split('class="sr-gone-row"')[1:]]


def _departures(signal):
    from dashboard.models import RailDeparture
    return list(RailDeparture.objects.filter(signal=signal))


class _HoldBase(_Base):
    def setUp(self):
        super().setUp()
        _switch(True)

    def _snap(self, when, gate=True):
        with _at(when, gate):
            return _snap(self.user)


class TheMarketShutSectionTests(_HoldBase):
    def test_1_a_forex_signal_on_saturday_waits_in_the_section(self):
        shut, always = self._two()
        snap = self._snap(SAT_NOON)
        self.assertEqual([s.pk for s in snap["cards"]], [always.pk])
        self.assertEqual([g.signal_id for g in snap["waiting"]], [shut.pk])
        self.assertEqual((snap["n"], snap["waiting_n"]), (1, 1))
        self.assertEqual([r["id"] for r in snap["rows"]], [always.pk])
        self.assertEqual(snap["title"],
                         "1 on the rail · 1 waiting for their market · 2 "
                         "active in the engine · 0 left in the last 24h · 0 "
                         "left earlier")
        html = self._rail(SAT_NOON)
        self.assertEqual(_cards(html), [always.pk])
        self.assertEqual(len(_waiting_rows(html)), 1)
        self.assertEqual(_row(html, shut), "")       # not in the headband list
        self.assertTrue(_row(html, always))
        meta = _meta(html)
        self.assertEqual((meta["n"], meta["waiting"]), (1, 1))
        # the rail's head and the headband's cell count the cards only
        with _at(SAT_NOON):
            page = _page(self.client)
        head = re.search(r'<span class="rh-count" id="railSigCount"'
                         r'[^>]*title="([^"]*)"[^>]*>(\d+)<', page)
        self.assertEqual(head.group(2), "1")
        self.assertIn("1 waiting for their market", head.group(1))
        cell = re.search(r'data-sv-live="hb-signals"[^>]*>([^<]*)<', page)
        self.assertEqual(cell.group(1).strip(), "1")
        self.assertRegex(page, r'<span class="dk">MARKET SHUT</span><span '
                               r'class="dv" data-sv-rail-n="waiting">1</span>')

    def test_2_its_row_says_when_the_market_opens_and_keeps_its_ticket(self):
        shut, _always = self._two()
        html = self._rail(SAT_NOON)
        row = _waiting_rows(html)[0]
        self.assertIn(f'data-signal-id="{shut.pk}"', row)
        self.assertIn("EURUSD", row)
        self.assertIn("BEAR", row)
        self.assertIn("rms_fx", row)
        self.assertIn("opens Sunday 22:00 UTC", row)
        self.assertIn(f"window.svTakeTrade({shut.pk})", row)
        self.assertIn("▶ TICKET", row)
        self.assertIn(f'title="{WAIT_TITLE}"', row)
        # no card, so no TAKE TRADE card, for it
        self.assertEqual(_card(html, shut), "")
        self.assertEqual(html.count("▶ TAKE TRADE"), 1)
        # the section's head and its count
        head = html.split('<section class="sr-shut-sec"', 1)[1][:400]
        self.assertIn('<span class="sr-gone-title">MARKET SHUT</span>', head)
        self.assertIn('<span class="sr-gone-count" data-sv-rail-n="waiting">'
                      '1</span>', head)

    def test_3_born_saturday_0005_its_24_hours_end_before_the_market_opens(
            self):
        early = _sig(self.fx, SAT_0005, rule="rms_early")
        late = _sig(_db_inst("RMSFB"), SUN_0900, rule="rms_late")
        html = self._rail(SAT_NOON)
        rows = {int(re.search(r'data-signal-id="(\d+)"', r).group(1)): r
                for r in _waiting_rows(html)}
        self.assertIn("Its 24 hours end Sunday 00:05 UTC, before the market "
                      "opens.", rows[early.pk])
        self.assertNotIn("before the market opens", rows[late.pk])
        snap = self._snap(SAT_NOON)
        facts = {g.signal_id: g.facts for g in snap["waiting"]}
        self.assertIs(facts[early.pk].misses_open, True)
        self.assertIs(facts[late.pk].misses_open, False)

    def test_4_it_is_a_card_again_once_the_market_has_opened_and_settled(self):
        sig = _sig(self.fx, SUN_0900, rule="rms_fx")
        self.assertEqual(self._snap(SUN_2130)["waiting_n"], 1)
        # the first quarter hour still waits, and says why
        snap = self._snap(SUN_2205)
        self.assertEqual((snap["n"], snap["waiting_n"]), (0, 1))
        self.assertIn("first quarter hour", snap["waiting"][0].words)
        self.assertEqual(snap["waiting"][0].tag, "SETTLING")
        _quote(self.fx, "1.08450", SUN_2217)
        snap = self._snap(SUN_2220)
        self.assertEqual([s.pk for s in snap["cards"]], [sig.pk])
        self.assertEqual(snap["waiting"], [])
        html = self._rail(SUN_2220)
        self.assertIn("▶ TAKE TRADE", _card(html, sig))
        self.assertNotIn("MARKET SHUT</span>", _card(html, sig))
        self.assertEqual(_waiting_rows(html), [])
        self.assertIn("No signal is waiting for its market.", html)

    def test_4_a_row_in_the_first_quarter_hour_never_says_shut(self):
        """Its market is open and settling: the row's tag, its words and
        its ticket's title say that, and the paper venue refuses a fill
        for the same quarter hour (paper_trader.REOPEN_SETTLE_SECONDS)."""
        from bot_program.engine import paper_trader
        from signals import market_hold
        self.assertEqual(paper_trader.REOPEN_SETTLE_SECONDS,
                         market_hold.SETTLE_MINUTES * 60)
        sig = _sig(self.fx, SUN_0900, rule="rms_fx")
        row = _waiting_rows(self._rail(SUN_2205))[0]
        self.assertIn(f'data-signal-id="{sig.pk}"', row)
        self.assertIn('data-reason="market_settling"', row)
        self.assertIn(">SETTLING<", row)
        self.assertIn("first quarter hour is not a market price yet", row)
        self.assertIn(f"window.svTakeTrade({sig.pk})", row)
        self.assertIn(f'title="{SETTLE_TITLE}"', row)
        self.assertNotIn("market is shut", row.lower())
        # a shut market's row keeps the other title
        shut = _waiting_rows(self._rail(SUN_2130))[0]
        self.assertIn(f'title="{WAIT_TITLE}"', shut)
        self.assertNotIn(SETTLE_TITLE, shut)

    def test_the_switch_row_says_what_it_does_to_the_rail(self):
        """Turned on, the switch takes a shut market's card off the rail:
        its own description says so, under Postgres's 300 characters."""
        from core import platform_control as pc
        row = [c for c in pc.DEFAULT_COMPONENTS
               if c["key"] == "signal_market_hold"][0]
        self.assertIn("rail card waits under MARKET SHUT", row["description"])
        self.assertIn("no money", row["description"])
        self.assertLess(len(row["description"]), 300)
        self.assertNotIn("is_enabled", row)

    def test_5_a_quote_through_the_stop_after_the_open_leaves_as_today(self):
        sig = _sig(self.fx, SUN_0900, rule="rms_fx")
        _quote(self.fx, "1.09100", SUN_2217)
        snap = self._snap(SUN_2220)
        self.assertEqual((snap["n"], snap["waiting_n"]), (0, 0))
        gone = [g for g in snap["gone"] if g.signal_id == sig.pk]
        self.assertEqual([(g.reason, g.tag) for g in gone],
                         [("stop_crossed", "STOP")])
        self.assertEqual(len(_departures(sig)), 1)

    def test_6_a_quote_written_while_the_market_is_shut_records_no_departure(
            self):
        sig = _sig(self.fx, SUN_0900, rule="rms_fx")
        _quote(self.fx, "1.09100", SUN_2130 - timedelta(minutes=2))
        snap = self._snap(SUN_2130)
        self.assertEqual([g.signal_id for g in snap["waiting"]], [sig.pk])
        self.assertEqual(snap["gone"], [])
        self.assertEqual(_departures(sig), [])
        # and it comes back as a card when the price is inside its plan
        _quote(self.fx, "1.08450", SUN_2217)
        self.assertEqual([s.pk for s in self._snap(SUN_2220)["cards"]],
                         [sig.pk])
        self.assertEqual(_departures(sig), [])

    def test_6_with_the_switch_off_the_same_quote_still_leaves_as_on_main(
            self):
        """What the hold changes is under the switch: off, the rail's
        price rules judge a shut market's quote as they always did."""
        _switch(False)
        sig = _sig(self.fx, SUN_0900, rule="rms_fx")
        _quote(self.fx, "1.09100", SUN_2130 - timedelta(minutes=2))
        snap = self._snap(SUN_2130)
        self.assertNotIn(sig.pk, [s.pk for s in snap["cards"]])
        self.assertEqual([g.reason for g in snap["gone"]], ["stop_crossed"])
        self.assertEqual(len(_departures(sig)), 1)

    def test_7_crypto_and_open_markets_are_cards_as_before(self):
        self._two(born=MON_1000 - timedelta(hours=1))
        aapl = _db_inst("AAPL", "stock", "NASDAQ")
        share = _sig(aapl, _t(2026, 11, 9, 15, 0), rule="rms_share",
                     direction="bullish", entry="100", stop="95", target="110")
        snap = self._snap(_t(2026, 11, 9, 15, 30))
        self.assertEqual((snap["n"], snap["waiting_n"]), (3, 0))
        self.assertIn(share.pk, [s.pk for s in snap["cards"]])
        # a share before the bell waits; crypto never does
        snap = self._snap(_t(2026, 11, 10, 9, 0))
        self.assertEqual([g.symbol for g in snap["waiting"]], ["AAPL"])
        self.assertIn("opens Tuesday 14:30 UTC", snap["waiting"][0].words)
        self.assertIn("BTCUSD", [s.instrument.symbol for s in snap["cards"]])

    def test_8_the_counts_add_up(self):
        from signals.models import Signal
        self._two()                                  # 1 waiting, 1 card
        left = _sig(_db_inst("ETHUSD", "crypto"), SAT_1100, rule="rms_left",
                    direction="bullish", entry="3000", stop="2900",
                    target="3200")
        _quote(left.instrument, "2800", SAT_NOON - timedelta(minutes=1))
        _sig(self.btc, SAT_NOON - timedelta(days=3), rule="rms_old",
             direction="bullish", entry="60000", stop="58000", target="64000")
        snap = self._snap(SAT_NOON)
        gone_active = sum(1 for g in snap["gone"] if g.engine_active)
        self.assertEqual((snap["n"], snap["waiting_n"], gone_active,
                          snap["older_n"], snap["unevaluated"]),
                         (1, 1, 1, 1, 0))
        self.assertEqual(snap["n"] + snap["waiting_n"] + gone_active
                         + snap["older_n"] + snap["unevaluated"],
                         snap["active_n"])
        self.assertEqual(snap["active_n"],
                         Signal.objects.filter(is_active=True).count())

    def test_9_no_query_is_added_per_row(self):
        insts = [_db_inst(f"RMSW{i:02d}") for i in range(30)]
        for inst in insts[:3]:
            _sig(inst, SAT_1100, rule="rms_qc")
        self._rail(SAT_NOON)
        with _at(SAT_NOON), CaptureQueriesContext(connection) as three:
            self.assertEqual(len(_waiting_rows(_partial(self.client))), 3)
        for inst in insts[3:]:
            _sig(inst, SAT_1100, rule="rms_qc")
        with _at(SAT_NOON), CaptureQueriesContext(connection) as thirty:
            self.assertEqual(len(_waiting_rows(_partial(self.client))), 30)
        self.assertEqual(len(three.captured_queries),
                         len(thirty.captured_queries),
                         "\n".join(q["sql"][:160]
                                   for q in thirty.captured_queries))

    def test_10_the_rail_writes_no_engine_row_with_waiting_rows(self):
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        from signals.models import PromotionEvent, RuleControl, Signal

        def world():
            def row(obj):
                return json.dumps({f.attname: getattr(obj, f.attname)
                                   for f in obj._meta.concrete_fields},
                                  sort_keys=True, default=str)
            return {m.__name__: sorted(row(o) for o in m.objects.all())
                    for m in (Signal, RuleControl, PromotionEvent,
                              AssetBotTrade, Instrument)}

        self._two()
        _sig(_db_inst("RMSFB"), SAT_0005, rule="rms_early")
        _quote(self.fx, "1.09100", SAT_NOON - timedelta(minutes=1))
        before = world()
        html = self._rail(SAT_NOON)
        self.assertEqual(len(_waiting_rows(html)), 2)
        with _at(SAT_NOON):
            _page(self.client)
            _page(self.client, "/signals/")
        self.assertEqual(world(), before)

    def test_11_the_switch_off_draws_nothing_of_the_section(self):
        """Off, and with no row at all: the rail of the commit before."""
        from core.platform_control import PlatformComponent
        shut, always = self._two()
        with _at(SAT_NOON):
            on = (_partial(self.client), _page(self.client))
        _switch(False)
        with _at(SAT_NOON):
            off = (_partial(self.client), _page(self.client))
        PlatformComponent.objects.filter(key="signal_market_hold").delete()
        with _at(SAT_NOON):
            none = (_partial(self.client), _page(self.client))
        token = re.compile(r'(csrf[\w-]*"?\s*(?:value|content)?=?"?)'
                           r'[A-Za-z0-9]{32,}')
        self.assertEqual(_ageless(off[0]), _ageless(none[0]))
        self.assertEqual(_ageless(token.sub(r"\1", off[1])),
                         _ageless(token.sub(r"\1", none[1])))
        for html in off:
            self.assertNotIn("sr-shut-sec", html)
            self.assertNotIn("data-sv-shut", html)
            self.assertNotIn('data-sv-rail-n="waiting"', html)
            self.assertNotIn('data-f-key="shut"', html)
            self.assertNotIn("data-f-shut=", html)
            self.assertNotIn("waiting for their market", html)
        self.assertNotIn('"waiting"', off[0])
        # off: a card with its badge, counted on the rail
        self.assertEqual(set(_cards(off[0])), {shut.pk, always.pk})
        self.assertIn("MARKET SHUT", _card(off[0], shut))
        self.assertEqual(_meta(off[0])["n"], 2)
        # on: the section, and no badged card
        self.assertIn("sr-shut-sec", on[0])
        self.assertEqual(_cards(on[0]), [always.pk])
        self.assertNotIn("sr-shut-tag", on[0])

    def test_11_the_gate_off_draws_no_section_rows(self):
        """The suite's default: no market reads shut, so every candidate
        is a card whatever the switch says."""
        shut, always = self._two()
        snap = self._snap(SAT_NOON, gate=False)
        self.assertEqual((snap["n"], snap["waiting_n"]), (2, 0))
        self.assertIs(snap["hold"], False)


class TheSectionsControlsTests(_HoldBase):
    def test_hidden_by_default_and_shown_by_its_chip_or_its_row(self):
        from bs4 import BeautifulSoup

        from dashboard import rail_prefs
        from tests.test_rail_filters_css import (CSS, _set_state, hidden,
                                                 parse_rules)
        self.assertIs(rail_prefs.SIG_DEFAULT["shut"], False)
        self.assertIs(rail_prefs.clean({"sig": {"shut": "junk"}})["sig"]
                      ["shut"], False)
        self.assertIs(rail_prefs.clean({"sig": {"shut": True}})["sig"]
                      ["shut"], True)
        self._two()
        with _at(SAT_NOON):
            page = _page(self.client)
        # the chip counts the waiting signals and is not pressed
        chip = re.search(r'<button type="button" class="rf-chip rf-shut"'
                         r'[^>]*>SHUT <b data-sv-rail-n="waiting">1</b>'
                         r'</button>', page)
        self.assertIsNotNone(chip, "the SHUT chip is not on the rail bar")
        self.assertIn('data-f-key="shut" data-f-val="1" data-f-toggle '
                      'aria-pressed="false"', chip.group(0))
        self.assertNotIn('data-f-key="shut_off"', page)
        # the filter row, as LEFT THE RAIL's
        self.assertIn(
            '<div class="rf-row"><span class="rf-k">MARKET SHUT</span>'
            '<button type="button" class="rf-opt" data-f-key="shut" '
            'data-f-val="0" aria-pressed="true">hidden</button>'
            '<button type="button" class="rf-opt" data-f-key="shut" '
            'data-f-val="1" aria-pressed="false">shown</button></div>', page)
        self.assertEqual(page.count('data-f-shut="0"'), 2)
        soup = BeautifulSoup(page, "html.parser")
        rail = soup.find(id="signalsRail")
        rail["class"] = rail.get("class", []) + ["open"]
        rules = parse_rules(CSS.read_text(encoding="utf-8"))
        host = soup.find(id="railSignals")
        section = host.find(attrs={"data-sv-shut": True})
        row = section.find(class_="sr-wait-row")
        _set_state(host)
        self.assertTrue(hidden(section, rules, host))
        _set_state(host, shut="0")
        self.assertTrue(hidden(section, rules, host))
        _set_state(host, shut="1")
        self.assertFalse(hidden(section, rules, host))
        self.assertFalse(hidden(row, rules, host))
        # the rail's other filters reach its rows: a class the host hides
        _set_state(host, shut="1", **{"class": "crypto"})
        self.assertTrue(hidden(row, rules, host))
        _set_state(host, shut="1", **{"class": "crypto", "peek": "1"})
        self.assertFalse(hidden(row, rules, host))

    def test_a_stored_choice_is_drawn_and_survives_the_switch_off(self):
        resp = self.client.post(
            "/api/rail-prefs/", data=json.dumps(
                {"prefs": {"sig": {"shut": True}}}),
            content_type="application/json", HTTP_HOST=HOST)
        self.assertIs(resp.json()["prefs"]["sig"]["shut"], True)
        self._two()
        with _at(SAT_NOON):
            page = _page(self.client)
        self.assertEqual(page.count('data-f-shut="1"'), 2)
        self.assertIn('data-f-key="shut" data-f-val="1" data-f-toggle '
                      'aria-pressed="true"', page)
        # the switch off: the hosts still carry the stored state, so the
        # next saved filter does not reset it; nothing else is drawn
        _switch(False)
        with _at(SAT_NOON):
            page = _page(self.client)
        self.assertEqual(page.count('data-f-shut="1"'), 2)
        self.assertNotIn('data-f-key="shut"', page)
        self.assertNotIn("sr-shut-sec", page)


RUN_TAIL_SECTION = r"""
async function shutSection() {
  const W = boot();
  const out = {};
  const chip = W.chip('#railSigFacets', 'shut', '1');
  out.found = !!chip;
  out.before = [W.attr('railSignals', 'data-f-shut'), W.attr('hbSignalsDD', 'data-f-shut'),
                chip && chip.getAttribute('aria-pressed')];
  W.click(chip); await W.advance(700);
  out.shown = [W.attr('railSignals', 'data-f-shut'), W.attr('hbSignalsDD', 'data-f-shut'),
               chip.getAttribute('aria-pressed')];
  out.row_buttons = W.doc.querySelectorAll('#railSigPanel [data-f-key="shut"]').map(b => b.getAttribute('aria-pressed'));
  out.posts = W.posts.length;
  out.body = W.posts.length ? JSON.parse(W.posts[0].body) : null;
  /* a filter hides the section's row: it is counted, and said apart */
  const row = W.doc.querySelector('[data-sv-shut] [data-sv-row]');
  out.row_found = !!row;
  if (row) row.setAttribute('data-x-hidden', '');
  W.fire('htmx:afterSwap', {}); await W.advance(50);
  out.status = W.status();
  out.errors = W.errors();
  return out;
}

(async () => {
  process.stdout.write(JSON.stringify({ shut_section: await shutSection() }));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(NODE, "node is not installed on this machine")
class TheSectionInTheBrowserTests(_HoldBase):
    def test_the_chip_shows_the_section_on_both_hosts_and_saves(self):
        report = TheChipInTheBrowserTests._report(self, tail=RUN_TAIL_SECTION)
        r = report["shut_section"]
        dump = json.dumps(r, indent=1)[:4000]
        self.assertTrue(r["found"], dump)
        self.assertEqual(r["before"], ["0", "0", "false"], dump)
        self.assertEqual(r["shown"], ["1", "1", "true"], dump)
        self.assertEqual(r["row_buttons"], ["false", "true"], dump)
        self.assertEqual(r["posts"], 1, dump)
        self.assertIs(r["body"]["prefs"]["sig"]["shut"], True, dump)
        self.assertIs(r["body"]["prefs"]["sig"]["shut_off"], False, dump)
        self.assertTrue(r["row_found"], dump)
        # the rail's own bar says it (the headband's list has no section)
        self.assertEqual([("1 in MARKET SHUT" in s) for s in r["status"]],
                         [False, True], dump)
        self.assertEqual(r["errors"], [], dump)


class TheSignalsPageSaysItWasHeldTests(_HoldBase):
    def _held(self, born=SAT_1100):
        from signals.announce import announce_new_signal
        sig = _sig(self.fx, born, rule="rms_fx")
        with _at(born):
            out = announce_new_signal(sig)
        self.assertIn("held", out)
        return sig

    def test_a_held_signal_says_born_while_its_market_was_shut(self):
        from io import StringIO

        from django.core.management import call_command
        sig = self._held()
        plain = _sig(self.btc, SAT_1100, rule="rms_btc", direction="bullish",
                     entry="60000", stop="58000", target="64000")
        with _at(SAT_NOON):
            html = _page(self.client, "/signals/")
        row = _signals_row(html, sig)
        self.assertIn('<div class="sig-hold" title="The forex market is '
                      'shut: it opens Sunday 22:00 UTC">announcement held: '
                      'born while its market was shut · it opens Sunday '
                      '22:00 UTC</div>', row)
        self.assertNotIn("sig-hold", _signals_row(html, plain))
        out = StringIO()
        with _at(SAT_NOON):
            call_command("signals", "show", str(sig.pk), stdout=out)
        self.assertIn("announcement held: born while its market was shut · "
                      "it opens Sunday 22:00 UTC", out.getvalue())

    def test_a_released_and_a_dropped_signal_say_what_happened(self):
        from signals.market_hold import release_due
        sig = self._held(born=SUN_0900)
        gapped = _sig(_db_inst("RMSFB"), SUN_0900, rule="rms_gap")
        from signals.announce import announce_new_signal
        with _at(SUN_0900):
            announce_new_signal(gapped)
        _quote(self.fx, "1.08450", SUN_2217)
        _quote(gapped.instrument, "1.09100", SUN_2217)
        with _at(SUN_2220):
            release_due()
            html = _page(self.client, "/signals/")
        self.assertIn("born while its market was shut · announced at the "
                      "open, Sunday 22:20 UTC", _signals_row(html, sig))
        self.assertIn("born while its market was shut · at the open the "
                      "first price, 1.09100, was at or through its stop, "
                      "1.09000: it was never announced.",
                      _signals_row(html, gapped))

    def test_with_no_hold_row_the_page_is_the_one_before(self):
        self._two()
        with _at(SAT_NOON):
            on = _signals_rows(_page(self.client, "/signals/"))
        _switch(False)
        with _at(SAT_NOON):
            off = _signals_rows(_page(self.client, "/signals/"))
        self.assertEqual(_ageless(on), _ageless(off))
        self.assertNotIn("sig-hold", on)
