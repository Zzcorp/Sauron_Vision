"""The activity drawer: Sauron's live log, tucked under the signals rail.

The operator, 2026-09-28: "pour le système de print des logs de détail de
l'activité de Sauron, un bandeau latéral vertical qui se place sous le
bandeau des signaux et watchlist actuel, avec juste un bout dépassant."

One JSON door, /api/activity/feed/ (dashboard.views_activity over
dashboard.activity_feed), one partial (templates/_partials/
activity_drawer.html, staff only), one sheet (static/css/sv-activity.css)
and one script (static/js/sv-activity.js).

What is pinned here:
  - the door needs a login and staff, never caches, and answers the lines
    of six sources merged newest first, with `since` and `limit` honoured;
  - one fact, one line: a gate refusal is the OrchestratorEvent row only,
    not also its audit-chain copy or its bell row; a fill is the audit
    row, not also its bell row;
  - the reader's own account rows only, platform rows for everyone;
  - titles are sentences, never a dict, and links are same-site or http;
  - a query ceiling that does not grow with the rows, and a source that
    raises costs the log that source only;
  - the drawer renders for staff after the rail and never for anyone else;
  - the sheet sits between the motion layer and the phone tier, on its own
    rung of the ladder (under the rail, over the chrome), and the phone
    tier hides it on the same one-line rule as the rail;
  - the script opens no socket, carries no template tag, writes no
    innerHTML, reads localStorage only inside a try, and parses under node.

Run with:  python manage.py test tests.test_activity_drawer
"""
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from dashboard import activity_feed as feed

URL = "/api/activity/feed/"
BASE = Path(settings.BASE_DIR)
JS = BASE / "static" / "js" / "sv-activity.js"
SHEET = BASE / "static" / "css" / "sv-activity.css"
PARTIAL = BASE / "templates" / "_partials" / "activity_drawer.html"
KEYS = {"id", "at", "ago", "kind", "level", "title", "detail", "url"}


def _read(*parts):
    return BASE.joinpath(*parts).read_text(encoding="utf-8")


def _user(name="act_u", staff=True):
    return User.objects.create_user(username=name, password="x", is_staff=staff)


def _ago(**kw):
    return timezone.now() - timedelta(**kw)


def _audit(user, kind, data, at):
    from bot_program.audit import record_event
    from bot_program.audit_models import AuditLogEntry
    row = record_event(kind, data, user=user)
    AuditLogEntry.objects.filter(pk=row.pk).update(created_at=at)
    return row


def _reject(user, symbol, at, side="BUY",
            reason="orchestrator: USD currency cap |+3.2| > 3.0"):
    from bot_program.orchestrator_models import OrchestratorEvent
    row = OrchestratorEvent.objects.create(
        user=user, asset_class="stock", symbol=symbol, side=side,
        decision="reject", reason=reason)
    OrchestratorEvent.objects.filter(pk=row.pk).update(created_at=at)
    return row


def _agent(at, success=True, error=""):
    from ai_agents.models import AgentTask
    row = AgentTask.objects.create(
        agent="sauron_mind", provider="anthropic", model="m-1",
        prompt_summary="p", input_tokens=1200, output_tokens=300,
        cost_usd=Decimal("0.0123"), success=success, error=error,
        duration_seconds=2.4)
    AgentTask.objects.filter(pk=row.pk).update(created_at=at)
    return row


def _component(key, at, status="success", message="stored 12 rows",
               enabled=True):
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.create(
        key=key, name=key.replace("_", " ").title(), category="scraper",
        is_enabled=enabled, last_run_at=at, last_status=status,
        last_message=message)


def _bot(user, name, at=None, status="OK", note="ok", enabled=True):
    from bot_program.models import AssetBotConfig
    extras = {}
    if at is not None:
        extras = {"last_tick_at": at.isoformat(), "last_tick_status": status,
                  "last_tick_note": note}
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, enabled=enabled,
        mode="paper", symbols=[], capital=Decimal("10000"),
        base_currency="USD", position_size_pct=2.0,
        max_concurrent_positions=5, max_daily_loss_pct=2.0,
        stop_loss_pct=1.5, take_profit_pct=3.0, entry_score_min=0.6,
        min_signals_for_entry=1, extras=extras)


def _notif(user, title, at, ntype="system", url="/notifications/",
           data=None, body=""):
    from alerts.models import Notification
    row = Notification.objects.create(
        user=user, notification_type=ntype, title=title, body=body, url=url,
        data=data or {})
    Notification.objects.filter(pk=row.pk).update(created_at=at)
    return row


def _open_trade(user, symbol, at, trade_id=41):
    return _audit(user, "trade_open", {
        "trade_id": trade_id, "asset_class": "forex", "symbol": symbol,
        "side": "BUY", "qty": "7900.00000000", "entry_price": "1.60725571",
        "stop_loss": "1.59000000", "take_profit": None,
        "rule_name": "golden_cross", "mode": "paper",
        "broker_order_id": ""}, at)


# ── 1. the door ──────────────────────────────────────────────────────────

class TheDoorTests(TestCase):

    def test_an_anonymous_reader_is_sent_to_sign_in(self):
        from django.shortcuts import resolve_url
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith(resolve_url(settings.LOGIN_URL)),
                        r["Location"])
        self.assertIn("next=/api/activity/feed/", r["Location"])

    def test_a_non_staff_reader_gets_the_day_live_refusal(self):
        self.client.force_login(_user("act_plain", staff=False))
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json(), {"staff_only": True})

    def test_staff_get_now_and_events_and_nothing_is_cached(self):
        self.client.force_login(_user())
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"now", "events"})
        self.assertRegex(body["now"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(body["events"], [])
        self.assertIn("no-cache", r.get("Cache-Control", ""))

    def test_only_get(self):
        self.client.force_login(_user())
        self.assertEqual(self.client.post(URL).status_code, 405)

    def test_a_since_that_is_not_a_timestamp_is_a_400(self):
        self.client.force_login(_user())
        r = self.client.get(URL, {"since": "yesterday"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("since", r.json()["error"])

    def test_the_route_is_named(self):
        from django.urls import reverse
        self.assertEqual(reverse("activity_feed"), URL)


# ── 2. the log ───────────────────────────────────────────────────────────

class TheLogTests(TestCase):

    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def _seed(self):
        _open_trade(self.user, "EURCAD", _ago(minutes=1))
        _reject(self.user, "NVDA", _ago(minutes=2))
        _agent(_ago(minutes=3))
        _component("scraper_fred", _ago(minutes=4))
        _bot(self.user, "Stocks bot", at=_ago(minutes=5))
        _notif(self.user, "Morning digest ready", _ago(minutes=6))
        _audit(None, "rule_demoted", {"rule_name": "rsi_reversal",
                                      "criterion": "avg_r_drop",
                                      "metrics": {"n": 30}, "notes": ""},
               _ago(minutes=7))

    def test_every_source_lands_merged_newest_first(self):
        self._seed()
        events = self.client.get(URL).json()["events"]
        self.assertEqual([e["kind"] for e in events],
                         ["trade", "gate", "ai", "pipeline", "bot", "alert",
                          "system"])
        ats = [e["at"] for e in events]
        self.assertEqual(ats, sorted(ats, reverse=True))
        for e in events:
            self.assertEqual(set(e), KEYS, e)
            self.assertIn(e["level"], feed.LEVELS)
            self.assertRegex(e["ago"], r"^(just now|\d+ min ago|\d+ h ago|\d+ d ago)$")
        self.assertEqual(events[0]["ago"], "1 min ago")
        self.assertEqual(len({e["id"] for e in events}), len(events))

    def test_the_lines_are_sentences_not_dicts(self):
        self._seed()
        events = {e["kind"]: e for e in self.client.get(URL).json()["events"]}
        self.assertEqual(events["trade"]["title"], "Bought EURCAD · paper")
        self.assertIn("qty 7,900 at 1.60725571", events["trade"]["detail"])
        self.assertIn("rule golden_cross", events["trade"]["detail"])
        self.assertEqual(events["trade"]["url"], "/forensics/41/")
        self.assertEqual(events["gate"]["title"], "Buying NVDA was blocked")
        self.assertIn("It would take the USD exposure", events["gate"]["detail"])
        self.assertIn("decision=reject&symbol=NVDA", events["gate"]["url"])
        self.assertEqual(events["ai"]["title"], "Sauron mind answered in 2.4 s")
        self.assertIn("1,500 tokens", events["ai"]["detail"])
        self.assertEqual(events["pipeline"]["title"], "Scraper Fred ran")
        self.assertEqual(events["pipeline"]["detail"], "stored 12 rows")
        self.assertEqual(events["bot"]["title"],
                         "Stocks bot ticked · open to new entries")
        self.assertEqual(events["alert"]["title"], "Morning digest ready")
        self.assertEqual(events["system"]["title"], "Rule rsi_reversal demoted")
        for e in events.values():
            for field in ("title", "detail"):
                self.assertNotRegex(e[field], r"[{}\[\]]", e)

    def test_since_keeps_only_what_is_newer(self):
        self._seed()
        cut = feed.iso(_ago(minutes=3, seconds=30))
        events = self.client.get(URL, {"since": cut}).json()["events"]
        self.assertEqual([e["kind"] for e in events], ["trade", "gate", "ai"])
        self.assertTrue(all(e["at"] > cut for e in events))
        # The function takes the same string, or an aware datetime.
        self.assertEqual(len(feed.activity_events(self.user, since=cut)), 3)

    def test_a_since_with_its_plus_decoded_to_a_space_still_reads(self):
        self._seed()
        cut = _ago(minutes=3, seconds=30).isoformat()   # +00:00
        r = self.client.get(URL + "?since=" + cut)          # '+' -> ' '
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["events"]), 3)

    def test_limit_caps_the_answer(self):
        for i in range(8):
            _notif(self.user, f"Alert {i}", _ago(minutes=i + 1))
        self.assertEqual(len(self.client.get(URL, {"limit": 3}).json()["events"]), 3)
        events = feed.activity_events(self.user, limit=5)
        self.assertEqual([e["title"] for e in events],
                         ["Alert 0", "Alert 1", "Alert 2", "Alert 3", "Alert 4"])
        self.assertEqual(len(feed.activity_events(self.user, limit=10_000)), 8)
        self.assertEqual(len(self.client.get(URL, {"limit": "x"}).json()["events"]), 8)

    def test_a_gate_refusal_is_one_line_not_three(self):
        """The orchestrator writes a refusal three times — its own event,
        the audit chain's gate_reject and the bell row — and pushes it on
        the eye. The log prints it once, from OrchestratorEvent."""
        from bot_program.audit import record_gate_reject
        from bot_program.notifications import NOTIFY_MARKS
        at = _ago(minutes=2)
        _reject(self.user, "NVDA", at)
        record_gate_reject(self.user, asset_class="stock", symbol="NVDA",
                           side="BUY", right="", reason="orchestrator: cap",
                           exposure_before={}, exposure_after={}, caps={})
        _notif(self.user, "\u2715 Buying NVDA was blocked", at, ntype="bot",
               url="/eye/", data={"items": [], "mark": NOTIFY_MARKS["orchestrator_reject"]})
        events = self.client.get(URL).json()["events"]
        nvda = [e for e in events if "NVDA" in e["title"]]
        self.assertEqual(len(nvda), 1, events)
        self.assertEqual(nvda[0]["kind"], "gate")
        self.assertTrue(nvda[0]["id"].startswith("gate:"))

    def test_a_fill_is_one_trade_line_not_also_its_bell_row(self):
        from bot_program.notifications import CLOSE_MARKS, NOTIFY_MARKS, OPEN_MARKS
        at = _ago(minutes=1)
        _open_trade(self.user, "EURCAD", at)
        _notif(self.user, "\u25c9 Bought EURCAD", at, ntype="bot",
               url="/forensics/41/", data={"mark": OPEN_MARKS["long"]})
        _notif(self.user, "\u25b8 Bought AAPL by hand", at, ntype="portfolio",
               data={"mark": NOTIFY_MARKS["manual_fill_open"]})
        _notif(self.user, "Closed EURCAD · +17.84 USD", at, ntype="bot",
               data={"mark": CLOSE_MARKS["gain"]})
        # The manual lane's own red mark is the SHORT open's too; on a
        # portfolio row it is the lane arming live — a fact of its own.
        _notif(self.user, "Manual lane is live", at, ntype="portfolio",
               data={"mark": NOTIFY_MARKS["manual_lane_live"]})
        events = self.client.get(URL).json()["events"]
        self.assertEqual(sorted(e["title"] for e in events),
                         ["Bought EURCAD · paper", "Manual lane is live"])

    def test_a_desk_plan_prints_only_when_the_desk_did_something(self):
        base = {"plan_id": 1, "venue": "paper", "mode": "paper",
                "budget": 120.0, "n_candidates": 4, "n_chosen": 0,
                "n_displaced": 0, "error": ""}
        _audit(self.user, "desk_plan", base, _ago(minutes=1))
        _audit(self.user, "desk_plan", {**base, "n_chosen": 2}, _ago(minutes=2))
        _audit(self.user, "desk_plan", {**base, "n_displaced": 1}, _ago(minutes=3))
        titles = [e["title"] for e in self.client.get(URL).json()["events"]]
        self.assertEqual(titles, ["The capital desk chose 2 of 4 entries",
                                  "The capital desk chose 0 of 4 entries, displaced 1"])

    def test_the_readers_own_account_rows_and_the_platforms(self):
        other = _user("act_other", staff=True)
        _open_trade(other, "AAPL", _ago(minutes=1))
        _reject(other, "MSFT", _ago(minutes=1))
        _bot(other, "Their bot", at=_ago(minutes=1))
        _notif(other, "Their alert", _ago(minutes=1))
        _component("scraper_eod", _ago(minutes=2))
        _agent(_ago(minutes=2))
        _audit(None, "setup_armed", {"setup": "breakout", "setup_id": 3,
                                     "path": "direct", "stage": "none"},
               _ago(minutes=2))
        kinds = sorted(e["kind"] for e in self.client.get(URL).json()["events"])
        self.assertEqual(kinds, ["ai", "pipeline", "system"])

    def test_the_pipeline_window_and_the_levels(self):
        _component("scraper_old", _ago(hours=30))
        _component("scraper_warn", _ago(minutes=2), status="warning",
                   message="parsed 40 rows, stored none")
        _component("scraper_err", _ago(minutes=3), status="error",
                   message="403 for https://x.test/?apikey=SECRET123456")
        _component("scraper_off", _ago(minutes=4), enabled=False)
        events = self.client.get(URL).json()["events"]
        self.assertEqual([(e["title"], e["level"]) for e in events], [
            ("Scraper Warn ran with a warning", "warn"),
            ("Scraper Err failed", "error"),
            ("Scraper Off ran", "ok")])
        self.assertNotIn("SECRET123456", events[1]["detail"])
        self.assertTrue(events[2]["detail"].startswith("switched off"))
        self.assertEqual(events[0]["url"], "/admin-dashboard/system-map/")

    def test_a_pipeline_that_runs_again_is_a_new_line(self):
        from core.platform_control import PlatformComponent
        row = _component("scraper_fred", _ago(minutes=5))
        first = feed.activity_events(self.user)[0]["id"]
        PlatformComponent.objects.filter(pk=row.pk).update(last_run_at=_ago(minutes=1))
        second = feed.activity_events(self.user)[0]["id"]
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith("pipeline:scraper_fred:"))

    def test_the_bot_ticks(self):
        _bot(self.user, "Halted", at=_ago(minutes=1),
             note="circuit breaker: 4 losses in a row")
        _bot(self.user, "Full", at=_ago(minutes=2),
             note="max 5 concurrent positions reached")
        _bot(self.user, "Stuck", at=_ago(minutes=45), status="RUNNING", note="")
        _bot(self.user, "Blind", at=_ago(minutes=3),
             note="ok (UNCHECKED: book unreadable)")
        _bot(self.user, "Off", at=_ago(minutes=1), enabled=False)
        _bot(self.user, "Never ticked")
        events = self.client.get(URL).json()["events"]
        self.assertEqual([(e["title"], e["level"]) for e in events], [
            ("Halted ticked · entries halted", "warn"),
            ("Full ticked · no new entries", "info"),
            ("Blind ticked · some gates could not be checked", "warn"),
            ("Stuck did not finish its last tick", "error")])
        self.assertIn("circuit breaker: 4 losses in a row", events[0]["detail"])

    def test_a_failed_agent_call_says_so_without_its_secret(self):
        _agent(_ago(minutes=1), success=False,
               error="HTTP 401 for https://api.test/v1?api_key=SECRET987654\nTraceback…")
        e = self.client.get(URL).json()["events"][0]
        self.assertEqual((e["title"], e["level"]), ("Sauron mind failed", "error"))
        self.assertNotIn("SECRET987654", e["detail"])
        self.assertNotIn("Traceback", e["detail"])

    def test_a_link_is_same_site_or_http_and_nothing_else(self):
        _notif(self.user, "Bad link", _ago(minutes=1), url="javascript:alert(1)")
        _notif(self.user, "Offsite", _ago(minutes=2), url="//evil.test/x")
        _notif(self.user, "External", _ago(minutes=3), url="https://example.test/a")
        urls = {e["title"]: e["url"] for e in self.client.get(URL).json()["events"]}
        self.assertEqual(urls["Bad link"], "/notifications/")
        self.assertEqual(urls["Offsite"], "/notifications/")
        self.assertEqual(urls["External"], "https://example.test/a")
        self.assertEqual(feed.safe_link("javascript:alert(1)"), "")

    def test_a_symbol_no_route_can_carry_still_links_somewhere(self):
        _audit(self.user, "trade_open", {"symbol": "BTC/USD", "side": "SELL",
                                         "mode": "live"}, _ago(minutes=1))
        e = self.client.get(URL).json()["events"][0]
        self.assertEqual(e["title"], "Sold BTC/USD short · live")
        self.assertEqual(e["url"], "/positions/")

    def test_an_unknown_audit_kind_reads_in_words(self):
        _audit(self.user, "admin_action", {"name": "reset", "deep": {"a": 1}},
               _ago(minutes=1))
        _audit(None, "promotion", {"rule_name": "golden_cross",
                                   "to": {"stage": 2}}, _ago(minutes=2))
        lines = [(e["title"], e["detail"]) for e in self.client.get(URL).json()["events"]]
        self.assertEqual(lines, [("Admin action", "name reset"),
                                 ("Promotion", "rule name golden_cross")])


# ── 3. the ceiling and the fences ────────────────────────────────────────

class TheCeilingTests(TestCase):

    def setUp(self):
        self.user = _user()
        self.client.force_login(self.user)

    def _seed(self, n):
        for i in range(n):
            _open_trade(self.user, f"S{i}", _ago(minutes=i + 1), trade_id=i + 1)
            _reject(self.user, f"R{i}", _ago(minutes=i + 1))
            _agent(_ago(minutes=i + 1))
            _component(f"scraper_{i}", _ago(minutes=i + 1))
            _bot(self.user, f"Bot {i}", at=_ago(minutes=i + 1))
            _notif(self.user, f"Alert {i}", _ago(minutes=i + 1))

    def _queries(self, call):
        with CaptureQueriesContext(connection) as ctx:
            call()
        return len(ctx.captured_queries)

    def test_one_query_per_source_whatever_the_rows(self):
        self._seed(2)
        small = self._queries(lambda: feed.activity_events(self.user))
        for i in range(2, 9):
            _open_trade(self.user, f"T{i}", _ago(minutes=i + 1), trade_id=100 + i)
            _reject(self.user, f"Q{i}", _ago(minutes=i + 1))
            _bot(self.user, f"More {i}", at=_ago(minutes=i + 1))
        big = self._queries(lambda: feed.activity_events(self.user))
        self.assertEqual(small, big)
        self.assertLessEqual(big, len(feed.SOURCES))

    def test_a_poll_stays_under_ten_queries(self):
        """A poll, not a sign-in: the session's first request also stamps
        presence and saves the session (middleware, not this door), so the
        count is taken on the second, which is what the drawer sends every
        20 s — the session, the user, the investor check and the six
        sources."""
        self._seed(5)
        self.client.get(URL)
        n = self._queries(lambda: self.assertEqual(
            self.client.get(URL).status_code, 200))
        self.assertLessEqual(n, 10)

    def test_a_source_that_raises_costs_only_itself(self):
        _notif(self.user, "Still here", _ago(minutes=1))
        _component("scraper_fred", _ago(minutes=2))
        broken = tuple((name, (lambda *a: 1 / 0) if name == "pipelines" else build)
                       for name, build in feed.SOURCES)
        with patch.object(feed, "SOURCES", broken):
            with self.assertLogs("dashboard.activity_feed", level="WARNING") as logs:
                r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([e["title"] for e in r.json()["events"]], ["Still here"])
        self.assertIn("pipelines unavailable", "\n".join(logs.output))


# ── 4. the markup ────────────────────────────────────────────────────────

class TheDrawerMarkupTests(TestCase):

    def _page(self, staff):
        self.client.force_login(_user("act_page_%s" % int(staff), staff=staff))
        r = self.client.get("/command/")
        self.assertEqual(r.status_code, 200)
        return r.content.decode("utf-8", "replace")

    def test_staff_get_the_drawer_after_the_rail(self):
        body = self._page(True)
        self.assertEqual(body.count('id="svActivity"'), 1)
        self.assertIn('<aside class="sv-activity" id="svActivity" '
                      'data-feed-url="/api/activity/feed/" '
                      'aria-label="Sauron activity">', body)
        self.assertGreater(body.index('id="svActivity"'), body.index('id="signalsRail"'))
        self.assertGreater(body.index('id="svActivity"'), body.index('id="railWatch"'))
        for s in ('class="sv-activity-tab"', 'aria-expanded="false"',
                  'aria-controls="svActivityPanel"', 'id="svActivityPanel"',
                  '<ol class="sv-activity-list" id="svActivityList" aria-live="polite">',
                  'id="svActivityBadge" hidden', ">ACTIVITY<",
                  'class="sv-loading"'):
            self.assertIn(s, body, s)
        chips = re.findall(r'data-filter="(\w+)" aria-pressed="(true|false)">([^<]+)<', body)
        self.assertEqual(chips, [
            ("all", "true", "All"), ("trade", "false", "Trades"),
            ("gate", "false", "Gates"), ("ai", "false", "AI"),
            ("pipeline", "false", "Pipelines"), ("bot", "false", "Bots"),
            ("alert", "false", "Alerts")])
        self.assertTrue(set(k for k, _p, _w in chips[1:]) <= set(feed.KINDS))

    def test_no_one_else_gets_the_drawer_or_its_door(self):
        body = self._page(False)
        self.assertNotIn('id="svActivity"', body)
        self.assertNotIn(URL, body)
        self.assertNotIn("sv-activity-tab\"", body)

    def test_the_shell_keeps_one_live_url_and_no_fast_timer(self):
        """tests/test_headband_truth.py's rule, with the drawer in the page:
        its door rides a data- attribute, never a second LIVE_URL."""
        self.client.force_login(_user("act_shell", staff=True))
        body = self.client.get("/signals/").content.decode("utf-8", "replace")
        self.assertIn('id="svActivity"', body)
        self.assertEqual(body.count("var LIVE_URL ="), 1)
        self.assertNotIn("{#", body)
        live = self.client.get("/getting-started/", HTTP_HOST="127.0.0.1")
        live = live.content.decode("utf-8", "replace")
        self.assertIn('id="svActivity"', live)
        self.assertNotRegex(live, r'hx-trigger="[^"]*every ')

    def test_the_partial_is_one_template_with_no_script(self):
        src = PARTIAL.read_text(encoding="utf-8")
        self.assertNotIn("<script", src)
        self.assertNotIn("<style", src)
        self.assertIn("{% url 'activity_feed' %}", src)


# ── 5. the shell's wiring ────────────────────────────────────────────────

class TheWiringTests(SimpleTestCase):

    def setUp(self):
        self.base = _read("templates", "base.html")

    def test_the_sheet_loads_once_after_the_motion_layer_before_the_phone_tier(self):
        link = '<link rel="stylesheet" href="{% static \'css/sv-activity.css\' %}">'
        self.assertEqual(self.base.count("'css/sv-activity.css'"), 1)
        self.assertIn(link, self.base)
        at = self.base.index("'css/sv-activity.css'")
        for sheet in ("'css/sauron.css'", "'css/sv-overlay.css'",
                      "'css/sv-tour.css'", "'css/sv-motion.css'"):
            self.assertGreater(at, self.base.index(sheet), sheet)
        self.assertLess(at, self.base.index("'css/sv-responsive.css'"))
        self.assertLess(at, self.base.index("{% block extra_css %}"))

    def test_the_script_loads_once_deferred_in_the_head(self):
        self.assertEqual(self.base.count("'js/sv-activity.js'"), 1)
        self.assertIn('<script src="{% static \'js/sv-activity.js\' %}" defer></script>',
                      self.base)
        at = self.base.index("'js/sv-activity.js'")
        self.assertGreater(at, self.base.index("'js/sv-motion.js'"))
        self.assertLess(at, self.base.index("</head>"))

    def test_the_partial_is_included_for_staff_right_after_the_rail(self):
        inc = ('{% if user.is_staff %}{% include "_partials/activity_drawer.html" %}'
               '{% endif %}')
        self.assertEqual(self.base.count("activity_drawer.html"), 1)
        self.assertIn(inc, self.base)
        rail = self.base.index('<div class="signals-rail" id="signalsRail">')
        self.assertGreater(self.base.index(inc), rail)
        # Before the next script: nothing sits between the rail and it.
        between = self.base[self.base.index('id="railWatchBody"'):self.base.index(inc)]
        self.assertNotIn("<script", between)

    def test_the_files_exist(self):
        for path in (JS, SHEET, PARTIAL):
            self.assertTrue(path.exists(), path)


# ── 6. the sheet and the ladder ──────────────────────────────────────────

class TheSheetTests(SimpleTestCase):

    def setUp(self):
        self.css = re.sub(r"/\*.*?\*/", "", SHEET.read_text(encoding="utf-8"), flags=re.S)
        self.ladder = _read("static", "css", "sv-overlay.css")
        self.phone = re.sub(r"/\*.*?\*/", "", _read("static", "css", "sv-responsive.css"),
                            flags=re.S)

    def _rule(self, selector):
        m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(m, selector)
        return " ".join(m.group(1).split())

    def test_the_drawer_rung_sits_between_the_chrome_and_the_rail(self):
        z = {k: int(v) for k, v in re.findall(r"--z-([a-z-]+):\s*(\d+)", self.ladder)}
        self.assertLess(z["chrome"], z["drawer"])
        self.assertLess(z["drawer"], z["rail"])
        self.assertEqual(self.ladder.count("--z-drawer:"), 1)

    def test_the_drawer_stands_under_the_rail_and_slides_out_of_it(self):
        body = self._rule(".sv-activity")
        for decl in ("position: fixed;", "top: var(--topbar-height);", "bottom: 0;",
                     "right: 44px;", "width: 360px;", "z-index: var(--z-drawer);",
                     "transform: translateX(100%);", "transition: transform .3s"):
            self.assertIn(decl, body, decl)
        self.assertIn("transform: none;", self._rule(".sv-activity.open"))
        self.assertRegex(self.css, r"@media \(min-width: 769px\) \{\s*"
                                   r"body:has\(\.signals-rail\.open\) \.sv-activity "
                                   r"\{ right: 280px; \}")

    def test_the_tab_hangs_off_the_left_edge_below_the_rail_toggle(self):
        body = self._rule(".sv-activity-tab")
        for decl in ("position: absolute;", "left: -28px;", "width: 28px;",
                     "height: 112px;", "top: calc(50% + 16px);",
                     "border-radius: 8px 0 0 8px;"):
            self.assertIn(decl, body, decl)

    def test_every_z_index_is_a_rung_and_no_colour_is_hex(self):
        for z in re.findall(r"z-index\s*:\s*([^;]+);", self.css):
            self.assertRegex(z.strip(), r"^(calc\()?var\(--z-", z)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", self.css), [])
        self.assertNotRegex(self.css, r"rgba?\(")

    def test_reduced_motion_switches_the_drawer_off(self):
        m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*)\}\s*$",
                      self.css, re.S)
        self.assertIsNotNone(m)
        block = m.group(1)
        for sel in (".sv-activity,", ".sv-activity-panel", ".sv-activity-tab",
                    ".sv-act-new", ".sv-activity-dot.live"):
            self.assertIn(sel, block, sel)
        self.assertIn("transition: none", block)
        self.assertIn("animation: none", block)
        self.assertNotRegex(self.css, r"animation[^;{}]*\b(forwards|both)\b")

    def test_the_phone_tier_hides_it_on_the_rails_own_line(self):
        line = re.search(r"^\s*([^{\n]*\.signals-rail[^{\n]*)\{ display: none !important; \}",
                         self.phone, re.M)
        self.assertIsNotNone(line)
        hidden = [s.strip() for s in line.group(1).split(",")]
        for sel in (".signals-rail", ".rail-toggle-btn", ".sv-activity",
                    ".sv-activity-tab"):
            self.assertIn(sel, hidden)


# ── 7. the script ────────────────────────────────────────────────────────

class TheScriptTests(SimpleTestCase):

    def setUp(self):
        self.js = JS.read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", self.js, flags=re.S)
        self.code = re.sub(r"(?m)^\s*//.*$", "", code)

    def test_no_socket_no_tag_no_second_live_url(self):
        for word in ("new WebSocket", "{%", "{{", "var LIVE_URL"):
            self.assertNotIn(word, self.js, word)

    def test_no_server_string_goes_through_innerhtml(self):
        self.assertNotRegex(self.code, r"innerHTML\s*=")
        self.assertNotIn("insertAdjacentHTML", self.code)
        self.assertNotIn("outerHTML", self.code)
        self.assertIn("textContent", self.code)

    def test_every_storage_access_is_fenced(self):
        lines = [ln for ln in self.code.splitlines() if "localStorage" in ln]
        self.assertTrue(lines)
        for ln in lines:
            self.assertIn("try {", ln, ln)
        self.assertIn("'sauron_activity_open'", self.code)

    def test_it_follows_the_house_polling_rules(self):
        for word in ("data-feed-url", "sv:eye-event", "sv:pin-unlocked",
                     "visibilitychange", "document.hidden", "r.status === 423",
                     "r.redirected", "/json/i.test(type)", "POLL_MS = 20000",
                     "EVENT_DELAY_MS = 800", "MAX_ROWS = 200", "aria-expanded",
                     "'Escape'", "prefers-reduced-motion", "encodeURIComponent",
                     "fill_open", "fill_close", "gate_reject", "notification"):
            self.assertIn(word, self.code, word)
        self.assertNotIn("setInterval(fetchFeed", self.code)

    def test_it_parses(self):
        from tests.test_inline_js_parses import NODE, _parse_all
        if NODE is None:
            self.skipTest("node is not installed on this machine")
        self.assertEqual(_parse_all([{"label": JS.name, "source": self.js}]), [])
