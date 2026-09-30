"""Real money is unmistakable, on every surface (2026-09-30).

The operator, the morning live trading was unblocked: live and paper were
"still light" for him and his father. The survey behind this found the
/positions/ table with no per-row marker, /asset-bots/ and the heartbeat
marking only paper rows (live marked by absence), four colour schemes
(paper painted green), demo fills printed LIVE, no indicator anywhere that
real money was armed, and Telegram /status with no split.

Pinned here:
  - the one reader, position_summary.world_of: live / demo / paper from
    the row's own stamps, "" for a row that states no venue;
  - the one marker, sauron_tags money_world: REAL MONEY (the only solid
    red fill), DEMO, PAPER; a config's mode reads the same words;
  - the pages: /positions/ (open rows and closed cards), /asset-bots/
    (bots, open and closed), the heartbeat rows, the armed pill on every
    page while a live config is enabled;
  - the activity drawer's fills and the audit rows behind them;
  - Telegram: REAL MONEY in a position line and a bot line, the status
    heading split, a demo fill never called live;
  - the style: the marker's CSS, and the old .sv-venue label untouched.

Run with:  python manage.py test tests.test_money_world
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from tests.test_position_page import _age, _config, _instrument, _quote, _trade

BASE = Path(__file__).resolve().parent.parent
ETORO_LIVE = {"broker": "etoro", "broker_env": "live"}
ETORO_DEMO = {"broker": "etoro", "broker_env": "paper"}


class _Row:
    def __init__(self, paper, metadata=None):
        self.paper, self.metadata = paper, metadata


class TheReaderTests(SimpleTestCase):

    def test_the_three_worlds(self):
        from dashboard.position_summary import world_of
        self.assertEqual(world_of(_Row(False, ETORO_LIVE)), "live")
        self.assertEqual(world_of(_Row(False, ETORO_DEMO)), "demo")
        self.assertEqual(world_of(_Row(True, ETORO_LIVE)), "paper")

    def test_a_live_row_with_no_stamp_is_real_money(self):
        """Real money at a broker the row never named: never guessed away."""
        from dashboard.position_summary import world_of
        self.assertEqual(world_of(_Row(False, None)), "live")
        self.assertEqual(world_of(_Row(False, {})), "live")

    def test_the_paper_carrier_is_paper_whatever_the_flag(self):
        from dashboard.position_summary import world_of
        self.assertEqual(world_of(_Row(False, {"broker": "paper"})), "paper")

    def test_a_row_that_states_no_venue_has_no_world(self):
        """A legacy Position has no `paper`: no marker, never a guess."""
        from dashboard.position_summary import world_of
        self.assertEqual(world_of(_Row(None, ETORO_LIVE)), "")
        self.assertEqual(world_of(object()), "")

    def test_a_dict_row_reads_the_same(self):
        from dashboard.position_summary import world_of
        self.assertEqual(world_of({"paper": False, "metadata": ETORO_DEMO}),
                         "demo")
        self.assertEqual(world_of({"paper": True}), "paper")
        self.assertEqual(world_of({"paper": None}), "")


class TheMarkerTests(SimpleTestCase):

    def _render(self, src, **ctx):
        return Template("{% load sauron_tags %}" + src).render(Context(ctx))

    def test_real_money_is_the_solid_red_marker(self):
        out = self._render("{% money_world t %}", t=_Row(False, ETORO_LIVE))
        self.assertIn('class="sv-world sv-world--live"', out)
        self.assertIn(">REAL MONEY<", out)

    def test_demo_and_paper(self):
        self.assertIn(">DEMO<", self._render("{% money_world t %}",
                                             t=_Row(False, ETORO_DEMO)))
        self.assertIn(">PAPER<", self._render("{% money_world t %}",
                                              t=_Row(True)))

    def test_a_config_mode_reads_the_same_words(self):
        self.assertIn(">REAL MONEY<", self._render('{% money_world "live" %}'))
        self.assertIn(">PAPER<", self._render('{% money_world "paper" %}'))

    def test_the_compact_form_for_the_heartbeat(self):
        out = self._render('{% money_world t compact="1" %}',
                           t={"world": "live"})
        self.assertIn(">REAL<", out)
        self.assertIn(">PAPER<", self._render('{% money_world t compact="1" %}',
                                              t={"world": "paper"}))

    def test_nothing_for_a_row_with_no_world(self):
        for value in (None, "", "shadow", _Row(None), {"world": ""}):
            self.assertEqual(self._render("{% money_world v %}", v=value), "",
                             value)

    def test_the_filter_for_a_row_class(self):
        out = self._render('{% if t|world == "live" %}edge{% endif %}',
                           t=_Row(False, ETORO_LIVE))
        self.assertEqual(out, "edge")


class ThePagesTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "world_u", password="x", is_staff=True)
        self.client.force_login(self.user)
        _quote(_instrument(), "1.60")

    def test_positions_marks_each_open_row_by_its_world(self):
        _trade(self.user, paper=False, metadata=ETORO_LIVE)
        _trade(self.user, paper=False, metadata=ETORO_DEMO,
               config=_config(self.user, mode="live"))
        _trade(self.user, paper=True)
        page = self.client.get(reverse("positions_list")).content.decode()
        self.assertEqual(page.count('class="sv-row--live"'), 1)
        self.assertEqual(page.count('data-pos-world="live"'), 1)
        self.assertEqual(page.count('data-pos-world="demo"'), 1)
        self.assertEqual(page.count('data-pos-world="paper"'), 1)
        for words in (">REAL MONEY<", ">DEMO<", ">PAPER<"):
            self.assertIn(words, page)

    def test_a_closed_real_money_card_carries_the_edge(self):
        from datetime import timedelta
        from django.utils import timezone
        t = _trade(self.user, paper=False, metadata=ETORO_LIVE,
                   status="CLOSED", exit_price="1.61", pnl="10")
        now = timezone.now()
        _age(t, opened=now - timedelta(hours=3), closed=now - timedelta(hours=1))
        page = self.client.get(reverse("positions_list") + "?tab=history"
                               ).content.decode()
        self.assertIn('class="ph-trade-card sv-row--live"', page)

    def test_asset_bots_marks_the_bot_and_its_positions(self):
        live = _config(self.user, mode="live")
        _trade(self.user, paper=False, metadata=ETORO_LIVE, config=live)
        page = self.client.get(reverse("asset_bots_dashboard")).content.decode()
        self.assertIn('<td data-label="Mode"><span class="sv-world sv-world--live"',
                      page)
        self.assertIn('<tr class="sv-row--live">', page)
        self.assertNotIn("badge-bullish\">paper", page)

    def test_the_armed_pill_stands_while_a_live_config_is_enabled(self):
        page = self.client.get(reverse("asset_bots_dashboard")).content.decode()
        self.assertNotIn('class="sv-armed-pill"', page)
        _config(self.user, mode="live")
        page = self.client.get(reverse("asset_bots_dashboard")).content.decode()
        self.assertIn('class="sv-armed-pill"', page)
        self.assertIn("1 bot armed", page)

    def test_the_heartbeat_rows_carry_the_world(self):
        from core.context_processors import _world_of
        from dashboard.position_summary import world_of
        self.assertIs(_world_of, world_of)
        src = (BASE / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("{% money_world t compact=\"1\" %}", src)
        self.assertNotIn('{% if t.paper %}<span class="sv-chip sv-chip--muted">'
                         'paper</span>{% endif %}', src)
        self.assertIn("{% if t.world == 'live' %} sv-row--live{% endif %}", src)


class TheDrawerTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("drawer_w")

    def test_a_new_fill_writes_its_world_and_the_drawer_reads_it(self):
        from bot_program import audit
        from bot_program.audit_models import AuditLogEntry
        from dashboard.activity_feed import _audit
        from django.utils import timezone
        _quote(_instrument(), "1.60")
        demo = _trade(self.user, paper=False, metadata=ETORO_DEMO)
        audit.record_trade_open(self.user, trade=demo)
        row = AuditLogEntry.objects.get(kind="trade_open")
        self.assertEqual(row.data["world"], "demo")
        self.assertEqual(row.data["mode"], "live")
        ev = _audit(self.user, None, 10, timezone.now())[0]
        self.assertEqual(ev["world"], "demo")

    def test_an_older_row_falls_back_to_its_mode(self):
        from dashboard.activity_feed import _audit_world
        self.assertEqual(_audit_world({"kind": "trade_close",
                                       "data": {"mode": "live"}}), "live")
        self.assertEqual(_audit_world({"kind": "trade_open",
                                       "data": {"mode": "paper"}}), "paper")
        self.assertEqual(_audit_world({"kind": "desk_plan",
                                       "data": {"mode": "live"}}), "")

    def test_the_script_renders_the_marker(self):
        js = (BASE / "static" / "js" / "sv-activity.js").read_text(encoding="utf-8")
        self.assertIn("WORLD_WORDS[ev.world]", js)
        self.assertIn("'sv-world sv-world--' + ev.world", js)
        self.assertIn("li.className += ' sv-row--live'", js)


class TheTelegramTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("tg_w")
        _quote(_instrument(), "1.60")

    def test_a_position_line_says_real_money_demo_or_paper(self):
        from bot_program.telegram_eye import position_line
        live = _trade(self.user, paper=False, metadata=ETORO_LIVE)
        demo = _trade(self.user, paper=False, metadata=ETORO_DEMO)
        paper = _trade(self.user, paper=True)
        self.assertIn("· REAL MONEY", position_line(live))
        self.assertIn("· demo", position_line(demo))
        self.assertNotIn("REAL MONEY", position_line(demo))
        self.assertTrue(position_line(paper).endswith("· paper"))

    def test_a_live_bot_line_says_real_money(self):
        from bot_program.telegram_eye import mode_word
        self.assertEqual(mode_word("live"), "REAL MONEY")
        self.assertEqual(mode_word("paper"), "paper")

    def test_the_positions_heading_counts_real_money_apart(self):
        from bot_program.telegram_eye import build_positions
        _trade(self.user, paper=False, metadata=ETORO_LIVE)
        _trade(self.user, paper=False, metadata=ETORO_DEMO)
        reply = build_positions(self.user)
        text = "\n".join(reply.lines) if hasattr(reply, "lines") else str(reply)
        self.assertIn("Open on the platform: 2 (1 real money · 1 simulated)",
                      text)


class TheStyleTests(SimpleTestCase):

    def test_real_money_is_the_one_solid_red_fill(self):
        css = (BASE / "static" / "css" / "sauron.css").read_text(encoding="utf-8")
        live = css[css.index(".sv-world--live {"):]
        live = live[:live.index("}")]
        self.assertIn("background: var(--accent-red)", live)
        for key in (".sv-world--demo {", ".sv-world--paper {"):
            rule = css[css.index(key):]
            self.assertIn("background: transparent", rule[:rule.index("}")])
        self.assertIn("inset 3px 0 0 var(--accent-red)", css)

    def test_the_old_label_is_untouched(self):
        css = (BASE / "static" / "css" / "sauron.css").read_text(encoding="utf-8")
        self.assertIn(".sv-venue--live { color: var(--accent-red); }", css)
        self.assertIn(".sv-venue--paper { color: var(--text-muted); }", css)

    def test_the_armed_pill_respects_reduced_motion(self):
        css = (BASE / "static" / "css" / "sauron.css").read_text(encoding="utf-8")
        self.assertIn("@media (prefers-reduced-motion: reduce) { .sv-armed-dot "
                      "{ animation: none; } }", css)

    def test_no_bot_mode_is_painted_green_any_more(self):
        for name in ("asset_bots.html", "_command_bots.html", "shares.html",
                     "personas.html", "evidence.html"):
            src = (BASE / "templates" / "dashboard" / name).read_text(
                encoding="utf-8")
            self.assertNotIn("mode == 'live' %}bearish{% else %}bullish", src,
                             name)
            self.assertIn("{% money_world", src, name)
