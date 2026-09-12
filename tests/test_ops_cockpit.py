"""The ops cockpit — /ops/ — and the command registry behind it.

One page says "everything, now": every switch, every decision queue,
the broker's reading with its age, the preflight verdict, and the whole
command catalogue. These tests pin the two things that can rot in
silence: the registry (every listed command exists, every command is
listed or named exempt, every usage line is the command's own docstring)
and the Run lane's rule (a registered read-only command with fixed argv,
audited; everything else refused and audited).

Run with:  python manage.py test tests.test_ops_cockpit
"""
import ast
import os
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.management import call_command, get_commands
from django.test import TestCase
from django.utils import timezone

User = get_user_model()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _flashes(resp) -> str:
    return " | ".join(str(m) for m in get_messages(resp.wsgi_request))


def _component(key, **kw):
    from core.platform_control import PlatformComponent
    fields = {"name": key.replace("_", " ").title(), "category": "system"}
    fields.update(kw)
    return PlatformComponent.objects.create(key=key, **fields)


def _acct(user, equity="2000.00", currency="EUR", *, age_seconds=0):
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, port=4003,
                                      is_primary_for_stocks=True)
    acct.set_credentials("U1234567")
    acct.username_enc, acct.password_enc = "x", "y"
    acct.last_equity = Decimal(equity)
    acct.last_equity_currency = currency
    acct.last_equity_at = timezone.now() - timedelta(seconds=age_seconds)
    acct.save()
    return acct


def _cfg(user, *, name, paper=True, research=False, enabled=True):
    from bot_program.models import AssetBotConfig
    extras = {"research_fleet": True} if research else {}
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name,
        mode="paper" if paper else "live", enabled=enabled,
        symbols=["AAPL"], capital=Decimal("1000"), extras=extras)


def _trade(cfg, *, status="OPEN", paper=True):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), status=status,
        paper=paper, rule_name="r1")


# ── the registry ────────────────────────────────────────────────────────
class RegistryTests(TestCase):

    def test_every_listed_management_command_exists(self):
        from core import ops_commands
        known = get_commands()
        for e in ops_commands.COMMANDS:
            if not ops_commands.is_management_command(e):
                continue
            self.assertIn(e["name"], known,
                          f"{e['name']} is registered but no such command")

    def test_every_management_command_is_listed_or_exempt(self):
        """The other direction: a command added under bot_program / brain
        / signals / core must land in the catalogue or be named exempt,
        with its reason — the registry cannot drift."""
        from core import ops_commands
        listed = {e["name"] for e in ops_commands.COMMANDS}
        for name, app in get_commands().items():
            if app not in ops_commands.REGISTRY_APPS:
                continue
            self.assertTrue(
                name in listed or name in ops_commands.EXEMPT,
                f"management command {name!r} ({app}) is neither in "
                f"core.ops_commands.COMMANDS nor in EXEMPT")
        for name in ops_commands.EXEMPT:
            self.assertNotIn(name, listed, f"{name} is both listed and exempt")

    def test_usage_lines_are_non_empty_and_copied_from_the_docstring(self):
        """Every usage line is the command's own — it appears verbatim in
        the command module's docstring, or is the bare `python manage.py
        <name>` (no flag invented). The host script's lines come from its
        header comment."""
        from core import ops_commands
        apps = get_commands()
        for e in ops_commands.COMMANDS:
            self.assertTrue(e["usage"], f"{e['name']}: no usage line")
            self.assertTrue(e["purpose"].strip())
            self.assertTrue(e["title"].strip())
            self.assertIn(e["category"], ("read", "decide", "ops"))
            if e["name"] == "ibkr-doctor":
                src = open(os.path.join(ROOT, "deploy", "ibkr-doctor"),
                           encoding="utf-8").read()
                for line in e["usage"]:
                    self.assertIn(line, src)
                continue
            if not ops_commands.is_management_command(e):
                continue
            app = apps[e["name"]]
            path = os.path.join(ROOT, app, "management", "commands",
                                e["name"] + ".py")
            doc = ast.get_docstring(ast.parse(
                open(path, encoding="utf-8").read())) or ""
            bare = f"python manage.py {e['name']}"
            for line in e["usage"]:
                self.assertTrue(
                    line in doc or line == bare,
                    f"{e['name']}: usage line {line!r} is not in the "
                    f"command's docstring")

    def test_run_args_and_runnable_flags(self):
        """run_args only on read-only entries; the host script is marked
        unrunnable with its reason; exactly the read-only management
        commands are what the Run lane may execute."""
        from core import ops_commands
        for e in ops_commands.COMMANDS:
            if e["run_args"]:
                self.assertTrue(e["read_only"], e["name"])
            self.assertEqual(e["read_only"], e["category"] == "read", e["name"])
        doctor = ops_commands.get("ibkr-doctor")
        self.assertFalse(ops_commands.is_runnable(doctor))
        self.assertEqual(doctor["runnable_reason"], "runs on the host, needs docker")
        # `signals` joined the Run lane on 2026-09-12: both its verbs read
        # and neither writes, so it is a `read` entry with fixed argv.
        # `setups` did NOT — its `arm` verb writes, and the registry is per
        # COMMAND, not per subcommand, so it is one `decide` entry like
        # `persona` and the lane refuses the whole of it.
        self.assertEqual(ops_commands.runnable_names(),
                         {"open_trades", "preflight_live", "why_no_trade",
                          "signals"})
        self.assertIsNone(ops_commands.get("nope"))
        self.assertEqual([k for k, _l, _r in ops_commands.by_category()],
                         ["read", "decide", "ops"])

    def test_the_recalculate_line_is_what_backfill_bars_prints(self):
        """Not a management command, so the docstring check skips it: pin
        the usage line to the 'Next:' line backfill_bars prints and to the
        Celery task it names — either can move, neither may drift."""
        import importlib
        from core import ops_commands
        e = ops_commands.get("recalculate_all_indicators")
        self.assertFalse(ops_commands.is_management_command(e))
        self.assertFalse(ops_commands.is_runnable(e))
        self.assertEqual(e["runnable_reason"],
                         "a Celery task, run through manage.py shell")
        [line] = e["usage"]
        path = os.path.join(ROOT, "market_data", "management", "commands",
                            "backfill_bars.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        printed = [n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value.startswith("Next: ")]
        self.assertEqual(printed, ["Next: " + line])
        task = getattr(importlib.import_module("indicators.tasks"),
                       "recalculate_all_indicators")
        self.assertTrue(callable(task))


# ── the page ────────────────────────────────────────────────────────────
class _Fixture(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.admin = User.objects.create_superuser("ops_admin", "a@x", "x")
        self.viewer = User.objects.create_user("ops_viewer", password="x")
        self.client.force_login(self.admin)


class PageGetTests(_Fixture):

    def setUp(self):
        super().setUp()
        _component("platform_master", is_enabled=True, category="system",
                   last_run_at=timezone.now() - timedelta(minutes=3),
                   last_status="success", run_count=4)
        _component("pipeline_asset_bots", is_enabled=False,
                   category="pipeline", last_status="error", error_count=2)
        _component("scraper_news", is_enabled=True, category="scraper")
        _component("agent_x", is_enabled=True, category="agent")
        _component("feature_odd", is_enabled=False, category="feature")

    def test_login_is_required(self):
        self.client.logout()
        resp = self.client.get("/ops/")
        self.assertEqual(resp.status_code, 302)

    def test_the_four_zones_every_component_key_and_the_nav_label(self):
        resp = self.client.get("/ops/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "OPS COCKPIT")
        for zone in ("ops-switches", "ops-queues", "ops-broker", "ops-commands"):
            self.assertContains(resp, f'id="{zone}"')
        for key in ("platform_master", "pipeline_asset_bots", "scraper_news",
                    "agent_x", "feature_odd"):
            self.assertContains(resp, f"<code>{key}</code>")
        self.assertContains(resp, "Feature / other")   # the 'other' bucket
        self.assertContains(resp, "3m ago")
        self.assertContains(resp, "never")
        # the nav row: label 'Ops', glyph, no data-nav-id on the link
        self.assertContains(resp, '<span class="label-text">Ops</span>')
        self.assertContains(resp, 'href="/ops/"')
        body = resp.content.decode()
        nav_line = [l for l in body.splitlines() if "label-text\">Ops<" in l][0]
        self.assertNotIn("data-nav-id", nav_line)
        self.assertIn("⌘", nav_line)
        # the catalogue: every title, every usage line, the mirrors link
        from core import ops_commands
        from django.utils.html import escape
        for e in ops_commands.COMMANDS:
            self.assertContains(resp, escape(e["title"]))
            self.assertContains(resp, escape(e["usage"][0]))
        self.assertContains(resp, "runs on the host, needs docker")
        self.assertContains(resp, "--yes or the PIN keeps its meaning")
        self.assertContains(resp, "python manage.py ops")
        # the wall's own number
        from core.wall_facts import TESTS_GREEN
        self.assertContains(resp, f">{TESTS_GREEN}<")
        self.assertContains(resp, "tests green")

    def test_the_switch_summary_counts_on_off_and_erroring(self):
        resp = self.client.get("/ops/")
        self.assertContains(resp, "3 on / 2 off / 1 erroring")
        self.assertContains(resp, "3/5")
        ctx = resp.context["switches"]
        self.assertEqual((ctx["on"], ctx["off"], ctx["erroring"]), (3, 2, 1))
        # a superuser sees the toggle form with next=ops on every row
        self.assertContains(resp, 'name="next" value="ops"')
        self.assertContains(resp, 'name="key" value="pipeline_asset_bots"')

    def test_unmeasured_renders_a_dash_not_a_zero(self):
        resp = self.client.get("/ops/")
        b = resp.context["broker"]
        self.assertIsNone(b["reading"])
        self.assertIsNone(b["drawdown"])
        self.assertContains(resp, "no broker reading yet")
        self.assertContains(resp, "no equity history yet")
        self.assertContains(resp, "no broker_account_sync row")
        body = resp.content.decode()
        self.assertGreaterEqual(body.count("—"), 3)
        # an empty queue is 0, a queue that could not be read is '—'
        for q in resp.context["queues"]["rows"]:
            self.assertEqual(q["count"], 0, q["label"])
            self.assertEqual(q["newest_age"], "—")

    def test_the_queues_count_seeded_rows_with_the_newest_age(self):
        from bot_program.share_models import SharePlan
        from brain.generator_models import GeneratedSetupProposal
        from signals.models_control import MetaAllocation, RuleAction
        RuleAction.objects.create(rule_name="macd", action="pause_rule")
        RuleAction.objects.create(rule_name="rsi", action="reduce_size")
        RuleAction.objects.create(rule_name="old", action="pause_rule",
                                  state="rejected")
        GeneratedSetupProposal.objects.create(proposed_name="gen_a")
        SharePlan.objects.create(user=self.admin)
        SharePlan.objects.create(user=self.viewer)       # not the viewer's
        MetaAllocation.objects.create()
        MetaAllocation.objects.create(state="applied")
        live = _cfg(self.admin, name="live_a", paper=False)
        paper = _cfg(self.admin, name="paper_a", research=True)
        _cfg(self.admin, name="paper_off", research=True, enabled=False)
        _trade(live, paper=False)
        _trade(live, status="CLOSE_PENDING", paper=False)
        _trade(paper)
        _trade(paper, status="CLOSED")

        resp = self.client.get("/ops/")
        self.assertEqual(resp.status_code, 200)
        rows = {q["label"]: q for q in resp.context["queues"]["rows"]}
        self.assertEqual(rows["Rule actuator proposals"]["count"], 2)
        self.assertEqual(rows["Generator proposals"]["count"], 1)
        self.assertEqual(rows["Share plans (yours)"]["count"], 1)
        self.assertEqual(rows["Meta-allocation shadows"]["count"], 1)
        self.assertEqual(rows["Pending closes"]["count"], 1)
        self.assertEqual(rows["Open positions — live"]["count"], 2)
        self.assertEqual(rows["Open positions — paper"]["count"], 1)
        self.assertEqual(rows["Research-fleet configs enabled"]["count"], 1)
        self.assertEqual(rows["Rule actuator proposals"]["newest_age"], "0m ago")
        self.assertEqual(rows["Rule actuator proposals"]["url"], "/rule-control/")
        self.assertEqual(rows["Share plans (yours)"]["url"], "/shares/")
        self.assertIn("applied today 0/", rows["Share plans (yours)"]["note"])
        # 2 + 1 + 1 + 1 + 1 pending close = 6 decisions; exposure not counted
        self.assertEqual(resp.context["queues"]["pending"], 6)
        self.assertContains(resp, "6 awaiting a decision")
        self.assertContains(resp, 'href="/rule-control/"')

    def test_a_broken_queue_blanks_one_cell_with_its_reason_not_the_page(self):
        from signals.models_control import RuleAction
        with patch.object(RuleAction.objects, "filter",
                          side_effect=RuntimeError("table gone")):
            resp = self.client.get("/ops/")
        self.assertEqual(resp.status_code, 200)
        rows = {q["label"]: q for q in resp.context["queues"]["rows"]}
        self.assertIsNone(rows["Rule actuator proposals"]["count"])
        self.assertIn("table gone", rows["Rule actuator proposals"]["error"])
        self.assertContains(resp, "table gone")
        self.assertEqual(rows["Generator proposals"]["count"], 0)
        self.assertTrue(resp.context["queues"]["unmeasured"])
        self.assertContains(resp, "one queue unmeasured")

    def test_a_non_staff_login_reads_its_own_zones_only(self):
        """/health/'s rule: the platform-wide zones (every component's
        last_message, every user's queue rows) are staff's; a viewer keeps
        the page, their own account, the preflight for their own user and
        the catalogue — with no toggle and no Run button."""
        self.client.force_login(self.viewer)
        resp = self.client.get("/ops/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="next" value="ops"')
        self.assertNotContains(resp, "▶ Run")
        self.assertContains(resp, "superusers run it")
        self.assertFalse(resp.context["is_staff"])
        # the platform-wide zones: not one component key, not one count
        for key in ("platform_master", "pipeline_asset_bots", "scraper_news",
                    "agent_x", "feature_odd"):
            self.assertNotContains(resp, f"<code>{key}</code>")
        self.assertContains(resp, "STAFF ONLY")
        self.assertContains(resp, "staff only — platform-wide, as on /health/")
        self.assertEqual(resp.context["switches"]["groups"], [])
        self.assertIsNone(resp.context["switches"]["total"])
        self.assertEqual(resp.context["queues"]["rows"], [])
        self.assertIsNone(resp.context["queues"]["pending"])
        self.assertNotContains(resp, "awaiting a decision")
        # the viewer's own zones stay: the account card, the preflight
        # for THEIR user, the four zone anchors, the catalogue
        self.assertContains(resp, "Account — ops_viewer")
        self.assertContains(resp, "preflight_live --user ops_viewer")
        for zone in ("ops-switches", "ops-queues", "ops-broker", "ops-commands"):
            self.assertContains(resp, f'id="{zone}"')
        self.assertContains(resp, "python manage.py open_trades --symbol SOL")

    def test_a_staff_login_reads_the_platform_zones_without_toggles(self):
        """Staff (not superuser): the switches and queues render, the
        decide buttons do not — exactly /health/'s split."""
        staff = User.objects.create_user("ops_staff", password="x", is_staff=True)
        self.client.force_login(staff)
        resp = self.client.get("/ops/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_staff"])
        self.assertFalse(resp.context["is_admin"])
        self.assertContains(resp, "<code>platform_master</code>")
        self.assertContains(resp, "3 on / 2 off / 1 erroring")
        self.assertContains(resp, "read-only for viewers")
        self.assertNotContains(resp, "STAFF ONLY")
        self.assertNotContains(resp, 'name="next" value="ops"')
        self.assertNotContains(resp, "▶ Run")
        self.assertEqual(resp.context["queues"]["pending"], 0)

    def test_the_broker_zone_shows_the_reading_its_age_and_the_stale_flag(self):
        _acct(self.admin, age_seconds=2 * 3600)
        _component("broker_account_sync", is_enabled=True, category="system",
                   last_run_at=timezone.now() - timedelta(hours=2),
                   last_status="success")
        _component("share_allocator_mode_live", is_enabled=True,
                   category="system")
        resp = self.client.get("/ops/")
        b = resp.context["broker"]
        self.assertEqual(b["reading"]["value_text"], "2,000.00")
        self.assertTrue(b["reading_stale"])
        self.assertContains(resp, "2,000.00 EUR")
        self.assertContains(resp, "STALE")
        self.assertContains(resp, "2.0h ago")
        self.assertTrue(b["live_mode"])
        self.assertContains(resp, ">LIVE<")
        self.assertIsNotNone(b["drawdown"])
        self.assertEqual(b["governor"], 1.0)
        self.assertContains(resp, "governor ×1.00")

    def test_the_preflight_verdict_is_summarised_and_cached_per_user(self):
        """The BLOCKERS lines (or NO BLOCKERS FOUND) off the real command,
        run once per 120 s per user: a refresh reads the cache."""
        resp = self.client.get("/ops/")
        pf = resp.context["broker"]["preflight"]
        self.assertTrue(pf["ok"], pf)
        self.assertEqual(pf["verdict"], "blocked")
        self.assertTrue(pf["lines"][0].startswith("BLOCKERS"))
        self.assertTrue(any("IBKRAccount" in l for l in pf["lines"]), pf["lines"])
        self.assertFalse(pf["cached"])
        self.assertContains(resp, "BLOCKERS")
        self.assertContains(resp, "preflight_live --user ops_admin")
        with patch("django.core.management.call_command") as fake:
            resp2 = self.client.get("/ops/")
        pf2 = resp2.context["broker"]["preflight"]
        self.assertTrue(pf2["cached"])
        self.assertEqual(pf2["lines"], pf["lines"])
        fake.assert_not_called()
        # another user gets their own run
        self.client.force_login(self.viewer)
        resp3 = self.client.get("/ops/")
        self.assertFalse(resp3.context["broker"]["preflight"]["cached"])

    def test_no_blockers_reads_as_clear(self):
        out = ("=" * 70 + "\nNO BLOCKERS FOUND.\nWhich is not the same as safe."
               "\n" + "=" * 70 + "\n")

        def fake(name, *a, **kw):
            kw["stdout"].write(out)
        with patch("django.core.management.call_command", side_effect=fake):
            resp = self.client.get("/ops/")
        pf = resp.context["broker"]["preflight"]
        self.assertEqual(pf["verdict"], "clear")
        self.assertEqual(pf["lines"], ["NO BLOCKERS FOUND."])
        self.assertContains(resp, "NO BLOCKERS FOUND")

    def test_the_preflight_passes_the_username_as_one_argv_item(self):
        """Django's username validator allows a leading '-'. Passed as a
        separate argv item, "-dash" is an option to argparse and the card
        read "error" for that user; `--user=-dash` is one item."""
        from django.core.cache import cache
        dash = User.objects.create_user("-dash", password="x")
        self.client.force_login(dash)
        resp = self.client.get("/ops/")
        pf = resp.context["broker"]["preflight"]
        self.assertTrue(pf["ok"], pf)
        self.assertEqual(pf["verdict"], "blocked")   # a fresh user: no account
        self.assertContains(resp, "preflight_live --user -dash")
        cache.clear()
        with patch("django.core.management.call_command") as fake:
            self.client.get("/ops/")
        fake.assert_called_once()
        self.assertEqual(fake.call_args.args, ("preflight_live", "--user=-dash"))


# ── the toggle's way back ───────────────────────────────────────────────
class ToggleNextTests(_Fixture):

    def setUp(self):
        super().setUp()
        self.comp = _component("scraper_news", is_enabled=False,
                               category="scraper")

    def test_toggle_with_next_ops_redirects_to_ops_and_flips(self):
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": "scraper_news", "next": "ops"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.comp.refresh_from_db()
        self.assertTrue(self.comp.is_enabled)
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": "scraper_news", "next": "ops"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.comp.refresh_from_db()
        self.assertFalse(self.comp.is_enabled)

    def test_toggle_without_next_still_returns_to_the_admin_dashboard(self):
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": "scraper_news"})
        self.assertRedirects(resp, "/admin-dashboard/",
                             fetch_redirect_response=False)
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": "scraper_news", "next": "elsewhere"})
        self.assertRedirects(resp, "/admin-dashboard/",
                             fetch_redirect_response=False)

    def test_bulk_toggle_with_next_ops_redirects_to_ops(self):
        _component("scraper_eod", is_enabled=False, category="scraper")
        resp = self.client.post("/admin-dashboard/bulk-toggle/",
                                {"category": "scraper", "action": "enable",
                                 "next": "ops"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        from core.platform_control import PlatformComponent
        self.assertEqual(PlatformComponent.objects.filter(
            category="scraper", is_enabled=True).count(), 2)
        resp = self.client.post("/admin-dashboard/bulk-toggle/",
                                {"category": "scraper", "action": "disable"})
        self.assertRedirects(resp, "/admin-dashboard/",
                             fetch_redirect_response=False)


# ── the Run lane ────────────────────────────────────────────────────────
class RunCommandTests(_Fixture):

    def _audit(self, kind):
        from bot_program.audit_models import AuditLogEntry
        return list(AuditLogEntry.objects.filter(kind=kind).order_by("id"))

    def test_runs_open_trades_and_the_output_appears_on_the_next_get(self):
        cfg = _cfg(self.admin, name="paper_a")
        _trade(cfg)
        resp = self.client.post("/ops/run/", {"name": "open_trades"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.assertIn("open_trades ran in", _flashes(resp))
        page = self.client.get("/ops/")
        last = page.context["last"]
        self.assertEqual(last["name"], "open_trades")
        self.assertTrue(last["ok"])
        self.assertFalse(last["truncated"])
        self.assertIn("AAPL", last["output"])
        self.assertIn("1 paper open", last["output"])
        self.assertContains(page, "Last command output")
        self.assertContains(page, "<code>open_trades</code>")
        self.assertContains(page, "AAPL")
        self.assertIsInstance(last["seconds"], float)
        # and the session carries it too (a cache flush does not lose it)
        self.assertEqual(self.client.session["ops_last"]["name"], "open_trades")
        from django.core.cache import cache
        self.assertEqual(cache.get(f"ops:last:{self.admin.pk}")["name"],
                         "open_trades")

    def test_refuses_a_decide_command(self):
        with patch("django.core.management.call_command") as fake:
            resp = self.client.post("/ops/run/", {"name": "component"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        fake.assert_not_called()
        self.assertIn("Refused: component", _flashes(resp))
        self.assertIn("not read-only", _flashes(resp))
        rows = self._audit("ops_run_refused")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["name"], "component")
        self.assertEqual(rows[0].user, self.admin)
        self.assertEqual(self._audit("ops_run"), [])

    def test_refuses_an_unknown_name_and_an_unrunnable_read_command(self):
        with patch("django.core.management.call_command") as fake:
            resp = self.client.post("/ops/run/",
                                    {"name": "open_trades --all; rm -rf /"})
            self.assertIn("not in the registry", _flashes(resp))
            resp = self.client.post("/ops/run/", {"name": "ibkr-doctor"})
            self.assertIn("runs on the host, needs docker", _flashes(resp))
            resp = self.client.post("/ops/run/", {})
            self.assertIn("(no name)", _flashes(resp))
        fake.assert_not_called()
        self.assertEqual(len(self._audit("ops_run_refused")), 3)
        self.assertIsNone(self.client.get("/ops/").context["last"])

    def test_a_non_superuser_is_403(self):
        self.client.force_login(self.viewer)
        with patch("django.core.management.call_command") as fake:
            resp = self.client.post("/ops/run/", {"name": "open_trades"})
        self.assertEqual(resp.status_code, 403)
        fake.assert_not_called()
        self.assertEqual(self._audit("ops_run"), [])

    def test_get_is_405(self):
        resp = self.client.get("/ops/run/?name=open_trades")
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(self._audit("ops_run"), [])

    def test_output_is_truncated_at_20000_chars(self):
        def fake(name, *a, **kw):
            kw["stdout"].write("x" * 25_000)
        with patch("django.core.management.call_command", side_effect=fake):
            self.client.post("/ops/run/", {"name": "why_no_trade"})
        last = self.client.get("/ops/").context["last"]
        self.assertEqual(len(last["output"]), 20_000)
        self.assertTrue(last["truncated"])
        self.assertTrue(last["ok"])
        page = self.client.get("/ops/")
        self.assertContains(page, "truncated at 20000 chars")

    def test_the_fixed_argv_is_the_registry_s_and_nothing_from_the_browser(self):
        with patch("django.core.management.call_command") as fake:
            self.client.post("/ops/run/", {"name": "preflight_live",
                                           "args": "--user root",
                                           "name2": "component"})
        fake.assert_called_once()
        args, kwargs = fake.call_args
        self.assertEqual(args, ("preflight_live",))
        self.assertEqual(set(kwargs), {"stdout", "stderr"})

    def test_a_crashing_command_is_reported_not_a_500(self):
        with patch("django.core.management.call_command",
                   side_effect=RuntimeError("db on fire")):
            resp = self.client.post("/ops/run/", {"name": "open_trades"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.assertIn("failed", _flashes(resp))
        last = self.client.get("/ops/").context["last"]
        self.assertFalse(last["ok"])
        self.assertIn("[RuntimeError] db on fire", last["output"])
        rows = self._audit("ops_run")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].data["ok"])

    def test_the_audit_rows_carry_name_seconds_and_ok(self):
        self.client.post("/ops/run/", {"name": "why_no_trade"})
        self.client.post("/ops/run/", {"name": "shares"})
        ran = self._audit("ops_run")
        refused = self._audit("ops_run_refused")
        self.assertEqual(len(ran), 1)
        self.assertEqual(set(ran[0].data), {"name", "seconds", "ok"})
        self.assertEqual(ran[0].data["name"], "why_no_trade")
        self.assertTrue(ran[0].data["ok"])
        self.assertEqual(ran[0].user, self.admin)
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0].data["name"], "shares")
        # kind fits Postgres' AuditLogEntry.kind max_length=20
        for row in ran + refused:
            self.assertLessEqual(len(row.kind), 20)

    def test_a_refused_name_with_control_bytes_is_still_audited(self):
        """A NUL is legal in a POST body and Postgres JSONB refuses it —
        the raw name in the audit data made record_event swallow the row
        and the refusal left no trace. The row carries a printable name,
        capped; the flash the same; nothing runs."""
        raw = "open_trades\x00\n; rm -rf /" + "x" * 200
        with patch("django.core.management.call_command") as fake:
            resp = self.client.post("/ops/run/", {"name": raw})
        fake.assert_not_called()
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        rows = self._audit("ops_run_refused")
        self.assertEqual(len(rows), 1)
        name = rows[0].data["name"]
        self.assertNotIn("\x00", name)
        self.assertNotIn("\n", name)
        self.assertLessEqual(len(name), 80)
        self.assertTrue(name.startswith("open_trades; rm -rf /"), name)
        flash = _flashes(resp)
        self.assertNotIn("\x00", flash)
        self.assertIn("not in the registry", flash)
        self.assertEqual(self._audit("ops_run"), [])


# ── the shell twin ──────────────────────────────────────────────────────
class OpsCommandTests(TestCase):

    def test_ops_prints_every_title_grouped_by_category(self):
        from core import ops_commands
        out = StringIO()
        call_command("ops", stdout=out)
        text = out.getvalue()
        for e in ops_commands.COMMANDS:
            self.assertIn(e["title"], text)
            self.assertIn(f"({e['name']})", text)
            self.assertIn(e["purpose"], text)
            for line in e["usage"]:
                self.assertIn(line, text)
            if e.get("mirrors"):
                self.assertIn(f"mirrors {e['mirrors']}", text)
        for key in ("[read]", "[decide]", "[ops]"):
            self.assertIn(key, text)
        self.assertLess(text.index("[read]"), text.index("[decide]"))
        self.assertLess(text.index("[decide]"), text.index("[ops]"))
        self.assertIn("runs on the host, needs docker", text)
        only = StringIO()
        call_command("ops", "--category", "read", stdout=only)
        self.assertIn("Open trades", only.getvalue())
        self.assertNotIn("[decide]", only.getvalue())
