"""His choice: Ambience Magic, Calm or Off (UI plan S1a, the magic kept,
2026-11-12).

The operator keeps Sauron's own theme inside the approved look, and chooses
how much of it shows:

  * MAGIC (the default): the embers, the light, the Eye's breath, the
    moments.
  * CALM: the still light only; nothing moves.
  * OFF: the approved look exactly.

The choice is saved with his profile's other display preferences
(TraderProfile.ambience), printed onto <body data-sv-ambience> by
{% get_ambience %}, and set from the user menu, beside the theme link:
three buttons that POST to /ambience/. The page changes ONLY when the
server answers 200 and echoes the value; on anything else the old value
stays and the menu says "Not saved". The embers, the breath, the void and
the light follow the attribute at once, with no reload.

DISPLAY ONLY. No engine, bot, Orc, alert, gate or ticket reads the choice:
the scan below walks every module of the project and allows the word in
four places only (the field, the tag, the view, the route). No order, size,
stop, switch or broker is reached; no network, no model. Every row here is
synthetic.

The node class runs static/js/sv-ambience.js as it ships with a stubbed
page; the measured class lays /positions/ out in a headless Chromium with
every network URL blocked and the save answered by a stub. Both skip, not
fail, where the machine has no node or no Chromium.

Run with:  python manage.py test tests.test_ambience_pref
"""
import ast
import json
import pathlib
import re
import subprocess
import tempfile
import unittest
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.shortcuts import resolve_url
from django.template import Context, Template
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from tests.test_close_advice import CHROME, NODE
from tests.test_magic_layer import (EMBER_COUNTER, POSITIONS, PROBES, _Browser, _book,
                                    _file_page, _luminance)
from tests.test_ui_s0_fixes import _get

ROOT = pathlib.Path(settings.BASE_DIR)
VALUES = ("magic", "calm", "off")
WORDS = {"magic": "Magic", "calm": "Calm", "off": "Off"}
BASE = "templates/base.html"
KIT_PAGE = "templates/dashboard/design_kit.html"
CONTROL = "static/js/sv-ambience.js"
#: A page under base.html that reads no book: the shell is what is read.
PAGE = "getting_started"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _user(name, **kw):
    return get_user_model().objects.create_user(name, password="x", **kw)


def _profile(user):
    from portfolio.trader_profile import get_or_create_profile
    return get_or_create_profile(user)


def _saved(user):
    from portfolio.trader_profile import TraderProfile
    return TraderProfile.objects.get(user=user).ambience


def _signed_in(name, ambience=None, **kw):
    user = _user(name, **kw)
    if ambience is not None:
        profile = _profile(user)
        profile.ambience = ambience
        profile.save(update_fields=["ambience"])
    client = Client()
    client.force_login(user)
    return user, client


# ══════════════════════════════════════════════════════════════════════════
# 1. The field: one column on the profile, "magic" for everyone on arrival
# ══════════════════════════════════════════════════════════════════════════

class AmbienceFieldTests(TestCase):

    def test_the_default_is_magic(self):
        profile = _profile(_user("amb_default"))
        self.assertEqual(profile.ambience, "magic")
        self.assertEqual(_saved(profile.user), "magic")

    def test_the_field_is_the_three_values_and_says_display_only(self):
        from portfolio.trader_profile import TraderProfile
        field = TraderProfile._meta.get_field("ambience")
        self.assertEqual(field.get_internal_type(), "CharField")
        self.assertEqual((field.max_length, field.default, field.null), (8, "magic", False))
        self.assertEqual(list(field.choices), [("magic", "Magic"), ("calm", "Calm"), ("off", "Off")])
        self.assertEqual(field.help_text, "Display only: embers, light and moments.")

    def test_one_migration_adds_the_column_and_nothing_else(self):
        """Its own migration, so the look can be reverted without it and
        the reverse: one AddField on the profile, after the rail's
        preferences; every row that exists takes "magic". Found by what it
        does, not by its number: a renumbering at a merge is no change."""
        from django.db import migrations
        from django.db.migrations.loader import MigrationLoader
        loader = MigrationLoader(None, ignore_no_migrations=True)
        adding = [(key, m) for key, m in sorted(loader.disk_migrations.items())
                  if any(getattr(op, "name", "") == "ambience" for op in m.operations)]
        self.assertEqual([key[0] for key, _m in adding], ["portfolio"])
        (_app, name), migration = adding[0]
        self.assertEqual(len(migration.operations), 1, name)
        op = migration.operations[0]
        self.assertIsInstance(op, migrations.AddField)
        self.assertEqual((op.model_name, op.name), ("traderprofile", "ambience"))
        self.assertEqual((op.field.default, op.field.max_length, op.field.null), ("magic", 8, False))
        self.assertEqual([app for app, _n in migration.dependencies], ["portfolio"])
        before = {n for _a, n in loader.graph.forwards_plan(("portfolio", name))}
        self.assertIn("0019_traderprofile_rail_prefs", before)

    def test_the_database_itself_answers_magic(self):
        """Review 2026-11-12: code that does not know the column (the old
        containers while the migrate step runs, or a rollback that keeps the
        migration) still creates a profile: the column keeps its default in
        the database, not in Python alone. Without it the column was NOT
        NULL with no default and such a create raised an IntegrityError."""
        from django.db import connection
        from portfolio.trader_profile import TraderProfile
        field = TraderProfile._meta.get_field("ambience")
        self.assertEqual(getattr(field.db_default, "value", field.db_default), "magic")
        with connection.cursor() as cursor:
            columns = {c.name: c for c in connection.introspection.get_table_description(
                cursor, TraderProfile._meta.db_table)}
        self.assertIn("magic", str(columns["ambience"].default))


# ══════════════════════════════════════════════════════════════════════════
# 2. The view: POST /ambience/ saves the one column and echoes it
# ══════════════════════════════════════════════════════════════════════════

class SetAmbienceViewTests(TestCase):

    def setUp(self):
        self.user, self.client = _signed_in("amb_view")
        self.url = reverse("set_ambience")

    def test_the_route(self):
        self.assertEqual(self.url, "/ambience/")

    def test_a_post_saves_the_value_and_echoes_it(self):
        for value in ("calm", "off", "magic"):
            with self.subTest(value=value):
                resp = self.client.post(self.url, {"ambience": value})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp["Content-Type"], "application/json")
                self.assertEqual(json.loads(resp.content), {"ambience": value})
                self.assertEqual(_saved(self.user), value)

    def test_a_first_post_makes_the_profile(self):
        from portfolio.trader_profile import TraderProfile
        self.assertFalse(TraderProfile.objects.filter(user=self.user).exists())
        self.assertEqual(self.client.post(self.url, {"ambience": "off"}).status_code, 200)
        profile = TraderProfile.objects.get(user=self.user)
        self.assertEqual((profile.ambience, profile.theme_mode), ("off", "dark"))

    def test_only_the_one_column_is_written(self):
        """save(update_fields=["ambience"]): a display choice never rewrites
        a limit, a PIN or a setting another request is saving."""
        from portfolio.trader_profile import TraderProfile
        _profile(self.user)
        writes = []
        real = TraderProfile.save

        def spy(profile, *args, **kw):
            writes.append((args, kw))
            return real(profile, *args, **kw)

        with mock.patch.object(TraderProfile, "save", spy):
            self.assertEqual(self.client.post(self.url, {"ambience": "calm"}).status_code, 200)
        self.assertEqual(writes, [((), {"update_fields": ["ambience"]})])
        # What another request saved meanwhile is still there afterwards.
        TraderProfile.objects.filter(user=self.user).update(theme_mode="light", max_usd_theme_exposure=7.5)
        self.client.post(self.url, {"ambience": "off"})
        profile = TraderProfile.objects.get(user=self.user)
        self.assertEqual((profile.ambience, profile.theme_mode, profile.max_usd_theme_exposure),
                         ("off", "light", 7.5))

    def test_a_get_is_refused(self):
        _profile(self.user)
        for url in (self.url, self.url + "?ambience=off"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 405)
            self.assertEqual(resp["Allow"], "POST")
        for method in (self.client.put, self.client.patch, self.client.delete):
            self.assertEqual(method(self.url, "ambience=off").status_code, 405)
        self.assertEqual(_saved(self.user), "magic")

    def test_a_bad_value_is_refused_and_nothing_is_saved(self):
        profile = _profile(self.user)
        profile.ambience = "calm"
        profile.save(update_fields=["ambience"])
        for bad in ("neon", "", "Calm", " calm", "calm ", "OFF", "magic,calm", "0", "true", "calm\x00"):
            with self.subTest(bad=bad):
                resp = self.client.post(self.url, {"ambience": bad})
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(json.loads(resp.content), {"error": "ambience must be magic, calm or off"})
                self.assertEqual(_saved(self.user), "calm")
        self.assertEqual(self.client.post(self.url).status_code, 400)                    # nothing sent
        self.assertEqual(self.client.post(self.url + "?ambience=off").status_code, 400)  # never the query string
        self.assertEqual(self.client.post(self.url, json.dumps({"ambience": "off"}),
                                          content_type="application/json").status_code, 400)
        self.assertEqual(_saved(self.user), "calm")

    def test_an_anonymous_user_is_sent_to_the_login(self):
        from portfolio.trader_profile import TraderProfile
        before = TraderProfile.objects.count()
        resp = Client().post(self.url, {"ambience": "off"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "%s?next=%s" % (resolve_url(settings.LOGIN_URL), self.url))
        self.assertEqual(TraderProfile.objects.count(), before)

    def test_csrf_is_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {"ambience": "off"}).status_code, 403)
        self.assertEqual(client.post(self.url, {"ambience": "off"}, HTTP_X_CSRFTOKEN="x" * 32).status_code, 403)
        self.assertEqual(_profile(self.user).ambience, "magic")
        client.get(reverse(PAGE))                      # the page sets the cookie the script reads
        token = client.cookies["csrftoken"].value
        resp = client.post(self.url, {"ambience": "off"}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_saved(self.user), "off")

    def test_the_view_is_not_exempt_from_csrf(self):
        from dashboard import views
        self.assertFalse(getattr(views.set_ambience, "csrf_exempt", False))

    def test_one_user_s_choice_is_his_own(self):
        other, other_client = _signed_in("amb_other", ambience="calm")
        self.client.post(self.url, {"ambience": "off"})
        self.assertEqual((_saved(self.user), _saved(other)), ("off", "calm"))
        other_client.post(self.url, {"ambience": "magic"})
        self.assertEqual((_saved(self.user), _saved(other)), ("off", "magic"))


# ══════════════════════════════════════════════════════════════════════════
# 3. The page: <body data-sv-ambience>, and the menu's three buttons
# ══════════════════════════════════════════════════════════════════════════

def _tag(request=None, twice=False):
    src = "{% load sauron_tags %}{% get_ambience %}" + ("|{% get_theme %}|{% get_ambience %}" if twice else "")
    return Template(src).render(Context({"request": request} if request is not None else {}))


def _request(user):
    request = RequestFactory().get("/")
    request.user = user
    return request


def _menu_control(page):
    """The Ambience control as the page carries it: from its own section's
    opening to the next section of the user menu."""
    menu = page.split('<div class="user-menu-dropdown" role="menu">', 1)[1]
    menu = menu.split('class="um-logout-form"', 1)[0]
    start = menu.index('<div class="um-section um-ambience"')
    return menu[start:menu.index('<div class="um-section">', start + 1)]


class GetAmbienceTagTests(TestCase):

    def test_each_saved_value_is_answered(self):
        user = _user("amb_tag")
        profile = _profile(user)
        for value in VALUES:
            profile.ambience = value
            profile.save(update_fields=["ambience"])
            fresh = get_user_model().objects.get(pk=user.pk)
            self.assertEqual(_tag(_request(fresh)), value)

    def test_magic_for_an_anonymous_user_and_with_no_request(self):
        self.assertEqual(_tag(_request(AnonymousUser())), "magic")
        self.assertEqual(_tag(), "magic")
        self.assertEqual(_tag(RequestFactory().get("/")), "magic")      # a request with no user on it

    def test_magic_for_a_user_with_no_profile_yet(self):
        from portfolio.trader_profile import TraderProfile
        user = _user("amb_noprofile")
        self.assertEqual(_tag(_request(user)), "magic")
        self.assertFalse(TraderProfile.objects.filter(user=user).exists())     # reading makes no row

    def test_magic_on_any_error(self):
        user = _user("amb_error")
        _profile(user)
        boom = mock.PropertyMock(side_effect=RuntimeError("the column is not there yet"))
        with mock.patch.object(get_user_model(), "trader_profile", boom, create=True):
            self.assertEqual(_tag(_request(user)), "magic")
        boom.assert_called()

    def test_a_value_that_is_not_one_of_the_three_is_never_printed(self):
        """The column takes any eight characters; the page takes three
        words. Anything else on the row reads as the default, so the sheets
        and the scripts never meet an Ambience they do not know."""
        from portfolio.trader_profile import TraderProfile
        user = _user("amb_junk")
        _profile(user)
        for junk in ("neon", "", "MAGIC", '"><b>'):
            TraderProfile.objects.filter(user=user).update(ambience=junk)
            fresh = get_user_model().objects.get(pk=user.pk)
            self.assertEqual(_tag(_request(fresh)), "magic", junk)

    def test_the_tag_reads_the_profile_the_theme_already_read(self):
        """One profile read a page, as before: the body tag asks for the
        theme, then the Ambience, and the menu asks again."""
        user = _user("amb_queries")
        profile = _profile(user)
        profile.ambience = "calm"
        profile.save(update_fields=["ambience"])
        fresh = get_user_model().objects.get(pk=user.pk)
        with self.assertNumQueries(1):
            self.assertEqual(_tag(_request(fresh), twice=True), "calm|dark|calm")


class BodyAndMenuTests(TestCase):

    def page(self, ambience=None, name="amb_page"):
        _user_, client = _signed_in("%s_%s" % (name, ambience or "new"), ambience=ambience)
        return _get(client, reverse(PAGE))

    def test_the_body_carries_each_value(self):
        for value in VALUES:
            with self.subTest(value=value):
                page = self.page(value)
                self.assertEqual(re.findall(r'<body class="[^"]*" data-sv-ambience="([^"]*)"', page), [value])

    def test_a_user_with_no_profile_gets_magic(self):
        page = self.page(None)
        self.assertEqual(re.findall(r'<body class="[^"]*" data-sv-ambience="([^"]*)"', page), ["magic"])
        self.assertEqual(re.findall(r'data-sv-ambience-set="(\w+)" aria-pressed="true"', page), ["magic"])

    def test_the_menu_presses_the_saved_value(self):
        for value in VALUES:
            with self.subTest(value=value):
                control = _menu_control(self.page(value))
                got = re.findall(r'<button type="button" class="sv-seg-btn" data-sv-ambience-set="(\w+)" '
                                 r'aria-pressed="(true|false)">(\w+)</button>', control)
                self.assertEqual(got, [(v, "true" if v == value else "false", WORDS[v]) for v in VALUES])
                self.assertEqual(control.count("<button"), 3)

    def test_the_control_says_ambience_and_explains_nothing(self):
        control = _menu_control(self.page("calm"))
        words = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"\{#.*?#\}", "", control)).split())
        self.assertEqual(words, "Ambience Magic Calm Off")
        self.assertIn('<span class="sv-label" id="umAmbienceLabel">Ambience</span>', control)
        self.assertIn('<div class="sv-seg" role="group" aria-labelledby="umAmbienceLabel">', control)
        # "Not saved" has its place, empty until a save fails, and is announced.
        self.assertIn('<span class="um-ambience-note" role="status"></span>', control)

    def test_the_control_posts_to_the_view_and_sits_in_no_form(self):
        control = _menu_control(self.page("off"))
        self.assertIn('id="umAmbience" data-sv-ambience-url="%s"' % reverse("set_ambience"), control)
        for never in ("<form", "<a ", "href=", "onclick", "hx-", "<input", 'type="submit"'):
            with self.subTest(never=never):
                self.assertNotIn(never, control)

    def test_it_sits_beside_the_theme_link(self):
        page = self.page("magic")
        menu = page.split('<div class="user-menu-dropdown" role="menu">', 1)[1]
        theme = menu.index('href="%s" role="menuitem"' % reverse("toggle_theme"))
        control = menu.index('id="umAmbience"')
        self.assertLess(theme, control)
        self.assertNotIn('class="um-link', menu[theme:control])        # nothing between the two
        self.assertLess(control, menu.index('href="%s"' % reverse("notifications_inbox")))
        self.assertEqual(page.count('id="umAmbience"'), 1)

    def test_the_control_s_script_loads_once_deferred(self):
        base = read(BASE)
        self.assertEqual(base.count("<script src=\"{% static 'js/sv-ambience.js' %}\" defer></script>"), 1)
        self.assertTrue((ROOT / CONTROL).is_file())

    def test_the_kit_s_preview_follows_the_page(self):
        """/design/kit/ keeps its own preview (it saves nothing); when the
        menu changes the page's Ambience, the preview's pressed button
        follows the attribute instead of saying the old one."""
        kit = read(KIT_PAGE)
        script = [m for m in re.findall(r"<script>(.*?)</script>", kit, flags=re.S) if "data-kit-ambience" in m]
        self.assertEqual(len(script), 1)
        self.assertIn("new MutationObserver(pressed).observe(document.body, "
                      "{ attributes: true, attributeFilter: ['data-sv-ambience'] })", script[0])
        self.assertNotIn("fetch(", script[0])
        self.assertNotIn("sv-ambience-set", kit)          # the kit's buttons are not the menu's


# ══════════════════════════════════════════════════════════════════════════
# 4. Display only: no module that decides reads it
# ══════════════════════════════════════════════════════════════════════════

#: Where the word may stand in Python: the field, the tag, the view, the
#: route. Everything else in the project is scanned and must not name it:
#: the engines and the bots (bot_program), the Orcs (bot_program/orcs), the
#: brain and the agents, the signals and the strategies, the alerts, the
#: gates and the sizing (portfolio), the tickets and the closes
#: (bot_program/manual_trade.py, dashboard/).
FIELD_FILE = "portfolio/trader_profile.py"
TAG_FILE = "core/templatetags/sauron_tags.py"
VIEW_FILE = "dashboard/views.py"
URLS_FILE = "dashboard/urls.py"
ALLOWED = {FIELD_FILE, TAG_FILE, VIEW_FILE, URLS_FILE}
#: Modules the scan must have walked, one or more of each kind named above.
DECIDERS = (
    "bot_program/asset_engine/base.py", "bot_program/engine/risk.py", "bot_program/engine/kill_switch.py",
    "bot_program/tasks.py", "bot_program/orchestrator.py", "bot_program/morgul.py",
    "bot_program/orcs/mind.py", "bot_program/orcs/intents.py", "bot_program/orcs/switches.py",
    "brain/close_advice.py", "ai_agents/tasks.py", "signals/engine.py", "signals/bot_bridge.py",
    "strategies/risk_manager.py", "alerts/dispatch.py", "alerts/notify.py",
    "portfolio/risk_gate.py", "portfolio/risk_engine.py", "portfolio/position_sizing.py", "portfolio/tasks.py",
    "bot_program/manual_trade.py", "bot_program/manual_close.py", "dashboard/ticket_outcome.py",
    "dashboard/views_command.py", "core/switch_pin.py", "core/idle_lock.py", "core/context_processors.py",
)
WORD = re.compile(r"ambience", re.I)


def _project_modules():
    """Every Python module of the project: each package at the root (the
    apps, core, config) and the root's own scripts; never the tests, a
    migration, a cache or another checkout under the root."""
    out = []
    for top in sorted(ROOT.iterdir()):
        if top.is_file() and top.suffix == ".py":
            out.append(top)
        elif top.is_dir() and (top / "__init__.py").is_file() and top.name != "tests":
            out.extend(p for p in sorted(top.rglob("*.py"))
                       if "migrations" not in p.parts and "__pycache__" not in p.parts)
    return out


def _mentions(tree):
    """[(line, what)] for every identifier, keyword, import or string of
    the tree that names the Ambience: profile.ambience, getattr(p,
    "ambience"), values("ambience"), filter(ambience=…), a docstring."""
    out = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.alias):
            names += [node.name, node.asname or ""]
        elif isinstance(node, ast.keyword):
            names.append(node.arg or "")
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            value = node.value
            names.append(value.decode("utf-8", "replace") if isinstance(value, bytes) else value)
        for name in names:
            if WORD.search(name):
                out.append((getattr(node, "lineno", 0), name[:40]))
    return sorted(set(out))


def _span(node):
    return range(node.lineno, node.end_lineno + 1)


def _allowed_lines(rel, tree):
    """The lines of an allowed file where the word may stand."""
    lines = set()
    if rel in (VIEW_FILE, TAG_FILE):
        wanted = "set_ambience" if rel == VIEW_FILE else "get_ambience"
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == wanted:
                lines.update(_span(node))
    elif rel == FIELD_FILE:
        for cls in tree.body:
            if isinstance(cls, ast.ClassDef) and cls.name == "TraderProfile":
                for node in cls.body:
                    if isinstance(node, ast.Assign) and all(
                            isinstance(t, ast.Name) and t.id in ("ambience", "AMBIENCE_CHOICES")
                            for t in node.targets):
                        lines.update(_span(node))
    elif rel == URLS_FILE:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "path" and node.args
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value == "ambience/"):
                lines.update(_span(node))
    return lines


class NoDecisionReadsAmbienceTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.files = {p.relative_to(ROOT).as_posix(): p for p in _project_modules()}

    def test_the_scan_walks_the_modules_that_decide(self):
        self.assertGreater(len(self.files), 400, "the scan found the project's modules")
        for rel in DECIDERS + tuple(ALLOWED):
            with self.subTest(module=rel):
                self.assertIn(rel, self.files)
        self.assertFalse([rel for rel in self.files if rel.startswith(("tests/", "venv/", ".claude/"))])
        self.assertFalse([rel for rel in self.files if "/migrations/" in rel])

    def test_no_module_names_the_ambience_but_the_field_the_tag_the_view_and_the_route(self):
        naming = {}
        for rel, path in self.files.items():
            src = path.read_text(encoding="utf-8")
            if not WORD.search(src):
                continue
            # The word in a comment is caught here too: nothing says it but these four.
            naming[rel] = _mentions(ast.parse(src))
        self.assertEqual(set(naming), ALLOWED, sorted(set(naming) ^ ALLOWED))

    def test_inside_those_four_only_the_field_the_tag_the_view_and_the_route_name_it(self):
        """dashboard/views.py holds other views, and the profile other
        fields and methods: the word stands in set_ambience, in
        get_ambience, in the field's two assignments and in the one route,
        and nowhere else in those files."""
        for rel in sorted(ALLOWED):
            src = self.files[rel].read_text(encoding="utf-8")
            tree = ast.parse(src)
            allowed = _allowed_lines(rel, tree)
            self.assertTrue(allowed, rel)
            stray = [(line, what) for line, what in _mentions(tree) if line not in allowed]
            self.assertFalse(stray, "%s names it outside its place: %s" % (rel, stray))
            # A comment outside those lines would be a module talking about it too.
            for n, text in enumerate(src.splitlines(), 1):
                if WORD.search(text) and n not in allowed:
                    self.assertTrue(self._beside(n, allowed), "%s:%d %s" % (rel, n, text.strip()))

    @staticmethod
    def _beside(line, allowed):
        """A comment or a decorator directly above the allowed lines (the
        field's own comment, the view's decorators)."""
        return any(line + k in allowed for k in range(1, 16))

    def test_a_module_reading_it_is_caught(self):
        for src in (
                "def size(profile, risk):\n    return risk * (2 if profile.ambience == 'magic' else 1)\n",
                "def gate(user):\n    return getattr(user.trader_profile, 'ambience', 'magic') != 'off'\n",
                "rows = TraderProfile.objects.filter(ambience='calm')\n",
                "rows = TraderProfile.objects.values_list('ambience', flat=True)\n",
                "from portfolio.trader_profile import AMBIENCE_CHOICES\n",
                "from core.templatetags.sauron_tags import get_ambience as mood\n",
                "def alert(ambience=None):\n    return ambience\n",
                "MODE = {'Ambience': 1}\n"):
            with self.subTest(src=src):
                self.assertTrue(_mentions(ast.parse(src)), src)
        self.assertFalse(_mentions(ast.parse("def size(profile):\n    return profile.theme_mode\n")))

    def test_the_view_writes_one_field_and_reaches_nothing_else(self):
        """set_ambience imports the profile and JsonResponse, and calls no
        engine, broker, task or notifier."""
        tree = ast.parse(self.files[VIEW_FILE].read_text(encoding="utf-8"))
        view = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "set_ambience")
        imported = sorted(a.name for n in ast.walk(view) if isinstance(n, ast.ImportFrom) for a in n.names)
        modules = sorted({n.module for n in ast.walk(view) if isinstance(n, ast.ImportFrom)})
        self.assertEqual(modules, ["django.http", "portfolio.trader_profile"])
        self.assertEqual(imported, ["JsonResponse", "TraderProfile"])
        decorators = [ast.unparse(d) for d in view.decorator_list]
        self.assertEqual(decorators, ["require_POST", "csrf_protect", "login_required"])

    def test_no_script_reads_it_but_the_embers_the_moments_and_the_control(self):
        """In the browser too: the ticket's, the rail's and the close
        path's scripts never ask what the Ambience is."""
        naming = sorted(p.name for p in (ROOT / "static" / "js").glob("*.js")
                        if WORD.search(p.read_text(encoding="utf-8")))
        self.assertEqual(naming, ["sv-ambience.js", "sv-embers.js", "sv-moments.js"])

    def test_no_template_reads_it_but_the_shell_and_the_kit(self):
        """A page may say in a comment that it shows embers under Magic;
        what reaches the template engine or the browser names the Ambience
        in the shell (the body's attribute, the menu's control) and on the
        kit's page only."""
        def live(markup):
            markup = re.sub(r"\{#.*?#\}", "", markup)
            return re.sub(r"\{%\s*comment\b.*?%\}.*?\{%\s*endcomment\s*%\}", "", markup, flags=re.S)
        naming = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "templates").rglob("*.html")
                        if WORD.search(live(p.read_text(encoding="utf-8"))))
        self.assertEqual(naming, [BASE, KIT_PAGE])
        # base.html carries the ticket's and the close path's inline scripts:
        # none of them names it.
        inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", read(BASE), flags=re.S)
        self.assertGreater(len(inline), 10)
        self.assertFalse([s[:60] for s in inline if WORD.search(s)])


# ══════════════════════════════════════════════════════════════════════════
# 5. The control's script, with a stubbed page (node)
# ══════════════════════════════════════════════════════════════════════════

CONTROL_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const turn = () => new Promise(r => setImmediate(r));

function element(attrs) {
  const el = { attrs: Object.assign({}, attrs), listeners: {}, textContent: '', writes: [] };
  el.getAttribute = k => (k in el.attrs ? el.attrs[k] : null);
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); el.writes.push(k + '=' + v); };
  el.hasAttribute = k => k in el.attrs;
  el.removeAttribute = k => { delete el.attrs[k]; };
  el.addEventListener = (t, f) => { (el.listeners[t] = el.listeners[t] || []).push(f); };
  return el;
}
function watched(target, reads) {
  return new Proxy(target, { get: (t, k) => { if (typeof k === 'string') reads.add(k); return t[k]; },
                             set: (t, k, v) => { reads.add('SET ' + String(k)); t[k] = v; return true; } });
}

function world(opts) {
  opts = Object.assign({ ambience: 'magic', cookie: 'theme=1; csrftoken=tok123; other=2', host: true, abort: true }, opts || {});
  const body = element({ 'data-sv-ambience': opts.ambience });
  const host = element({ id: 'umAmbience', 'data-sv-ambience-url': '/ambience/' });
  const note = element({});
  const buttons = ['magic', 'calm', 'off'].map(v => {
    const b = element({ 'data-sv-ambience-set': v, 'aria-pressed': v === opts.ambience ? 'true' : 'false' });
    b.closest = sel => (sel === '[data-sv-ambience-set]' ? b : null);
    return b;
  });
  const label = element({}); label.closest = () => null;
  host.querySelector = sel => (sel === '.um-ambience-note' ? note : null);
  host.querySelectorAll = sel => (sel === '[data-sv-ambience-set]' ? buttons : []);
  host.contains = el => buttons.indexOf(el) >= 0 || el === note || el === label;
  const calls = [], pending = [], timers = [], winReads = new Set(), docReads = new Set(), aborted = [];
  const win = watched({
    fetch: (url, o) => {
      calls.push({ url, method: o.method, body: o.body, headers: o.headers, credentials: o.credentials });
      return new Promise((resolve, reject) => {
        pending.push({ resolve, reject });
        if (o.signal) o.signal.addEventListener('abort', () => { aborted.push(url); reject(new Error('aborted')); });
      });
    },
    setTimeout: (f, ms) => { timers.push({ f, ms }); return timers.length; },
    clearTimeout: id => { if (timers[id - 1]) timers[id - 1].f = null; },
    AbortController: opts.abort ? AbortController : undefined,
  }, winReads);
  const doc = watched({ body, cookie: opts.cookie,
                        getElementById: id => (opts.host && id === 'umAmbience' ? host : null) }, docReads);
  vm.runInNewContext(src, { window: win, document: doc });
  const api = {
    calls, timers, aborted,
    click: async v => { (host.listeners.click || []).forEach(f => f({ target: buttons[['magic', 'calm', 'off'].indexOf(v)] })); await turn(); },
    clickLabel: async () => { (host.listeners.click || []).forEach(f => f({ target: label })); await turn(); },
    answer: async (status, payload) => {
      const p = pending.shift();
      p.resolve({ status, ok: status >= 200 && status < 300,
                  json: () => (payload === 'html' ? Promise.reject(new SyntaxError('Unexpected token <')) : Promise.resolve(payload)) });
      await turn(); await turn();
    },
    lose: async () => { pending.shift().reject(new TypeError('Failed to fetch')); await turn(); await turn(); },
    late: async (status, payload) => { await api.answer(status, payload); },
    timeout: async () => { timers.forEach(t => { if (t.f) { const f = t.f; t.f = null; f(); } }); await turn(); await turn(); },
    state: () => ({ attr: body.attrs['data-sv-ambience'], pressed: buttons.filter(b => b.attrs['aria-pressed'] === 'true').map(b => b.attrs['data-sv-ambience-set']),
                    note: note.textContent, busy: host.attrs['aria-busy'] || null, calls: calls.length }),
    bodyWrites: () => body.writes.slice(),
    reads: () => ({ win: Array.from(winReads).sort(), doc: Array.from(docReads).sort() }),
    listening: () => Object.keys(host.listeners),
  };
  return api;
}

(async () => {
  const out = {};
  // 1. a 200 that echoes the value: the page changes, after the answer only
  { const w = world(); await w.click('calm');
    out.waiting = w.state(); out.request = w.calls[0]; out.timer = w.timers.map(t => t.ms);
    await w.answer(200, { ambience: 'calm' });
    out.saved = w.state(); out.savedWrites = w.bodyWrites(); out.timerCleared = w.timers.every(t => t.f === null); }
  // 2. a 500, a refusal, the lock's 423: nothing changes, "Not saved"
  for (const status of [500, 400, 403, 423, 302, 204]) {
    const w = world({ ambience: 'calm' }); await w.click('off'); await w.answer(status, { ambience: 'off' });
    out['status' + status] = [w.state(), w.bodyWrites().length]; }
  // 3. no network
  { const w = world(); await w.click('off'); await w.lose(); out.lost = [w.state(), w.bodyWrites().length]; }
  // 4. a 200 that does not echo the value: another value, the login page, nothing
  { const w = world(); await w.click('off'); await w.answer(200, { ambience: 'calm' }); out.otherValue = w.state(); }
  { const w = world(); await w.click('off'); await w.answer(200, 'html'); out.loginPage = w.state(); }
  { const w = world(); await w.click('off'); await w.answer(200, {}); out.emptyAnswer = w.state(); }
  { const w = world(); await w.click('off'); await w.answer(200, null); out.nullAnswer = w.state(); }
  { const w = world(); await w.click('off'); await w.answer(200, { ok: true, ambience: ['off'] }); out.listAnswer = w.state(); }
  // 5. a save that works after one that failed takes the words away
  { const w = world(); await w.click('calm'); await w.answer(500, {}); out.failedFirst = w.state();
    await w.click('calm'); await w.answer(200, { ambience: 'calm' }); out.thenSaved = w.state(); }
  // 6. one request at a time; the control answers again afterwards
  { const w = world(); await w.click('calm'); await w.click('off'); await w.click('calm'); out.oneAtATime = w.state().calls;
    await w.answer(200, { ambience: 'calm' }); await w.click('off'); out.thenAgain = [w.state().calls, w.calls[1].body];
    await w.answer(200, { ambience: 'off' }); out.thenOff = w.state(); }
  // 7. the pressed value is posted too: this tab may be behind another one
  { const w = world(); await w.click('magic'); out.samePosted = w.state().calls; await w.answer(200, { ambience: 'magic' }); out.sameSaved = w.state(); }
  // 8. no answer in ten seconds: "Not saved", the request dropped, a late answer ignored
  { const w = world(); await w.click('calm'); await w.timeout(); out.timedOut = [w.state(), w.aborted.length];
    await w.click('off'); out.afterTimeout = w.state().calls; }
  { const w = world({ abort: false }); await w.click('calm'); await w.timeout(); out.timedOutPlain = w.state();
    await w.late(200, { ambience: 'calm' }); out.lateAnswer = [w.state(), w.bodyWrites().length]; }
  // 9. a click on the label or the words is no request
  { const w = world(); await w.clickLabel(); out.label = w.state(); }
  // 10. a page with no menu (the login page): nothing, and no error
  { const w = world({ host: false }); out.noHost = w.reads(); }
  // 11. what it touches: fetch and its own timer, the cookie, the body and its host
  { const w = world(); await w.click('calm'); await w.answer(200, { ambience: 'calm' }); out.reads = w.reads(); out.listening = w.listening(); }
  // 12. the token is the session's own, whatever else the cookie holds
  { const w = world({ cookie: 'xcsrftoken=wrong; a=b; csrftoken=right77' }); await w.click('calm'); out.token = w.calls[0].headers['X-CSRFToken']; }
  { const w = world({ cookie: '' }); await w.click('calm'); out.noToken = w.calls[0].headers['X-CSRFToken']; }
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""


@unittest.skipUnless(NODE, "node is not on this machine")
class AmbienceControlNodeTests(SimpleTestCase):
    """static/js/sv-ambience.js as it ships, with a stubbed page. Only a
    200 answer that echoes the value changes <body data-sv-ambience> and
    the pressed button; a 500, a refusal, no network, no answer or the
    login page leave both as they were and the menu says "Not saved"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with tempfile.TemporaryDirectory() as tmp:
            harness = pathlib.Path(tmp) / "harness.js"
            harness.write_text(CONTROL_HARNESS, encoding="utf-8")
            done = subprocess.run([NODE, str(harness), str(ROOT / CONTROL)], capture_output=True,
                                  text=True, timeout=60)
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.got = json.loads(done.stdout)

    def state(self, attr, pressed, note, calls, busy=None):
        return {"attr": attr, "pressed": [pressed], "note": note, "busy": busy, "calls": calls}

    def test_nothing_changes_before_the_server_answers(self):
        self.assertEqual(self.got["waiting"], self.state("magic", "magic", "", 1, busy="true"))

    def test_the_request_is_a_post_of_the_value_with_the_session_s_token(self):
        self.assertEqual(self.got["request"], {
            "url": "/ambience/", "method": "POST", "body": "ambience=calm", "credentials": "same-origin",
            "headers": {"Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": "tok123",
                        "X-Requested-With": "XMLHttpRequest"}})
        self.assertEqual((self.got["token"], self.got["noToken"]), ("right77", ""))

    def test_a_200_that_echoes_the_value_changes_the_page(self):
        self.assertEqual(self.got["saved"], self.state("calm", "calm", "", 1))
        self.assertEqual(self.got["savedWrites"], ["data-sv-ambience=calm"])      # one write, the answer's
        self.assertEqual(self.got["sameSaved"], self.state("magic", "magic", "", 1))
        self.assertEqual(self.got["samePosted"], 1)

    def test_a_500_or_a_refusal_leaves_the_page_and_says_not_saved(self):
        for status in (500, 400, 403, 423, 302, 204):
            with self.subTest(status=status):
                state, writes = self.got["status%d" % status]
                self.assertEqual(state, self.state("calm", "calm", "Not saved", 1))
                self.assertEqual(writes, 0)

    def test_a_network_failure_leaves_the_page_and_says_not_saved(self):
        state, writes = self.got["lost"]
        self.assertEqual(state, self.state("magic", "magic", "Not saved", 1))
        self.assertEqual(writes, 0)

    def test_a_200_that_does_not_echo_the_value_is_a_failure(self):
        for case in ("otherValue", "loginPage", "emptyAnswer", "nullAnswer", "listAnswer"):
            with self.subTest(case=case):
                self.assertEqual(self.got[case], self.state("magic", "magic", "Not saved", 1))

    def test_a_later_save_takes_the_words_away(self):
        self.assertEqual(self.got["failedFirst"], self.state("magic", "magic", "Not saved", 1))
        self.assertEqual(self.got["thenSaved"], self.state("calm", "calm", "", 2))

    def test_one_request_at_a_time(self):
        self.assertEqual(self.got["oneAtATime"], 1)
        self.assertEqual(self.got["thenAgain"], [2, "ambience=off"])
        self.assertEqual(self.got["thenOff"], self.state("off", "off", "", 2))

    def test_no_answer_in_ten_seconds_is_a_failure_and_frees_the_control(self):
        self.assertEqual(self.got["timer"], [10000])
        self.assertTrue(self.got["timerCleared"])
        state, aborted = self.got["timedOut"]
        self.assertEqual(state, self.state("magic", "magic", "Not saved", 1))
        self.assertEqual(aborted, 1)
        self.assertEqual(self.got["afterTimeout"], 2)
        self.assertEqual(self.got["timedOutPlain"], self.state("magic", "magic", "Not saved", 1))
        late, writes = self.got["lateAnswer"]
        self.assertEqual(late, self.state("magic", "magic", "Not saved", 1))
        self.assertEqual(writes, 0)

    def test_a_click_beside_the_buttons_asks_nothing(self):
        self.assertEqual(self.got["label"], self.state("magic", "magic", "", 0))

    def test_it_touches_the_cookie_the_body_and_its_own_buttons_only(self):
        """No storage, no event, no global, no other node: what the script
        asks of the window and the document is this and nothing else."""
        self.assertEqual(self.got["reads"], {"win": ["AbortController", "clearTimeout", "fetch", "setTimeout"],
                                             "doc": ["body", "cookie", "getElementById"]})
        self.assertEqual(self.got["listening"], ["click"])
        self.assertLessEqual(set(self.got["noHost"]["win"]), {"fetch"})
        src = read(CONTROL)
        for never in ("localStorage", "sessionStorage", "dispatchEvent", "CustomEvent", "location", "htmx",
                      "WebSocket", "new XMLHttpRequest", "innerHTML", "SV."):
            with self.subTest(never=never):
                self.assertNotIn(never, src)
        self.assertEqual(src.count("fetch("), 1)


# ══════════════════════════════════════════════════════════════════════════
# 6. Measured: the switch stops the embers at once, with no reload
# ══════════════════════════════════════════════════════════════════════════

#: The save, answered in the page: what the server would say (window
#: .__svAnswer: 200 echoes the value, 0 is no network), 20 ms later.
SAVE_STUB = r"""(function () {
  window.__svPosted = []; window.__svAnswer = 200; window.__svMark = 'kept';
  window.fetch = function (url, o) {
    o = o || {};
    var m = /^ambience=(.*)$/.exec(String(o.body || '')), status = window.__svAnswer;
    window.__svPosted.push({ url: String(url), method: o.method, body: o.body });
    return new Promise(function (resolve, reject) { setTimeout(function () {
      if (!status) { reject(new TypeError('Failed to fetch')); return; }
      resolve({ status: status, ok: status === 200, json: function () {
        return Promise.resolve(status === 200 ? { ambience: m ? decodeURIComponent(m[1]) : null } : { error: 'refused' }); } });
    }, 20); });
  };
})();"""

#: Click a value in the menu and watch the canvas: its state before, at the
#: moment <body data-sv-ambience> changes, one frame later and a second
#: later; or, where the attribute never changes, 1.2 s after the click.
SWITCH = r"""(function (value) {
  var s = window.__svEmberStats, canvas = document.getElementById('particles-canvas'), body = document.body;
  var host = document.getElementById('umAmbience');
  function now() { return { frames: s ? s.frames : -1, display: getComputedStyle(canvas).display, attr: body.getAttribute('data-sv-ambience') }; }
  var out = { before: now(), changed: false }, sent = window.__svPosted.length;
  return new Promise(function (resolve) {
    var done = false;
    function finish() {
      if (done) return;
      done = true; mo.disconnect();
      out.after = now();
      out.pressed = Array.prototype.filter.call(host.querySelectorAll('[data-sv-ambience-set]'), function (b) {
        return b.getAttribute('aria-pressed') === 'true'; }).map(function (b) { return b.getAttribute('data-sv-ambience-set'); });
      out.note = host.querySelector('.um-ambience-note').textContent;
      out.busy = host.getAttribute('aria-busy');
      out.posted = window.__svPosted.slice(sent);
      out.loads = performance.getEntriesByType('navigation').length;
      out.mark = window.__svMark;
      resolve(out);
    }
    var mo = new MutationObserver(function () {
      if (out.changed) return;
      out.changed = true; out.atSwitch = now();
      requestAnimationFrame(function () { out.oneFrame = now(); setTimeout(finish, 1000); });
    });
    mo.observe(body, { attributes: true, attributeFilter: ['data-sv-ambience'] });
    host.querySelector('[data-sv-ambience-set="' + value + '"]').click();
    setTimeout(function () { if (!out.changed) finish(); }, 1200);
  });
})"""

LOOK = r"""(function () {
  document.getElementById('userMenu').classList.add('open');
  var host = document.getElementById('umAmbience'), menu = document.querySelector('.user-menu-dropdown');
  function box(e) {
    var r = e.getBoundingClientRect(), c = getComputedStyle(e);
    return { x: r.left, right: r.right, w: r.width, h: r.height, size: parseFloat(c.fontSize), color: c.color,
             family: c.fontFamily.split(',')[0].replace(/["']/g, '').trim(), shadow: c.textShadow, text: (e.textContent || '').trim() };
  }
  return { menu: box(menu), ground: getComputedStyle(menu).backgroundColor, host: box(host),
           label: box(host.querySelector('.sv-label')), note: box(host.querySelector('.um-ambience-note')),
           buttons: Array.prototype.map.call(host.querySelectorAll('.sv-seg-btn'), box),
           overflow: host.scrollWidth - host.clientWidth };
})()"""


def _rgb(colour):
    m = re.match(r"rgba?\((\d+), (\d+), (\d+)", colour)
    return tuple(int(v) for v in m.groups())


def _contrast(fg, bg):
    a, b = _luminance(*_rgb(fg)), _luminance(*_rgb(bg))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class AmbienceSwitchMeasuredTests(TestCase):
    """/positions/ (it opted into the embers) as the server renders it for
    a user on Magic, with sv-embers.js and sv-ambience.js as they ship, at
    1440. A save the server refuses changes nothing and the embers keep
    drawing; the server's 200 for Calm stops the canvas within one frame
    and takes it off the page (display: none), with no reload; Off keeps it
    off; Magic brings it back, still with no reload."""

    @classmethod
    def setUpTestData(cls):
        page = _file_page(_get(_book("ambience_switch"), POSITIONS), scripts=("sv-embers.js", "sv-ambience.js"),
                          before=EMBER_COUNTER + SAVE_STUB)
        b = _Browser({POSITIONS: page}, "sv-ambience-")
        try:
            sid = b.tab()
            b.open(sid, POSITIONS, PROBES)
            b.js(sid, "(function () { return new Promise(function (r) { var n = 0, t = setInterval(function () {"
                      " if ((window.__svEmberStats && __svEmberStats.maps) || ++n > 100) { clearInterval(t); r(0); } }, 50); }); })()")
            cls.start = b.js(sid, "document.body.getAttribute('data-sv-ambience')")
            got = {}
            b.js(sid, "window.__svAnswer = 500; 0")
            got["refused"] = b.js(sid, SWITCH + "('calm')")
            cls.look = b.js(sid, LOOK)                       # "Not saved" is on the page now
            b.js(sid, "window.__svAnswer = 0; 0")
            got["lost"] = b.js(sid, SWITCH + "('off')")
            b.js(sid, "window.__svAnswer = 200; 0")
            for value in ("calm", "off", "magic"):
                got[value] = b.js(sid, SWITCH + "('%s')" % value)
            cls.got = got
        finally:
            b.close()

    def test_the_page_starts_on_magic_with_the_embers_drawing(self):
        self.assertEqual(self.start, "magic")
        first = self.got["refused"]["before"]
        self.assertEqual((first["attr"], first["display"]), ("magic", "block"))

    def test_a_refused_or_lost_save_changes_nothing_and_the_embers_keep_drawing(self):
        for case, asked in (("refused", "calm"), ("lost", "off")):
            with self.subTest(case=case):
                got = self.got[case]
                self.assertFalse(got["changed"])
                self.assertEqual((got["after"]["attr"], got["after"]["display"]), ("magic", "block"))
                self.assertGreater(got["after"]["frames"], got["before"]["frames"])
                self.assertEqual((got["pressed"], got["note"], got["busy"]), (["magic"], "Not saved", None))
                self.assertEqual(got["posted"], [{"url": "/ambience/", "method": "POST", "body": "ambience=" + asked}])

    def test_calm_stops_the_canvas_within_one_frame_and_takes_it_off_the_page(self):
        got = self.got["calm"]
        self.assertTrue(got["changed"])
        self.assertEqual((got["atSwitch"]["attr"], got["atSwitch"]["display"]), ("calm", "none"))
        self.assertLessEqual(got["oneFrame"]["frames"] - got["atSwitch"]["frames"], 1)
        self.assertEqual(got["after"]["frames"], got["oneFrame"]["frames"])      # and none in the second after
        self.assertEqual(got["after"]["display"], "none")
        self.assertEqual((got["pressed"], got["note"], got["busy"]), (["calm"], "", None))
        self.assertEqual(got["posted"], [{"url": "/ambience/", "method": "POST", "body": "ambience=calm"}])

    def test_off_keeps_it_off_and_magic_brings_it_back(self):
        off, magic = self.got["off"], self.got["magic"]
        self.assertEqual((off["atSwitch"]["attr"], off["after"]["display"]), ("off", "none"))
        self.assertEqual(off["after"]["frames"], off["before"]["frames"])
        self.assertEqual(off["pressed"], ["off"])
        self.assertEqual((magic["atSwitch"]["attr"], magic["atSwitch"]["display"]), ("magic", "block"))
        self.assertGreater(magic["after"]["frames"], magic["atSwitch"]["frames"])
        self.assertEqual(magic["pressed"], ["magic"])

    def test_none_of_it_reloads_the_page(self):
        for case, got in sorted(self.got.items()):
            with self.subTest(case=case):
                self.assertEqual((got["loads"], got["mark"]), (1, "kept"))
        self.assertEqual(sum(len(g["posted"]) for g in self.got.values()), 5)       # one request a click

    def test_the_control_fits_the_menu_and_nothing_is_under_11_px(self):
        look = self.look
        self.assertEqual([b["text"] for b in look["buttons"]], ["Magic", "Calm", "Off"])
        self.assertEqual((look["label"]["text"], look["note"]["text"]), ("Ambience", "Not saved"))
        for part in [look["label"], look["note"]] + look["buttons"]:
            with self.subTest(part=part["text"]):
                self.assertGreaterEqual(part["size"], 11)
                self.assertGreater(part["w"], 0)
                self.assertGreaterEqual(part["x"], look["menu"]["x"])
                self.assertLessEqual(part["right"], look["menu"]["right"])
                self.assertEqual(part["shadow"], "none")
        widths = [b["w"] for b in look["buttons"]]
        self.assertLessEqual(max(widths) - min(widths), 1)                     # three equal thirds
        self.assertLessEqual(look["overflow"], 0)
        self.assertEqual({b["family"] for b in look["buttons"]}, {"Inter"})

    def test_not_saved_reads_at_4_5_to_1_on_the_menu(self):
        look = self.look
        self.assertRegex(look["ground"], r"^rgb\(")                             # an opaque ground
        for part in (look["note"], look["label"]):
            with self.subTest(part=part["text"]):
                self.assertGreaterEqual(_contrast(part["color"], look["ground"]), 4.5)
