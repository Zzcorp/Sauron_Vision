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
from tests.test_signal_market_hold import (MON_1000, SAT_NOON, SUN_2205,
                                           SUN_2220, _at, _db_inst, _quote,
                                           _sig, _t)

NODE = shutil.which("node")
SAT_1100 = _t(2026, 11, 7, 11, 0)
OPENS = "opens Sun 22:00 UTC"
TICKET_WORDS = ("a paper ticket is refused until it opens; a live ticket "
                "warns and is yours to send")
ROW_ANY = re.compile(r'<div class="ip-dd-row sv-sig-row"[^>]*?'
                     r'data-signal-id="(\d+)".*?</div>', re.S)


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
        return on, off

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

    def _report(self):
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
            (tmp / "run.js").write_text(boot + RUN_TAIL, encoding="utf-8")
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
