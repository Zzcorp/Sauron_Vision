"""THE COUNCIL BAND (task #104, 2026-10-22): Sauron's voices on the right
edge of every staff page, read-only.

What Sauron thinks now, who disagrees and who has been right: the council
of ten with the Emperor in the chair, its sittings, the round table, the
voices' dossiers, the Emperor's Hand, the people's mood and the traders'
personalities. The band reads; nothing in it acts.

The groups follow the build plan (scratchpad councilband2/delta.md §6.5):

  A. the markup and the include      E. the truth contract
  B. the sheet                       F. Council 2: the Hand and the mood
  C. the script                      G. the council_sitting event
  D. the view                        H. the chrome around it

Run with:  python manage.py test tests.test_council_band
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

URL = "/api/council/band/"
BASE = Path(settings.BASE_DIR)
JS = BASE / "static" / "js" / "sv-council-band.js"
SHEET = BASE / "static" / "css" / "sv-council-band.css"
PARTIAL = BASE / "templates" / "_partials" / "council_band.html"
BAND_PY = BASE / "dashboard" / "council_band.py"
VIEW_PY = BASE / "dashboard" / "views_council_band.py"
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
WITHHELD = "Withheld: this line may name an amount of money."
INCLUDE = ('{% if user.is_staff %}{% include "_partials/council_band.html" %}'
           '{% endif %}')


def _read(*parts):
    return BASE.joinpath(*parts).read_text(encoding="utf-8")


def _strip_js(src):
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", code)


def _strip_css(src):
    return re.sub(r"/\*.*?\*/", "", src, flags=re.S)


def _text(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def _strings(obj):
    """Every string value (and every key) in a JSON-shaped answer."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _keys(v)


# ── fixtures ─────────────────────────────────────────────────────────────

def _user(name, staff=False):
    return User.objects.create_user(username=name, password="x",
                                    is_staff=staff)


def _switch(key, on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=key, defaults={"name": key, "category": "agent",
                           "is_enabled": on})


def _session(**kw):
    from ai_agents.council_models import CouncilSession
    fields = {"origin": "bot", "venue": "live", "status": "done",
              "symbol": "EURUSD", "asset_class": "forex", "side": "BUY",
              "regime": "trending"}
    created = kw.pop("created_at", None)
    fields.update(kw)
    s = CouncilSession.objects.create(**fields)
    if created is not None:
        CouncilSession.objects.filter(id=s.id).update(created_at=created)
        s.refresh_from_db()
    return s


def _speak(s, voice, answer=None, *, status="spoke", wave=None, why="",
           model="test-model", weight_seen=None, weight_reason=""):
    """One voice as the sitting lands it: its row, then its claims, from
    the council's own claims_for (council._land's order)."""
    from ai_agents.agents import council as C
    from ai_agents.council_models import CouncilClaim, CouncilVoice
    answer = dict(answer or {})
    spoken = status in ("spoke", "copied", "late")
    p, conv = C.p_and_conviction(voice, answer) if spoken else (None, None)
    row = CouncilVoice.objects.create(
        session=s, voice=voice, wave=C.VOICE_WAVE[voice] if wave is None
        else wave, status=status, why=why,
        verdict=str(answer.get("verdict", ""))[:20] if spoken else "",
        p_work=p, conviction=conv, answer=answer if spoken else {},
        model=model if spoken else "", weight_seen=weight_seen,
        weight_reason=weight_reason,
        answered_at=timezone.now() if spoken else None)
    if spoken:
        for c in C.claims_for(voice, answer, late=status == "late"):
            CouncilClaim.objects.create(
                session=s, voice=row, voice_key=voice, regime=s.regime,
                asset_class=s.asset_class, venue=s.venue, origin=s.origin,
                kind=c["kind"], stance=c["stance"], p=c["p"],
                payload=c["payload"], symbol=c["symbol"], grade=c["grade"],
                grade_notes=c["grade_notes"])
    return row


def _report(regime="trending", conf=0.71, minutes=10, error=""):
    from brain.models import BrainReport
    r = BrainReport.objects.create(regime_label=regime,
                                   regime_confidence=conf, error=error)
    BrainReport.objects.filter(id=r.id).update(
        created_at=timezone.now() - timedelta(minutes=minutes))
    return r


def _rm(**over):
    """A record_matrix() answer in the council's own shape."""
    from ai_agents.agents import council as C
    from bot_program.persona_mix import REGIMES
    voices = [{"voice": v, "name": C.VOICE_NAMES[v], "factor": 1.0,
               "lane": "neutral", "n": 0, "brier": None, "base_rate": None,
               "reference": None, "reason": "neutral: 0 graded calls in this "
               "cell, 10 needed", "right": 0, "wrong": 0, "bot_n": 0,
               "hand_n": 0, "specialty": "calls right 0 of 0",
               "cost_30d": 0.0} for v in C.ALL_VOICES]
    out = {"schema_version": 1, "voices": voices,
           "benchmarks": [{"name": "The Emperor", "brier": None, "n": 0},
                          {"name": "The council, weighted by record",
                           "brier": None, "n": 0},
                          {"name": "The council, plain average",
                           "brier": None, "n": 0}],
           "benchmarks_unpaired": 0, "regimes": list(REGIMES),
           "matrix": [{"voice": v, "name": C.VOICE_NAMES[v],
                       "cells": [{"regime": rg, "factor": 1.0, "n": 0,
                                  "lane": "neutral"} for rg in REGIMES]}
                      for v in C.ALL_VOICES],
           "replay": {"n": 0, "agree": 0},
           "chair": {"over_wrong": 0, "over_n": 0, "follow_right": 0,
                     "follow_n": 0},
           "graded_any": False, "asset_class": "", "hands": [],
           "against_hand": {"overruled": 0, "graded": 0, "emperor_right": 0,
                            "hand_right": 0, "unresolved": 0, "pending": 0,
                            "no_reason": 0, "by_voice": {},
                            "agreed": {"n": 0, "right": 0}},
           "skeptic_first": {"named": 0, "attacked": 0, "first": 0,
                             "right": 0, "graded": 0},
           "moods": []}
    out.update(over)
    return out


def _mood(level="steady", inputs=None, measured_n=None, why=""):
    from ai_agents import council_mood as M
    inputs = inputs if inputs is not None else {
        k: {"label": M.LABELS[k], "measured": True, "reading": 0.0,
            "band": 0, "words": "+0.00R over 2 real closes"}
        for k in M.INPUTS}
    n = measured_n if measured_n is not None else sum(
        1 for e in inputs.values() if e.get("measured"))
    out = {"level": level, "reasons": [M.LEVEL_WORDS.get(level, "")],
           "inputs": inputs, "measured_n": n, "of": len(M.INPUTS), "at": ""}
    if why:
        out["why"] = why
    return out


def _everything(user):
    """Every answer the band can give this reader, as one text."""
    from ai_agents.agents import council as C
    from ai_agents.council_models import CouncilSession
    from dashboard import council_band as B
    out = {"room": B.build_room(user), "sittings": B.build_sittings(user)}
    for sid in CouncilSession.objects.filter(venue="live").values_list(
            "id", flat=True):
        out[f"sitting{sid}"] = B.build_sitting(user, sid)
    for v in C.ALL_VOICES:
        out[f"voice_{v}"] = B.build_voice(user, v)
    return out


class _Case(TestCase):
    def setUp(self):
        cache.clear()


# ══ A. the markup and the include ═══════════════════════════════════════

@override_settings(CACHES=LOCMEM)
class TheMarkupTests(_Case):

    def test_a_staff_page_carries_the_band_once_and_a_member_none(self):
        self.client.force_login(_user("cb_staff", staff=True))
        body = self.client.get("/getting-started/").content.decode()
        self.assertEqual(body.count('id="svCouncilBand"'), 1)
        tab = body[body.index('id="svCouncilBandTab"') - 200:
                   body.index('id="svCouncilBandTab"') + 300]
        self.assertIn('aria-expanded="false"', tab)
        self.assertIn('aria-controls="svCouncilBandPanel"', tab)
        panel = body[body.index('id="svCouncilBandPanel"'):
                     body.index('id="svCouncilBandPanel"') + 300]
        self.assertIn("inert", panel)
        self.assertIn(URL, body)
        self.client.force_login(_user("cb_member"))
        body = self.client.get("/getting-started/").content.decode()
        self.assertNotIn("svCouncilBand", body)
        self.assertNotIn(URL, body)

    def test_the_include_sits_between_the_drawer_and_the_horde_outside_the_page(self):
        base = _read("templates", "base.html")
        self.assertEqual(base.count("council_band.html"), 1)
        self.assertIn(INCLUDE, base)
        at = base.index(INCLUDE)
        self.assertGreater(at, base.index('{% include "_partials/activity_drawer.html" %}'))
        self.assertGreater(at, base.index("</main>"))
        self.assertGreater(at, base.index('<div class="page-content'))
        self.assertLess(at, base.index('{% include "_partials/the_horde.html" %}'))

    def test_no_public_page_carries_it(self):
        staff = _user("cb_public", staff=True)
        self.client.force_login(staff)
        for path in ("/wall/", "/book/"):
            r = self.client.get(path)
            self.assertNotIn("svCouncilBand", r.content.decode(), path)
        self.client.logout()
        for path in ("/login/", "/wall/", "/book/", "/"):
            r = self.client.get(path)
            self.assertNotIn("svCouncilBand", r.content.decode(), path)
        for name in ("the_book.html", "the_wall.html", "withheld.html"):
            self.assertNotIn("council_band", _read("templates", "landing", name))

    def test_the_partial_is_markup_only(self):
        src = PARTIAL.read_text(encoding="utf-8")
        for banned in ("<script", "<style", "data-sv-live", "hx-trigger",
                       " as council_url"):
            self.assertNotIn(banned, src, banned)
        self.assertIn("{% url 'council_dashboard' %}", src)
        self.assertIn("{% url 'council_band' %}", src)

    def test_every_static_word_lives_in_the_template(self):
        from dashboard.council_band import WORDS
        src = PARTIAL.read_text(encoding="utf-8")
        spans = dict(re.findall(r'<span data-w="([a-z0-9_]+)">([^<]*)</span>', src))
        import html
        spans = {k: html.unescape(v) for k, v in spans.items()}
        self.assertEqual(spans, WORDS)
        want = set(re.findall(r"\bW\('([a-z0-9_]+)'", _strip_js(JS.read_text(encoding="utf-8"))))
        self.assertTrue(want)
        self.assertEqual(want - set(spans), set())

    def test_every_sentence_is_plain_english(self):
        """English, plain: no French article, no accented letter, and
        beyond ASCII only the typographic marks the platform already
        prints (×, ·, —, ›, ‹, …) and the table's glyphs."""
        from ai_agents.council_mood import CAUTION_ONLY
        from dashboard import council_band as B
        allowed = set("×·—›‹…▲▼●○◐✕⇔’")
        texts = list(B.WORDS.values()) + [
            v for k, v in vars(B).items()
            if k.isupper() and isinstance(v, str)]
        for name in ("ROLE", "SENTENCE", "GRADE_WORDS"):
            texts += list(getattr(B, name).values())
        texts += [t["title"] for t in B.TRIADS] + [t["sub"] for t in B.TRIADS]
        texts += list(B.VERDICT_TOKENS.values())
        self.assertGreater(len(texts), 120)
        for t in texts:
            for ch in t:
                self.assertTrue(ord(ch) < 128 or ch in allowed, (t, ch))
            low = f" {t.lower()} "
            for fr in (" le ", " la ", " les ", " des ", " est ", " une ",
                       " du ", " et "):
                self.assertNotIn(fr, low, t)
            for word in ("happy", "bold"):
                self.assertNotRegex(low, rf"\b{word}\b", t)
            # "calm" only ever denied: "unmeasured, never calm"
            self.assertNotRegex(low, r"(?<!never )(?<!as )\bcalm\b", t)
            if t != CAUTION_ONLY:
                self.assertNotRegex(low, r"\bcontent\b", t)


# ══ B. the sheet ════════════════════════════════════════════════════════

class TheSheetTests(SimpleTestCase):

    def setUp(self):
        self.css = _strip_css(SHEET.read_text(encoding="utf-8"))
        self.base = _read("templates", "base.html")

    def _rule(self, selector, text=None):
        m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}",
                      text or self.css)
        self.assertIsNotNone(m, selector)
        return " ".join(m.group(1).split())

    def _media(self, query):
        return re.findall(r"@media " + re.escape(query) + r" \{(.*?)\n\}",
                          self.css, re.S)

    def test_the_sheet_and_script_load_after_the_horde_before_the_phone_tier(self):
        link = '<link rel="stylesheet" href="{% static \'css/sv-council-band.css\' %}">'
        self.assertEqual(self.base.count("'css/sv-council-band.css'"), 1)
        self.assertIn(link, self.base)
        at = self.base.index("'css/sv-council-band.css'")
        self.assertGreater(at, self.base.index("'css/sv-horde.css'"))
        self.assertLess(at, self.base.index("'css/sv-responsive.css'"))
        tag = '<script src="{% static \'js/sv-council-band.js\' %}" defer></script>'
        self.assertEqual(self.base.count("'js/sv-council-band.js'"), 1)
        self.assertIn(tag, self.base)
        js = self.base.index("'js/sv-council-band.js'")
        self.assertGreater(js, self.base.index("'js/sv-horde.js'"))
        self.assertLess(js, self.base.index("</head>"))

    def test_every_z_index_is_a_rung_and_no_colour_is_hex(self):
        zs = re.findall(r"z-index\s*:\s*([^;]+);", self.css)
        self.assertTrue(zs)
        for z in zs:
            self.assertRegex(z.strip(), r"^(calc\()?var\(--z-", z)
        self.assertIn("z-index: var(--z-drawer);", self._rule(".sv-council-band"))
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", self.css), [])
        self.assertNotRegex(self.css, r"rgba?\(")
        self.assertNotRegex(self.css, r"animation[^;{}]*\b(forwards|both)\b")

    def test_the_column_stops_under_the_headbands_and_clears_the_strip(self):
        root = self._rule(".sv-council-band")
        for decl in ("--cb-top: calc(var(--topbar-height) + 88px);",
                     "--cb-foot: 28px;",
                     "--cb-bottom: calc(var(--ip-h, 0px) + var(--cb-foot));",
                     "top: var(--cb-top);", "bottom: var(--cb-bottom);",
                     "position: fixed;", "transform: translateX(100%);",
                     "pointer-events: none;"):
            self.assertIn(decl, root, decl)
        self.assertIn("--cb-foot: 0px;",
                      self._rule("body.page-dashboard .sv-council-band"))
        wide = [b for b in self._media("(min-width: 769px)")
                if "body:has(.info-panel-wrap.minimized) .sv-council-band" in b]
        self.assertEqual(len(wide), 1)
        self.assertIn("--cb-foot: 44px;", self._rule(
            "body:has(.info-panel-wrap.minimized) .sv-council-band", wide[0]))

    def test_the_tab_keeps_one_height_and_can_be_moved_by_measure(self):
        tab = self._rule(".sv-council-band-tab")
        self.assertIn("top: var(--cb-tab-top, max(8px, calc(50% - 156px - "
                      "var(--cb-top) / 2 + var(--cb-bottom) / 2)));", tab)
        for decl in ("position: absolute;", "left: -28px;", "width: 28px;",
                     "height: 112px;", "pointer-events: auto;"):
            self.assertIn(decl, tab, decl)

    def test_an_open_band_pushes_the_horde_on_desktop_and_never_touches_its_sheet(self):
        blocks = [b for b in self._media("(min-width: 769px)")
                  if "body:has(.sv-council-band.open) .sv-horde" in b]
        self.assertEqual(len(blocks), 1)
        # an OPEN Horde only (round 1): pushing a shut one crushed its tab
        # to "HC" and its REAL pill out of sight
        push = self._rule("body:has(.sv-council-band.open) .sv-horde.open", blocks[0])
        # by the band AND the tabs' 28px gutter (round 2: the COUNCIL and
        # ACTIVITY tabs stood on the pushed Horde's body)
        self.assertIn("right: calc(var(--sv-rail-w) + var(--sv-cband-w) + 28px);", push)
        self.assertIn("--hd-r: calc(var(--sv-rail-w) + var(--sv-cband-w) + 28px);", push)
        self.assertNotRegex(self.css, r"\.sv-horde\s*\{")
        self.assertNotRegex(self.css, r"\.sv-horde:not\(")
        self.assertNotIn("--hd-sr", self.css)
        horde = _strip_css(_read("static", "css", "sv-horde.css"))
        for decl in ("right: 404px;", "right: 640px;", "--hd-r: 404px;"):
            self.assertIn(decl, horde, decl)
        self.assertNotIn("council", horde.lower())

    def test_the_rides_and_the_shut_root_take_no_click(self):
        blocks = "\n".join(self._media("(min-width: 769px)"))
        self.assertIn("right: calc(var(--sv-rail-w) + 360px);",
                      self._rule("body:has(.sv-activity.open) .sv-council-band", blocks))
        act = self._rule("body:has(.sv-council-band.open) .sv-activity", blocks)
        self.assertIn("right: calc(var(--sv-rail-w) + var(--sv-cband-w));", act)
        self.assertIn("pointer-events: none;", act)
        self.assertIn("pointer-events: auto;",
                      self._rule("body:has(.sv-council-band.open) .sv-activity-tab", blocks))
        self.assertRegex(blocks, r"body:has\(\.sv-activity\.open\) \.rail-toggle-btn,\s*"
                                 r"body:has\(\.sv-council-band\.open\) \.rail-toggle-btn "
                                 r"\{ right: calc\(var\(--sv-rail-w\) \+ var\(--sv-dock-w\)\); \}")
        self.assertIn("pointer-events: auto;",
                      self._rule(".sv-council-band.open .sv-council-band-panel"))
        drawer = _strip_css(_read("static", "css", "sv-activity.css"))
        self.assertNotIn("council", drawer.lower())

    def test_reduced_motion_switches_it_off(self):
        m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*)\}\s*$",
                      self.css, re.S)
        self.assertIsNotNone(m)
        block = m.group(1)
        for sel in (".sv-council-band,", ".sv-council-band-panel",
                    ".sv-council-band-tab", ".cb-dossier", ".cb-seat",
                    ".cb-dot.live", ".cb-new", "#svCouncilBandTab.gl-pointed"):
            self.assertIn(sel, block, sel)
        self.assertIn("transition: none", block)
        self.assertIn("animation: none", block)

    def test_the_phone_tier_hides_it_on_the_rails_line(self):
        phone = _strip_css(_read("static", "css", "sv-responsive.css"))
        line = re.search(r"^\s*([^{\n]*\.signals-rail[^{\n]*)\{ display: none !important; \}",
                         phone, re.M)
        self.assertIsNotNone(line)
        hidden = [s.strip() for s in line.group(1).split(",")]
        for sel in (".signals-rail", ".sv-activity", ".sv-council-band",
                    ".sv-council-band-tab"):
            self.assertIn(sel, hidden)
        self.assertNotIn("horde", phone.lower())

    def test_no_mood_level_is_painted_as_good(self):
        self.assertIn("var(--text-secondary)", self._rule(".cb-mood--steady"))
        for level in ("steady", "uneasy", "restless", "afraid", "unmeasured"):
            rule = self._rule(f".cb-mood--{level}")
            self.assertNotIn("--accent)", rule, level)
            self.assertNotIn("var(--accent);", rule, level)
        self.assertIn("var(--accent-gold-ink)", self._rule(".cb-mood--uneasy"))
        self.assertIn("var(--warning)", self._rule(".cb-mood--restless"))
        self.assertIn("var(--danger)", self._rule(".cb-mood--afraid"))
        self.assertIn("dashed", self._rule(".cb-mood--unmeasured"))


# ══ C. the script ═══════════════════════════════════════════════════════

class TheScriptTests(SimpleTestCase):

    def setUp(self):
        self.js = JS.read_text(encoding="utf-8")
        self.code = _strip_js(self.js)

    def _fn(self, name):
        start = self.code.index(f"function {name}(")
        depth, i = 0, self.code.index("{", start)
        for i in range(i, len(self.code)):
            if self.code[i] == "{":
                depth += 1
            elif self.code[i] == "}":
                depth -= 1
                if not depth:
                    break
        return self.code[start:i + 1]

    def test_no_html_injection_no_post_no_socket_one_url(self):
        self.assertNotRegex(self.code, r"innerHTML")
        for banned in ("insertAdjacentHTML", "outerHTML", "new WebSocket",
                       "POST", "XMLHttpRequest", "{%", "{{"):
            self.assertNotIn(banned, self.code, banned)
        self.assertIn("textContent", self.code)
        self.assertIn("createElementNS", self.code)
        self.assertEqual(self.code.count("fetch("), 1)
        self.assertIn("fetch(BAND_URL", self.code)
        self.assertIn("root.getAttribute('data-band-url')", self.code)
        self.assertIn("method: 'GET'", self.code)

    def test_one_interval_started_only_on_open_and_the_tick_guard(self):
        self.assertEqual(self.code.count("setInterval("), 1)
        self.assertIn("setInterval(", self._fn("startPoll"))
        tick = self._fn("tick")
        self.assertIn("if (!state.open || document.hidden || !desk()) return;",
                      tick.split("\n")[1])
        set_open = self._fn("setOpen")
        self.assertRegex(set_open, r"if \(open\) \{[^}]*startPoll\(\)")
        self.assertEqual(len(re.findall(r"(?<!function )startPoll\(\)", self.code)), 1)
        self.assertIn("clearInterval(", self._fn("stopPoll"))
        self.assertIn(".abort()", self._fn("stopPoll"))
        self.assertIn("'(min-width: 769px)'", self.code)
        self.assertIn("return !mq || mq.matches;", self._fn("desk"))
        for const in ("TICK_MS = 30000", "READ_EVERY = 2", "EVENT_DELAY_MS = 800",
                      "READ_MIN_GAP_MS = 10000", "CHAMBER_MIN_W = 760",
                      "OPEN_KEY = 'sauron_council_band_open'",
                      "FOLD_KEY = 'sauron_council_band_fold'",
                      "SIDE_KEY = 'sauron_council_band_side'"):
            self.assertIn(const, self.code, const)
        self.assertIn("READ_MIN_GAP_MS", self._fn("read"))
        self.assertIn("opts.ev", self._fn("read"))

    def test_storage_is_fenced_and_the_open_key_is_desk_only(self):
        lines = [ln for ln in self.code.splitlines() if "localStorage" in ln]
        self.assertTrue(lines)
        for ln in lines:
            self.assertIn("try {", ln, ln)
        for ln in self.code.splitlines():
            if "OPEN_KEY" in ln and "var OPEN_KEY" not in ln:
                self.assertIn("desk()", ln, ln)

    def test_the_failure_words_and_the_unlock(self):
        for word in ("r.status === 423", "r.redirected", "/json/i.test(type)",
                     "r.status === 403", "'sv:pin-unlocked'", "visibilitychange",
                     "W('locked')", "W('signed_out')", "W('staff_only')",
                     "W('cannot_reach'"):
            self.assertIn(word, self.code, word)
        src = PARTIAL.read_text(encoding="utf-8")
        for words in ("Locked. The council carries on once the PIN is entered.",
                      "Signed out. Sign in again to see the council.",
                      "Staff only. This account cannot see the council.",
                      "Cannot reach Sauron. Retrying; the figures below are from {t}."):
            self.assertIn(words, src, words)

    def test_escape_answers_only_from_inside(self):
        at = self.code.index("'Escape'")
        handler = self.code[self.code.rindex("addEventListener('keydown'", 0, at):at + 600]
        self.assertIn("defaultPrevented", handler)
        self.assertIn("root.contains(", handler)

    def test_one_dock_at_a_time_both_ways(self):
        self.assertIn("'sv:dock-open'", self.code)
        self.assertIn("detail: 'council'", self.code)
        self.assertIn("e.detail === 'activity'", self.code)
        act = _strip_js(_read("static", "js", "sv-activity.js"))
        self.assertIn("'sv:dock-open'", act)
        self.assertIn("detail: 'activity'", act)
        self.assertIn("e.detail === 'council'", act)
        self.assertIn("if (remembered() && onDesk())", act)
        self.assertIn("|| !onDesk()", act[act.index("function fetchFeed"):
                                            act.index("function fetchFeed") + 200])
        self.assertIn("'(min-width: 769px)'", act)

    def test_the_badge_counts_only_council_sitting_and_one_global(self):
        self.assertIn("kind === 'council_sitting'", self.code)
        for kind in ("gate_reject", "notification", "sauron_answer"):
            self.assertNotIn(kind, self.code, kind)
        globals_ = re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", self.code)
        self.assertEqual(globals_, ["SVCouncilBand"])
        self.assertIn("window.SVCouncilBand = { toggle: toggle, widen: widen };",
                      self.code)

    def test_the_chamber_needs_room_and_a_shut_horde(self):
        self.assertIn("CHAMBER_MIN_W = 760", self.code)
        self.assertIn("'.sv-horde.open'", self.code)
        self.assertIn("W('narrowed_horde')", self.code)
        self.assertIn("W('narrowed_room')", self.code)
        src = PARTIAL.read_text(encoding="utf-8")
        self.assertIn("Council narrowed: the Horde is open.", src)
        self.assertIn("Council narrowed: not enough room.", src)
        self.assertIn("Close the Horde to widen the council.", src)
        self.assertIn("attributeFilter: ['class']", self.code)

    def test_the_tab_is_placed_by_measure(self):
        place = self._fn("placeTab")
        for word in ("railToggleBtn", "svActivityTab", "svHordeHead",
                     "seEyeFab", "'--cb-tab-top'"):
            self.assertIn(word, place, word)
        self.assertNotIn("setTimeout", place)
        self.assertIn("addEventListener('resize'", self.code)
        self.assertIn("'sv:chrome-moved'", self.code)
        self.assertIn("by === 'council'", self.code)
        self.assertIn("attributeFilter: ['style']", self.code)
        self.assertIn("requestAnimationFrame", self.code)

    def test_it_parses(self):
        from tests.test_inline_js_parses import NODE, _parse_all
        if NODE is None:
            self.skipTest("node is not installed on this machine")
        self.assertEqual(_parse_all([{"label": JS.name, "source": self.js}]), [])


# ══ D. the view ═════════════════════════════════════════════════════════

@override_settings(CACHES=LOCMEM)
class TheDoorTests(_Case):

    def test_the_door_is_staffs(self):
        from django.urls import reverse
        self.assertEqual(reverse("council_band"), URL)
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 302)
        self.client.force_login(_user("cb_door_member"))
        r = self.client.get(URL)
        self.assertEqual((r.status_code, r.json()), (403, {"staff_only": True}))
        self.client.force_login(_user("cb_door_staff", staff=True))
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertIn("no-cache", r.get("Cache-Control", ""))
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(set(body["panels"]),
                         {"head", "direction", "throne", "nine", "traders"})
        self.assertEqual(self.client.post(URL).status_code, 405)

    def test_a_locked_session_gets_423(self):
        self.client.force_login(_user("cb_lock", staff=True))
        session = self.client.session
        session["pin_locked"] = True
        session.save()
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 423)

    def test_bad_requests_are_400(self):
        self.client.force_login(_user("cb_bad", staff=True))
        for q in ({"part": "mind"}, {"part": "claims"}, {"voice": "king"},
                  {"sitting": "d5"}, {"sitting": "c"},
                  {"sitting": "c1234567890123"}, {"ev": "foo"},
                  {"ev": "fill_open", "voice": "skeptic"},
                  {"sitting": "c5", "voice": "skeptic"},
                  {"part": "sittings", "before": "x"},
                  {"part": "room", "before": "5"}):
            r = self.client.get(URL, q)
            self.assertEqual(r.status_code, 400, q)
            self.assertEqual(r.json(), {"ok": False, "error": "bad_request",
                                        "t": "Unknown part, voice or sitting."})

    def test_a_rehearsal_or_missing_sitting_is_404(self):
        self.client.force_login(_user("cb_404", staff=True))
        demo = _session(venue="demo")
        for sid in (demo.id, demo.id + 999):
            r = self.client.get(URL, {"sitting": f"c{sid}"})
            self.assertEqual(r.status_code, 404, sid)
            self.assertEqual(r.json(), {"ok": False, "error": "not_found",
                                        "t": "This sitting is not on record."})
        live = _session()
        r = self.client.get(URL, {"sitting": f"c{live.id}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sitting"]["id"], f"c{live.id}")

    def test_a_failing_panel_says_its_sentence_and_hides_its_exception(self):
        from dashboard import council_band as B
        self.client.force_login(_user("cb_fail", staff=True))
        _report()
        with mock.patch("ai_agents.council_grading.record_matrix",
                        side_effect=RuntimeError("boom_rm")):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        text = _text(body)
        self.assertNotIn("boom_rm", text)
        self.assertNotIn("RuntimeError", text)
        self.assertEqual(set(body["panels"]),
                         {"head", "direction", "throne", "nine", "traders"})
        for name in ("head", "direction", "throne", "nine", "traders"):
            self.assertNotIn("error", body["panels"][name], name)
        self.assertIn(B.SENTENCE["record"], text)
        self.assertIn("The seats could not be read.", text)

    def test_a_failed_build_is_503_without_its_text(self):
        self.client.force_login(_user("cb_503", staff=True))
        with mock.patch("dashboard.council_band.build_room",
                        side_effect=ValueError("secret_503")):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"ok": False, "error": "unavailable",
                                    "t": "The council could not be read. "
                                         "Nothing was changed."})

    def test_a_warm_room_costs_nothing_and_an_event_rebuilds_only_its_panels(self):
        from ai_agents import council_grading, council_mood
        from dashboard import council_band as B
        user = _user("cb_warm", staff=True)
        _report()
        s = _session()
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6})
        rm = mock.Mock(wraps=council_grading.record_matrix)
        pm = mock.Mock(wraps=council_mood.people_mood)
        with mock.patch("ai_agents.council_grading.record_matrix", rm), \
                mock.patch("ai_agents.council_mood.people_mood", pm):
            B.build_room(user)
            with self.assertNumQueries(0):
                B.build_room(user)
            self.assertEqual((rm.call_count, pm.call_count), (1, 1))
            with mock.patch.object(B, "EV_MIN_AGE_S", 0), \
                    CaptureQueriesContext(connection) as q:
                B.build_room(user, ev="fill_open")
            self.assertEqual((rm.call_count, pm.call_count), (1, 1))
        sql = " ".join(x["sql"] for x in q.captured_queries)
        self.assertIn("ai_agents_councilsession", sql)
        self.assertEqual(B.WAKE["fill_open"], {"sittings", "war"})
        self.assertIn("mood", B.WAKE["fill_close"])
        self.assertIn("record", B.WAKE["council_sitting"])
        self.assertEqual(B.EV_MIN_AGE_S, 5)

    def test_a_cold_room_stays_inside_its_budget(self):
        from dashboard import council_band as B
        user = _user("cb_cold", staff=True)
        _report()
        _switch("council_bots")
        for i in range(6):
            s = _session(symbol=f"SYM{i}", hand={"voice": "champion",
                                                 "name": "The Champion",
                                                 "side": "for"},
                         mood="uneasy", weights={"emperor": {"factor": 1.0}})
            for v in ("executioner", "champion", "skeptic", "emperor"):
                _speak(s, v, {"executioner": {"verdict": "pass", "conviction": 0.3},
                              "champion": {"verdict": "back", "conviction": 0.7},
                              "skeptic": {"verdict": "sound", "conviction": 0.5},
                              "emperor": {"verdict": "fight", "p_work": 0.6}}[v])
        with CaptureQueriesContext(connection) as q:
            room = B.build_room(user)
        self.assertLessEqual(len(q), 70, len(q))
        for name in ("head", "direction", "throne", "nine", "traders"):
            self.assertNotIn("error", room[name], name)


# ══ E. the truth contract ═══════════════════════════════════════════════

@override_settings(CACHES=LOCMEM)
class TheTruthTests(_Case):

    def _money_fixtures(self, user):
        from ai_agents.models import AgentTask
        _report()
        s = _session(user=user,
                     brief="THE TRADE\n  risk at the stop 1,234.56",
                     extras="THE WAR\n  daily stop: realized 777.77 USD",
                     why="AI budget: daily AI budget spent ($15.00 of $15.00)",
                     status="partial",
                     hand={"voice": "champion", "name": "The Champion",
                           "side": "for"})
        _speak(s, "champion", {"verdict": "back", "conviction": 0.8,
                               "edge": "the edge is the trend"})
        _speak(s, "skeptic", status="silent",
               why="AI budget: daily AI budget spent ($15.00 of $15.00)")
        _speak(s, "emperor", {"verdict": "refuse", "p_work": 0.3,
                              "war_cost": "costs $2,000 if lost",
                              "battle": "one battle of many",
                              "hand": "champion", "hand_side": "for",
                              "hand_overruled": True,
                              "hand_why": "risking 500 USD is too much",
                              "overruled": [{"voice": "champion",
                                             "why": "equity 84.8 is thin"}]})
        AgentTask.objects.create(agent="council_gambler", provider="x",
                                 model="test-model", cost_usd="3.2173")
        AgentTask.objects.create(agent="council_skeptic", provider="x",
                                 model="test-model", cost_usd="0.7319")
        return s

    def test_no_money_reaches_the_band(self):
        from dashboard.council_band import CURRENCY
        user = _user("cb_money", staff=True)
        self._money_fixtures(user)
        out = _everything(user)
        text = _text(out)
        for leak in ("1,234.56", "777.77", "$2,000", "500 USD", "$15.00",
                     "3.2173", "0.7319", "3.22", "0.73", "84.8"):
            self.assertNotIn(leak, text, leak)
        keys = set(_keys(out))
        for key in ("cost_usd", "spent_usd", "cost_30d"):
            self.assertNotIn(key, keys, key)
        for s in _strings(out):
            self.assertIsNone(CURRENCY.search(s), s)
        self.assertIn(WITHHELD, text)

    def test_the_scrub_keeps_r_and_percent(self):
        from dashboard.council_band import scrub
        from tests.test_alarm_bot import MONEY_SHAPES
        for kept in ("a loss of 1R", "-12.35% realized", "stop 1.0790",
                     "drawdown 4%", "a loss of -1.2R over 3 closes",
                     "the trade risks 0.8% of the book"):
            self.assertEqual(scrub(kept), kept, kept)
        # "1,234.50" is the debate brief's own amount shape (final review)
        passing = {"1.13716", "EURUSD at 1.13716", "stop 1.0790", "336.1",
                   "84.8", "-3.2%", "+0.4 %", "60%", "price 336",
                   "prices at 1.2"}
        for shape in MONEY_SHAPES:
            want = shape if shape in passing else WITHHELD
            self.assertEqual(scrub(shape), want, shape)
        self.assertEqual(len(scrub("x" * 900, 300)), 300)

    def test_no_exception_text_reaches_the_band(self):
        from dashboard.council_band import no_exc
        user = _user("cb_exc", staff=True)
        _report()
        s = _session(user=user, why="the sitting failed (OperationalError)",
                     status="silent",
                     hand={"voice": "", "why_empty":
                           "the seat could not be read (KeyError)",
                           "trusted": "", "trusted_why": "unread"})
        _speak(s, "fixer", status="silent", why="KeyError")
        _speak(s, "executioner", status="silent", wave=0,
               why="debate unavailable (ValueError: secret_x)")
        _speak(s, "champion", {"verdict": "back", "conviction": 0.8,
                               "edge": "fine (LookupError)"}, wave=0,
               status="copied")
        inputs = {"r_short": {"label": "R, last 5 trading days",
                              "measured": False, "reading": None,
                              "band": None,
                              "words": "unmeasured (not read (TypeError))"}}
        posture = {"level": "unmeasured", "raw_level": "", "score": None,
                   "fresh": False, "why": "posture unreadable: LookupError",
                   "what_it_does": "", "crisis_mode_on": False,
                   "sizes_real_orders": False, "title_word": "unmeasured",
                   "note": "posture unreadable: LookupError"}
        with mock.patch("ai_agents.council_mood.people_mood",
                        return_value=_mood("unmeasured", inputs, 0)), \
                mock.patch("brain.strategist.measured_posture",
                           return_value=posture):
            text = _text(_everything(user))
        for name in ("KeyError", "ValueError", "secret_x", "OperationalError",
                     "TypeError", "LookupError", "Exception"):
            self.assertNotIn(name, text, name)
        self.assertIn("The sitting failed.", text)
        self.assertIn("the call failed", text)
        self.assertIn("the debate did not hear it", text)
        self.assertIn("The seat could not be read at this sitting.", text)
        for kept in ("(paper)", "(3)", "(override)"):
            self.assertEqual(no_exc(f"a reading {kept} here"),
                             f"a reading {kept} here")
        self.assertEqual(no_exc("debate unavailable (ValueError: secret_x)"),
                         "debate unavailable")
        self.assertEqual(no_exc("posture unreadable: KeyError"),
                         "posture unreadable")

    def test_what_is_never_serialized_stays_home(self):
        from ai_agents.council_models import CouncilClaim
        user = _user("cb_home", staff=True)
        _report()
        s = _session(user=user, brief="MARKER_BRIEF", extras="MARKER_EXTRAS",
                     facts={"note": "MARKER_FACTS"},
                     weights={"emperor": {"factor": 1.0, "lane": "neutral",
                                          "n": 0, "reason": "neutral"},
                              "champion": {"factor": 1.0, "lane": "neutral",
                                           "n": 0, "reason": "neutral",
                                           "zz": "MARKER_WEIGHT"}},
                     grade_notes="MARKER_NOTES unmatched",
                     graded_at=timezone.now(), rule_name="MARKER_RULE")
        _speak(s, "theorist", {"verdict": "none", "p_work": 0.5,
                               "how": "no theory covers it",
                               "zz_secret": "MARKER_ANSWER",
                               "new_theory": {"claim_text": "MARKER_THEORY"}})
        row = _speak(s, "skeptic", {"verdict": "shaky", "conviction": 0.6,
                                    "target": "theorist", "claim": "it holds",
                                    "flaw": "noise"})
        CouncilClaim.objects.filter(voice=row).update(
            payload={"target": "theorist", "claim": "MARKER_CLAIM"},
            grade_notes="MARKER_CLAIM_NOTES")
        text = _text(_everything(user))
        for marker in ("MARKER_BRIEF", "MARKER_EXTRAS", "MARKER_FACTS",
                       "MARKER_WEIGHT", "MARKER_NOTES", "MARKER_ANSWER",
                       "MARKER_THEORY", "MARKER_CLAIM", "MARKER_RULE"):
            self.assertNotIn(marker, text, marker)

    def test_only_live_sittings_count_and_rehearsals_are_said(self):
        from ai_agents.council_grading import REHEARSAL_NOTES
        from dashboard import council_band as B
        user = _user("cb_live", staff=True)
        _report()
        old = timezone.now() - timedelta(hours=3)
        _session(venue="demo", symbol="DEMOSYM", created_at=old)
        _session(symbol="REHEARSED", grade_notes=REHEARSAL_NOTES,
                 graded_at=timezone.now(),
                 why="the order filled in a rehearsal world", created_at=old)
        first = _session(symbol="AGAIN", created_at=old - timedelta(hours=1))
        _session(symbol="AGAIN", grade_notes=f"a repeat of session #{first.id}",
                 graded_at=timezone.now(), created_at=old)
        _session(symbol="UNSENT", created_at=old)
        out = _everything(user)
        text = _text(out)
        self.assertNotIn("DEMOSYM", text)
        self.assertIn("Filled in a rehearsal world: not real money.", text)
        self.assertIn(f"Argued again: a repeat of sitting #{first.id}.", text)
        battles = " ".join(out["room"]["throne"]["battles"]["lines"])
        self.assertIn("Argued, no order sent: 2.", battles)
        self.assertIn("1 filled in a rehearsal world", battles)
        self.assertIn("1 repeat", battles)
        cards = {c["symbol"]: c for c in out["sittings"]["cards"]}
        self.assertEqual(cards["UNSENT"]["outcome"], B.OUTCOME_NOT_SENT)

    def test_each_side_is_the_councils(self):
        from ai_agents.agents import council as C
        from ai_agents.council_models import CouncilSession
        from dashboard import council_band as B
        user = _user("cb_sides", staff=True)
        a = _session(entry=1.10, stop=1.09, target=1.13)
        _speak(a, "executioner", {"verdict": "pass", "conviction": 0.3})
        _speak(a, "champion", {"verdict": "back", "conviction": 0.8})
        _speak(a, "opportunist", {"verdict": "pass", "p_work": 0.4})
        _speak(a, "striker", {"verdict": "wait", "p_work": 0.62,
                              "trigger": {"level": 1.105, "within_hours": 6}})
        _speak(a, "fixer", {"verdict": "fix", "p_work": 0.40,
                            "fix": {"kind": "stop", "value": 1.095}})
        _speak(a, "gambler", {"verdict": "all_in", "p_work": 0.70})
        _speak(a, "skeptic", {"verdict": "shaky", "conviction": 0.7,
                              "target": "champion", "claim": "x",
                              "flaw": "noise"})
        _speak(a, "awakened", {"verdict": "clean", "p_work": 0.3,
                               "footprints": ["F1"]}, status="late")
        _speak(a, "theorist", status="silent", why="timeout")
        _speak(a, "emperor", {"verdict": "fight_smaller", "commit": 0.5,
                              "p_work": 0.55})
        b = _session(status="sitting")
        _speak(b, "executioner", {"verdict": "cut", "conviction": 0.7,
                                  "size_scale": 0.5})
        _speak(b, "champion", {"verdict": "neutral", "conviction": 0.5})
        _speak(b, "skeptic", {"verdict": "sound", "conviction": 0.5})
        _speak(b, "striker", status="asked")
        sa = B.build_sitting(user, a.id)["sides"]
        self.assertEqual(sa, {"executioner": "for", "champion": "for",
                              "opportunist": "against", "striker": "for",
                              "fixer": "against", "gambler": "for",
                              "skeptic": "against", "awakened": "for",
                              "theorist": "silent", "emperor": "against"})
        sb = B.build_sitting(user, b.id)["sides"]
        self.assertEqual((sb["executioner"], sb["champion"], sb["skeptic"],
                          sb["striker"], sb["gambler"]),
                         ("against", "none", "none", "waiting", "absent"))
        for s, sides in ((a, sa), (b, sb)):
            obj = CouncilSession.objects.get(id=s.id)
            for row in obj.voices.filter(status__in=("spoke", "copied")):
                if row.voice == "emperor":
                    continue
                want = C.claim_side(obj, row.voice) or "none"
                self.assertEqual(sides[row.voice], want, row.voice)

    def test_dissent_reads_the_overruled_list_then_the_hand_then_the_sides(self):
        from dashboard import council_band as B
        rows = lambda *xs: [{"voice": v, "status": st, "verdict": vd,  # noqa: E731
                             "answer": an} for v, st, vd, an in xs]
        sides = {"executioner": "against", "champion": "for",
                 "skeptic": "none", "emperor": "against"}
        named = B.dissent_of(rows(
            ("emperor", "spoke", "refuse",
             {"verdict": "refuse", "overruled": [{"voice": "skeptic"}],
              "hand": "champion", "hand_side": "for",
              "hand_overruled": True})), sides)
        self.assertEqual(named["dissent"], ["skeptic", "champion"])
        self.assertEqual(named["chair"], "against")
        by_side = B.dissent_of(rows(("emperor", "spoke", "refuse",
                                     {"verdict": "refuse"})), sides)
        self.assertEqual((by_side["dissent"], by_side["split"]), (["champion"], False))
        split = B.dissent_of([], {"executioner": "against", "champion": "for"})
        self.assertEqual((split["chair"], split["dissent"], split["split"]),
                         ("", [], True))
        same = B.dissent_of([], {"executioner": "for", "champion": "for"})
        self.assertFalse(same["split"])
        late = B.dissent_of(rows(("emperor", "late", "fight",
                                  {"verdict": "fight"})), sides)
        self.assertEqual(late["chair"], "")

    def test_the_band_never_spells_the_weight_reader(self):
        for path in (BAND_PY, VIEW_PY, JS, PARTIAL, SHEET):
            self.assertNotIn("voice_weight", path.read_text(encoding="utf-8"),
                             path.name)
        # Not routed around the pin either: no reader fetched by name from
        # the council's modules, no name built from pieces.
        src = BAND_PY.read_text(encoding="utf-8")
        self.assertNotRegex(src, r"getattr\(\s*(C|G|council|council_grading)\s*,")
        self.assertNotRegex(src, r"[\"']voice_[\"']\s*\+")

    def test_the_weight_shown_is_the_one_the_emperor_read(self):
        from dashboard import council_band as B
        user = _user("cb_weight", staff=True)
        _report()
        reason = ("measured in trending on forex, 34 graded calls, Brier 0.18 "
                  "against 0.24 for always saying the base rate")
        s = _session(weights={"emperor": {"factor": 1.0, "lane": "neutral",
                                          "n": 0, "reason": "neutral"},
                              "champion": {"factor": 1.18,
                                           "lane": "measured", "n": 34,
                                           "brier": 0.18, "rung": "regime_class",
                                           "reason": reason}})
        _speak(s, "champion", {"verdict": "back", "conviction": 0.8},
               weight_seen=1.18, weight_reason=reason)
        # the weights the chair READ: he sat (final review: a silent chair
        # read none)
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6})
        room = B.build_room(user)
        champ = [v for t in room["nine"]["triads"] for v in t["voices"]
                 if v["key"] == "champion"][0]
        self.assertEqual(champ["weight"]["factor"], 1.18)
        # short on the row; the sitting it was read at, once, above them
        self.assertEqual(champ["weight"]["t"],
                         "×1.18 measured · 34 graded · Brier 0.18 vs 0.24")
        self.assertRegex(room["nine"]["weights_note"],
                         r"^Weights as the Emperor read them at the \d\d:\d\d "
                         r"UTC sitting \(trending on forex\)\. ")
        # the whole reason stays in the dossier
        self.assertIn(reason, _text(B.build_voice(user, "champion")["weights"]))
        sit = B.build_sitting(user, s.id)
        block = [b for b in sit["others"] if b["voice"] == "champion"][0]
        self.assertEqual(block["weight"],
                         "Weight ×1.18 (measured · 34 graded · Brier 0.18 vs 0.24)")
        bare = _session(symbol="BARE")
        _speak(bare, "champion", {"verdict": "back", "conviction": 0.8})
        self.assertIn("Weight: none read at this sitting",
                      _text(B.build_sitting(user, bare.id)))

    def test_who_has_been_right_reads_the_record(self):
        from dashboard import council_band as B
        from bot_program.persona_mix import REGIMES
        user = _user("cb_right", staff=True)
        _report("trending")

        def matrix(cells):
            out = []
            for v, rows in cells.items():
                out.append({"voice": v, "name": v.title(), "cells": [
                    {"regime": rg, **rows.get(rg, {"factor": 1.0, "n": 0,
                                                    "lane": "neutral"})}
                    for rg in REGIMES]})
            return out

        thin = matrix({"executioner": {"trending": {"factor": 1.0, "n": 7, "lane": "neutral"}},
                       "champion": {"trending": {"factor": 1.0, "n": 9, "lane": "neutral"}},
                       "gambler": {"trending": {"factor": 1.0, "n": 2, "lane": "neutral"}},
                       "fixer": {"trending": {"factor": 1.0, "n": 1, "lane": "neutral"}}})
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(matrix=thin)):
            t = B.build_room(user)["direction"]["right"]["t"]
        self.assertEqual(t, "No one yet: no voice has 10 graded calls in "
                            "trending (the Champion 9, the Executioner 7, the "
                            "Gambler 2; live, 180 days).")
        cache.clear()
        best = matrix({"executioner": {"trending": {"factor": 1.15, "n": 40, "lane": "measured"}},
                       "champion": {"trending": {"factor": 1.15, "n": 12, "lane": "measured"}},
                       "gambler": {"trending": {"factor": 0.9, "n": 50, "lane": "measured"}}})
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(matrix=best)):
            right = B.build_room(user)["direction"]["right"]
        self.assertEqual(right["t"], "The Executioner: weight ×1.15 in trending, "
                                     "40 graded calls (live, 180 days, every "
                                     "class).")
        self.assertEqual(right["voice"], "executioner")
        cache.clear()
        from brain.models import BrainReport
        BrainReport.objects.all().delete()
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(matrix=best)):
            t = B.build_room(user)["direction"]["right"]["t"]
        self.assertEqual(t, "No one in an unknown regime: the Mind has "
                            "recorded none.")

    def test_the_regime_is_the_newest_good_report(self):
        from dashboard import council_band as B
        user = _user("cb_regime", staff=True)
        _report("trending", 0.71, minutes=50)
        _report("risk_off", 0.9, minutes=5, error="the model timed out")
        t = B.build_room(user)["direction"]["thinks"]["t"]
        self.assertTrue(t.startswith("Trending (confidence 0.71) · "), t)
        self.assertIn("Mind read 50 min ago", t)
        self.assertNotIn("overdue", t)
        cache.clear()
        from brain.models import BrainReport
        BrainReport.objects.all().delete()
        _report("trending", 0.71, minutes=90)
        t = B.build_room(user)["direction"]["thinks"]["t"]
        self.assertIn("(overdue)", t)

    def test_the_model_shown_is_the_one_that_answered(self):
        from dashboard import council_band as B
        user = _user("cb_model", staff=True)
        s = _session()
        _speak(s, "gambler", {"verdict": "press", "p_work": 0.6},
               model="test-model-answered")
        sit = B.build_sitting(user, s.id)
        # one model for every answer: said once, in the head (round 2)
        self.assertEqual(sit["model"],
                         "Every answer came from test-model-answered.")
        self.assertEqual([b["model"] for b in sit["others"]], [""])
        _speak(s, "striker", {"verdict": "take", "p_work": 0.6},
               model="test-model-other")
        sit = B.build_sitting(user, s.id)
        self.assertEqual(sit["model"], "")
        self.assertEqual(sorted(b["model"] for b in sit["others"]),
                         ["answered by test-model-answered",
                          "answered by test-model-other"])

    def test_the_traders_never_call_the_n_plus_one_reader(self):
        from dashboard import council_band as B
        user = _user("cb_traders", staff=True)
        _report()
        with mock.patch("bot_program.evidence.persona_rows",
                        side_effect=AssertionError("N+1")):
            traders = B.build_room(user)["traders"]
        self.assertNotIn("error", traders)
        self.assertEqual([c["key"] for c in traders["cards"]],
                         ["scalp", "swing", "position"])
        self.assertIn("The mix moves shares only, never the risk per trade.",
                      _text(traders))
        cache.clear()
        with mock.patch("dashboard.views_personas._mix_matrix",
                        return_value=([], {}, "The regime mix could not be "
                                              "read (boom_mix).")):
            traders = B.build_room(user)["traders"]
        self.assertNotIn("boom_mix", _text(traders))
        self.assertIn("The regime mix could not be read. The presets are "
                      "unaffected.", _text(traders))

    def test_the_ai_line_is_percent_of_the_core_line(self):
        from ai_agents.models import AgentTask
        from dashboard import council_band as B
        user = _user("cb_ai", staff=True)
        AgentTask.objects.create(agent="council_emperor", provider="x",
                                 model="test-model", cost_usd="2.0")
        AgentTask.objects.create(agent="brain_synth", provider="x",
                                 model="test-model", cost_usd="6.0")
        with mock.patch("ai_agents.spend.daily_budget",
                        return_value=10.0) as budget:
            ai = B.build_room(user)["throne"]["ai"]
        budget.assert_called_with("core")
        self.assertEqual((ai["used_pct"], ai["council_pct"]), (80, 25))
        self.assertTrue(ai["deep_refused"])
        self.assertEqual(ai["t"], "AI today (core line): 80% of the day's "
                                  "allowance · the council's share of that "
                                  "spend: 25% · deep calls refused, so the bot "
                                  "lane's council is silent")
        cache.clear()
        with mock.patch("ai_agents.spend.daily_budget", return_value=0.0):
            ai = B.build_room(user)["throne"]["ai"]
        self.assertEqual(ai["t"], "AI today: no daily budget is set.")


# ══ F. Council 2: the Hand and the mood ═════════════════════════════════

@override_settings(CACHES=LOCMEM)
class TheCouncilTwoTests(_Case):

    def setUp(self):
        super().setUp()
        self.user = _user("cb_two", staff=True)

    def _room(self, rm=None, mood=None):
        from dashboard import council_band as B
        cache.clear()
        patches = []
        if rm is not None:
            patches.append(mock.patch("ai_agents.council_grading.record_matrix",
                                      return_value=rm))
        if mood is not None:
            patches.append(mock.patch("ai_agents.council_mood.people_mood",
                                      return_value=mood))
        for p in patches:
            p.start()
        try:
            return B.build_room(self.user)
        finally:
            for p in patches:
                p.stop()

    def test_the_triad_is_the_move_and_the_hand_is_the_emperors(self):
        from dashboard import council_band as B
        self.assertEqual([t["title"] for t in B.TRIADS],
                         ["THE TRIAL", "THE SIGHT", "THE MOVE"])
        self.assertEqual([t["voices"] for t in B.TRIADS],
                         [("executioner", "champion", "skeptic"),
                          ("awakened", "theorist", "opportunist"),
                          ("striker", "fixer", "gambler")])
        self.assertEqual(B.TRIADS[2]["sub"], "what to do now")
        for t in B.TRIADS:
            self.assertNotIn("HAND", t["title"])
        self.assertEqual(B.ROLE, {
            "executioner": "Why the trade fails.",
            "champion": "Why it works.",
            "skeptic": "Attacks the evidence of the other voices, never the trade.",
            "awakened": "The trap, the hunter and the prey, from cited footprints only.",
            "theorist": "Falsifiable theories, graded in the hypothesis market.",
            "opportunist": "What the crowd misses, or a better trade elsewhere.",
            "striker": "One decision now: take it, wait for a touch, or skip it.",
            "fixer": "The one flaw that matters, and its repair.",
            "gambler": "How hard to press, never past the limits.",
            "emperor": "The chair: the war over the battle. He weighs every "
                       "voice by its record."})
        text = _text(self._room()) + "".join(B.WORDS.values())
        self.assertIn("THE MOVE", text)
        self.assertIn("THE EMPEROR'S HAND", text)
        for m in re.finditer(r"HAND", text):
            ctx = text[max(0, m.start() - 16):m.end() + 8]
            self.assertTrue("EMPEROR'S HAND" in ctx or "THE HAND ·" in ctx
                            or "AGAINST HIS HAND" in ctx
                            or "HAND, CELL" in ctx, ctx)
        # nor the lowercase word for the ticket lane: the record's hand_n
        # counts tickets (round 1: "bot 23 / hand 3" in every dossier)
        from ai_agents.agents import council as C
        for v in C.ALL_VOICES:
            dossier = _text(B.build_voice(self.user, v))
            self.assertIn(" / ticket ", dossier, v)
            self.assertNotIn("/ hand", dossier, v)

    def test_the_seat_per_cell_and_the_empty_seats_are_said(self):
        from ai_agents.council_grading import HAND_EMPTY
        _report("trending")
        hands = [{"regime": "trending", "asset_class": "forex",
                  "voice": "champion", "name": "The Champion", "factor": 1.18,
                  "n": 34, "brier": 0.18, "reference": 0.24, "reason": "x",
                  "why_empty": "", "cell": "trending on forex"},
                 {"regime": "trending", "asset_class": "crypto", "voice": "",
                  "name": "", "factor": None, "n": 0, "brier": None,
                  "reference": None, "reason": "", "why_empty": HAND_EMPTY,
                  "cell": "trending on crypto"},
                 {"regime": "risk_off", "asset_class": "forex", "voice": "",
                  "name": "", "factor": None, "n": 0, "brier": None,
                  "reference": None, "reason": "", "why_empty": HAND_EMPTY,
                  "cell": "risk_off on forex"}]
        now = self._room(_rm(hands=hands))["throne"]["hand"]["now"]
        self.assertEqual(now, [
            "forex: the Champion · ×1.18 · 34 graded calls in this cell (live, "
            "180 days) · Brier 0.18",
            "crypto: no voice has earned it yet (the seat needs 30 graded calls "
            "in this regime and class and a weight of at least 1.15)"])
        from brain.models import BrainReport
        BrainReport.objects.all().delete()
        _report("mean_reverting")
        now = self._room(_rm(hands=hands))["throne"]["hand"]["now"]
        self.assertEqual(now, ["No cell in mean reverting has a graded call "
                               "yet: no voice holds the Hand here."])
        BrainReport.objects.all().delete()
        now = self._room(_rm(hands=hands))["throne"]["hand"]["now"]
        self.assertEqual(now, ["No seat: the regime is unknown, so no cell is "
                               "measured."])
        room = self._room(_rm(hands=hands))
        nine = _text(room["nine"])
        self.assertNotIn("THE HAND · forex", nine)
        BrainReport.objects.all().delete()
        _report("trending")
        room = self._room(_rm(hands=hands))
        champ = [v for t in room["nine"]["triads"] for v in t["voices"]
                 if v["key"] == "champion"][0]
        self.assertEqual(champ["hand"], ["THE HAND · forex"])

    def test_an_unread_seat_is_said_unread_never_unearned(self):
        from dashboard import council_band as B
        _report("trending")
        cache.clear()
        with mock.patch("ai_agents.council_grading.record_matrix",
                        side_effect=RuntimeError("x")):
            hand = B.build_room(self.user)["throne"]["hand"]
        self.assertEqual(hand["now"], ["The seats could not be read."])
        self.assertNotIn("no voice has earned", _text(hand))

    def test_the_emperor_against_his_hand_is_counts_never_a_rate(self):
        against = {"overruled": 6, "graded": 4, "emperor_right": 3,
                   "hand_right": 1, "unresolved": 1, "pending": 1,
                   "no_reason": 2, "by_voice": {"champion": {
                       "graded": 4, "emperor_right": 3, "hand_right": 1}},
                   "agreed": {"n": 9, "right": 5}}
        lines = self._room(_rm(against_hand=against))["throne"]["hand"]["against"]
        text = " ".join(lines)
        self.assertEqual(text, "Went against it 6 times (live sittings, 180 "
                               "days). Graded 4: the Emperor "
                               "right 3, the Hand right 1; 1 inside a quarter "
                               "R; 1 not graded yet. Without a reason: 2. When "
                               "they agreed: right 5 of 9. Under 10 graded: "
                               "not measured.")
        self.assertNotIn("%", text)
        none = self._room(_rm())["throne"]["hand"]["against"]
        self.assertEqual(none, ["He has not gone against his Hand yet (live "
                                "sittings, 180 days)."])

    def test_the_last_sitting_names_the_hand_its_side_and_the_overruling(self):
        from dashboard import council_band as B
        _report("trending")
        s = _session(hand={"voice": "champion", "name": "The Champion",
                           "side": "for", "cell": "trending on forex"})
        _speak(s, "champion", {"verdict": "back", "conviction": 0.8})
        _speak(s, "emperor", {"verdict": "refuse", "p_work": 0.3,
                              "hand": "champion", "hand_side": "for",
                              "hand_overruled": True,
                              "hand_why": "the war cannot spare it"})
        last = " ".join(self._room()["throne"]["hand"]["last"])
        self.assertIn("The Champion held the Hand, for the trade.", last)
        self.assertIn('The Emperor went against it: "the war cannot spare it".', last)
        self.assertIn("against his Hand, the Champion",
                      self._room()["direction"]["disagrees"]["t"])
        s2 = _session(symbol="SECOND", hand={"voice": "champion",
                                             "name": "The Champion",
                                             "side": "for"})
        _speak(s2, "emperor", {"verdict": "refuse", "p_work": 0.3,
                               "hand": "champion", "hand_side": "for",
                               "hand_overruled": True, "hand_why": "",
                               "hand_note": "overruled the Hand without "
                                            "saying why"})
        last = " ".join(self._room()["throne"]["hand"]["last"])
        self.assertIn("The Emperor went against it without saying why.", last)
        s3 = _session(symbol="THIRD", hand={"voice": "champion",
                                            "name": "The Champion",
                                            "side": "for"})
        _speak(s3, "emperor", {"verdict": "fight", "p_work": 0.7,
                               "hand": "champion", "hand_side": "for",
                               "hand_overruled": False})
        self.assertIn("The Emperor went with it.",
                      " ".join(self._room()["throne"]["hand"]["last"]))
        _session(symbol="FOURTH", status="record")
        s5 = _session(symbol="FIFTH", hand={})
        _speak(s5, "emperor", {"verdict": "fight", "p_work": 0.7})
        self.assertIn("The Hand was not read at this sitting.",
                      " ".join(self._room()["throne"]["hand"]["last"]))
        self.assertIn("The Hand was not read at this sitting.",
                      _text(B.build_sitting(self.user, s5.id)))

    def test_the_skeptic_told_line_and_his_counts(self):
        from dashboard import council_band as B
        cases = {"hand": "Told to attack the Champion first: the Emperor's Hand.",
                 "highest": "Told to attack the Champion first: the best "
                            "measured record in this cell.",
                 "none": "No voice was named: none had earned trust in this cell.",
                 "unread": "Not told: the record could not be read."}
        for how, words in cases.items():
            s = _session(symbol=f"SK{how.upper()}",
                         hand={"voice": "", "trusted": "" if how in
                               ("none", "unread") else "champion",
                               "trusted_why": how})
            _speak(s, "skeptic", {"verdict": "sound", "conviction": 0.5})
            self.assertIn(words, _text(B.build_sitting(self.user, s.id)), how)
        first = {"named": 7, "attacked": 6, "first": 4, "right": 2, "graded": 3}
        cache.clear()
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(skeptic_first=first)):
            dossier = _text(B.build_voice(self.user, "skeptic"))
        self.assertIn("Told 7 times (live sittings, 180 days); his attack "
                      "named the voice he was told 4 of 6 times; right 2 of 3 "
                      "graded. Under 10 graded: not measured.", dossier)

    def test_the_mood_is_caution_only(self):
        from ai_agents import council_mood as M
        for level in M.MOOD_LEVELS:
            mood = self._room(mood=_mood(level))["throne"]["mood"]
            self.assertEqual(mood["level"], level)
            self.assertEqual(mood["level_words"], M.LEVEL_WORDS[level])
            self.assertEqual(mood["caution"], M.CAUTION_ONLY)
            self.assertEqual(len(mood["inputs"]), len(M.INPUTS))
            self.assertIn("Now, the real-money book (yours, world live: no "
                          "demo, no SIM, no paper): ", mood["head"])
        nothing = self._room(mood=_mood("unmeasured", {}, 0))["throne"]["mood"]
        self.assertEqual(nothing["level"], "unmeasured")
        self.assertIn("unmeasured, 0 of 7 inputs measured", nothing["head"])
        self.assertEqual([i["words"] for i in nothing["inputs"]],
                         ["not read"] * 7)
        part = {"r_short": {"label": M.LABELS["r_short"], "measured": False,
                            "reading": None, "band": None,
                            "words": "unmeasured (every close in the window "
                                     "unpriced (2))"}}
        mood = self._room(mood=_mood("unmeasured", part, 0))["throne"]["mood"]
        self.assertIn("unmeasured (every close in the window unpriced (2))",
                      mood["inputs"][0]["words"])
        self.assertNotIn("steady", mood["head"])
        weird = self._room(mood=_mood("elated"))["throne"]["mood"]
        self.assertEqual(weird["level"], "unmeasured")
        thinks = self._room(mood=_mood("uneasy"))["direction"]["thinks"]["t"]
        self.assertIn(" · the people: uneasy", thinks)

    def test_the_mood_is_the_viewers_and_code_only(self):
        from ai_agents import council_mood
        from dashboard import council_band as B
        pm = mock.Mock(wraps=council_mood.people_mood)
        cache.clear()
        with mock.patch("ai_agents.council_mood.people_mood", pm), \
                mock.patch("ai_agents.base_agent.BaseAgent.run",
                           side_effect=AssertionError("a model call")) as run, \
                mock.patch("ai_agents.spend.can_spend",
                           side_effect=AssertionError("a bill")) as spend:
            room = B.build_room(self.user)
        pm.assert_called_once()
        self.assertEqual(pm.call_args[0][0].pk, self.user.pk)
        run.assert_not_called()
        spend.assert_not_called()
        self.assertNotIn("error", room["throne"])
        cache.clear()
        with mock.patch("ai_agents.council_mood.people_mood",
                        side_effect=RuntimeError("x")):
            mood = B.build_room(self.user)["throne"]["mood"]
        self.assertEqual(mood["level"], "unmeasured")
        self.assertIn("The people's mood could not be read: unmeasured, never "
                      "calm.", _text(mood))

    def test_the_mood_at_a_sitting_and_what_it_predicted(self):
        from dashboard import council_band as B
        s = _session(mood="")
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6})
        self.assertIn("The people's mood at the sitting: not read",
                      _text(B.build_sitting(self.user, s.id)))
        s2 = _session(symbol="MOODY", mood="restless")
        _speak(s2, "emperor", {"verdict": "fight", "p_work": 0.6})
        self.assertIn("The people's mood at the sitting: restless",
                      _text(B.build_sitting(self.user, s2.id)))
        moods = [{"level": "steady", "n": 12, "thin": False,
                  "avg_r_text": "+0.20R", "won_text": "60%",
                  "commit_text": "100%"},
                 {"level": "uneasy", "n": 3, "thin": True,
                  "avg_r_text": "-0.40R", "won_text": "33%",
                  "commit_text": "50%"},
                 {"level": "afraid", "n": 0, "thin": True,
                  "avg_r_text": "none", "won_text": "none",
                  "commit_text": "none"}]
        mood = self._room(_rm(moods=moods))["throne"]["mood"]
        self.assertEqual(mood["graded"], [
            "steady: 12 graded · average +0.20R · won 60% · the Emperor's "
            "average commitment 100%", "uneasy: 3 graded, too few to read",
            "afraid: none graded"])
        self.assertIn("If the mood predicts nothing, these rows will not "
                      "differ.", mood["graded_note"])
        self.assertIn("(live, graded, 180 days)", mood["graded_title"])


# ══ G. the event ════════════════════════════════════════════════════════

class TheEventTests(SimpleTestCase):

    def test_a_finished_sitting_tells_its_owner_once(self):
        from ai_agents import tasks
        owner = SimpleNamespace(id=7, is_authenticated=True)
        session = SimpleNamespace(id=42, origin="bot", symbol="EURUSD",
                                  side="BUY", status="done", user=owner,
                                  config_id=None, config=None)

        class _Voices:
            def filter(self, **kw):
                return self

            def values_list(self, *a, **kw):
                return self

            def first(self):
                return "fight_smaller"

        session.voices = _Voices()
        qs = mock.Mock()
        qs.select_related.return_value.filter.return_value.first.return_value = session
        with mock.patch("ai_agents.agents.council.run_sitting",
                        return_value={"status": "done", "session": 42}), \
                mock.patch("ai_agents.council_models.CouncilSession.objects", qs), \
                mock.patch("dashboard.consumers.push_eye_event") as push:
            out = tasks.run_council_sitting(42)
        self.assertEqual(out, {"status": "done", "session": 42})
        push.assert_called_once()
        user, kind, data = push.call_args[0]
        self.assertIs(user, owner)
        self.assertEqual(kind, "council_sitting")
        self.assertEqual(set(data), {"session", "origin", "symbol", "side",
                                     "status", "verdict"})
        self.assertEqual(data["verdict"], "fight_smaller")
        with mock.patch("ai_agents.agents.council.run_sitting",
                        return_value={"status": "noop", "session": 42}), \
                mock.patch("dashboard.consumers.push_eye_event") as push:
            tasks.run_council_sitting(42)
        push.assert_not_called()
        with mock.patch("ai_agents.agents.council.run_sitting",
                        return_value={"status": "done", "session": 42}), \
                mock.patch("ai_agents.council_models.CouncilSession.objects", qs), \
                mock.patch("dashboard.consumers.push_eye_event",
                           side_effect=RuntimeError("no layer")):
            self.assertEqual(tasks.run_council_sitting(42),
                             {"status": "done", "session": 42})
        src = _read("ai_agents", "tasks.py")
        body = src[src.index("def run_council_sitting"):]
        body = body[:body.index("\n@shared_task")]
        for banned in ("telegram", "alarm", "alerts.", "notify("):
            self.assertNotIn(banned, body.lower(), banned)
        self.assertIn('"council_sitting"', body)


# ══ H. the chrome ═══════════════════════════════════════════════════════

class TheChromeTests(SimpleTestCase):

    def setUp(self):
        self.base = _read("templates", "base.html")

    # the tall chart beside an open dock is driven under node, not read
    # as text: TheFinalChromeTests.test_the_tall_chart_keeps_its_insets...

    def test_the_motion_layer_leaves_it_alone(self):
        js = _read("static", "js", "sv-motion.js")
        outside = js[js.index("var OUTSIDE"):js.index(";", js.index("var OUTSIDE"))]
        self.assertIn("'#svHorde, #svCouncilBand, ", outside)

    def test_gollum_points_and_never_opens(self):
        js = _read("static", "js", "sv-gollum.js")
        self.assertIn('href: "#council", needs: "#svCouncilBandTab"', js)
        self.assertIn("if (l.needs && !d.querySelector(l.needs)) return;", js)
        start = js.index('e.href === "#council"')
        branch = js[start:js.index("return;", start)]
        self.assertIn("svCouncilBandTab", branch)
        self.assertIn("gl-pointed", branch)
        for banned in (".click(", "toggle(", "setOpen", "SVCouncilBand"):
            self.assertNotIn(banned, branch, banned)
        self.assertLess(js.index('href: "#horde"'), js.index('href: "#council"'))

    def test_c_and_shift_c_after_the_h_branch_and_staff_kbd_rows(self):
        h = self.base.index("key === 'h'")
        c = self.base.index("key === 'c' && !ctrl && !e.altKey")
        big = self.base.index("key === 'C' && e.shiftKey && !ctrl && !e.altKey")
        self.assertGreater(c, h)
        self.assertGreater(big, c)
        self.assertIn("window.SVCouncilBand.toggle('key')", self.base[c:c + 200])
        self.assertIn("window.SVCouncilBand.widen('key')", self.base[big:big + 200])
        rows = ('{% if user.is_staff %}<div class="kbd-row"><span class="kbd-label">'
                'Toggle the council</span><span class="kbd-keys"><kbd>c</kbd></span>'
                '</div><div class="kbd-row"><span class="kbd-label">Widen the '
                'council</span><span class="kbd-keys"><kbd>Shift</kbd><kbd>C</kbd>'
                '</span></div>{% endif %}')
        self.assertIn(rows, self.base)
        self.assertGreater(self.base.index(rows), self.base.index("Toggle the Horde"))

    def test_the_sidebar_row_is_staff_only_under_what_is_measured(self):
        row = ('{% if request.user.is_staff %}<a href="{% url \'council_dashboard\' %}" '
               'class="nav-link {% if page_id == \'council\' %}active{% endif %}">'
               '<span class="icon">♔</span> <span class="label-text">The Council'
               '</span></a>{% endif %}')
        self.assertIn(row, self.base)
        measured = self.base.index('<div class="nav-section">What is measured</div>')
        invented = self.base.index('<div class="nav-section">What is invented</div>')
        at = self.base.index(row)
        self.assertTrue(measured < at < invented)
        self.assertGreater(at, self.base.index("Agent Calibration"))
        count = sum(p.read_text(encoding="utf-8").count("♔")
                    for p in (BASE / "templates").rglob("*.html"))
        self.assertEqual(count, 1)

    def test_the_ask_kinds_and_the_shared_facts_label(self):
        kinds = self.base[self.base.index("var ASK_KINDS = {"):
                          self.base.index("function setContext")]
        self.assertIn("sitting: {", kinds)
        self.assertIn("voice: {", kinds)
        self.assertIn("'What do you make of the council on '", kinds)
        self.assertIn("(Facts shown on screen: '", self.base)
        self.assertNotIn("Facts shown by the Horde", self.base)


@override_settings(CACHES=LOCMEM)
class TheSidebarRenderTests(_Case):

    def test_the_row_renders_for_staff_and_not_for_a_member(self):
        self.client.force_login(_user("cb_nav_staff", staff=True))
        body = self.client.get("/getting-started/").content.decode()
        self.assertIn('href="/council/"', body)
        self.assertIn("Toggle the council", body)
        self.client.force_login(_user("cb_nav_member"))
        body = self.client.get("/getting-started/").content.decode()
        self.assertNotIn('href="/council/"', body)
        self.assertNotIn("Toggle the council", body)


@override_settings(CACHES=LOCMEM)
class TheReadsTests(_Case):
    """The sittings list, one transcript and one dossier, end to end."""

    def test_the_sittings_list_the_transcript_and_the_dossier(self):
        from ai_agents.agents import council as C
        user = _user("cb_reads", staff=True)
        _report()
        s = _session(symbol="GBPCAD", side="SELL",
                     hand={"voice": "champion", "name": "The Champion",
                           "side": "for", "trusted": "champion",
                           "trusted_why": "hand"}, mood="uneasy")
        _speak(s, "executioner", {"verdict": "veto", "conviction": 0.82,
                                  "killer": "the level is a trap",
                                  "reasons": ["one", "two"]}, wave=0,
               status="copied")
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7,
                               "edge": "the trend carries it"}, wave=0,
               status="copied")
        _speak(s, "emperor", {"verdict": "fight_smaller", "commit": 0.5,
                              "p_work": 0.55, "followed": ["champion"],
                              "overruled": [{"voice": "executioner",
                                             "why": "the trap is old"}],
                              "battle": "a small battle", "plan": "the trend",
                              "war_cost": "-0.5R if lost"})
        self.client.force_login(user)
        r = self.client.get(URL, {"part": "sittings"})
        self.assertEqual(r.status_code, 200)
        card = r.json()["sittings"]["cards"][0]
        self.assertEqual(card["id"], f"c{s.id}")
        self.assertIn("1 DISSENT", card["chips"])
        self.assertIn("Dissent: the Executioner (VETO, says it works 18%)",
                      card["dissent"])
        r = self.client.get(URL, {"sitting": f"c{s.id}"})
        sit = r.json()["sitting"]
        text = _text(sit)
        self.assertIn("FIGHT ×0.50", text)
        self.assertEqual([b["voice"] for b in sit["dissent"]], ["executioner"])
        self.assertIn("the level is a trap", text)
        self.assertIn("The people's mood at the sitting: uneasy", text)
        self.assertLessEqual(len(sit["ask"]["facts"]), 900)
        self.assertEqual(sit["ask"]["kind"], "sitting")
        for v in C.ALL_VOICES:
            r = self.client.get(URL, {"voice": v})
            self.assertEqual(r.status_code, 200, v)
            self.assertEqual(r.json()["voice"]["key"], v)
        r = self.client.get(URL, {"part": "sittings", "before": str(s.id)})
        self.assertEqual(r.json()["sittings"]["cards"], [])


# ══ I. polish, round 1: what the eyes saw ═══════════════════════════════
# (scratchpad councilband2/eyes_r1.md: each finding pinned where it lives)

def _claim_of(s, voice, kind):
    from ai_agents.council_models import CouncilClaim
    return CouncilClaim.objects.get(session=s, voice_key=voice, kind=kind)


@override_settings(CACHES=LOCMEM)
class ThePolishTruthTests(_Case):
    """A. Untrue or misleading: every sentence the eyes caught."""

    def setUp(self):
        super().setUp()
        self.user = _user("cb_polish", staff=True)

    def test_a1_the_hands_dossier_never_says_never_overruled(self):
        from dashboard import council_band as B
        pending = {"overruled": 1, "graded": 0, "emperor_right": 0,
                   "hand_right": 0, "unresolved": 0, "pending": 1,
                   "no_reason": 0, "by_voice": {},
                   "agreed": {"n": 0, "right": 0}}
        seat = [{"regime": "trending", "asset_class": "forex",
                 "voice": "champion", "factor": 1.15, "n": 34, "brier": 0.08,
                 "why_empty": ""}]
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(against_hand=pending, hands=seat)):
            hand = B.build_voice(self.user, "champion")["hand"]
        self.assertEqual(hand, ["No graded overruling of it as the Hand yet "
                                "(live sittings, 180 days)."])
        self.assertNotIn("has not been overruled", _text(hand))
        cache.clear()
        graded = dict(pending, by_voice={"champion": {
            "graded": 4, "emperor_right": 3, "hand_right": 1}})
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(against_hand=graded)):
            hand = B.build_voice(self.user, "champion")["hand"]
        self.assertEqual(hand, ["When the Emperor went against it as his Hand "
                                "(live sittings, 180 days): graded 4, it was "
                                "right 1, he was right 3."])

    def test_a2_and_29_the_hands_side_is_unread_until_wave_two(self):
        from dashboard import council_band as B
        asked = [{"voice": "emperor", "status": "asked", "answer": {}}]
        sitting = {"status": "sitting", "hand": {"voice": "champion",
                                                 "name": "The Champion"}}
        self.assertEqual(B._hand_at(sitting, asked), [
            "The Champion holds the Hand; its side is read once wave 2 has "
            "answered.", "The Emperor has not ruled yet: the council is "
                         "sitting."])
        # a side written empty while a wave-2 voice is still asked is not
        # read yet either
        early = {"status": "sitting", "hand": {"voice": "champion",
                                               "side": ""}}
        wave2 = asked + [{"voice": "skeptic", "wave": 2, "status": "asked"}]
        self.assertEqual(B._hand_at(early, wave2)[0],
                         "The Champion holds the Hand; its side is read once "
                         "wave 2 has answered.")
        ruled = [{"voice": "emperor", "status": "spoke",
                  "answer": {"verdict": "fight", "hand": "champion",
                             "hand_overruled": False}}]
        unread = {"status": "done", "hand": {"voice": "champion"}}
        self.assertEqual(B._hand_at(unread, ruled), [
            "The Champion held the Hand; its side was not read.",
            "Whether he went with it is not measured: its side was not read."])
        none = {"status": "done", "hand": {"voice": "champion", "side": ""}}
        self.assertEqual(B._hand_at(none, ruled), [
            "The Champion held the Hand, with no side taken.",
            "Its side was none: there was nothing to overrule."])
        side = {"status": "done", "hand": {"voice": "champion", "side": "for"}}
        self.assertEqual(B._hand_at(side, ruled), [
            "The Champion held the Hand, for the trade.",
            "The Emperor went with it."])
        empty = {"status": "done", "hand": {"voice": "", "why_empty": "x"}}
        self.assertEqual(B._hand_at(empty, ruled),
                         ["No voice had earned the Hand in this cell."])
        for lines in (B._hand_at(sitting, asked), B._hand_at(empty, ruled)):
            self.assertNotRegex(" ".join(lines), r"\b(held|earned) it\b")

    def test_a3_best_and_worst_calls_say_what_the_call_earned(self):
        from dashboard import council_band as B
        s = _session(symbol="EURUSD", side="BUY")
        _speak(s, "emperor", {"verdict": "fight_smaller", "commit": 0.5,
                              "p_work": 0.55})
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
        battle = _claim_of(s, "emperor", "battle")
        battle.grade, battle.r, battle.value_r = "right", -1.0, 0.5
        battle.save()
        work = _claim_of(s, "champion", "work")
        work.grade, work.r = "wrong", -1.0
        work.save()
        best = B.build_voice(self.user, "emperor")["best"]
        self.assertEqual(len(best), 1)
        self.assertIn("EURUSD BUY · FIGHT ×0.50 · right · the trade -1.00R · "
                      "his size saved +0.50R · ", best[0]["t"])
        worst = B.build_voice(self.user, "champion")["worst"]
        self.assertIn("BACK · wrong · the trade -1.00R · ", worst[0]["t"])
        self.assertNotIn("saved", worst[0]["t"])
        for v, want in ((-0.4, "the call cost 0.40R"),
                        (0.0, "the call changed nothing")):
            self.assertIn(want, B.call_worth("executioner", {
                "grade": "right", "r": 1.0, "value_r": v}))

    def test_a4_the_ticket_lane_is_never_called_the_hand(self):
        from ai_agents.agents import council as C
        from dashboard import council_band as B
        rm = _rm()
        for v in rm["voices"]:
            v.update(bot_n=23, hand_n=3)
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=rm):
            texts = {k: _text(B.build_voice(self.user, k))
                     for k in C.ALL_VOICES}
        for k, text in texts.items():
            self.assertIn("bot 23 / ticket 3", text, k)
            self.assertNotRegex(text, r"(?i)\bhand \d", k)

    def test_a5_a_voice_still_asked_is_waiting_never_silent(self):
        from dashboard import council_band as B
        _report()
        s = _session(status="sitting", symbol="WAITING")
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
        _speak(s, "striker", status="asked")
        room = B.build_room(self.user)
        row = [v for t in room["nine"]["triads"] for v in t["voices"]
               if v["key"] == "striker"][0]
        self.assertEqual(row["latest"]["side"], "waiting")
        self.assertRegex(row["latest"]["words"],
                         r"^Waiting at the last sitting \(\d\d:\d\d UTC\): not "
                         r"answered yet\.$")
        block = [b for b in B.build_sitting(self.user, s.id)["others"]
                 if b["voice"] == "striker"][0]
        self.assertEqual(block["silence"], "Waiting: not answered yet.")
        done = _session(symbol="TIMEDOUT")
        _speak(done, "striker", status="silent", why="timeout")
        block = [b for b in B.build_sitting(self.user, done.id)["others"]
                 if b["voice"] == "striker"][0]
        self.assertEqual(block["silence"], "Silent: no answer in time.")

    def test_a6_the_late_emperor_is_said_once_never_unheard_by_himself(self):
        from dashboard import council_band as B
        s = _session(symbol="LATECHAIR")
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7},
               status="late")
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6},
               status="late")
        sit = B.build_sitting(self.user, s.id)
        self.assertEqual(sit["emperor_late"], B.EMPEROR_LATE)
        blocks = {b["voice"]: b for b in sit["others"]}
        self.assertEqual(blocks["emperor"]["silence"], "")
        self.assertEqual(blocks["champion"]["silence"],
                         "Late: not heard by the chair.")

    def test_a7_the_grade_chip_tells_pending_from_by_rule(self):
        from ai_agents.council_grading import REHEARSAL_NOTES
        from dashboard import council_band as B
        now = timezone.now()
        self.assertEqual(B._grade_chip({}), "GRADE PENDING")
        self.assertEqual(B._grade_chip({"status": "sitting"}), "GRADE PENDING")
        self.assertEqual(B._grade_chip({"graded_at": now}), "NOT MEASURED")
        for notes in (REHEARSAL_NOTES, "a repeat of session #12"):
            self.assertEqual(B._grade_chip({"graded_at": now,
                                            "grade_notes": notes}),
                             "NOT GRADED (BY RULE)", notes)
        self.assertEqual(B._grade_chip({"truth": "realized", "truth_r": 0.8,
                                        "graded_at": now}), "GRADED +0.8R")
        self.assertEqual(B._grade_chip({"truth": "replay", "truth_r": -1,
                                        "graded_at": now}), "REPLAYED -1.0R")

    def test_a8_the_cards_shadow_count_says_it_is_the_entrys(self):
        from dashboard import council_band as B
        s = {"id": 7, "origin": "bot", "symbol": "EURUSD", "side": "BUY",
             "asset_class": "forex", "status": "done", "why": "",
             "trade_id": 41, "trade__status": "OPEN", "created_at": timezone.now(),
             "trade_meta": {"binding": False, "graded": 6}}
        with mock.patch.object(B, "_world", return_value="live"):
            chips = B._card(s, [], [], timezone.now())["chips"]
        self.assertIn("SHADOW AT ENTRY 6/30", chips)
        self.assertFalse([c for c in chips if c.startswith("SHADOW 6")])

    def test_a9_the_campaign_quotes_the_long_line_he_last_stated(self):
        from dashboard import council_band as B
        _report()
        self.assertEqual(B.build_room(self.user)["throne"]["campaign"]["t"],
                         B.CAMPAIGN)
        s = _session(symbol="EURUSD", side="BUY")
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6,
                              "plan": "Stay with the trend on the majors."})
        cache.clear()
        t = B.build_room(self.user)["throne"]["campaign"]["t"]
        self.assertTrue(t.startswith("No season objective is set. The last "
                                     "long line he stated (EURUSD BUY, "), t)
        self.assertTrue(t.endswith(' UTC): "Stay with the trend on the '
                                   'majors."'), t)
        self.assertNotIn("No campaign plan is recorded", t)
        money = _session(symbol="GBPCAD", side="SELL")
        _speak(money, "emperor", {"verdict": "fight", "p_work": 0.6,
                                  "plan": "risk 500 USD a day"})
        cache.clear()
        t = B.build_room(self.user)["throne"]["campaign"]["t"]
        self.assertIn("(GBPCAD SELL, ", t)
        self.assertTrue(t.endswith(WITHHELD), t)
        self.assertNotIn("500", t)

    def test_a10_every_number_says_its_book(self):
        from dashboard import council_band as B
        _report("trending")
        bench = [{"name": "The Emperor", "brier": 0.223, "n": 64},
                 {"name": "The council, weighted by record", "brier": 0.231,
                  "n": 64},
                 {"name": "The council, plain average", "brier": 0.24,
                  "n": 64}]
        rm = _rm(benchmarks=bench, chair={"over_wrong": 2, "over_n": 3,
                                          "follow_right": 4, "follow_n": 5},
                 replay={"n": 4, "agree": 3})
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=rm):
            room = B.build_room(self.user)
            record = B.build_record(self.user)
        chair = room["throne"]["chair"]["lines"]
        self.assertTrue(chair[0].startswith("Over 64 graded sittings (live, "
                                            "180 days): the Emperor Brier "
                                            "0.223 (best)"), chair[0])
        self.assertIn("Of the voices he overruled (live, 180 days), 2 of 3",
                      chair[1])
        self.assertIn("On 4 sittings with both (live sittings, all time)",
                      _text(record["bench"]))
        self.assertTrue(record["hand_bar"].startswith("Live record, 180 days."))
        cache.clear()
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm()):
            lines = B.build_room(self.user)["throne"]["chair"]["lines"]
        self.assertEqual(lines[0], "Not measured: 0 graded sittings (live, "
                                   "180 days), 10 needed.")
        traders = B.build_room(self.user)["traders"]
        for card in traders["cards"]:
            self.assertRegex(card["band_t"], r"^share of the book [\d.]+–[\d.]+%, "
                                             r"now ([\d.]+–[\d.]+%|—)$")
            self.assertNotIn("→", card["band_t"])
        self.assertEqual(B._share("17.925–52.925%"), "17.9–52.9%")
        self.assertEqual(B._share("5–25%"), "5–25%")
        self.assertEqual(B._share(""), B.DASH)

    def test_a11_a_sitting_of_another_day_says_its_date(self):
        from ai_agents.council_models import CouncilSession
        from dashboard import council_band as B
        now = timezone.now()
        old_at = now - timedelta(days=2)
        self.assertEqual(B._at(now, now), f"{now.astimezone(dt_utc()):%H:%M} UTC")
        self.assertEqual(B._at(old_at, now),
                         f"{old_at.astimezone(dt_utc()):%Y-%m-%d %H:%M} UTC")
        _report()
        old = _session(symbol="OLDSYM", created_at=old_at,
                       weights={"emperor": {"factor": 1.0, "lane": "neutral",
                                            "n": 0, "reason": "neutral"},
                                "champion": {"factor": 1.0, "lane": "neutral",
                                             "n": 0, "reason": "neutral"}})
        _speak(old, "champion", {"verdict": "back", "conviction": 0.7})
        _speak(old, "emperor", {"verdict": "fight", "p_work": 0.6})
        day = f"{old_at.astimezone(dt_utc()):%Y-%m-%d}"
        self.assertIn(f"argued {day} ", B.build_sitting(self.user, old.id)["head"])
        room = B.build_room(self.user)
        self.assertIn(f"({day} ", room["direction"]["disagrees"]["t"])
        self.assertIn(f"at the {day} ", room["nine"]["weights_note"])
        CouncilSession.objects.filter(id=old.id).update(created_at=now)
        cache.clear()
        head = B.build_sitting(self.user, old.id)["head"]
        self.assertNotIn(day if day != f"{now:%Y-%m-%d}" else "@@", head)
        self.assertRegex(head, r"argued \d\d:\d\d UTC")

    def test_a12_the_theorist_without_a_theory_is_no_theory(self):
        from dashboard import council_band as B
        self.assertEqual(B.token("theorist", "none"), "NO THEORY")
        self.assertNotIn("NONE", B.VERDICT_TOKENS.values())

    def test_a13_a_smaller_commitment_is_drawn_apart_from_a_refusal(self):
        from dashboard import council_band as B
        for verdict, smaller in (("fight_smaller", True), ("refuse", False),
                                 ("fight", False)):
            s = _session(symbol=f"T{verdict.upper()}")
            _speak(s, "emperor", {"verdict": verdict, "commit": 0.5,
                                  "p_work": 0.55})
            sit = B.build_sitting(self.user, s.id)
            self.assertEqual(sit["table"]["smaller"], smaller, verdict)
            self.assertEqual(sit["emperor"]["smaller"], smaller, verdict)
            if verdict == "fight_smaller":
                # the side stays the council's: against
                self.assertEqual(sit["table"]["chair"], "against")
                self.assertEqual(sit["table"]["chair_glyph"], "◐")

    def test_a14_an_unvalued_battle_is_never_zero(self):
        from dashboard import council_band as B
        _report()
        now = timezone.now()
        a = _session(symbol="VAL1")
        _speak(a, "emperor", {"verdict": "fight_smaller", "commit": 0.5,
                              "p_work": 0.55})
        b = _session(symbol="VAL2")
        _speak(b, "emperor", {"verdict": "fight", "p_work": 0.6})
        for s in (a, b):
            c = _claim_of(s, "emperor", "battle")
            c.grade, c.graded_at, c.value_r = "right", now, None
            c.save()
        line = B.build_room(self.user)["throne"]["battles"]["lines"][-1]
        self.assertTrue(line.endswith("on 2 graded, what his commitment saved "
                                      "is not measured."), line)
        self.assertNotIn("+0.00R", line)
        c = _claim_of(a, "emperor", "battle")
        c.value_r = 0.5
        c.save()
        cache.clear()
        line = B.build_room(self.user)["throne"]["battles"]["lines"][-1]
        self.assertTrue(line.endswith("on 2 graded (1 with a value), his "
                                      "commitment saved +0.50R."), line)


def dt_utc():
    from datetime import timezone as _tz
    return _tz.utc


@override_settings(CACHES=LOCMEM)
class ThePolishWordsTests(_Case):
    """E. Words said twice, raw codes, grammar."""

    def setUp(self):
        super().setUp()
        self.user = _user("cb_words", staff=True)

    def test_26a_a_rehearsal_is_said_once(self):
        from ai_agents.council_grading import REHEARSAL_NOTES
        from dashboard import council_band as B
        s = _session(symbol="REHEARSED", grade_notes=REHEARSAL_NOTES,
                     graded_at=timezone.now(),
                     why="the order filled in a rehearsal world")
        card = B.build_sittings(self.user)["cards"][0]
        self.assertEqual(card["outcome"], B.OUTCOME_REHEARSAL)
        self.assertEqual((card["sentence"], card["graded"]), ("", ""))
        self.assertIn("NOT GRADED (BY RULE)", card["chips"])
        sit = B.build_sitting(self.user, s.id)
        self.assertEqual((sit["sentence"], sit["graded"]), ("", ""))
        shown = {k: v for k, v in sit.items() if k != "ask"}
        self.assertEqual(_text(shown).count("rehearsal world"), 1)
        first = _session(symbol="AGAIN", created_at=timezone.now() - timedelta(hours=2))
        again = _session(symbol="AGAIN", grade_notes=f"a repeat of session #{first.id}",
                         graded_at=timezone.now())
        sit = B.build_sitting(self.user, again.id)
        self.assertEqual(sit["outcome"], f"Argued again: a repeat of sitting #{first.id}.")
        self.assertEqual(sit["graded"], "")

    def test_26b_c_the_emperors_battle_and_the_mood_once(self):
        from dashboard import council_band as B
        s = _session(symbol="ONCE", mood="uneasy")
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6,
                              "battle": "a small battle", "plan": "the trend"})
        sit = B.build_sitting(self.user, s.id)
        self.assertEqual(sit["emperor"]["key"], "a small battle")
        self.assertNotIn("The battle: a small battle", sit["emperor"]["extra"])
        self.assertEqual(_text(sit).count("a small battle"), 1)
        self.assertEqual(sit["mood"], "")
        self.assertIn("The people's mood at the sitting: uneasy.",
                      sit["emperor"]["extra"])
        bare = _session(symbol="NOCHAIR", mood="steady")
        _speak(bare, "champion", {"verdict": "back", "conviction": 0.7})
        self.assertEqual(B.build_sitting(self.user, bare.id)["mood"],
                         "The people's mood at the sitting: steady.")

    def test_26d_e_the_last_sitting_and_the_lane_said_once(self):
        from dashboard import council_band as B
        _report("trending")
        reason = ("measured in trending on forex, 34 graded calls, Brier 0.18 "
                  "against 0.24 for always saying the base rate")
        s = _session(symbol="GBPCAD", side="SELL",
                     hand={"voice": "champion", "side": "for"},
                     weights={"emperor": {"factor": 1.0, "lane": "neutral",
                                          "n": 0, "reason": "neutral"},
                              "champion": {"factor": 1.18, "lane": "measured",
                                           "n": 34, "reason": reason}})
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6})
        last = B.build_room(self.user)["throne"]["hand"]["last"]
        self.assertRegex(last[0], r"^GBPCAD SELL, \d\d:\d\d UTC:$")
        weights = B.build_voice(self.user, "champion")["weights"]
        self.assertIn(f"×1.18 · {reason}", weights[0])
        self.assertNotIn("measured · measured", weights[0])

    def test_27_no_raw_code_in_prose(self):
        from dashboard import council_band as B
        _report("mean_reverting")
        s = _session(symbol="CODES", regime="mean_reverting",
                     weights={"emperor": {"factor": 1.0, "lane": "neutral",
                                          "n": 0, "reason": "neutral"},
                              "skeptic": {"factor": 0.8, "lane": "measured",
                                          "n": 12, "reason": "measured in "
                                          "mean_reverting on forex, 12 "
                                          "graded calls"}})
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
        _speak(s, "skeptic", {"verdict": "shaky", "conviction": 0.6,
                              "target": "champion",
                              "claim": "the rule earned on this pair",
                              "flaw": "thin_sample"})
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6})
        sit = B.build_sitting(self.user, s.id)
        self.assertIn("regime mean reverting", sit["head"])
        sk = [b for b in sit["dissent"] + sit["others"]
              if b["voice"] == "skeptic"][0]
        # the flaw is in his verdict's words already: said once (round 2)
        self.assertIn("a thin sample", sk["words"])
        self.assertEqual(sk["key"], 'The Champion: "the rule earned on this '
                                    'pair"')
        self.assertIn("the battle: pending", sit["emperor"]["grades"])
        self.assertIn("works or not: pending", sit["emperor"]["grades"])
        champ = [b for b in sit["dissent"] + sit["others"]
                 if b["voice"] == "champion"][0]
        self.assertIn("for or against: pending", champ["grades"])
        dossier = B.build_voice(self.user, "skeptic")
        texts = [sit["head"], sk["key"], sit["emperor"]["grades"],
                 champ["grades"], sit["ask"]["facts"]] + dossier["weights"] \
            + [c["t"] for c in dossier["regimes"]]
        for t in texts:
            for raw in ("mean_reverting", "risk_on", "risk_off", "blow_off",
                        "thin_sample", "champion:"):
                self.assertNotIn(raw, t, (raw, t))
            self.assertNotRegex(t, r"(^|· )(work|stance|battle|attack):")
        self.assertIn("mean reverting: —", _text(dossier["regimes"]))
        self.assertIn("×0.80 · measured in mean reverting on forex, 12 graded "
                      "calls", dossier["weights"][0])

    def test_28_the_fixer_is_not_forex(self):
        from dashboard import council_band as B
        self.assertEqual(B.MONO["fixer"], "FI")
        self.assertEqual(len(set(B.MONO.values())), len(B.MONO))
        self.assertNotIn("FX", B.MONO.values())

    def test_30_grammar(self):
        from ai_agents.models import AgentTask
        from dashboard import council_band as B
        AgentTask.objects.create(agent="council_gambler", provider="x",
                                 model="test-model", cost_usd="0.1")
        today = B.build_voice(self.user, "gambler")["today"]
        self.assertTrue(today.startswith("Today: 1 call"), today)
        self.assertNotIn("1 calls", today)
        s = _session(status="sitting", symbol="SITTING")
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
        t = B.build_room(self.user)["direction"]["disagrees"]["t"]
        self.assertRegex(t, r"^The council is sitting on SITTING BUY: so far 1 "
                            r"for, none against \(\d\d:\d\d UTC\)\.$")
        self.assertNotIn(". (", t)


class ThePolishSheetTests(SimpleTestCase):
    """B, C, D: the sheet and the script."""

    def setUp(self):
        self.css = _strip_css(SHEET.read_text(encoding="utf-8"))
        self.js = _strip_js(JS.read_text(encoding="utf-8"))

    def _rules(self):
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", self.css):
            yield " ".join(m.group(1).split()), " ".join(m.group(2).split())

    def test_15_16_the_pushed_hordes_close_stays_on_its_first_row(self):
        # pushed by the band, or by ACTIVITY (round 2: "Positions ›" and the
        # close wrapped alone to a lower row with ACTIVITY open at 1100)
        rules = {}
        for sel, body in self._rules():
            parts = sel.split(", body:")
            for i, one in enumerate(parts):
                rules[one if i == 0 else "body:" + one] = body
        for pre in ("body:has(.sv-council-band.open) .sv-horde.open .hd-row1",
                    "body:has(.sv-activity.open) .sv-horde.open .hd-row1"):
            self._first_row(rules, pre)
        for sel in rules:
            if ".sv-horde" in sel:
                self.assertIn(".sv-horde.open", sel, sel)

    def _first_row(self, rules, pre):
        self.assertIn("row-gap: 4px;", rules[pre])
        # five on one 304px row at 1100 beside the band (297px at 6px)
        self.assertIn("column-gap: 6px;", rules[pre])
        self.assertIn("order: 2;", rules[pre + " > *"])
        self.assertIn("order: 0;", rules[pre + " > :is(.hd-title, .hd-dot, "
                                               ".hd-snaps, .hd-link, .hd-close)"])
        self.assertIn("margin-left: auto;", rules[pre + " > .hd-dot"])
        brk = rules[pre + "::after"]
        for decl in ('content: "";', "order: 1;", "flex-basis: 100%;"):
            self.assertIn(decl, brk, decl)
        for sel in rules:
            if ".sv-horde" in sel:
                self.assertIn(".sv-horde.open", sel, sel)

    def test_17_the_shut_tab_never_stands_on_the_eye(self):
        place = self.js[self.js.index("function placeTab("):
                        self.js.index("function schedule(")]
        self.assertIn("rectOf('seEyeFab')", place)
        self.assertIn("var others = soft ? [toggle, act, eye, head] : [toggle, act, eye];", place)
        self.assertIn("floor = Math.min(floor, eye.top - 8)", place)
        # the below slot and the scan for a free slot both stop at that floor
        self.assertIn("if (below + TAB_H <= floor && !hits(below, soft)) y = below;", place)
        self.assertIn("for (var at = box.top + 8; y === null && at + TAB_H <= floor; at += 8)", place)

    def test_18_the_scrollers_keep_the_eyes_clearance(self):
        shared = [b for s, b in self._rules()
                  if s == ".cb-room, .cb-sidebody, .cb-dossier"]
        self.assertEqual(len(shared), 1)
        self.assertIn("padding-bottom: max(16px,", shared[0])
        for sel, body in self._rules():
            if re.search(r"\.cb-(room|sidebody|dossier)(?![-\w])", sel):
                self.assertNotRegex(body, r"(?<![-\w])padding\s*:", sel)

    def test_20_the_head_keeps_its_buttons_on_the_first_row(self):
        rules = dict(self._rules())
        self.assertIn("order: 2;", rules[".cb-head > .cb-chips, .cb-head > .cb-stamp"])
        brk = rules[".cb-head::after"]
        for decl in ('content: "";', "order: 1;", "flex-basis: 100%;"):
            self.assertIn(decl, brk, decl)
        self.assertIn("margin-left: auto;", rules[".cb-widen"])
        self.assertIn("display: none;", rules[".sv-council-band.chamber .cb-head::after"])
        src = PARTIAL.read_text(encoding="utf-8")
        head = src[src.index('<header class="cb-head">'):src.index("</header>")]
        self.assertLess(head.index("svCouncilBandTitle"), head.index("svCouncilBandWiden"))
        self.assertLess(head.index("svCouncilBandWiden"), head.index("svCouncilBandClose"))

    def test_21_one_way_back_from_a_transcript_in_the_overlay(self):
        rules = dict(self._rules())
        self.assertIn("display: none;",
                      rules[".sv-council-band.cb-in-sitting .cb-sidehead"])
        self.assertIn("root.classList.toggle('cb-in-sitting', !!state.sitting && state.over);",
                      self.js)
        for fn in ("function setOver(", "function showSide(", "function openSitting("):
            body = self.js[self.js.index(fn):self.js.index(fn) + 900]
            self.assertIn("markSitting();", body, fn)

    def test_22_23_25_nothing_cramped_or_under_nine_pixels(self):
        rules = dict(self._rules())
        self.assertIn("grid-template-columns: 3px 64px minmax(0, 1fr);", rules[".cb-sitting"])
        self.assertIn("grid-template-columns: 3px 88px minmax(0, 1fr);",
                      rules[".sv-council-band.chamber .cb-sitting"])
        self.assertIn("drawTable(c.table || {}, state.chamber ? 88 : 64, false)", self.js)
        age = rules[".cb-sitting-head .cb-age"]
        self.assertIn("white-space: nowrap;", age)
        self.assertIn("flex-shrink: 0;", age)
        for sel, body in self._rules():
            if ".cb-table" in sel:
                continue  # SVG user units, scaled with the table
            for px in re.findall(r"font-size:\s*(\d+)px", body):
                self.assertGreaterEqual(int(px), 9, sel)
        self.assertIn("margin: 8px 0 2px;", rules["p.cb-label"])
        sub = rules[".cb-sub"]
        self.assertIn("font-size: 10px;", sub)
        self.assertIn("var(--text-secondary)", sub)
        self.assertIn("border-bottom: 1px solid var(--border);", sub)
        self.assertNotIn("padding", rules[".cb-mood-level"])

    def test_13_the_smaller_chair_is_amber_not_red(self):
        rules = dict(self._rules())
        for sel in (".cb-chair.cb-chair--smaller", ".cb-mark.cb-mark--smaller",
                    ".cb-token.cb-token--smaller", ".cb-ring.cb-ring--smaller"):
            self.assertIn("var(--warning)", rules[sel], sel)
            self.assertNotIn("--accent-red", rules[sel], sel)
        order = list(rules)
        self.assertGreater(order.index(".cb-chair.cb-chair--smaller"),
                           order.index(".cb-chair.cb-side--against"))
        self.assertGreater(order.index(".cb-mark.cb-mark--smaller"),
                           order.index(".cb-mark.cb-side--against"))
        self.assertGreater(order.index(".cb-ring.cb-ring--smaller"),
                           order.index(".cb-ring.cb-side--against"))
        for word in ("' cb-chair--smaller'", "' cb-mark--smaller'",
                     "' cb-token--smaller'", "classList.add('cb-ring--smaller')"):
            self.assertIn(word, self.js, word)

    def test_28_the_weights_rows_name_their_voice(self):
        paint = self.js[self.js.index("function paintRecord("):
                        self.js.index("function openDossier(")]
        self.assertIn("th.title = row.name || '';", paint)


# ══ J. polish, round 2: what the eyes saw ═══════════════════════════════
# (scratchpad councilband2/eyes_r2.md: each finding pinned where it lives)

def _graded(s, voice, kind, grade, r=None, value_r=None):
    c = _claim_of(s, voice, kind)
    c.grade, c.r, c.value_r, c.graded_at = grade, r, value_r, timezone.now()
    c.save()
    return c


@override_settings(CACHES=LOCMEM)
class ThePolishTwoTruthTests(_Case):
    """A. Untrue or misleading (round 2)."""

    def setUp(self):
        super().setUp()
        self.user = _user("cb_polish2", staff=True)

    def test_r2_1_the_skeptics_graded_attacks_are_his_best_and_worst(self):
        from dashboard import council_band as B
        attack = {"verdict": "shaky", "conviction": 0.6, "target": "champion",
                  "claim": "the rule earned on this pair", "flaw": "thin_sample"}
        lost = _session(symbol="LOST", truth="realized", truth_r=-1.0)
        _speak(lost, "skeptic", attack)
        won = _session(symbol="WON", truth="realized", truth_r=1.6)
        _speak(won, "skeptic", attack)
        # the council's grader writes no R on an attack
        _graded(lost, "skeptic", "attack", "right")
        _graded(won, "skeptic", "attack", "wrong")
        d = B.build_voice(self.user, "skeptic")
        self.assertEqual(len(d["best"]), 1)
        self.assertEqual(len(d["worst"]), 1)
        self.assertIn("LOST BUY · SHAKY · right: the Champion's call was wrong "
                      "· the trade -1.00R · ", d["best"][0]["t"])
        self.assertIn("WON BUY · SHAKY · wrong: the Champion's call was right "
                      "· the trade +1.60R · ", d["worst"][0]["t"])

    def test_r2_2_best_calls_rank_by_what_the_call_was_worth(self):
        from dashboard import council_band as B
        big = _session(symbol="BIGWIN")
        _speak(big, "emperor", {"verdict": "fight", "p_work": 0.6})
        _graded(big, "emperor", "battle", "right", r=1.6, value_r=0.0)
        saved = _session(symbol="SAVED")
        _speak(saved, "emperor", {"verdict": "fight_smaller", "commit": 0.5,
                                  "p_work": 0.55})
        _graded(saved, "emperor", "battle", "right", r=-1.0, value_r=0.5)
        cost = _session(symbol="COST")
        _speak(cost, "emperor", {"verdict": "fight_smaller", "commit": 0.5,
                                 "p_work": 0.55})
        _graded(cost, "emperor", "battle", "wrong", r=1.0, value_r=-0.5)
        small = _session(symbol="SMALL")
        _speak(small, "emperor", {"verdict": "fight_smaller", "commit": 0.8,
                                  "p_work": 0.55})
        _graded(small, "emperor", "battle", "wrong", r=2.0, value_r=-0.4)
        d = B.build_voice(self.user, "emperor")
        self.assertEqual([c["sitting"] for c in d["best"]],
                         [f"c{saved.id}", f"c{big.id}"])
        self.assertIn("his size saved +0.50R", d["best"][0]["t"])
        self.assertEqual([c["sitting"] for c in d["worst"]],
                         [f"c{cost.id}", f"c{small.id}"])
        # the Executioner's call is his stance: what his veto saved
        veto = _session(symbol="VETO")
        _speak(veto, "executioner", {"verdict": "veto", "conviction": 0.8})
        _graded(veto, "executioner", "stance", "right", r=-1.0, value_r=1.0)
        passed = _session(symbol="PASSED")
        _speak(passed, "executioner", {"verdict": "pass", "conviction": 0.2})
        _graded(passed, "executioner", "stance", "right", r=1.6, value_r=0.0)
        best = B.build_voice(self.user, "executioner")["best"]
        self.assertEqual([c["sitting"] for c in best],
                         [f"c{veto.id}", f"c{passed.id}"])
        self.assertIn("VETO · right · the trade -1.00R · the call saved "
                      "+1.00R", best[0]["t"])

    def test_r2_3_the_debates_voices_are_in_the_path_only_once_binding(self):
        from dashboard import council_band as B
        for key in ("platform_master", "trade_debate", "council_bots"):
            _switch(key)
        with mock.patch.dict(B.READERS, {"phase": lambda u, n: {
                "graded": 1, "shadow_n": 30}}):
            ex = B.build_voice(self.user, "executioner")["status"]
            ch = B.build_voice(self.user, "champion")["status"]
        self.assertEqual(ex, "Argues every live bot entry in shadow (1 of 30 "
                             "graded): his veto binds once 30 are graded.")
        self.assertEqual(ch, "Argues every live bot entry in shadow (1 of 30 "
                             "graded): once 30 are graded, past the daily stop "
                             "an elite entry needs his backing.")
        for t in (ex, ch):
            self.assertNotIn("In the order's path", t)
        cache.clear()
        with mock.patch.dict(B.READERS, {"phase": lambda u, n: {
                "graded": 30, "shadow_n": 30}}):
            self.assertEqual(B.build_voice(self.user, "executioner")["status"],
                             "In the order's path, by rule (the debate's two "
                             "voices).")

    def test_r2_4_a_voice_with_no_seat_is_never_told_of_its_overrulings(self):
        from dashboard import council_band as B
        seat = [{"regime": "mean_reverting", "asset_class": "crypto",
                 "voice": "champion", "factor": 1.15, "n": 34, "brier": 0.08,
                 "why_empty": ""}]
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(hands=seat)):
            sk = B.build_voice(self.user, "skeptic")
            ch = B.build_voice(self.user, "champion")
        self.assertEqual(sk["hand"][0], "Holds the Hand in no cell now.")
        self.assertNotIn("overruling of it", _text(sk["hand"]))
        self.assertEqual(ch["hand_cells"],
                         ["Holds the Hand in mean reverting on crypto"])
        self.assertEqual(ch["hand"], ["No graded overruling of it as the Hand "
                                      "yet (live sittings, 180 days)."])

    def test_r2_5_6_a_late_chair_and_a_sitting_in_progress(self):
        from dashboard import council_band as B
        late = _session(symbol="EURUSD")
        _speak(late, "champion", {"verdict": "back", "conviction": 0.7})
        _speak(late, "executioner", {"verdict": "veto", "conviction": 0.8})
        _speak(late, "emperor", {"verdict": "fight", "p_work": 0.6},
               status="late")
        t = B.build_sitting(self.user, late.id)["table"]
        self.assertEqual((t["chair_token"], t["chair_glyph"], t["chair"]),
                         ("LATE", "…", ""))
        self.assertTrue(t["label"].startswith("Council on EURUSD BUY: the "
                                              "Emperor ruled late (fight"),
                        t["label"])
        self.assertNotIn("no chair", t["label"])
        sitting = _session(symbol="GBPCAD", side="SELL", status="sitting")
        _speak(sitting, "champion", {"verdict": "back", "conviction": 0.7})
        _speak(sitting, "executioner", {"verdict": "veto", "conviction": 0.8})
        _speak(sitting, "emperor", status="asked")
        card = [c for c in B.build_sittings(self.user)["cards"]
                if c["id"] == f"c{sitting.id}"][0]
        self.assertFalse(card["split"])
        self.assertFalse(card["table"]["split"])
        self.assertFalse([c for c in card["chips"] if "SPLIT" in c])
        self.assertEqual(card["table"]["chair_token"], "SITTING")
        self.assertIn("the Emperor has not ruled yet", card["table"]["label"])
        # a closed debate record with both sides is still a split
        record = _session(symbol="RECORD", status="record")
        _speak(record, "champion", {"verdict": "back", "conviction": 0.7},
               status="copied", wave=0)
        _speak(record, "executioner", {"verdict": "veto", "conviction": 0.8},
               status="copied", wave=0)
        cache.clear()
        card = [c for c in B.build_sittings(self.user)["cards"]
                if c["id"] == f"c{record.id}"][0]
        self.assertIn("SPLIT", card["chips"])
        self.assertEqual(card["table"]["chair_token"], "NO CHAIR")

    def test_r2_7_the_specialty_lines_read_right(self):
        from ai_agents.council_grading import specialty_line
        base = {"right": 1, "wrong": 2, "refused": 0, "value_r": 0.0,
                "posted": 0, "trust": None, "over_wrong": 0, "over_n": 0,
                "all_in_n": 0, "all_in_avg": 0.0, "rest_n": 13,
                "rest_avg": 0.2}
        self.assertEqual(specialty_line("executioner", dict(base, value_r=-1.1)),
                         "his vetoes and cuts would have cost 1.10R")
        self.assertEqual(specialty_line("executioner", dict(base, value_r=0.5)),
                         "his vetoes and cuts would have saved +0.50R")
        self.assertEqual(specialty_line("gambler", base),
                         "all in: none yet; other calls: 13")
        self.assertEqual(specialty_line("champion", dict(base, right=43,
                                                          wrong=4)),
                         "for-or-against calls right 43 of 47")
        self.assertEqual(specialty_line("emperor", dict(
            base, value_r=-0.4, over_wrong=1, over_n=1)),
            "his commitment cost 0.40R in total; of the voices he overruled, "
            "1 of 1 was wrong")
        self.assertEqual(specialty_line("emperor", dict(
            base, right=0, wrong=0, value_r=0.0)),
            "his commitment: none graded yet; of the voices he overruled, "
            "none graded yet")
        for v in ("executioner", "emperor"):
            self.assertNotRegex(specialty_line(v, dict(base, value_r=-1.1)),
                                r"saved:? [-−]")

    def test_r2_9_a_silenced_sitting_says_what_it_knows(self):
        from dashboard import council_band as B
        s = _session(symbol="BTCUSD", asset_class="crypto", status="silent",
                     why="AI budget: core line spent ($15.00 of $15.00)",
                     created_at=timezone.now() - timedelta(hours=3))
        _speak(s, "executioner", {"verdict": "pass", "conviction": 0.2},
               status="copied", wave=0)
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7},
               status="copied", wave=0)
        for v in ("opportunist", "gambler", "awakened", "theorist"):
            _speak(s, v, status="silent", why="AI budget: core line spent")
        card = B.build_sittings(self.user)["cards"][0]
        sit = B.build_sitting(self.user, s.id)
        for x in (card, sit):
            self.assertEqual(x["outcome"], B.OUTCOME_ONLY_DEBATE)
            self.assertEqual(x["sentence"], "The other eight did not sit: "
                                            "today's AI budget refused it.")
            self.assertNotIn("refused after the debate", _text(x))
            self.assertNotIn("$", _text(x))
        # a ticket the budget silenced had no debate: the whole table
        t = _session(symbol="TICKET", origin="ticket", status="silent",
                     why="AI budget: core line spent")
        for v in ("executioner", "champion"):
            _speak(t, v, status="silent", why="AI budget: core line spent")
        self.assertEqual(B.build_sitting(self.user, t.id)["sentence"],
                         "Did not sit: today's AI budget refused it.")
        # the battles still count it among the orders not sent
        self.assertEqual(B._outcome_kind(B.OUTCOME_ONLY_DEBATE), "not_sent")

    def test_r2_10_11_the_regime_says_confidence_and_rulings_their_time(self):
        from dashboard import council_band as B
        _report("trending", 0.71)
        now = timezone.now()
        old_at = now - timedelta(days=2)
        old = _session(symbol="OLDRULE", created_at=old_at)
        _speak(old, "emperor", {"verdict": "fight", "p_work": 0.6})
        new = _session(symbol="NEWRULE")
        _speak(new, "emperor", {"verdict": "refuse", "p_work": 0.3})
        room = B.build_room(self.user)
        rulings = [r["t"] for r in room["throne"]["rulings"]]
        self.assertRegex(rulings[0], r"^\d\d:\d\d UTC · NEWRULE BUY · REFUSE · ")
        self.assertTrue(rulings[1].startswith(
            f"{old_at.astimezone(dt_utc()):%Y-%m-%d %H:%M} UTC · OLDRULE BUY · "),
            rulings[1])
        self.assertIn("Trending (confidence 0.71)",
                      room["direction"]["thinks"]["t"])
        traders = {"unread": False, "cards": [], "matrix": [],
                   "regime": "trending", "confidence": 0.71, "age_min": 5,
                   "measured": 1, "n_measured": 2, "n_cells": 15}
        cache.clear()
        with mock.patch.dict(B.READERS, {"traders": lambda u, n: traders}):
            line = B.build_room(self.user)["traders"]["line"]
        self.assertTrue(line.startswith("Trending (confidence 0.71) · "), line)

    def test_r2_12_who_disagrees_names_the_minority_while_it_sits(self):
        from dashboard import council_band as B
        s = _session(symbol="GBPCAD", side="SELL", status="sitting")
        _speak(s, "executioner", {"verdict": "veto", "conviction": 0.8},
               status="copied", wave=0)
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7},
               status="copied", wave=0)
        _speak(s, "gambler", {"verdict": "press", "p_work": 0.6})
        _speak(s, "opportunist", {"verdict": "seize", "p_work": 0.65})
        _speak(s, "striker", status="asked")
        t = B.build_room(self.user)["direction"]["disagrees"]["t"]
        self.assertRegex(t, r"^The council is sitting on GBPCAD SELL: so far "
                            r"the Executioner \(VETO\) stands against it, 3 "
                            r"for; 1 waiting \(\d\d:\d\d UTC\)\.$")

    def test_r2_13_history_says_statuses_in_words(self):
        from dashboard import council_band as B
        sitting = _session(symbol="ASKED", status="sitting")
        _speak(sitting, "champion", status="asked")
        record = _session(symbol="COPIED", status="record")
        _speak(record, "champion", {"verdict": "back", "conviction": 0.7},
               status="copied", wave=0)
        silent = _session(symbol="SILENT")
        _speak(silent, "champion", status="silent", why="timeout")
        hist = {h["sitting"]: h["t"] for h in
                B.build_voice(self.user, "champion")["history"]}
        self.assertTrue(hist[f"c{sitting.id}"].endswith(
            "ASKED BUY · waiting · nothing to grade"), hist)
        self.assertTrue(hist[f"c{record.id}"].endswith(
            "COPIED BUY · BACK · in the debate · pending"), hist)
        self.assertTrue(hist[f"c{silent.id}"].endswith(
            "SILENT BUY · silent · nothing to grade"), hist)
        for t in hist.values():
            for raw in ("· asked", "· copied", "no claim", "· — ·"):
                self.assertNotIn(raw, t, t)

    def test_r2_14_the_chambers_title_says_no_sitting_is_under_way(self):
        from dashboard import council_band as B
        self.assertEqual(B.WORDS["title_chamber"], "THE COUNCIL CHAMBER")
        self.assertNotIn("IN SESSION", PARTIAL.read_text(encoding="utf-8"))


@override_settings(CACHES=LOCMEM)
class ThePolishTwoWordsTests(_Case):
    """C. Readability, clutter, said twice, grammar, legends (round 2)."""

    def setUp(self):
        super().setUp()
        self.user = _user("cb_words2", staff=True)

    def test_r2_17_the_sitting_of_the_weights_is_said_once(self):
        from dashboard import council_band as B
        _report("trending")
        forex = {"factor": 1.15, "lane": "measured", "n": 34,
                 "reason": "measured in trending on forex, 34 graded calls, "
                           "Brier 0.08 against 0.16 for always saying the "
                           "base rate"}
        wide = {"factor": 0.5, "lane": "measured", "n": 12,
                "reason": "measured in trending across classes, 12 graded "
                          "calls, Brier 0.36 against 0.08 for always saying "
                          "the base rate"}
        neutral = {"factor": 1.0, "lane": "neutral", "n": 0,
                   "reason": "neutral: 0 graded calls in this cell, 10 needed"}
        crypto = _session(symbol="BTCUSD", asset_class="crypto",
                          regime="mean_reverting",
                          created_at=timezone.now() - timedelta(hours=5),
                          weights={"emperor": neutral, "fixer": neutral})
        _speak(crypto, "fixer", {"verdict": "fix", "p_work": 0.6})
        _speak(crypto, "emperor", {"verdict": "fight", "p_work": 0.6})
        s = _session(symbol="EURUSD", weights={
            "emperor": neutral, "champion": forex, "skeptic": wide,
            "striker": neutral})
        for v in ("champion", "striker"):
            _speak(s, v, {"verdict": "back" if v == "champion" else "take",
                          "conviction": 0.7, "p_work": 0.6})
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6})
        nine = B.build_room(self.user)["nine"]
        rows = {v["key"]: v["weight"]["t"] for t in nine["triads"]
                for v in t["voices"]}
        self.assertRegex(nine["weights_note"],
                         r"^Weights as the Emperor read them at the \d\d:\d\d "
                         r"UTC sitting \(trending on forex\)\. ")
        self.assertEqual(rows["champion"],
                         "×1.15 measured · 34 graded · Brier 0.08 vs 0.16")
        self.assertEqual(rows["skeptic"], "×0.50 measured in trending across "
                                          "classes · 12 graded · Brier 0.36 "
                                          "vs 0.08")
        self.assertEqual(rows["striker"], "×1.00 neutral: 0 of 10 graded")
        # read at another sitting: it says its own
        self.assertRegex(rows["fixer"], r"^×1\.00 neutral: 0 of 10 graded · "
                                        r"read at the (\d{4}-\d\d-\d\d )?"
                                        r"\d\d:\d\d UTC sitting "
                                        r"\(mean reverting on crypto\)$")
        for v, t in rows.items():
            self.assertNotIn("as the Emperor read it", t, v)
            self.assertNotIn("for always saying", t, v)

    def test_r2_19a_a_sent_orders_r_is_said_once(self):
        from dashboard import council_band as B
        self.assertEqual(B.outcome_shown("Sent · trade #5 · +0.8R",
                                         "GRADED +0.8R"),
                         "Sent · trade #5 · closed")
        self.assertEqual(B.outcome_shown("Sent · trade #5 · +0.8R",
                                         "GRADE PENDING"),
                         "Sent · trade #5 · +0.8R")
        s = {"id": 9, "origin": "bot", "symbol": "EURUSD", "side": "BUY",
             "asset_class": "forex", "status": "done", "why": "",
             "trade_id": 5, "trade__status": "CLOSED",
             "trade__realized_r": 0.8, "truth": "realized", "truth_r": 0.8,
             "graded_at": timezone.now(), "created_at": timezone.now(),
             "trade_meta": {"binding": False, "graded": None}}
        with mock.patch.object(B, "_world", return_value="live"):
            card = B._card(s, [], [], timezone.now())
        self.assertEqual(card["outcome"], "Sent · trade #5 · closed")
        self.assertIn("GRADED +0.8R", card["chips"])

    def test_r2_20_grammar(self):
        from dashboard import council_band as B
        rm = _rm(chair={"over_wrong": 1, "over_n": 1, "follow_right": 1,
                        "follow_n": 3})
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=rm):
            lines = B.build_room(self.user)["throne"]["chair"]["lines"]
        self.assertIn("1 of 1 was wrong; of those he followed, 1 of 3 was "
                      "right.", lines[-1])
        battles = {"sat": 3, "bots": 3, "tickets": 0, "left": 2, "won": 1,
                   "lost": 0, "open": 1, "unpriced": 0, "net_r": 0.8,
                   "no_order": 1, "rehearsal": 0, "repeat": 0, "young": 0,
                   "emperor": {"fight": 1, "fight_smaller": 1, "refuse": 0,
                               "graded": 2, "valued": 2, "saved_r": -0.4}}
        cache.clear()
        with mock.patch.dict(B.READERS, {"battles": lambda u, n: battles}):
            lines = B.build_room(self.user)["throne"]["battles"]["lines"]
        self.assertIn("Orders that left: 2 (won 1, lost 0, open 1) · net +0.8R",
                      lines)
        self.assertTrue(lines[-1].endswith("on 2 graded, his commitment cost "
                                           "0.40R."), lines[-1])

    def test_r2_19b_23_24_legends_and_the_two_books(self):
        from dashboard import council_band as B
        _report("trending")
        record = B.build_record(self.user)
        self.assertTrue(record["weights_key"].startswith(
            "EX the Executioner · CH the Champion · "), record["weights_key"])
        self.assertIn("Shaded: the regime now.", record["weights_key"])
        traders = {"unread": False, "cards": [], "regime": "trending",
                   "matrix": [{"key": "steady", "label": "Steady", "cells": [
                       {"regime": "trending", "factor": 1.0, "lane": "prior",
                        "current": True}]}],
                   "confidence": 0.7, "age_min": 5, "measured": 0,
                   "n_measured": 0, "n_cells": 5}
        with mock.patch.dict(B.READERS, {"traders": lambda u, n: traders}):
            self.assertEqual(B.build_room(self.user)["traders"]["key"],
                             B.TRADERS_KEY)
        for words in ("dashed", "gold", "outlined"):
            self.assertIn(words, B.TRADERS_KEY.lower())
        self.assertNotIn("your book", B.MOOD_BOOK.lower())
        self.assertNotIn("your book", B.WAR_LABEL.lower())
        self.assertIn("the real-money book", B.MOOD_BOOK)
        self.assertTrue(B.WAR_LABEL.startswith("The book the gates read (a "
                                               "demo world included)"))


class ThePolishTwoSheetTests(SimpleTestCase):
    """B and C: the sheet and the script (round 2)."""

    def setUp(self):
        self.css = _strip_css(SHEET.read_text(encoding="utf-8"))
        self.js = _strip_js(JS.read_text(encoding="utf-8"))

    def _rules(self):
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", self.css):
            yield " ".join(m.group(1).split()), " ".join(m.group(2).split())

    def test_r2_21_no_text_under_ten_pixels_and_legible_chips(self):
        for sel, body in self._rules():
            if ".cb-table" in sel:
                continue  # SVG user units, scaled with the table
            for px in re.findall(r"font-size:\s*(\d+)px", body):
                self.assertGreaterEqual(int(px), 10, sel)
        chip = dict(self._rules())[".cb-chip"]
        self.assertIn("color: var(--text-secondary);", chip)

    def test_r2_22_the_cards_kind_line_stays_one_line(self):
        kind = dict(self._rules())[".cb-sitting-head .cb-kind"]
        for decl in ("white-space: nowrap;", "overflow: hidden;",
                     "text-overflow: ellipsis;"):
            self.assertIn(decl, kind, decl)
        card = self.js[self.js.index("function sittingCard("):
                       self.js.index("function paintSittings(")]
        self.assertIn("state.chamber ? c['class'] : ''", card)
        self.assertIn("kind.title = ", card)

    def test_r2_16_the_tab_avoids_the_open_hordes_head(self):
        place = self.js[self.js.index("function placeTab("):
                        self.js.index("function schedule(")]
        self.assertIn("var head = hordeOpen() ? rectOf('svHordeHead') : null;",
                      place)
        self.assertIn("var others = soft ? [toggle, act, eye, head] : [toggle, act, eye];",
                      place)
        # clear of the head where there is room; never on a control where
        # there is none
        self.assertIn("var y = slot(true);\n    if (y === null) y = slot(false);",
                      place)
        self.assertIn("if (!hits(fallback, true))", place)

    def test_r2_18_23_the_head_model_and_the_legends_are_painted(self):
        self.assertIn("lines(head, [s.model], 'cb-line--muted cb-mono');",
                      self.js)
        self.assertIn("lines(body, [n.weights_note], 'cb-line--muted');",
                      self.js)
        self.assertIn("lines(body, [t.key], 'cb-line--muted');", self.js)
        self.assertIn("lines(sideBody, [r.weights_key, W('r_weights_note')], "
                      "'cb-line--muted');", self.js)


# ══ K. the final review: each confirmed finding, pinned where it lives ══
# (scratchpad councilband2/review: the probes P1-P10, the coexistence
# probes and the mutants J1-J10, A1, W1-W4, B1, B4-B8, B16, B18, B19,
# K1-K6, R1, S1, C1 and E2; each test below fails on its finding)

NODE = shutil.which("node")
HARNESS = BASE / "tests" / "horde_dom_harness.js"
ACTIVITY_JS = BASE / "static" / "js" / "sv-activity.js"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "source", "track", "wbr"}


def _band_tree(activity=False):
    """The rendered band (and the activity drawer beside it) as a JSON
    tree for tests/horde_dom_harness.js."""
    from html.parser import HTMLParser

    from django.template.loader import render_to_string

    class Tree(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.root = {"tag": "root", "attrs": {}, "children": []}
            self.stack = [self.root]

        def handle_starttag(self, tag, attrs):
            node = {"tag": tag, "attrs": {k: (v if v is not None else "")
                                          for k, v in attrs}, "children": []}
            self.stack[-1]["children"].append(node)
            if tag not in _VOID:
                self.stack.append(node)

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i]["tag"] == tag:
                    del self.stack[i:]
                    break

        def handle_data(self, data):
            if data:
                self.stack[-1]["children"].append(data)

    html = render_to_string("_partials/council_band.html", {})
    if activity:
        html = render_to_string("_partials/activity_drawer.html", {}) + html
    t = Tree()
    t.feed(html)
    return t.root["children"]


def _drive_band(scenario, payloads=None, activity=False):
    """sv-council-band.js (after sv-activity.js when `activity`) run in the
    harness under a scenario; the scenario's return value comes back."""
    from django.core.serializers.json import DjangoJSONEncoder
    payloads = payloads or {"board": {"ok": True, "now": "2026-10-23T00:00:00Z",
                                      "panels": {}}}
    tmp = Path(tempfile.mkdtemp(prefix="sv-cband-dom-"))
    try:
        (tmp / "tree.json").write_text(json.dumps(_band_tree(activity)),
                                       encoding="utf-8")
        src = JS.read_text(encoding="utf-8")
        if activity:
            src = ACTIVITY_JS.read_text(encoding="utf-8") + "\n;\n" + src
        (tmp / "band.js").write_text(src, encoding="utf-8")
        (tmp / "scenario.js").write_text(scenario, encoding="utf-8")
        (tmp / "payloads.json").write_text(json.dumps(payloads, cls=DjangoJSONEncoder),
                                           encoding="utf-8")
        proc = subprocess.run([NODE, str(HARNESS), str(tmp / "tree.json"),
                               str(tmp / "band.js"), str(tmp / "scenario.js"),
                               str(tmp / "payloads.json")],
                              capture_output=True, text=True, timeout=120)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-3000:])
    return json.loads(proc.stdout)


SHUT = """
env.load();
await env.settle();
await env.advance(70000);
const a = env.fetched.length;
env.fire('sv:eye-event', {kind: 'council_sitting', data: {symbol: 'EURUSD', side: 'BUY', status: 'silent'}});
const silentHidden = env.$('svCouncilBandBadge').hidden;
env.fire('sv:eye-event', {kind: 'council_sitting', data: {symbol: 'EURUSD', side: 'BUY', status: 'done'}});
env.fire('sv:eye-event', {kind: 'fill_close', data: {symbol: 'EURUSD', status: 'done'}});
env.doc.hidden = true; env.fire('visibilitychange'); env.doc.hidden = false; env.fire('visibilitychange');
env.fire('sv:pin-unlocked');
await env.advance(70000);
return {shut_70s: a, shut_after_events: env.fetched.length,
        silent_badge_hidden: silentHidden, badge: env.$('svCouncilBandBadge').textContent};
"""

OPEN = """
env.load();
await env.settle();
env.click(env.$('svCouncilBandTab'));
await env.settle();
const onOpen = env.fetched.length;
await env.advance(60000);
const after60 = env.fetched.length;
env.doc.hidden = true;
env.fire('sv:eye-event', {kind: 'fill_close'});
env.fire('sv:eye-event', {kind: 'council_sitting', data: {symbol: 'EURUSD', side: 'BUY', status: 'done'}});
await env.advance(120000);
const hidden120 = env.fetched.length;
env.doc.hidden = false;
env.fire('visibilitychange');
await env.settle();
const shown = env.fetched.length;
env.click(env.$('svCouncilBandTab'));
await env.settle();
await env.advance(120000);
return {onOpen, after60, hidden120, shown, shut120: env.fetched.length};
"""

FORBIDDEN = """
env.serve(() => ({__status: 403, staff_only: true}));
env.load();
await env.settle();
env.click(env.$('svCouncilBandTab'));
await env.settle();
await env.advance(180000);
return {reads_after_403: env.fetched.length};
"""

PHONE = """
env.store['sauron_council_band_open'] = 'open';
env.media.matches = true;
env.load();
await env.settle();
env.click(env.$('svCouncilBandTab'));
env.fire('sv:eye-event', {kind: 'fill_open'});
await env.advance(120000);
return {phone_reads: env.fetched.length, open: env.$('svCouncilBand').classList.contains('open')};
"""

RESTORE = """
env.store['sauron_council_band_open'] = 'open';
env.load();
await env.settle();
return {restored_reads: env.fetched.length, open: env.$('svCouncilBand').classList.contains('open')};
"""

RESTORE_HIDDEN = """
env.store['sauron_council_band_open'] = 'open';
env.doc.hidden = true;
env.load();
await env.settle();
await env.advance(5000);
const loaded = env.fetched.length;
env.doc.hidden = false;
env.fire('visibilitychange');
await env.settle();
return {hidden_load_reads: loaded, on_show: env.fetched.length,
        open: env.$('svCouncilBand').classList.contains('open')};
"""

WORDS_OPEN = """
env.load();
await env.settle();
env.click(env.$('svCouncilBandTab'));
await env.settle();
env.fire('sv:eye-event', {kind: 'council_sitting', data: {symbol: 'EURUSD', side: 'BUY', status: 'silent'}});
const notSat = env.$('svCouncilBandSay').textContent;
env.fire('sv:eye-event', {kind: 'council_sitting', data: {symbol: 'GBPUSD', side: 'SELL', status: 'partial'}});
return {notSat, sat: env.$('svCouncilBandSay').textContent,
        badge_hidden: env.$('svCouncilBandBadge').hidden};
"""

DOCKS = """
env.load();
await env.settle();
const open = () => [env.$('svCouncilBand').classList.contains('open'),
                    env.$('svActivity').classList.contains('open')];
env.click(env.$('svCouncilBandTab'));
await env.settle();
const band = open();
env.click(env.$('svActivityTab'));
await env.settle();
const act = open();
env.click(env.$('svCouncilBandTab'));
await env.settle();
return {band, act, back: open()};
"""

REPAINT = """
const P = env.payloads;
let roomRev = 0, pageRev = 0, voiceRev = 0;
const copy = (o) => JSON.parse(JSON.stringify(o));
env.serve((url) => {
  if (url.indexOf('voice=') !== -1) { const v = copy(P.voice); if (voiceRev) v.voice.rev = 'v' + voiceRev; return v; }
  if (url.indexOf('before=') !== -1) return P.older;
  if (url.indexOf('part=sittings') !== -1) {
    const s = copy(P.page1);
    if (pageRev) { s.sittings.rev = 'p' + pageRev; s.sittings.cards.unshift(copy(P.fresh_card)); }
    return s;
  }
  if (url.indexOf('part=record') !== -1) return P.record;
  const r = copy(P.room);
  if (roomRev) { r.panels.throne.rev = 't' + roomRev; r.panels.nine.rev = 'n' + roomRev; }
  return r;
});
const $q = (s) => env.doc.querySelector(s);
const $all = (s) => env.doc.querySelectorAll(s);
const active = () => env.doc.activeElement;
const inside = (id) => env.$(id).contains(active());
env.load();
await env.settle();
env.click(env.$('svCouncilBandTab'));
await env.settle();
const meta = ($q('#cbNine .cb-voice-open[data-voice="champion"] .cb-voice-meta') || {}).textContent || '';
// 1. the room: a changed throne is repainted under the reader's focus
const ring = $q('#cbThrone .cb-ring');
ring.focus();
roomRev = 1;
await env.advance(60000);
const room = {in_throne: inside('cbThrone'), text: active().textContent, replaced: active() !== ring};
// 2. the sittings in the overlay
const link = $q('.cb-links [data-side="sittings"]');
link.focus();
env.click(link);
await env.settle();
const over = {room_inert: env.$('svCouncilBandRoom').hasAttribute('inert'), focus_in_side: inside('svCouncilBandSide')};
const more = $q('#svCouncilBandSideBody .cb-link');
more.focus();
env.click(more);
await env.settle();
const n1 = $all('#svCouncilBandSideBody .cb-sitting').length;
const older = $all('#svCouncilBandSideBody .cb-sitting')[22];
const olderId = older.getAttribute('data-sitting');
older.focus();
await env.advance(60000);
const n2 = $all('#svCouncilBandSideBody .cb-sitting').length;
const kept = active() === older;
pageRev = 1;
await env.advance(60000);
const n3 = $all('#svCouncilBandSideBody .cb-sitting').length;
const refocused = active().getAttribute && active().getAttribute('data-sitting');
env.key(active(), 'Escape');
await env.settle();
const esc = {over: env.$('svCouncilBand').classList.contains('over'),
             room_inert: env.$('svCouncilBandRoom').hasAttribute('inert'),
             on_link: active() === link};
// 3. the dossier
const row = $q('#cbNine .cb-voice-open[data-voice="champion"]');
row.focus();
env.click(row);
await env.settle();
await env.advance(1000);
const dossierInert = env.$('svCouncilBandRoom').hasAttribute('inert');
const hist = $all('#svCouncilBandDossier .cb-rulings button');
const pick = hist[hist.length - 1];
const pickText = pick.textContent;
pick.focus();
env.$('svCouncilBandDossier').scrollTop = 967;
await env.advance(60000);
const d1 = {same: active() === pick, top: env.$('svCouncilBandDossier').scrollTop};
voiceRev = 1;
await env.advance(60000);
const d2 = {text: active().textContent === pickText, rebuilt: active() !== pick,
            top: env.$('svCouncilBandDossier').scrollTop};
env.key(active(), 'Escape');
await env.settle();
const out = {dossier_hidden: env.$('svCouncilBandDossier').hidden,
             on_row: active().getAttribute && active().getAttribute('data-voice'),
             room_inert: env.$('svCouncilBandRoom').hasAttribute('inert')};
return {meta, room, over, n1, n2, n3, kept, olderId, refocused, esc,
        dossierInert, d1, d2, out};
"""


@unittest.skipUnless(NODE, "node is not installed")
class ThePollingBehaviourTests(SimpleTestCase):
    """sv-council-band.js run in tests/horde_dom_harness.js: what it READS
    is counted, not looked for in its text (mutants J1-J10 kept every
    string the old checks looked for)."""

    def test_shut_nothing_is_read_and_only_a_sitting_that_sat_counts(self):
        self.assertEqual(_drive_band(SHUT), {
            "shut_70s": 0, "shut_after_events": 0,
            "silent_badge_hidden": True, "badge": "1"})

    def test_open_reads_once_a_minute_and_never_while_hidden_or_shut(self):
        self.assertEqual(_drive_band(OPEN), {
            "onOpen": 1, "after60": 2, "hidden120": 2, "shown": 3,
            "shut120": 3})

    def test_a_403_stops_every_read(self):
        self.assertEqual(_drive_band(FORBIDDEN), {"reads_after_403": 1})

    def test_the_phone_reads_nothing_and_never_opens(self):
        self.assertEqual(_drive_band(PHONE), {"phone_reads": 0, "open": False})

    def test_a_band_left_open_comes_back_open_and_reads_once(self):
        self.assertEqual(_drive_band(RESTORE), {"restored_reads": 1, "open": True})

    def test_a_page_loaded_hidden_reads_when_it_is_shown(self):
        self.assertEqual(_drive_band(RESTORE_HIDDEN), {
            "hidden_load_reads": 0, "on_show": 1, "open": True})

    def test_a_sitting_that_did_not_sit_is_said_so(self):
        self.assertEqual(_drive_band(WORDS_OPEN), {
            "notSat": "The council did not sit on EURUSD BUY.",
            "sat": "The council sat on GBPUSD SELL.", "badge_hidden": True})

    def test_one_dock_at_a_time_both_ways(self):
        """A1: the drawer shuts when the band opens, the band when the
        drawer opens."""
        self.assertEqual(_drive_band(DOCKS, activity=True), {
            "band": [True, False], "act": [False, True], "back": [True, False]})


@unittest.skipUnless(NODE, "node is not installed")
@override_settings(CACHES=LOCMEM)
class TheRepaintBehaviourTests(_Case):
    """The periodic reads, driven with the endpoint's own answers: the
    reader keeps their place, their focus and their older pages."""

    def test_a_repaint_keeps_focus_place_older_pages_and_the_cover(self):
        from django.core.serializers.json import DjangoJSONEncoder

        from dashboard import council_band as B
        user = _user("cb_repaint", staff=True)
        _report()
        now = timezone.now()
        # oldest first, as the table fills: "Show older" pages by id
        for i in reversed(range(B.SITTINGS_MAX + 5)):
            s = _session(symbol=f"SYM{i}", created_at=now - timedelta(minutes=5 * i))
            _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
            _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6})
        page1 = B.build_sittings(user)
        older = B.build_sittings(user, before=int(page1["cards"][-1]["id"][1:]))
        fresh = json.loads(json.dumps(page1["cards"][0], cls=DjangoJSONEncoder))
        fresh["id"] = "c999999"
        room = B.build_room(user)
        payloads = {"room": {"ok": True, "panels": room},
                    "page1": {"ok": True, "sittings": page1},
                    "older": {"ok": True, "sittings": older},
                    "fresh_card": fresh,
                    "record": {"ok": True, "record": B.build_record(user)},
                    "voice": {"ok": True, "voice": B.build_voice(user, "champion")},
                    "board": {"ok": True, "panels": room}}
        got = _drive_band(REPAINT, payloads)
        champ = [v for t in room["nine"]["triads"] for v in t["voices"]
                 if v["key"] == "champion"][0]
        # THE NINE says the day of the voice's last call
        self.assertTrue(got["meta"].endswith(" · " + champ["latest"]["when"]),
                        got["meta"])
        self.assertEqual(got["room"], {"in_throne": True, "text": "EM",
                                       "replaced": True})
        self.assertEqual(got["over"], {"room_inert": True, "focus_in_side": True})
        self.assertEqual((got["n1"], got["n2"], got["n3"]), (25, 25, 26))
        self.assertTrue(got["kept"])
        self.assertEqual(got["refocused"], got["olderId"])
        self.assertEqual(got["esc"], {"over": False, "room_inert": False,
                                      "on_link": True})
        self.assertTrue(got["dossierInert"])
        self.assertEqual(got["d1"], {"same": True, "top": 967})
        self.assertEqual(got["d2"], {"text": True, "rebuilt": True, "top": 967})
        self.assertEqual(got["out"], {"dossier_hidden": True, "on_row": "champion",
                                      "room_inert": False})


@unittest.skipUnless(NODE, "node is not installed")
class TheFinalChromeTests(SimpleTestCase):
    """tallBox() beside an open dock, and the open column's width."""

    def _boxes(self, cases):
        # the Horde's own driver of tallBox(), imported here so the loader
        # does not collect its class twice
        from tests.test_the_horde import TheTallChartTests as T
        self.RUN = T.RUN
        return T._boxes(self, cases)

    def test_the_tall_chart_keeps_its_insets_beside_any_dock(self):
        rect = lambda t, b, l=0, r=1280: {"top": t, "bottom": b, "left": l, "right": r}  # noqa: E731
        base = {".topbar": rect(0, 106), ".info-panel-wrap": rect(740, 800, 240, 1236),
                ".sidebar": rect(0, 800, 0, 240), ".signals-rail": rect(0, 800, 1236, 1280)}
        band = ".sv-council-band.open .sv-council-band-panel"
        act = ".sv-activity.open .sv-activity-panel"
        wide = {".topbar": rect(0, 106, 0, 1100),
                ".info-panel-wrap": rect(740, 800, 240, 820),
                ".sidebar": rect(0, 800, 0, 240),
                ".signals-rail": rect(0, 800, 820, 1100)}
        open_, chamber, drawer, narrow = self._boxes([
            {"vh": 800, "vw": 1280, "rects": {**base, band: rect(114, 712, 880, 1236)}},
            {"vh": 800, "vw": 1280, "rects": {**base, band: rect(114, 712, 356, 1236)}},
            {"vh": 800, "vw": 1280, "rects": {**base, act: rect(114, 712, 920, 1236)}},
            {"vh": 800, "vw": 1100, "rects": {**wide, band: rect(114, 712, 420, 820)}},
        ])
        self.assertEqual(open_, {"top": 114, "right": 408, "bottom": 68, "left": 248})
        self.assertEqual(drawer, {"top": 114, "right": 368, "bottom": 68, "left": 248})
        # the chamber, and the band at 1100 with the rail open, would leave
        # a sliver: the chart keeps the rail's, the topbar's and the strip's
        # insets, never {8, 8, 8, 8} over everything
        self.assertEqual(chamber, {"top": 114, "right": 52, "bottom": 68, "left": 248})
        self.assertEqual(narrow, {"top": 114, "right": 288, "bottom": 68, "left": 248})


class TheOpenWidthTests(SimpleTestCase):

    def _width(self, css, vw, rail, left=260):
        """The sheet's --sv-cband-open-w at one width: clamp, min, calc
        and px, worked out (CSS's own arithmetic, no browser)."""
        import ast
        expr = re.search(r"--sv-cband-open-w:\s*(.+?);", css).group(1)
        expr = (expr.replace("var(--se-left-chrome, 260px)", str(left))
                .replace("var(--sv-rail-w)", str(rail)).replace("100vw", str(vw))
                .replace("px", "").replace("calc(", "("))
        fns = {"clamp": lambda a, b, c: max(a, min(b, c)), "min": min, "max": max}

        def ev(n):
            if isinstance(n, ast.Expression):
                return ev(n.body)
            if isinstance(n, ast.Constant):
                return n.value
            if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub)):
                a, b = ev(n.left), ev(n.right)
                return a + b if isinstance(n.op, ast.Add) else a - b
            if isinstance(n, ast.Call) and n.func.id in fns:
                return fns[n.func.id](*[ev(x) for x in n.args])
            raise ValueError(ast.dump(n))
        return ev(ast.parse(expr, mode="eval"))

    def test_the_open_column_never_puts_its_tab_under_the_sidebar(self):
        css = _strip_css(SHEET.read_text(encoding="utf-8"))
        # 860 with the rail open: the column starts 28px right of the
        # sidebar, its tab on the gap (probe: 220 and the tab under it)
        w = self._width(css, 860, 280)
        self.assertEqual(w, 292)
        self.assertEqual(860 - 280 - w - 28, 260)
        for vw in range(769, 1601, 7):
            for rail in (44, 280):
                w = self._width(css, vw, rail)
                self.assertGreaterEqual(vw - rail - w - 28, 260, (vw, rail, w))
                self.assertLessEqual(w, 400, (vw, rail))
        self.assertEqual(self._width(css, 1440, 44), 400)
        self.assertEqual(self._width(css, 1024, 280), 388)


def _matrix(cells):
    from bot_program.persona_mix import REGIMES
    return [{"voice": v, "name": v.title(), "cells": [
        {"regime": rg, **rows.get(rg, {"factor": 1.0, "n": 0, "lane": "neutral"})}
        for rg in REGIMES]} for v, rows in cells.items()]


@override_settings(CACHES=LOCMEM)
class TheFinalTruthTests(_Case):
    """The truth contract, where the final review found it broken."""

    def setUp(self):
        super().setUp()
        self.user = _user("cb_final", staff=True)

    # finding 1: the brief's own amount, echoed by the voices
    def test_the_briefs_amount_echoed_by_a_voice_is_withheld(self):
        from dashboard import council_band as B
        _report()
        s = _session(user=self.user, symbol="ECHOSYM", entry=1.10, stop=1.09,
                     qty=123456, value_per_unit=1.0,
                     brief="THE TRADE\n  size 123456 units, risk at the stop 1,234.56")
        _speak(s, "gambler", {"verdict": "press", "p_work": 0.6,
                              "case": "Risk at the stop 1,234.56 is modest for this book",
                              "reasons": ["risking 1,234.56 to make 2,469.12",
                                          "one stop is 1234.56 here"],
                              "note": "it costs 1,235 at worst"})
        _speak(s, "striker", {"verdict": "wait", "p_work": 0.6,
                              "decision": "wait for 1.0950",
                              "trigger": {"level": 1.095, "within_hours": 6}})
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6,
                              "war_cost": "one stop costs 1,234.56",
                              "battle": "a battle of 1235 a stop",
                              "plan": "the line costs 1235 a week"})
        out = _everything(self.user)
        text = _text(out)
        for leak in ("1,234.56", "1234.56", "1,235", "1235", "2,469.12", "123456"):
            self.assertNotIn(leak, text, leak)
        sit = out[f"sitting{s.id}"]
        for leak in ("1,234.56", "1235"):
            self.assertNotIn(leak, sit["ask"]["facts"], leak)
        gambler = [b for b in sit["others"] if b["voice"] == "gambler"][0]
        self.assertEqual(gambler["key"], B.WITHHELD)
        self.assertEqual(gambler["reasons"], [B.WITHHELD, B.WITHHELD])
        # a level is not money: the Striker's price stays
        self.assertIn("wait for 1.0950", text)
        self.assertIn(B.WITHHELD, out["room"]["throne"]["campaign"]["t"])
        self.assertIsNone(B.money_marks({"entry": 1.1, "stop": None, "qty": 3}))

    def test_the_scrub_withholds_the_briefs_shapes(self):
        from dashboard.council_band import WITHHELD, scrub
        for shape in ("risk at the stop 1,234.56", "risking 1,234.56 to make 2,469.12",
                      "one stop costs 1,234.56", "a stake of 300",
                      "notional 12,000", "exposure 4,000", "book value 9,876",
                      "500 dollars", "dollars 40"):
            self.assertEqual(scrub(shape), WITHHELD, shape)
        for kept in ("risk 1.2R", "risking 1R to make 2R", "the trade risks "
                     "0.8% of the book", "risk at the stop 0.5%", "+1,234 more",
                     "stop 1.0790", "1,234.56R"):
            self.assertEqual(scrub(kept), kept, kept)

    # finding 20: every free-text sink, its own amount
    def test_money_in_every_free_text_field_is_withheld(self):
        _report()
        s = _session(user=self.user, symbol="MONEYSYM")
        _speak(s, "executioner", {"verdict": "veto", "conviction": 0.8,
                                  "killer": "it loses 1,111.11 USD",
                                  "reasons": ["a loss of $2,222 today"],
                                  "note": "equity 3,333 is thin"})
        _speak(s, "opportunist", {"verdict": "elsewhere", "p_work": 0.4,
                                  "asymmetry": "x", "alternative": {
                                      "symbol": "GBPUSD", "direction": "SELL",
                                      "horizon_hours": 6, "confidence": 0.6,
                                      "why": "it pays 4,444 EUR"}})
        _speak(s, "emperor", {"verdict": "fight", "p_work": 0.6,
                              "battle": "worth 5,555 USD",
                              "plan": "risk 6,666 USD a week"})
        text = _text(_everything(self.user))
        for leak in ("1,111.11", "2,222", "3,333", "4,444", "5,555", "6,666"):
            self.assertNotIn(leak, text, leak)

    # finding 2: twenty debate records never hide the last ruling
    def test_twenty_debate_records_never_hide_the_last_sitting(self):
        from dashboard import council_band as B
        _report()
        now = timezone.now()
        sat = _session(symbol="RULED", mood="steady",
                       created_at=now - timedelta(hours=3),
                       hand={"voice": "champion", "side": "for"})
        _speak(sat, "gambler", {"verdict": "press", "p_work": 0.6})
        _speak(sat, "emperor", {"verdict": "fight", "p_work": 0.6,
                                "plan": "ride the trend"})
        for i in range(B.SITTINGS_MAX):
            r = _session(symbol=f"REC{i}", status="record",
                         created_at=now - timedelta(minutes=5 * i))
            _speak(r, "champion", {"verdict": "back", "conviction": 0.7},
                   status="copied", wave=0)
        room = B.build_room(self.user)
        th = room["throne"]
        self.assertEqual(th["rulings_none"], "")
        self.assertIn("RULED BUY · FIGHT", th["rulings"][0]["t"])
        self.assertTrue(th["hand"]["last"][0].startswith("RULED BUY, "),
                        th["hand"]["last"])
        self.assertEqual(th["mood"]["last"], "At the last sitting: steady.")
        self.assertIn('"ride the trend"', th["campaign"]["t"])
        gambler = [v for t in room["nine"]["triads"] for v in t["voices"]
                   if v["key"] == "gambler"][0]
        self.assertEqual(gambler["latest"]["symbol"], "RULED")
        self.assertNotIn(B.NO_SITTING_7, _text(th))
        # the list is still the newest twenty, the older offered
        cards = B.build_sittings(self.user)
        self.assertEqual(len(cards["cards"]), B.SITTINGS_MAX)
        self.assertTrue(cards["more"])
        self.assertNotIn("RULED", [c["symbol"] for c in cards["cards"]])

    # finding 3: a weight at or under 1.00 is no one's
    def test_who_has_been_right_needs_a_weight_above_one(self):
        from dashboard import council_band as B
        _report("trending")
        weak = _matrix({"executioner": {"trending": {"factor": 0.8, "n": 40,
                                                     "lane": "measured"}},
                        "champion": {"trending": {"factor": 1.0, "n": 30,
                                                  "lane": "measured"}}})
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(matrix=weak)):
            right = B.build_room(self.user)["direction"]["right"]
        self.assertEqual(right, {"t": "No one: the 2 measured voices in trending "
                                      "weigh ×1.00 or less (live, 180 days).",
                                 "voice": None})
        cache.clear()
        one = _matrix({"executioner": {"trending": {"factor": 0.5, "n": 40,
                                                    "lane": "measured"}}})
        with mock.patch("ai_agents.council_grading.record_matrix",
                        return_value=_rm(matrix=one)):
            t = B.build_room(self.user)["direction"]["right"]["t"]
        self.assertEqual(t, "No one: the one measured voice in trending weighs "
                            "×1.00 or less (live, 180 days).")

    # findings 4 and 19: the real-money book's limits, as the gates read them
    def _war(self, user, daily, openr, elite=1):
        from dashboard import council_band as B
        with mock.patch("portfolio.risk_gate.daily_loss_state", return_value=daily) as d, \
                mock.patch("portfolio.risk_gate.open_risk_state", return_value=openr) as o, \
                mock.patch("portfolio.risk_gate.elite_entries_since", return_value=elite) as e:
            war = B.build_room(user)["throne"]["war"]
        return war, d, o, e

    def test_the_war_lines_read_the_live_book(self):
        _report()
        daily = {"ok": True, "limit_pct": 8.0, "limit_money": -800.0,
                 "realized": -400.0, "book_value": 10000.0, "mode": "open",
                 "unmeasured": 0}
        openr = {"ok": True, "limit_pct": 15.0, "limit_money": 1500.0,
                 "open_risk": 300.0, "rows": 2, "unstopped": 1}
        war, d, o, e = self._war(self.user, daily, openr)
        self.assertEqual(war["lines"], [
            "Daily stop: OPEN · 50% of it used (the stop: 8% of the book)",
            "Open risk: 20% of the ceiling used (the ceiling: 15% of the book), "
            "at the stops of 2 positions · 1 without a stop, counted whole",
            "Elite entries: 1 of 2 in 24 h"])
        self.assertEqual(d.call_args.kwargs["venue"], "live")
        self.assertEqual(o.call_args.kwargs["venue"], "live")
        self.assertIs(e.call_args.kwargs["paper"], False)
        for leak in ("800", "400", "10000", "1500", "300"):
            self.assertNotIn(leak, _text(war), leak)

    def test_closes_without_a_price_are_said_beside_the_daily_stop(self):
        _report()
        daily = {"ok": True, "limit_pct": 8.0, "limit_money": -800.0,
                 "realized": -400.0, "book_value": 10000.0, "mode": "open",
                 "unmeasured": 2}
        openr = {"ok": True, "limit_pct": None, "limit_money": None}
        war, *_ = self._war(self.user, daily, openr)
        self.assertEqual(war["lines"][0], "Daily stop: OPEN · 50% of it used (the "
                                          "stop: 8% of the book) · 2 closes "
                                          "without a price, not counted")

    # finding 5: a priced break-even is measured
    def test_a_break_even_close_is_even_never_unpriced(self):
        from decimal import Decimal

        from bot_program.asset_models import AssetBotConfig, AssetBotTrade
        from dashboard import council_band as B
        _report()
        cfg = AssetBotConfig.objects.create(user=self.user, asset_class="forex",
                                            name="b", enabled=True, mode="live",
                                            symbols=["EURUSD"])
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("1.1"), status="CLOSED",
            paper=False, rule_name="r", metadata={"broker": "etoro"},
            realized_r=0.0)
        _session(trade=t)
        lines = B.build_room(self.user)["throne"]["battles"]["lines"]
        self.assertIn("Orders that left: 1 (won 0, lost 0, even 1, open 0) · net "
                      "+0.0R", lines)
        self.assertNotIn("unpriced", _text(lines))

    # finding 6: the master switch, said as itself
    def test_the_master_switch_off_is_said_in_every_dossier(self):
        from dashboard import council_band as B
        for key, on in (("platform_master", False), ("council_bots", True),
                        ("council_ticket", True), ("trade_debate", True)):
            _switch(key, on)
        for v in ("gambler", "executioner", "champion"):
            self.assertEqual(B.build_voice(self.user, v)["status"],
                             B.STATUS_MASTER, v)

    # finding 7: a late chair ruled
    def test_a_late_emperor_ruled_late_at_the_last_sitting(self):
        from dashboard import council_band as B
        _report()
        s = _session(hand={"voice": "champion", "side": "for"})
        _speak(s, "champion", {"verdict": "back", "conviction": 0.8})
        _speak(s, "emperor", {"verdict": "refuse", "p_work": 0.3,
                              "hand": "champion", "hand_overruled": True,
                              "hand_why": "too late"}, status="late")
        last = B.build_room(self.user)["throne"]["hand"]["last"]
        self.assertEqual(last[1:], ["The Champion held the Hand, for the trade.",
                                    "The Emperor ruled late, after the sitting "
                                    "closed: against it, not counted as an "
                                    "overruling."])
        self.assertNotIn("did not rule", _text(last))
        t = _session(symbol="LATE2", hand={"voice": "champion", "side": "for"})
        _speak(t, "emperor", {"verdict": "fight", "p_work": 0.6}, status="late")
        cache.clear()
        last = B.build_room(self.user)["throne"]["hand"]["last"]
        self.assertTrue(last[0].startswith("LATE2 BUY, "), last)
        self.assertEqual(last[-1], "The Emperor ruled late, after the sitting "
                                   "closed.")

    # finding 9: the weights a silent chair never read
    def test_weights_stored_for_a_chair_that_never_ran_are_not_his(self):
        from dashboard import council_band as B
        _report()
        w = {"emperor": {"factor": 1.0, "lane": "neutral", "n": 0,
                         "reason": "neutral"},
             "champion": {"factor": 1.18, "lane": "measured", "n": 34,
                          "reason": "measured in trending on forex, 34 graded "
                                    "calls, Brier 0.18 against 0.24 for always "
                                    "saying the base rate"}}
        s = _session(weights=w, status="partial",
                     why="AI budget: deep-tier reserve reached")
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
        _speak(s, "emperor", status="silent", why="AI budget: deep-tier reserve reached")
        nine = B.build_room(self.user)["nine"]
        champ = [v for t in nine["triads"] for v in t["voices"]
                 if v["key"] == "champion"][0]
        self.assertEqual(nine["weights_note"], "")
        self.assertEqual(champ["weight"]["t"], B.NO_WEIGHT_READ)
        self.assertEqual(B.build_voice(self.user, "champion")["weights"],
                         [B.NO_WEIGHT_READ])
        late = _session(symbol="LATECHAIR", weights=w)
        _speak(late, "emperor", {"verdict": "fight", "p_work": 0.6}, status="late")
        cache.clear()
        self.assertTrue(B.build_room(self.user)["nine"]["weights_note"]
                        .startswith("Weights as the Emperor read them at the "))

    # finding 10: a voice's last call says its day
    def test_the_nines_last_call_says_its_day(self):
        from dashboard import council_band as B
        _report()
        old_at = timezone.now() - timedelta(days=3)
        s = _session(symbol="OLDCALL", created_at=old_at)
        _speak(s, "gambler", {"verdict": "press", "p_work": 0.6})
        gambler = [v for t in B.build_room(self.user)["nine"]["triads"]
                   for v in t["voices"] if v["key"] == "gambler"][0]
        day = f"{old_at.astimezone(dt_utc()):%Y-%m-%d %H:%M} UTC"
        self.assertEqual(gambler["latest"]["when"], day)
        # a silence at that sitting says its time too
        _speak(s, "fixer", status="silent", why="timeout")
        cache.clear()
        fixer = [v for t in B.build_room(self.user)["nine"]["triads"]
                 for v in t["voices"] if v["key"] == "fixer"][0]
        self.assertEqual(fixer["latest"]["words"],
                         f"Silent at the last sitting ({day}): no answer in time.")
        js = _strip_js(JS.read_text(encoding="utf-8"))
        self.assertIn("latest.when].filter(Boolean)", js)

    # finding 11: who wears a persona, by book
    def test_a_personas_wearers_are_named_by_book(self):
        from bot_program.asset_models import AssetBotConfig
        from dashboard import council_band as B
        _report()
        for mode, on in (("live", True), ("live", False), ("paper", True)):
            AssetBotConfig.objects.create(user=self.user, asset_class="forex",
                                          name=f"{mode}{on}", enabled=on, mode=mode,
                                          symbols=["EURUSD"],
                                          extras={"persona": "swing"})
        cards = {c["key"]: c for c in B.build_room(self.user)["traders"]["cards"]}
        self.assertEqual(cards["swing"]["worn_t"],
                         "worn by 2 live configs (1 on) and 1 paper")
        self.assertEqual(cards["scalp"]["worn_t"], "worn by no config")
        self.assertEqual(B.worn_words(0, 0, 3), "worn by 3 paper configs")
        self.assertEqual(B.worn_words(1, 0, 0), "worn by 1 live config (off)")
        self.assertEqual(B.worn_words(1, 1, 2), "worn by 1 live config (on) and 2 paper")
        self.assertEqual(B.worn_words(2, 2, 0), "worn by 2 live configs (all on)")

    # finding 21: a rehearsal debate reaches no dossier, no weight, no battle
    def test_a_rehearsal_debate_reaches_no_dossier(self):
        _report()
        demo = _session(venue="demo", symbol="DEMOSYM", weights={
            "emperor": {"factor": 1.0, "lane": "neutral", "n": 0, "reason": "neutral"},
            "champion": {"factor": 9.99, "lane": "measured", "n": 99,
                         "reason": "DEMO_REASON"}})
        _speak(demo, "champion", {"verdict": "back", "conviction": 0.7}, weight_seen=9.99)
        _speak(demo, "emperor", {"verdict": "fight", "p_work": 0.6})
        _speak(demo, "skeptic", {"verdict": "shaky", "conviction": 0.6,
                                 "target": "champion", "claim": "x", "flaw": "noise"})
        _graded(demo, "champion", "work", "right", r=1.0)
        _graded(demo, "emperor", "battle", "right", r=1.0, value_r=0.5)
        _graded(demo, "skeptic", "attack", "right")
        out = _everything(self.user)
        text = _text(out)
        for leak in ("DEMOSYM", "9.99", "DEMO_REASON"):
            self.assertNotIn(leak, text, leak)
        self.assertNotIn("+0.50R", " ".join(out["room"]["throne"]["battles"]["lines"]))


@override_settings(CACHES=LOCMEM)
class TheFinalCacheTests(_Case):
    """What the script relies on in the answers and the cache."""

    def setUp(self):
        super().setUp()
        self.user = _user("cb_cache", staff=True)

    # finding 22: one staff member never reads another's book
    def test_the_viewers_book_is_never_another_staffs(self):
        from dashboard import council_band as B
        other = _user("cb_cache_b", staff=True)
        _report()
        moods = {self.user.pk: _mood("afraid"), other.pk: _mood("steady")}
        used = {self.user.pk: -400.0, other.pk: -80.0}

        def daily(u, **k):
            return {"limit_pct": 8.0, "limit_money": -800.0, "realized": used[u.pk],
                    "book_value": 10000.0, "mode": "open", "unmeasured": 0}

        with mock.patch("ai_agents.council_mood.people_mood",
                        side_effect=lambda u, *x, **k: moods[u.pk]), \
                mock.patch("portfolio.risk_gate.daily_loss_state", side_effect=daily):
            a = B.build_room(self.user)["throne"]
            b = B.build_room(other)["throne"]
        self.assertEqual((a["mood"]["level"], b["mood"]["level"]), ("afraid", "steady"))
        self.assertIn("50% of it used", a["war"]["lines"][0])
        self.assertIn("10% of it used", b["war"]["lines"][0])

    # finding 24: rev, more, the event debounce, a failure never kept
    def test_a_panels_rev_follows_its_data(self):
        from dashboard import council_band as B
        _report()
        r1 = B.build_room(self.user)["throne"]["rev"]
        self.assertEqual(B.build_room(self.user)["throne"]["rev"], r1)
        cache.clear()
        with mock.patch("ai_agents.council_mood.people_mood",
                        return_value=_mood("afraid")):
            self.assertNotEqual(B.build_room(self.user)["throne"]["rev"], r1)

    def test_twenty_sittings_offer_older_and_the_list_has_a_rev(self):
        from dashboard import council_band as B
        for i in range(B.SITTINGS_MAX):
            _session(symbol=f"S{i}")
        first = B.build_sittings(self.user)
        self.assertTrue(first["more"])
        self.assertEqual(first["rev"], B.build_sittings(self.user)["rev"])
        _session(symbol="NEWEST")
        cache.clear()
        self.assertNotEqual(B.build_sittings(self.user)["rev"], first["rev"])

    def test_a_burst_of_events_is_one_read(self):
        from dashboard import council_band as B
        _report()
        _speak(_session(), "emperor", {"verdict": "fight", "p_work": 0.6})
        B.build_room(self.user)
        with self.assertNumQueries(0):
            B.build_room(self.user, ev="fill_close")

    def test_a_failed_panel_is_read_again_next_time(self):
        from dashboard import council_band as B
        _report()
        with mock.patch("ai_agents.council_grading.record_matrix",
                        side_effect=RuntimeError("x")):
            self.assertEqual(B.build_record(self.user), {"error": B.SENTENCE["record"]})
        self.assertNotIn("error", B.build_record(self.user))

    # finding 13: an open dossier asked again costs nothing when unchanged
    def test_a_dossier_is_kept_with_its_rev_and_never_kept_failed(self):
        from dashboard import council_band as B
        _report()
        s = _session()
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
        first = B.build_voice(self.user, "champion")
        self.assertTrue(first["rev"])
        with self.assertNumQueries(0):
            again = B.build_voice(self.user, "champion")
        self.assertEqual(again["rev"], first["rev"])
        cache.clear()
        with mock.patch("ai_agents.council_grading.record_matrix",
                        side_effect=RuntimeError("x")):
            failed = B.build_voice(self.user, "champion")
        self.assertEqual(failed["table"], B.DASH)
        self.assertNotEqual(B.build_voice(self.user, "champion")["table"], B.DASH)


@override_settings(CACHES=LOCMEM)
class TheFinalEventTests(_Case):

    # finding 25: the event carries the chair's SPOKEN verdict only
    def test_the_event_carries_the_chairs_spoken_verdict_only(self):
        from ai_agents import tasks
        user = _user("cb_ev", staff=True)
        s = _session(user=user)
        _speak(s, "champion", {"verdict": "back", "conviction": 0.7})
        late = _speak(s, "emperor", {"verdict": "refuse", "p_work": 0.3},
                      status="late")
        with mock.patch("ai_agents.agents.council.run_sitting",
                        return_value={"status": "done", "session": s.id}), \
                mock.patch("dashboard.consumers.push_eye_event") as push:
            tasks.run_council_sitting(s.id)
        owner, kind, data = push.call_args[0]
        self.assertEqual((owner.pk, kind, data["verdict"], data["status"]),
                         (user.pk, "council_sitting", "", "done"))
        late.status = "spoke"
        late.save()
        with mock.patch("ai_agents.agents.council.run_sitting",
                        return_value={"status": "done", "session": s.id}), \
                mock.patch("dashboard.consumers.push_eye_event") as push:
            tasks.run_council_sitting(s.id)
        self.assertEqual(push.call_args[0][2]["verdict"], "refuse")
