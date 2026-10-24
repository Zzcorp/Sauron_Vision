"""The Mind's memory of a pause, and the three ways it ends (2026-10-24).

A `rule_state` KnowledgeNode is the Mind's memory of a pause or a watch on
one rule. A pause blocks every bot entry of that rule, paper and live,
before the stage, proof and posture gates (bot_program/asset_engine/base.py,
the BRAIN_PAUSED skip). Before this, the memory could never end: a repeated
status was a no-op, a later "active" was dropped, nothing expired, and the
operator could not clear one short of the ORM.

The contract (brain/context.py's docstring):

* the scheduled 03:00 consolidation is the only pass that releases, and
  only from a fresh report: a pause the report repeats is re-affirmed in
  place (no new version), an "active" (or a "watch" for a pause) releases
  it, and three fresh nights in a row that no longer name it release it,
  one miss a night and once per report; every release is a written
  version, an audit row and one staff notice naming each rule's stage,
  even when a later step of the pass raises;
* a night with no fresh report releases nothing and counts nothing, and
  the Mind's last report of the past day may still add or tighten: a
  Mind that is down keeps its pauses (critique H2), and the reader never
  ages a node out on its own (critique H1);
* the "Run consolidation now" button never releases or counts (critique
  H3), and neither does any run within 20 hours of a releasing pass (the
  admin's "Run selected tasks");
* a superuser may clear one pause on /knowledge/ with the trading PIN,
  an ACT door (critique H5);
* the stricter of the node and a fresh report wins (D3).

Run with:  python manage.py test tests.test_mind_rule_state_contract
"""
import io
from datetime import timedelta
from decimal import Decimal
from unittest import mock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.management import call_command
from django.db.models import F
from django.test import TestCase
from django.utils import timezone

from tests.test_desk_seam import ROUTER, _client, _config, _signal, _user
from tests.test_no_account_figures_broadcast import FIGURES
from tests.test_switch_pin import TEST_PIN, WRONG_PIN, _set_pin

NOTIFY = "bot_program.notifications.notify_staff"


def _node(rule, status="pause_recommended", *, days_old=0, **payload):
    from brain.knowledge_models import KnowledgeNode
    n = KnowledgeNode.upsert(kind="rule_state", key=rule,
                             payload={"status": status, **payload},
                             confidence=0.7, source="sauron_mind")
    if days_old:
        KnowledgeNode.objects.filter(pk=n.pk).update(
            created_at=timezone.now() - timedelta(days=days_old))
        n.refresh_from_db()
    return n


def _current(rule):
    from brain.knowledge_models import KnowledgeNode
    return KnowledgeNode.current("rule_state", rule)


def _report(overlay, *, age_minutes=30, venues=None, **kw):
    from brain.models import BrainReport
    fields = dict(regime_label="risk_off", regime_confidence=0.7,
                  rule_status_overlay=overlay,
                  rule_status_venue=venues or {})
    fields.update(kw)
    r = BrainReport.objects.create(**fields)
    BrainReport.objects.filter(pk=r.pk).update(
        created_at=timezone.now() - timedelta(minutes=age_minutes))
    r.refresh_from_db()
    return r


def _a_day_passes():
    """Every stored time the rule pass reads moves a day back: the
    reports, the nodes, the runs, and each node's last counted miss."""
    from brain.knowledge_models import ConsolidationRun, KnowledgeNode
    from brain.models import BrainReport
    day = timedelta(days=1)
    BrainReport.objects.update(created_at=F("created_at") - day)
    KnowledgeNode.objects.update(created_at=F("created_at") - day)
    ConsolidationRun.objects.update(started_at=F("started_at") - day,
                                    finished_at=F("finished_at") - day)
    for n in KnowledgeNode.objects.filter(kind="rule_state"):
        payload = dict(n.payload or {})
        if payload.get("last_missed_at"):
            from brain.context import _parse_iso
            payload["last_missed_at"] = (
                _parse_iso(payload["last_missed_at"]) - day).isoformat()
            KnowledgeNode.objects.filter(pk=n.pk).update(payload=payload)


def _night(overlay=None, *, fresh=True, releases=True, venues=None):
    """One scheduled 03:00 pass: yesterday moves a day back, the night's
    report lands (fresh: 30 minutes old; else 3 hours), and the
    consolidation runs as the beat runs it."""
    from brain.consolidation import consolidate_now
    _a_day_passes()
    if overlay is not None:
        _report(overlay, age_minutes=30 if fresh else 180, venues=venues)
    with patch(NOTIFY) as notify:
        result = consolidate_now(releases=releases)
    return result, notify


def _audit(kind):
    from bot_program.audit_models import AuditLogEntry
    return list(AuditLogEntry.objects.filter(kind=kind).order_by("id"))


# ── the scheduled pass ─────────────────────────────────────────────────────

class TheNightlyPassIsTheOnlyWriterTests(TestCase):

    def test_an_active_report_supersedes_a_pause_with_allow(self):
        from brain.context import brain_rule_advisory
        _node("rs_active")
        result, notify = _night({"rs_active": "active"})
        node = _current("rs_active")
        self.assertEqual(node.version, 2)
        self.assertEqual(node.payload["status"], "allow")
        self.assertIn("active", node.payload["why"])
        self.assertEqual(brain_rule_advisory("rs_active"), ("allow", ""))
        self.assertIn("released 1", result["notes"])
        rows = _audit("rule_state_release")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["rule_name"], "rs_active")
        self.assertEqual(rows[0].data["was_status"], "pause_recommended")
        notify.assert_called_once()

    def test_a_rule_the_mind_stops_naming_is_released_after_three_fresh_nights(self):
        from brain.context import brain_rule_advisory, rule_state_view
        _node("rs_gone")
        for night, misses in ((1, 1), (2, 2)):
            _, notify = _night({"rs_other": "watch"})
            node = _current("rs_gone")
            self.assertEqual(node.version, 1, night)
            self.assertEqual(rule_state_view(node)["misses"], misses)
            self.assertEqual(brain_rule_advisory("rs_gone")[0],
                             "pause_recommended", night)
            notify.assert_not_called()
        _, notify = _night({"rs_other": "watch"})
        node = _current("rs_gone")
        self.assertEqual(node.version, 2)
        self.assertEqual(node.payload["status"], "allow")
        self.assertIn("not named", node.payload["why"])
        self.assertEqual(brain_rule_advisory("rs_gone"), ("allow", ""))
        notify.assert_called_once()
        self.assertIn("rs_gone", notify.call_args.kwargs["body"])

    def test_an_empty_overlay_releases_nothing_in_one_night(self):
        """A guard (critique L1): one empty or malformed overlay counts one
        miss at most, never a release."""
        from brain.context import brain_rule_advisory
        _node("rs_empty")
        _night({})
        self.assertEqual(_current("rs_empty").version, 1)
        self.assertEqual(brain_rule_advisory("rs_empty")[0],
                         "pause_recommended")

    def test_a_repeated_status_is_reaffirmed_in_place_and_never_released(self):
        from brain.context import brain_rule_advisory, rule_state_view
        from brain.knowledge_models import KnowledgeNode
        _night({"rs_kept": "pause_recommended"},
               venues={"rs_kept": "live"})
        first = _current("rs_kept")
        n_rows = KnowledgeNode.objects.count()
        for _ in range(5):
            result, _ = _night({"rs_kept": "pause_recommended"},
                               venues={"rs_kept": "live"})
            self.assertIn("re-affirmed 1", result["notes"])
        node = _current("rs_kept")
        self.assertEqual(node.pk, first.pk)
        self.assertEqual(node.version, 1)
        self.assertEqual(KnowledgeNode.objects.count(), n_rows)
        view = rule_state_view(node)
        self.assertEqual(view["misses"], 0)
        self.assertLess(view["age_hours"], 1.0)
        self.assertEqual(brain_rule_advisory("rs_kept")[0],
                         "pause_recommended")

    def test_a_night_without_any_report_of_the_past_day_writes_nothing(self):
        from brain.knowledge_models import KnowledgeNode
        _report({"rs_ancient": "pause_recommended"},
                age_minutes=26 * 60, venues={"rs_ancient": "live"})
        result, _ = _night(None)
        self.assertIsNone(_current("rs_ancient"))
        self.assertEqual(KnowledgeNode.objects.filter(
            kind="rule_state").count(), 0)
        self.assertIn("no fresh report, nothing re-affirmed or released",
                      result["notes"])

    def test_three_nights_without_a_fresh_report_keep_the_pause(self):
        """Critique H2: a Mind that is down (spend guard, feed gate,
        provider) keeps its pauses; the clock does not run."""
        from brain.context import brain_rule_advisory, rule_state_view
        _node("rs_outage")
        for _ in range(3):
            _night({"rs_other": "watch"}, fresh=False)
            _night(None)
        node = _current("rs_outage")
        self.assertEqual(node.version, 1)
        self.assertEqual(rule_state_view(node)["misses"], 0)
        self.assertEqual(brain_rule_advisory("rs_outage")[0],
                         "pause_recommended")
        _night({"rs_other": "watch"})
        self.assertEqual(rule_state_view(_current("rs_outage"))["misses"], 1)

    def test_the_node_carries_its_evidence_venue(self):
        from brain.context import rule_state_view
        _night({"rs_venue": "pause_recommended"},
               venues={"rs_venue": "live"})
        node = _current("rs_venue")
        self.assertEqual(node.payload["venue"], "live")
        self.assertEqual(rule_state_view(node)["venue"], "live")

    def test_a_watch_after_a_pause_is_a_release_and_is_announced(self):
        _node("rs_soft")
        _, notify = _night({"rs_soft": "watch"})
        node = _current("rs_soft")
        self.assertEqual(node.payload["status"], "watch")
        self.assertEqual(len(_audit("rule_state_release")), 1)
        notify.assert_called_once()

    def test_the_release_names_each_rules_stage_and_no_figure(self):
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name="rs_live", status="active",
                                   promotion_stage="live_full")
        _node("rs_live")
        _node("rs_paper")
        _, notify = _night({"rs_live": "active", "rs_paper": "active"})
        notify.assert_called_once()
        kw = notify.call_args.kwargs
        self.assertIn("2", kw["title"])
        self.assertIn("rs_live", kw["body"])
        self.assertIn("live_full", kw["body"])
        self.assertIn("real money", kw["body"])
        self.assertIn("rs_paper", kw["body"])
        self.assertIn("no promotion record", kw["body"])
        for row in _audit("rule_state_release"):
            self.assertIn("promotion_stage", row.data)
        for figure in FIGURES:
            self.assertNotIn(figure, kw["body"])


class AManualRunNeverReleasesTests(TestCase):
    """Critique H3: the staff "Run consolidation now" button has no PIN,
    so it may add and re-affirm, never release."""

    def test_a_manual_consolidation_run_never_releases(self):
        from brain.consolidation import consolidate_now
        from brain.context import brain_rule_advisory
        _node("rs_manual")
        _node("rs_manual_watch", "pause_recommended")
        _report({"rs_manual": "active", "rs_manual_watch": "watch",
                 "rs_new": "pause_recommended"}, venues={"rs_new": "live"})
        with patch(NOTIFY) as notify:
            for _ in range(4):
                result = consolidate_now()
        self.assertEqual(_current("rs_manual").payload["status"],
                         "pause_recommended")
        self.assertEqual(_current("rs_manual_watch").payload["status"],
                         "pause_recommended")
        self.assertEqual(_current("rs_new").payload["status"],
                         "pause_recommended")
        self.assertEqual(brain_rule_advisory("rs_manual")[0],
                         "pause_recommended")
        self.assertEqual(_audit("rule_state_release"), [])
        notify.assert_not_called()
        self.assertIn("manual", result["notes"])

    def test_the_button_runs_without_releases_and_the_beat_with_them(self):
        from brain.tasks import run_consolidation
        staff = User.objects.create_user(username="rs_btn", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        _node("rs_button")
        _report({"rs_button": "active"})
        with patch(NOTIFY):
            r = self.client.post("/consolidation/run/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_current("rs_button").payload["status"],
                         "pause_recommended")
        with patch(NOTIFY):
            run_consolidation(manual=True)
        self.assertEqual(_current("rs_button").payload["status"],
                         "pause_recommended")
        with patch(NOTIFY):
            run_consolidation()
        self.assertEqual(_current("rs_button").payload["status"], "allow")

    def test_the_button_dispatches_the_task_as_manual(self):
        staff = User.objects.create_user(username="rs_btn2", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        with patch("dashboard.run_async.maybe_dispatch_async",
                   return_value=None) as dispatch, patch(NOTIFY):
            self.client.post("/consolidation/run/")
        self.assertEqual(dispatch.call_args.kwargs.get("kwargs"),
                         {"manual": True})


# ── the reader ─────────────────────────────────────────────────────────────

class TheReaderNeverAgesANodeOutTests(TestCase):
    """Guards: each of these holds at 6e30161 too. They pin that the
    reader's restructure keeps them, and they are what the plan's
    reader-side age-out would have broken (critique H1, H2)."""

    def test_deploy_releases_nothing_before_the_first_nightly_pass(self):
        """Critique H1: a 90-day-old pause the Mind still names, trust
        low: the node holds (not softened, not aged out)."""
        from brain.context import brain_rule_advisory
        _node("rs_old", days_old=90,
              as_of=(timezone.now() - timedelta(days=90)).isoformat())
        _report({"rs_old": "pause_recommended"}, venues={"rs_old": "live"})
        with patch("brain.context._brain_trust_score", return_value=0.2):
            status, why = brain_rule_advisory("rs_old")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("knowledge_graph rule_state v1", why)

    def test_an_old_node_with_no_report_still_blocks(self):
        from brain.context import brain_rule_advisory
        _node("rs_alone", days_old=30)
        self.assertEqual(brain_rule_advisory("rs_alone")[0],
                         "pause_recommended")

    def test_a_node_read_error_falls_through_to_the_report_path(self):
        from brain.context import brain_rule_advisory
        _report({"rs_err": "pause_recommended"}, venues={"rs_err": "live"})
        with patch("brain.knowledge_models.KnowledgeNode.current",
                   side_effect=RuntimeError("db")):
            status, why = brain_rule_advisory("rs_err")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("brain_report", why)
        with patch("brain.knowledge_models.KnowledgeNode.current",
                   side_effect=RuntimeError("db")):
            self.assertEqual(brain_rule_advisory("rs_none"), ("allow", ""))

    def test_a_report_read_error_still_answers_from_the_node(self):
        from brain.context import brain_rule_advisory
        _node("rs_rep_err")
        with patch("brain.context.get_brain_context",
                   side_effect=RuntimeError("db")):
            status, why = brain_rule_advisory("rs_rep_err")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("knowledge_graph", why)

    def test_a_released_node_falls_through_to_a_fresh_report_pause_softened_by_trust(self):
        from brain.context import brain_rule_advisory
        _node("rs_rel", "allow")
        _report({"rs_rel": "pause_recommended"}, venues={"rs_rel": "live"})
        self.assertEqual(brain_rule_advisory("rs_rel")[0],
                         "pause_recommended")
        with patch("brain.context._brain_trust_score", return_value=0.2):
            status, why = brain_rule_advisory("rs_rel")
        self.assertEqual(status, "watch")
        self.assertIn("softened", why)


class TheStricterOneWinsTests(TestCase):
    """D3: a stale watch node no longer hides a fresh live pause."""

    def test_a_stale_watch_node_no_longer_hides_a_fresh_live_pause(self):
        from brain.context import brain_rule_advisory
        _node("rs_d3", "watch")
        _report({"rs_d3": "pause_recommended"}, venues={"rs_d3": "live"})
        status, why = brain_rule_advisory("rs_d3")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("brain_report", why)

    def test_a_pause_node_and_a_watch_report_stay_paused(self):
        """A guard: holds at 6e30161 (node first) and under D3."""
        from brain.context import brain_rule_advisory
        _node("rs_d3b")
        _report({"rs_d3b": "watch"})
        status, why = brain_rule_advisory("rs_d3b")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("knowledge_graph", why)

    def test_when_both_pause_the_reason_names_both(self):
        """Critique M2: clearing the node does not look like a failure
        while the report still pauses the rule."""
        from brain.context import brain_rule_advisory
        _node("rs_both")
        _report({"rs_both": "pause_recommended"}, venues={"rs_both": "live"})
        status, why = brain_rule_advisory("rs_both")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("knowledge_graph rule_state v1", why)
        self.assertIn("brain_report", why)


class TheEntryPathReadsARealNodeTests(TestCase):

    def test_a_pause_node_skips_the_entry_and_its_release_lets_it_through(self):
        """A guard on the real entry path: a REAL node, not a patched
        advisory (tests/test_desk_seam.py patches it)."""
        from bot_program.asset_engine import StockBot, skips
        cfg = _config(_user("rs_entry"), symbols=["RSE1"])
        _signal("RSE1", "bullish", 0.85, rule="rs_entry_rule")
        _node("rs_entry_rule")
        with patch(ROUTER, return_value=_client()) as router:
            self.assertIsNone(StockBot(cfg).scan_symbol("RSE1"))
        router.assert_not_called()
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg)["RSE1"]
        self.assertEqual(note["code"], skips.BRAIN_PAUSED)
        self.assertIn("knowledge_graph rule_state v1", note["detail"])

        _node("rs_entry_rule", "allow", why="released")
        cfg.refresh_from_db()
        with patch(ROUTER, return_value=_client()):
            StockBot(cfg).scan_symbol("RSE1")
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg).get("RSE1") or {}
        self.assertNotEqual(note.get("code"), skips.BRAIN_PAUSED)


# ── the operator's read ─────────────────────────────────────────────────────

class MindContractCommandTests(TestCase):

    def _counts(self):
        from ai_agents.models import AgentPrediction
        from bot_program.audit_models import AuditLogEntry
        from brain.knowledge_models import (ConsolidationRun, Hypothesis,
                                            KnowledgeNode)
        from brain.models import BrainReport
        return [m.objects.count() for m in (
            AgentPrediction, AuditLogEntry, ConsolidationRun, Hypothesis,
            KnowledgeNode, BrainReport)]

    def test_it_lists_every_node_with_its_effect_and_writes_nothing(self):
        from bot_program.models import AssetBotTrade
        cfg = _config(_user("rs_cmd"), symbols=["RSC1"])
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="RSC1", side="BUY",
            qty=Decimal("98765"), entry_price=Decimal("100"),
            exit_price=Decimal("150"), pnl=Decimal("4321.09"),
            status="CLOSED", paper=False, rule_name="rs_cmd_pause")
        _node("rs_cmd_pause", venue="live")
        _node("rs_cmd_watch", "watch")
        _node("rs_cmd_allow", "allow")
        _report({"rs_cmd_pause": "pause_recommended"},
                venues={"rs_cmd_pause": "live"}, age_minutes=50)
        before = self._counts()
        out = io.StringIO()
        call_command("mind_contract", stdout=out)
        text = out.getvalue()
        self.assertEqual(before, self._counts())
        self.assertIn("75 min", text)
        self.assertIn("rs_cmd_pause", text)
        self.assertIn("blocks bot entries (paper and live)", text)
        self.assertIn("rs_cmd_watch", text)
        self.assertIn("watch only", text)
        self.assertIn("live", text)
        for figure in FIGURES:
            self.assertNotIn(figure, text)
        self.assertEqual(text.strip().splitlines()[-1],
                         "Clear a node at /knowledge/ with your trading PIN.")

    def test_nodes_alone(self):
        _node("rs_cmd_only")
        out = io.StringIO()
        call_command("mind_contract", "nodes", stdout=out)
        self.assertIn("rs_cmd_only", out.getvalue())


# ── the clear: an ACT door ─────────────────────────────────────────────────

def _clear_url(rule):
    return f"/knowledge/rule_state/{rule}/clear/"


class KnowledgeClearIsAnActDoorTests(TestCase):

    def setUp(self):
        from core import security
        from core.platform_control import seed_components
        cache.clear()
        security._login_attempts.clear()
        self.addCleanup(security._login_attempts.clear)
        seed_components()
        self.admin = User.objects.create_superuser(
            "rs_admin", "rs_admin@example.test", "pw-of-the-test")
        _set_pin(self.admin)
        self.client.force_login(self.admin)
        self.node = _node("rs_clear")

    def _post(self, pin=None, rule="rs_clear"):
        data = {} if pin is None else {"pin": pin}
        with patch(NOTIFY):
            return self.client.post(_clear_url(rule), data)

    def _msgs(self, r):
        return " ".join(str(m) for m in get_messages(r.wsgi_request))

    def test_no_pin_is_refused_and_writes_nothing(self):
        r = self._post()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_current("rs_clear").version, 1)
        self.assertIn("trading PIN", self._msgs(r))
        self.assertEqual(_audit("rule_state_clear"), [])

    def test_a_wrong_pin_is_counted_and_writes_nothing(self):
        from core.trading_pin import ATTEMPTS_KEY
        r = self._post(WRONG_PIN)
        self.assertEqual(_current("rs_clear").version, 1)
        self.assertEqual(int(self.client.session.get(ATTEMPTS_KEY) or 0), 1)
        self.assertEqual(_audit("rule_state_clear"), [])
        self.assertNotIn(WRONG_PIN, self._msgs(r))

    def test_the_fifth_wrong_answer_ends_the_session(self):
        for _ in range(5):
            self._post(WRONG_PIN)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(_current("rs_clear").version, 1)

    def test_a_stale_login_mark_is_refused(self):
        _set_pin(self.admin, WRONG_PIN)
        r = self._post(WRONG_PIN)
        self.assertEqual(_current("rs_clear").version, 1)
        self.assertIn("log in again", self._msgs(r))

    def test_the_right_pin_writes_allow_and_one_audit_row(self):
        from core.trading_pin import ATTEMPTS_KEY
        r = self._post(TEST_PIN)
        node = _current("rs_clear")
        self.assertEqual(node.version, 2)
        self.assertEqual(node.payload["status"], "allow")
        self.assertIn("operator", node.source_agents)
        rows = _audit("rule_state_clear")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["rule_name"], "rs_clear")
        self.assertEqual(rows[0].data["was_status"], "pause_recommended")
        self.assertEqual(rows[0].data["was_version"], 1)
        self.assertEqual(rows[0].user, self.admin)
        blob = str(rows[0].data)
        self.assertNotIn(TEST_PIN, blob)
        self.assertNotIn("pin", blob.lower())
        self.assertEqual(int(self.client.session.get(ATTEMPTS_KEY) or 0), 0)
        msg = self._msgs(r)
        self.assertIn("does not mute the Mind", msg)

    def test_get_is_405(self):
        r = self.client.get(_clear_url("rs_clear"))
        self.assertEqual(r.status_code, 405)
        self.assertEqual(_current("rs_clear").version, 1)

    def test_a_staff_login_that_is_not_superuser_writes_nothing(self):
        staff = User.objects.create_user(username="rs_staff", password="x",
                                         is_staff=True)
        _set_pin(staff)
        self.client.force_login(staff)
        r = self._post(TEST_PIN)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(_current("rs_clear").version, 1)

    def test_a_plain_login_writes_nothing(self):
        self.client.force_login(User.objects.create_user(
            username="rs_plain", password="x"))
        r = self._post(TEST_PIN)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(_current("rs_clear").version, 1)

    def test_an_unknown_key_is_404_and_writes_nothing(self):
        from django.urls import resolve
        from brain.knowledge_models import KnowledgeNode
        # the door exists: the 404 below is the key's, not the route's
        self.assertEqual(resolve(_clear_url("rs_nobody")).url_name,
                         "knowledge_rule_state_clear")
        n = KnowledgeNode.objects.count()
        r = self._post(TEST_PIN, rule="rs_nobody")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(KnowledgeNode.objects.count(), n)

    def test_a_watch_node_is_404_and_writes_nothing(self):
        """Critique H5: clearing a watch would UNMASK a report pause and
        add a block; it is no release, so no door."""
        from django.urls import resolve
        self.assertEqual(resolve(_clear_url("rs_watch_only")).url_name,
                         "knowledge_rule_state_clear")
        _node("rs_watch_only", "watch")
        r = self._post(TEST_PIN, rule="rs_watch_only")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(_current("rs_watch_only").version, 1)

    def test_after_a_clear_a_fresh_report_pause_still_blocks(self):
        from brain.context import brain_rule_advisory
        _report({"rs_clear": "pause_recommended"},
                venues={"rs_clear": "live"})
        r = self._post(TEST_PIN)
        self.assertEqual(_current("rs_clear").payload["status"], "allow")
        self.assertIn("still pauses", self._msgs(r))
        status, why = brain_rule_advisory("rs_clear")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("brain_report", why)

    def test_the_next_scheduled_pass_that_sees_pause_writes_it_again(self):
        from brain.context import brain_rule_advisory
        self._post(TEST_PIN)
        _night({"rs_clear": "pause_recommended"},
               venues={"rs_clear": "live"})
        node = _current("rs_clear")
        self.assertEqual(node.version, 3)
        self.assertEqual(node.payload["status"], "pause_recommended")
        self.assertEqual(brain_rule_advisory("rs_clear")[0],
                         "pause_recommended")


class TheKnowledgePageShowsEachRuleStatesEffectTests(TestCase):

    def setUp(self):
        _node("rs_page_pause", venue="live")
        _node("rs_page_watch", "watch")

    def test_any_login_sees_the_effect_and_no_form(self):
        self.client.force_login(User.objects.create_user(
            username="rs_page_plain", password="x"))
        html = self.client.get("/knowledge/").content.decode()
        self.assertIn("blocks bot entries (paper and live)", html)
        self.assertIn("watch only", html)
        self.assertNotIn(_clear_url("rs_page_pause"), html)
        self.assertNotIn('name="pin"', html)

    def test_a_superuser_gets_the_form_on_a_pause_alone(self):
        self.client.force_login(User.objects.create_superuser(
            "rs_page_admin", "rs_page_admin@example.test", "x"))
        html = self.client.get("/knowledge/").content.decode()
        self.assertIn(_clear_url("rs_page_pause"), html)
        self.assertNotIn(_clear_url("rs_page_watch"), html)
        self.assertIn('name="pin"', html)

    def test_the_page_shows_what_the_rule_does_now(self):
        """Critique M2: the node's own effect and the rule's, side by side
        (a watch node under a fresh report pause is a blocked rule)."""
        _report({"rs_page_watch": "pause_recommended"},
                venues={"rs_page_watch": "live"})
        self.client.force_login(User.objects.create_user(
            username="rs_page_now", password="x"))
        r = self.client.get("/knowledge/")
        rows = {row["key"]: row for row in r.context["rule_rows"]}
        self.assertEqual(rows["rs_page_watch"]["now"], "pause_recommended")
        self.assertEqual(rows["rs_page_watch"]["view"]["status"], "watch")


# ── review fixes (2026-10-24) ──────────────────────────────────────────────

def _misses(rule):
    from brain.context import rule_state_view
    return rule_state_view(_current(rule))["misses"]


class OneMissANightTests(TestCase):
    """Review F1/F5: a miss used to be counted on every run asked to
    release, so three "Run selected tasks" in the admin (the stored kwargs
    are {}, so releases on) against one fresh report released every pause
    the report did not name, with no PIN. Now a miss counts once per
    report and once per night, and a releasing pass runs once a night."""

    def test_three_bare_runs_against_one_report_count_one_miss(self):
        from brain.context import brain_rule_advisory
        from brain.knowledge_models import ConsolidationRun
        from brain.tasks import run_consolidation
        _node("rs_live", venue="live")
        _report({"other_rule": "watch"}, age_minutes=10)
        with patch(NOTIFY) as notify:
            for _ in range(3):
                run_consolidation.apply(kwargs={}).get()
        node = _current("rs_live")
        self.assertEqual(node.version, 1)
        self.assertEqual(node.payload["status"], "pause_recommended")
        self.assertEqual(_misses("rs_live"), 1)
        self.assertEqual(brain_rule_advisory("rs_live")[0],
                         "pause_recommended")
        self.assertEqual(_audit("rule_state_release"), [])
        notify.assert_not_called()
        notes = [r.notes for r in ConsolidationRun.objects.order_by("id")]
        self.assertIn("releasing pass", notes[0])
        for later in notes[1:]:
            self.assertIn("a releasing pass ran 0 h ago: this run releases "
                          "nothing", later)

    def test_a_miss_counts_once_per_report(self):
        """The per-node guard on its own (the run's spacing patched out)."""
        from brain.consolidation import consolidate_now
        _node("rs_once")
        _report({"rs_other": "watch"})
        with patch("brain.consolidation._releasing_pass_hold",
                   return_value=None), patch(NOTIFY) as notify:
            for _ in range(3):
                consolidate_now(releases=True)
        self.assertEqual(_misses("rs_once"), 1)
        self.assertEqual(_current("rs_once").version, 1)
        notify.assert_not_called()

    def test_a_report_fresh_over_two_passes_counts_one_miss(self):
        """A beat slower than a day keeps one report fresh across two
        passes: it still counts once (the night spacing alone would let the
        second pass count it again)."""
        from tests.test_mind_contract import _beat
        _node("rs_slow")
        with _beat(2 * 86400.0):
            _night({"rs_other": "watch"})
            _night(None)
        self.assertEqual(_misses("rs_slow"), 1)

    def test_a_miss_counts_once_per_night_even_on_new_reports(self):
        from brain.consolidation import consolidate_now
        _node("rs_hourly")
        with patch("brain.consolidation._releasing_pass_hold",
                   return_value=None), patch(NOTIFY) as notify:
            for minutes in (50, 30, 10):
                _report({"rs_other": "watch"}, age_minutes=minutes)
                consolidate_now(releases=True)
        self.assertEqual(_misses("rs_hourly"), 1)
        self.assertEqual(_current("rs_hourly").payload["status"],
                         "pause_recommended")
        notify.assert_not_called()

    def test_a_run_within_the_night_never_releases_on_an_active(self):
        """F5: one admin click at any hour released a pause the fresh
        report called active. It now waits for the next night's pass."""
        from brain.context import brain_rule_advisory
        from brain.tasks import run_consolidation
        _night({"rs_other": "watch"})                 # tonight's pass
        _node("rs_act")
        _report({"rs_act": "active"}, age_minutes=5)
        with patch(NOTIFY) as notify:
            result = run_consolidation.apply(kwargs={}).get()
        self.assertEqual(_current("rs_act").payload["status"],
                         "pause_recommended")
        self.assertEqual(brain_rule_advisory("rs_act")[0], "pause_recommended")
        self.assertIn("this run releases nothing", result["notes"])
        notify.assert_not_called()
        _, notify = _night({"rs_act": "active"})
        self.assertEqual(_current("rs_act").payload["status"], "allow")
        notify.assert_called_once()

    def test_an_unreadable_run_history_holds_the_release(self):
        from brain.consolidation import consolidate_now
        _node("rs_hold")
        _report({"rs_hold": "active"})
        with patch("brain.knowledge_models.ConsolidationRun.objects.filter",
                   side_effect=RuntimeError("db")), patch(NOTIFY) as notify:
            result = consolidate_now(releases=True)
        self.assertEqual(_current("rs_hold").payload["status"],
                         "pause_recommended")
        self.assertIn("could not be read", result["notes"])
        notify.assert_not_called()


class InARowMeansInARowTests(TestCase):
    """Review F15: a night that names the rule again restarts its count,
    so a pause named on nights 1 and 4 is not released on night 5."""

    def test_a_rule_named_again_restarts_its_miss_count(self):
        from brain.context import brain_rule_advisory
        _night({"rs_flap": "pause_recommended"}, venues={"rs_flap": "live"})
        _night({"rs_other": "watch"})
        _night({"rs_other": "watch"})
        self.assertEqual(_misses("rs_flap"), 2)
        _night({"rs_flap": "pause_recommended"}, venues={"rs_flap": "live"})
        self.assertEqual(_misses("rs_flap"), 0)
        _night({"rs_other": "watch"})
        _, notify = _night({"rs_other": "watch"})
        node = _current("rs_flap")
        self.assertEqual(node.version, 1)
        self.assertEqual(node.payload["status"], "pause_recommended")
        self.assertEqual(brain_rule_advisory("rs_flap")[0], "pause_recommended")
        self.assertEqual(_audit("rule_state_release"), [])
        notify.assert_not_called()


class TheButtonNeverCountsAMissTests(TestCase):
    """Review F16 (critique H3 on the miss path): the PIN-less staff button
    neither counts a miss nor releases a rule the report no longer names."""

    def test_three_presses_on_an_unnamed_pause_release_nothing(self):
        from brain.context import brain_rule_advisory
        staff = User.objects.create_user(username="rs_btn3", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        _node("rs_quiet")
        _report({"rs_other": "watch"})
        with patch(NOTIFY) as notify:
            for _ in range(3):
                self.assertEqual(
                    self.client.post("/consolidation/run/").status_code, 302)
        node = _current("rs_quiet")
        self.assertEqual(node.version, 1)
        self.assertEqual(_misses("rs_quiet"), 0)
        self.assertEqual(brain_rule_advisory("rs_quiet")[0],
                         "pause_recommended")
        self.assertEqual(_audit("rule_state_release"), [])
        notify.assert_not_called()


class AReleaseIsNeverSilentTests(TestCase):
    """Review F2/F8/F14: every release is a written version WITH an audit
    row and the staff notice. A later step of the same rule pass raising
    used to leave a written release unannounced."""

    def test_a_release_then_a_failing_touch_is_still_announced(self):
        from brain import consolidation as C
        from brain.context import brain_rule_advisory
        from brain.knowledge_models import ConsolidationRun, KnowledgeNode
        older = _node("rs_b")                         # walked second: raises
        KnowledgeNode.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=2))
        _node("rs_a", misses=2)                       # walked first: released
        _report({})
        with patch.object(C, "_touch_rule_state",
                          side_effect=RuntimeError("db hiccup")), \
                patch(NOTIFY) as notify:
            out = C.consolidate_now(releases=True)
        self.assertFalse(out["ok"])
        self.assertEqual(_current("rs_a").payload["status"], "allow")
        self.assertEqual(brain_rule_advisory("rs_a"), ("allow", ""))
        rows = _audit("rule_state_release")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["rule_name"], "rs_a")
        notify.assert_called_once()
        self.assertIn("rs_a", notify.call_args.kwargs["body"])
        # the failed pass still counts as the night's releasing pass
        self.assertIn("releasing pass", ConsolidationRun.objects.get(
            pk=out["run_id"]).notes)

    def test_a_release_between_two_touches_is_still_announced(self):
        from brain import consolidation as C
        _node("rs_zzz_touch")
        _node("rs_aaa_release", misses=2)
        _node("rs_000_touch")
        real_touch, real_write = C._touch_rule_state, C.write_rule_state
        written = []

        def write(*a, **kw):
            new = real_write(*a, **kw)
            if new is not None and a[0] == "rs_aaa_release":
                written.append(new)
            return new

        def boom(node, changes):
            if written:
                raise RuntimeError("db hiccup")
            return real_touch(node, changes)
        with patch.object(C, "_touch_rule_state", side_effect=boom), \
                patch.object(C, "write_rule_state", side_effect=write):
            result, notify = _night({"rs_other": "watch"})
        self.assertTrue(written)
        self.assertEqual(_current("rs_aaa_release").payload["status"], "allow")
        self.assertEqual(len(_audit("rule_state_release")), 1, result["notes"])
        notify.assert_called_once()


class AQuietMindKeepsItsLastPauseTests(TestCase):
    """Review F3/F6: a live pause the Mind said before it went quiet used
    to be memorised by the 03:00 pass at any age; PR2 first wrote nothing
    without a fresh report, so the pause lapsed at minute 75 and the rule
    traded live through the outage. The last report of the past day now
    adds or tightens, and never re-affirms, counts or releases."""

    def test_a_stale_live_pause_at_the_scheduled_pass_is_written(self):
        from brain.context import brain_rule_advisory
        from brain.tasks import run_consolidation
        _report({"rs_stale": "pause_recommended"}, age_minutes=180,
                venues={"rs_stale": "live"})
        with patch(NOTIFY) as notify:
            result = run_consolidation.apply().get()
        node = _current("rs_stale")
        self.assertEqual(node.payload["status"], "pause_recommended")
        self.assertEqual(node.payload["venue"], "live")
        self.assertEqual(node.version, 1)
        self.assertEqual(brain_rule_advisory("rs_stale"),
                         ("pause_recommended", "knowledge_graph rule_state v1"))
        self.assertIn("no fresh report; +1 from the last report (180 min "
                      "old), nothing re-affirmed, counted or released",
                      result["notes"])
        self.assertNotIn("releasing pass", result["notes"])
        notify.assert_not_called()

    def test_the_last_report_only_adds_or_tightens(self):
        from brain.consolidation import consolidate_now
        _node("rs_kept", days_old=1)                  # report: active
        _node("rs_soft", days_old=1)                  # report: watch
        _node("rs_tight", "watch", days_old=1)        # report: pause
        _report({"rs_kept": "active", "rs_soft": "watch",
                 "rs_tight": "pause_recommended", "rs_new": "watch"},
                age_minutes=180)
        with patch(NOTIFY) as notify:
            consolidate_now(releases=True)
        self.assertEqual(_current("rs_kept").payload["status"],
                         "pause_recommended")
        self.assertEqual(_current("rs_kept").version, 1)
        self.assertEqual(_misses("rs_kept"), 0)
        self.assertEqual(_current("rs_soft").payload["status"],
                         "pause_recommended")
        self.assertEqual(_current("rs_tight").payload["status"],
                         "pause_recommended")
        self.assertEqual(_current("rs_tight").version, 2)
        self.assertEqual(_current("rs_new").payload["status"], "watch")
        self.assertEqual(_audit("rule_state_release"), [])
        notify.assert_not_called()

    def test_a_clear_after_the_last_report_stands(self):
        _report({"rs_cleared": "pause_recommended"}, age_minutes=180)
        _node("rs_cleared", "allow", why="cleared by a superuser")
        from brain.consolidation import consolidate_now
        with patch(NOTIFY):
            consolidate_now(releases=True)
        self.assertEqual(_current("rs_cleared").payload["status"], "allow")
        self.assertEqual(_current("rs_cleared").version, 1)

    def test_the_staff_button_also_remembers_a_stale_pause(self):
        staff = User.objects.create_user(username="rs_btn4", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        _report({"rs_btn_stale": "pause_recommended"}, age_minutes=120)
        with patch(NOTIFY):
            self.client.post("/consolidation/run/")
        self.assertEqual(_current("rs_btn_stale").payload["status"],
                         "pause_recommended")


class TheStageIsNeverGuessedTests(TestCase):
    """Review F4: a failed RuleControl read used to say "no promotion
    record (paper venue only)" and real_money False."""

    RC = "signals.models_control.RuleControl.objects.filter"

    def test_an_unreadable_stage_is_said_as_unknown(self):
        from brain.consolidation import STAGE_UNREADABLE, rule_reach
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name="rs_x", status="active",
                                   promotion_stage="live_full")
        with patch(self.RC, side_effect=RuntimeError("db")):
            reach = rule_reach("rs_x")
        self.assertIsNone(reach["real_money"])
        self.assertEqual(reach["words"], STAGE_UNREADABLE)
        self.assertNotIn("paper", reach["words"])

    def test_a_release_with_an_unreadable_stage_is_never_paper_only(self):
        from brain.consolidation import _announce_releases
        with patch(self.RC, side_effect=RuntimeError("db")), \
                patch(NOTIFY) as notify:
            _announce_releases([{
                "rule_name": "rs_y", "was_status": "pause_recommended",
                "was_version": 1, "now_status": "allow", "why": "active"}])
        row = _audit("rule_state_release")[0]
        self.assertIsNone(row.data["real_money"])
        body = notify.call_args.kwargs["body"]
        self.assertIn("stage unreadable", body)
        self.assertNotIn("paper venue only", body)

    def test_a_live_small_release_is_named_real_money(self):
        """Review F20: live_small trades live at quarter size."""
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name="rs_small", status="active",
                                   promotion_stage="live_small")
        _node("rs_small")
        _, notify = _night({"rs_small": "active"})
        self.assertIn("live_small: real money",
                      notify.call_args.kwargs["body"])
        self.assertIs(_audit("rule_state_release")[0].data["real_money"], True)


class TheKeepOffDoorExistsTests(TestCase):
    """Review F7: the notice and /knowledge/ sent the operator to "the rule
    lever on /brain/", which /brain/ draws only for a rule its latest
    report names at watch or pause, never for a released rule."""

    def test_the_notice_and_the_page_name_a_door_that_exists(self):
        from brain.consolidation import KEEP_OFF_WORDS
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name="r_live", status="active",
                                   promotion_stage="live_full")
        RuleControl.objects.create(rule_name="r_quiet", status="active",
                                   promotion_stage="live_full")
        _node("r_live")
        _node("r_quiet", misses=2)
        _, notify = _night({"r_live": "active", "other": "watch"})
        body = notify.call_args.kwargs["body"]
        self.assertIn("r_live", body)
        self.assertIn("r_quiet", body)
        self.assertIn(KEEP_OFF_WORDS, body)
        self.assertIn("/promotions/", body)
        self.assertNotIn("/brain/", body)
        su = User.objects.create_superuser("rs_door", "rs_door@example.test",
                                           "pw-of-the-test")
        self.client.force_login(su)
        html = self.client.get("/promotions/").content.decode()
        for rule in ("r_live", "r_quiet"):
            self.assertIn(f'name="rule_name" value="{rule}"', html, rule)
        self.assertIn("/admin-dashboard/promotions/demote/", html)
        page = self.client.get("/knowledge/").content.decode()
        self.assertIn("/promotions/", page)
        self.assertNotIn("the rule lever on /brain/", page)


class TheContractWordsTests(TestCase):
    """Review F9: the in-product words named neither the pause-to-watch
    release nor the button and the clear as writers."""

    def test_the_page_the_command_and_the_contract_say_the_same(self):
        import brain.context
        _node("rs_words")
        self.client.force_login(User.objects.create_user(
            username="rs_words", password="x"))
        page = self.client.get("/knowledge/").content.decode()
        self.assertIn('a "watch" for a paused rule', page)
        self.assertIn("only adds and re-affirms", page)
        self.assertIn("one miss a night", page)
        out = io.StringIO()
        call_command("mind_contract", "nodes", stdout=out)
        text = out.getvalue()
        self.assertIn("'watch' for a paused rule", text)
        self.assertIn("only adds and re-affirms", text)
        self.assertIn("superuser's clear", text)
        doc = " ".join(brain.context.__doc__.split())
        self.assertIn('"active", or "watch" for a paused rule', doc)
        self.assertIn("which only adds and re-affirms", doc)
        self.assertIn("at most once in 20 hours", doc)


class TheClearRefusesAStaleReadTests(TestCase):
    """Review F18: write_rule_state's expect_pk (critique H5, a clear
    racing the 03:00 pass) and the view's "changed while you read it"."""

    def test_write_rule_state_refuses_a_caller_that_read_an_older_version(self):
        from brain.consolidation import write_rule_state
        from brain.knowledge_models import KnowledgeNode
        v1 = _node("rs_race")
        _node("rs_race", "watch")                     # the pass got there
        n = KnowledgeNode.objects.count()
        self.assertIsNone(write_rule_state(
            "rs_race", {"status": "allow"}, source="operator",
            expect_pk=v1.pk))
        self.assertEqual(KnowledgeNode.objects.count(), n)
        self.assertEqual(_current("rs_race").payload["status"], "watch")

    def test_the_view_writes_nothing_when_the_node_moved(self):
        from core import security
        from core.platform_control import seed_components
        cache.clear()
        security._login_attempts.clear()
        self.addCleanup(security._login_attempts.clear)
        seed_components()
        admin = User.objects.create_superuser("rs_moved", "rs_m@example.test",
                                              "pw-of-the-test")
        _set_pin(admin)
        self.client.force_login(admin)
        _node("rs_moved")
        with patch("brain.consolidation.write_rule_state",
                   return_value=None), patch(NOTIFY):
            r = self.client.post(_clear_url("rs_moved"), {"pin": TEST_PIN})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_current("rs_moved").version, 1)
        self.assertEqual(_audit("rule_state_clear"), [])
        msgs = " ".join(str(m) for m in get_messages(r.wsgi_request))
        self.assertIn("changed while you read it", msgs)


class TheOperatorSeesTheClearsWordsTests(TestCase):
    """Review F19: base.html renders no messages, so the /knowledge/ flash
    block is the only place a refusal or the "still pauses" warning shows."""

    def setUp(self):
        from core import security
        from core.platform_control import seed_components
        cache.clear()
        security._login_attempts.clear()
        self.addCleanup(security._login_attempts.clear)
        seed_components()
        self.admin = User.objects.create_superuser(
            "rs_flash", "rs_flash@example.test", "pw-of-the-test")
        _set_pin(self.admin)
        self.client.force_login(self.admin)
        _node("rs_flash")

    def test_the_clear_message_is_on_the_page_it_redirects_to(self):
        with patch(NOTIFY):
            r = self.client.post(_clear_url("rs_flash"), {"pin": TEST_PIN},
                                 follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("does not mute the Mind", r.content.decode())

    def test_a_refusal_is_on_the_page_too(self):
        with patch(NOTIFY):
            r = self.client.post(_clear_url("rs_flash"), {}, follow=True)
        self.assertIn("none was entered, so the pause stays",
                      r.content.decode())
        self.assertEqual(_current("rs_flash").version, 1)
