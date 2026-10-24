"""A class key in the Mind's memory blocks nothing, and says so (2026-10-24).

Before the 2026-10-15 evidence gate the Mind improvised class suffixes in
its rule_status_overlay ("bollinger_squeeze_breakout/stock",
"manual_take:forex"), and the consolidation remembered each as a
rule_state node like any other. Every reader of the Mind asks with the
BARE rule name (bot_program/asset_engine/base.py, the manual ticket,
brain/position_review.py), so such a node is read by no gate. Yet the
command, /knowledge/ and the release notice said it "blocks bot entries
(paper and live)", read its stage by the suffixed key ("no promotion
record (paper venue only)" for a live_full rule), counted its pause among
the D2 softenings and offered a PIN clear on it.

The fix is words only: nothing any gate reads changes.
brain.context.split_rule_key names a class key; the readers say it blocks
nothing and ask the bare rule for what its entries get and where it
trades; the consolidation no longer writes one, so a class node left from
before is released on its third fresh night through the usual path.

Run with:  python manage.py test tests.test_mind_class_keys
"""
import io
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from tests.test_desk_seam import ROUTER, _client, _config, _signal, _user
from tests.test_mind_rule_state_contract import (NOTIFY, _audit, _current,
                                                 _night, _node, _report)
from tests.test_switch_pin import TEST_PIN, _set_pin


def _live_full(rule):
    from signals.models import RuleControl
    return RuleControl.objects.create(rule_name=rule, status="active",
                                      promotion_stage="live_full")


def _nodes_text():
    out = io.StringIO()
    call_command("mind_contract", "nodes", stdout=out)
    return out.getvalue()


def _line_pair(text, key):
    """The node's two lines in `mind_contract nodes`."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}:"):
            return line + "\n" + lines[i + 1]
    raise AssertionError(f"no line for {key}")


# ── the helper ─────────────────────────────────────────────────────────────

class SplitRuleKeyTests(TestCase):

    def test_a_class_suffix_after_a_slash_or_a_colon(self):
        from brain.context import split_rule_key
        self.assertEqual(split_rule_key("bollinger_squeeze_breakout/stock"),
                         ("bollinger_squeeze_breakout", "stock", False))
        self.assertEqual(split_rule_key("manual_take:forex"),
                         ("manual_take", "forex", False))
        self.assertEqual(split_rule_key("golden_cross/paper"),
                         ("golden_cross", "paper", False))

    def test_any_suffix_makes_a_class_key(self):
        """No real rule name holds a "/" (the registry's slugs,
        "<parent>_evolved_vN", "generated_YYYYMMDD_<slug>"), so whatever
        the Mind put after one, the key is read by no gate."""
        from brain.context import split_rule_key
        for key, rule, suffix in (
                ("bollinger_squeeze_breakout/stocks",
                 "bollinger_squeeze_breakout", "stocks"),
                ("x/stock/live", "x", "stock/live"),
                ("manual_take:fx", "manual_take", "fx"),
                ("golden_cross/commodities", "golden_cross", "commodities"),
                ("x/live_full", "x", "live_full"),
                ("momentum/fast", "momentum", "fast")):
            self.assertEqual(split_rule_key(key), (rule, suffix, False), key)

    def test_the_bare_name_is_stripped(self):
        """A space before the separator never makes a wrong bare name for
        the advisory and the stage to be asked by."""
        from brain.context import split_rule_key
        self.assertEqual(split_rule_key("a /stock"), ("a", "stock", False))
        self.assertEqual(split_rule_key("a: forex "), ("a", "forex", False))

    def test_a_bare_name_is_read(self):
        from brain.context import split_rule_key
        self.assertEqual(split_rule_key("manual_take"),
                         ("manual_take", "", True))

    def test_a_rule_name_with_a_colon_of_its_own_stays_whole(self):
        """The TradingView webhook names its rules "tradingview:<strategy>"
        and the entry gate asks for that whole name: never a class key,
        whatever the strategy is called."""
        from brain.context import split_rule_key
        for key in ("tradingview:ema_cross", "tradingview:forex",
                    "tradingview:EMA 9/21", "tradingview",
                    "/stock", "x/", "x:"):
            self.assertEqual(split_rule_key(key), (key, "", True), key)


# ── the node's own words ───────────────────────────────────────────────────

class RuleStateViewTests(TestCase):

    def test_a_class_key_pause_blocks_nothing(self):
        from brain.context import CLASS_KEY_EFFECT, rule_state_view
        for key, suffix in (("mk_view/stock", "stock"),
                            ("mk_view:forex", "forex")):
            view = rule_state_view(_node(key))
            self.assertEqual(view["status"], "pause_recommended", key)
            self.assertEqual(view["effect"], CLASS_KEY_EFFECT, key)
            self.assertIn("blocks nothing", view["effect"])
            self.assertIn("bare rule name", view["effect"])
            self.assertNotIn("blocks bot entries", view["effect"])
            self.assertIs(view["read_by_gates"], False)
            self.assertEqual(view["rule"], "mk_view")
            self.assertEqual(view["class_suffix"], suffix)

    def test_an_unlisted_suffix_blocks_nothing_too(self):
        from brain.context import CLASS_KEY_EFFECT, rule_state_view
        for key in ("mk_un/stocks", "mk_un/stock/live", "mk_un:fx"):
            view = rule_state_view(_node(key))
            self.assertEqual(view["effect"], CLASS_KEY_EFFECT, key)
            self.assertIs(view["read_by_gates"], False, key)
            self.assertEqual(view["rule"], "mk_un", key)

    def test_the_effect_calls_the_ticket_a_warning_not_a_gate(self):
        from brain.context import CLASS_KEY_EFFECT
        self.assertIn("no reader asks for a class key", CLASS_KEY_EFFECT)
        self.assertIn("the ticket's warning", CLASS_KEY_EFFECT)
        self.assertNotIn("no gate reads", CLASS_KEY_EFFECT)

    def test_a_class_key_watch_blocks_nothing_and_allow_stays_allow(self):
        from brain.context import CLASS_KEY_EFFECT, rule_state_view
        self.assertEqual(rule_state_view(_node("mk_w/stock", "watch"))
                         ["effect"], CLASS_KEY_EFFECT)
        self.assertEqual(rule_state_view(_node("mk_a/stock", "allow"))
                         ["effect"], "allow")

    def test_the_bare_rule_is_unaffected(self):
        from brain.context import EFFECT_WORDS, rule_state_view
        _node("mk_view/stock")
        view = rule_state_view(_node("mk_view"))
        self.assertEqual(view["effect"], EFFECT_WORDS["pause_recommended"])
        self.assertIs(view["read_by_gates"], True)
        self.assertEqual(view["rule"], "mk_view")
        self.assertEqual(view["class_suffix"], "")


class TheClassNodeIsInertTests(TestCase):
    """The words above are true: on the bot path, a class node and a class
    overlay entry block nothing."""

    def test_the_bare_advisory_stays_allow_while_only_the_class_key_pauses(self):
        from brain.context import brain_rule_advisory
        _node("mk_inert/stock")
        _node("mk_inert:forex")
        _report({"mk_inert/stock": "pause_recommended"},
                venues={"mk_inert/stock": "live"})
        self.assertEqual(brain_rule_advisory("mk_inert"), ("allow", ""))

    def test_a_bot_entry_of_the_rule_is_not_skipped(self):
        """The real entry path (base.py's BRAIN_PAUSED skip), a REAL node."""
        from bot_program.asset_engine import StockBot, skips
        cfg = _config(_user("mk_entry"), symbols=["MKE1"])
        _signal("MKE1", "bullish", 0.85, rule="mk_entry_rule")
        _node("mk_entry_rule/stock")
        with patch(ROUTER, return_value=_client()):
            StockBot(cfg).scan_symbol("MKE1")
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg).get("MKE1") or {}
        self.assertNotEqual(note.get("code"), skips.BRAIN_PAUSED)


# ── the operator's read ────────────────────────────────────────────────────

class MindContractReadsTheBareRuleTests(TestCase):

    def test_a_class_pause_of_a_live_full_rule_says_real_money_and_blocks_nothing(self):
        _live_full("mk_bsb")
        _node("mk_bsb/stock")
        text = _nodes_text()
        pair = _line_pair(text, "mk_bsb/stock")
        self.assertIn("stage live_full: real money", pair)
        self.assertNotIn("paper venue only", pair)
        self.assertNotIn("blocks bot entries", pair)
        self.assertIn("blocks nothing", pair)
        self.assertIn("the class node itself is read by no gate", pair)
        self.assertNotIn("read by nothing", pair)
        self.assertIn("the rule mk_bsb now: allow", pair)

    def test_the_rule_now_is_the_bare_rules_word(self):
        _node("mk_both")
        _node("mk_both:forex")
        pair = _line_pair(_nodes_text(), "mk_both:forex")
        self.assertIn("the rule mk_both now: pause_recommended", pair)

    def test_the_d2_count_and_the_summary_count_only_what_a_gate_reads(self):
        _node("mk_d2")
        _node("mk_d2/stock")
        _node("mk_d2:forex")
        _node("mk_d2_watch", "watch")
        with patch("brain.context._brain_trust_score", return_value=0.2):
            text = _nodes_text()
        self.assertIn("1 node pause(s) would soften to watch at today's "
                      "band (low)", text)
        self.assertIn("summary: 2 node(s) a gate reads, 1 pause(s) among "
                      "them bind bot entries; 2 class-suffixed node(s) "
                      "block nothing: mk_d2/stock, mk_d2:forex", text)
        self.assertEqual(text.strip().splitlines()[-1],
                         "Clear a node at /knowledge/ with your trading PIN.")

    def test_manual_takes_pause_is_counted_apart_as_a_ticket_warning(self):
        """No bot trades manual_take; on the ticket its pause is a warning,
        never a block: it is no pause that binds bot entries."""
        _node("manual_take")
        _node("manual_take/stock")
        _node("mk_mt")
        text = _nodes_text()
        self.assertIn("summary: 2 node(s) a gate reads, 1 pause(s) among "
                      "them bind bot entries (manual_take's pause is a "
                      "warning on the ticket, never a block); 1 class-"
                      "suffixed node(s) block nothing: manual_take/stock",
                      text)

    def test_the_header_says_a_class_node_is_never_reaffirmed(self):
        self.assertIn("a class key ('<rule>/stock') is never re-affirmed: "
                      "it takes a miss every fresh night, named or not, "
                      "and is released on the 3rd", _nodes_text())

    def test_the_report_section_says_a_class_entry_is_read_by_no_gate(self):
        _report({"mk_rep/stock": "pause_recommended"},
                venues={"mk_rep/stock": "live"})
        out = io.StringIO()
        call_command("mind_contract", "report", stdout=out)
        self.assertIn("overlay mk_rep/stock: pause_recommended (live) -> a "
                      "class key, read by no rule gate (the trade debate "
                      "sees it as text); the rule mk_rep now: allow",
                      out.getvalue())

    def test_the_trust_section_never_lists_a_class_pause(self):
        _report({"mk_tr/stock": "pause_recommended"},
                venues={"mk_tr/stock": "live"})
        with patch("brain.context._brain_trust_score", return_value=0.8), \
                patch("brain.calibration.projected_mind_trust",
                      return_value={"score": 0.2, "band": "low", "n": 9,
                                    "current_n": 9,
                                    "newest_graded_hours": 1}):
            out = io.StringIO()
            call_command("mind_contract", "trust", stdout=out)
        self.assertNotIn("mk_tr/stock", out.getvalue())
        self.assertIn("no fresh report pause changes", out.getvalue())


# ── /knowledge/ ────────────────────────────────────────────────────────────

class TheKnowledgePageTellsTheTruthTests(TestCase):

    def setUp(self):
        from core import security
        from core.platform_control import seed_components
        cache.clear()
        security._login_attempts.clear()
        self.addCleanup(security._login_attempts.clear)
        seed_components()
        self.admin = User.objects.create_superuser(
            "mk_admin", "mk_admin@example.test", "pw-of-the-test")
        _set_pin(self.admin)
        self.client.force_login(self.admin)
        _live_full("mk_page")
        _node("mk_page/stock")
        _node("mk_page:forex")
        _node("mk_page/stocks")
        _node("mk_page_bare")

    def test_no_clear_form_on_a_class_node_and_the_bare_rules_reach(self):
        r = self.client.get("/knowledge/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn("/knowledge/rule_state/mk_page:forex/clear/", html)
        self.assertNotIn("/knowledge/rule_state/mk_page/stock/clear/", html)
        self.assertNotIn("/knowledge/rule_state/mk_page/stocks/clear/", html)
        self.assertIn("/knowledge/rule_state/mk_page_bare/clear/", html)
        self.assertIn("a class key: read by no gate; its readers ask for "
                      "mk_page", html)
        rows = {row["key"]: row for row in r.context["rule_rows"]}
        for key in ("mk_page/stock", "mk_page:forex", "mk_page/stocks"):
            row = rows[key]
            self.assertFalse(row["can_clear"], key)
            self.assertFalse(row["view"]["read_by_gates"], key)
            self.assertEqual(row["now"], "allow", key)
            self.assertIs(row["reach"]["real_money"], True, key)
            self.assertIn("live_full", row["reach"]["words"])
        self.assertTrue(rows["mk_page_bare"]["can_clear"])

    def test_the_history_link_of_a_slash_key_resolves(self):
        from django.urls import reverse
        url = reverse("knowledge_node_history",
                      args=["rule_state", "mk_page/stock"])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_posted_clear_on_a_class_node_is_404_and_writes_nothing(self):
        from brain.knowledge_models import KnowledgeNode
        n = KnowledgeNode.objects.count()
        for key in ("mk_page:forex", "mk_page/stock", "mk_page/stocks"):
            with patch(NOTIFY):
                r = self.client.post(f"/knowledge/rule_state/{key}/clear/",
                                     {"pin": TEST_PIN})
            self.assertEqual(r.status_code, 404, key)
            self.assertEqual(_current(key).version, 1, key)
        self.assertEqual(KnowledgeNode.objects.count(), n)
        self.assertEqual(_audit("rule_state_clear"), [])


# ── the consolidation ──────────────────────────────────────────────────────

class TheConsolidationNeverWritesAClassKeyTests(TestCase):

    def test_a_fresh_class_pause_writes_no_node(self):
        from brain.knowledge_models import KnowledgeNode
        result, _ = _night({"mk_c/stock": "pause_recommended",
                            "mk_c:forex": "watch"},
                           venues={"mk_c/stock": "live"})
        self.assertIsNone(_current("mk_c/stock"))
        self.assertIsNone(_current("mk_c:forex"))
        self.assertIsNone(_current("mk_c"))
        self.assertEqual(KnowledgeNode.objects.filter(
            kind="rule_state").count(), 0)
        self.assertIn("rules: +0/", result["notes"])

    def test_the_last_report_never_adds_a_class_key(self):
        from brain.consolidation import consolidate_now
        _report({"mk_t/stock": "pause_recommended", "mk_t": "watch"},
                age_minutes=180, venues={"mk_t/stock": "live"})
        with patch(NOTIFY):
            consolidate_now(releases=True)
        self.assertIsNone(_current("mk_t/stock"))
        self.assertEqual(_current("mk_t").payload["status"], "watch")

    def test_the_staff_button_never_reaffirms_a_class_node(self):
        from brain.consolidation import consolidate_now
        _node("mk_btn/stock")
        _report({"mk_btn/stock": "pause_recommended"},
                venues={"mk_btn/stock": "live"})
        with patch(NOTIFY):
            result = consolidate_now()
        self.assertIn("re-affirmed 0", result["notes"])

    def test_a_class_node_takes_a_miss_a_night_and_is_released_on_the_third(self):
        from brain.context import rule_state_view
        _live_full("mk_rel")
        _node("mk_rel/stock")
        for night in (1, 2):
            # named in every report: still not re-affirmed, a miss counts
            _, notify = _night({"mk_rel/stock": "pause_recommended"},
                               venues={"mk_rel/stock": "live"})
            node = _current("mk_rel/stock")
            self.assertEqual(node.version, 1, night)
            self.assertEqual(rule_state_view(node)["misses"], night)
            notify.assert_not_called()
        _, notify = _night({"mk_rel/stock": "pause_recommended"},
                           venues={"mk_rel/stock": "live"})
        node = _current("mk_rel/stock")
        self.assertEqual(node.version, 2)
        self.assertEqual(node.payload["status"], "allow")
        # named every night, so "not named" would be false
        self.assertNotIn("not named", node.payload["why"])
        self.assertIn("a class key, never re-affirmed: 3 fresh nights in "
                      "a row", node.payload["why"])
        notify.assert_called_once()
        kw = notify.call_args.kwargs
        self.assertIn("released 0 rules and 1 class key no gate read",
                      kw["title"])
        self.assertIn("mk_rel/stock", kw["body"])
        self.assertIn("mk_rel/stock: pause_recommended -> allow (a class "
                      "key, never re-affirmed: 3 fresh nights in a row",
                      kw["body"])
        self.assertIn("read by no gate, so nothing changes for mk_rel's "
                      "entries", kw["body"])
        self.assertNotIn("not named", kw["body"])
        self.assertNotIn("no longer blocked", kw["body"])
        self.assertIn("stage live_full: real money", kw["body"])
        self.assertNotIn("paper venue only", kw["body"])
        rows = _audit("rule_state_release")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["rule_name"], "mk_rel/stock")
        self.assertIs(rows[0].data["real_money"], True)
        self.assertEqual(rows[0].data["promotion_stage"], "live_full")
        self.assertIs(rows[0].data["read_by_gates"], False)

    def test_a_bare_pause_beside_a_class_key_is_kept_as_before(self):
        """A guard: the bare rule's node is re-affirmed by the bare name
        alone; a class key in the same report changes nothing for it."""
        from brain.context import brain_rule_advisory
        _night({"mk_g": "pause_recommended", "mk_g/stock": "watch"},
               venues={"mk_g": "live"})
        for _ in range(3):
            _night({"mk_g": "pause_recommended", "mk_g/stock": "active"},
                   venues={"mk_g": "live"})
        node = _current("mk_g")
        self.assertEqual(node.version, 1)
        self.assertEqual(node.payload["status"], "pause_recommended")
        self.assertEqual(brain_rule_advisory("mk_g")[0], "pause_recommended")
        self.assertIsNone(_current("mk_g/stock"))

    def test_a_tradingview_rule_is_remembered_whole(self):
        """A guard on the helper: "tradingview:<strategy>" is a rule the
        entry gate reads, so its pause is still written."""
        from brain.context import brain_rule_advisory
        _night({"tradingview:forex": "pause_recommended"},
               venues={"tradingview:forex": "live"})
        self.assertEqual(_current("tradingview:forex").payload["status"],
                         "pause_recommended")
        with patch("brain.context.get_brain_context", return_value=None):
            self.assertEqual(brain_rule_advisory("tradingview:forex")[0],
                             "pause_recommended")


# ── the synthesizer ────────────────────────────────────────────────────────

class TheSynthesizerKeepsTheMindsWordsTests(TestCase):

    def _persist(self, overlay, concerns=None):
        from brain.synthesizer import _persist_report
        return _persist_report(
            parsed={"regime_label": "trending", "regime_confidence": 0.8,
                    "rule_status_overlay": overlay,
                    "top_concerns": concerns or []},
            snapshot={}, model="t", tokens_in=0, tokens_out=0,
            cost_usd=0.0, n_consumed=0)

    def test_a_class_key_is_stored_as_given_and_never_folded(self):
        from brain.context import brain_rule_advisory
        report = self._persist(
            {"mk_s/stock": "pause_recommended"},
            [{"kind": "rule_decay", "severity": 0.8, "ref": "mk_s/stock",
              "venue": "live", "text": "t"}])
        self.assertEqual(report.rule_status_overlay,
                         {"mk_s/stock": "pause_recommended"})
        self.assertEqual(report.rule_status_venue, {"mk_s/stock": "live"})
        self.assertEqual(brain_rule_advisory("mk_s"), ("allow", ""))

    def test_the_bare_rules_own_word_is_unaffected(self):
        from brain.context import brain_rule_advisory
        self._persist(
            {"mk_s2/stock": "pause_recommended", "mk_s2": "watch"},
            [{"kind": "rule_decay", "severity": 0.8, "ref": "mk_s2/stock",
              "venue": "live", "text": "t"}])
        self.assertEqual(brain_rule_advisory("mk_s2")[0], "watch")

    def test_the_schema_asks_for_the_bare_rule_name(self):
        from brain.synthesizer import SCHEMA_HINT, SauronMindAgent
        prompt = SauronMindAgent.__new__(SauronMindAgent).get_system_prompt()
        self.assertIn(SCHEMA_HINT, prompt)
        self.assertIn("the bare name", SCHEMA_HINT)
        self.assertIn("never with a class or venue suffix", SCHEMA_HINT)


class TheBrainPageMarksAClassKeyTests(TestCase):

    def test_a_class_entry_says_no_rule_gate_reads_it(self):
        """No rule gate reads it, but the Mind's text block still carries
        it to the trade debate: the page says both."""
        _report({"mk_b/stock": "pause_recommended", "mk_b2": "watch"},
                venues={"mk_b/stock": "live"})
        self.client.force_login(User.objects.create_user(
            username="mk_brain", password="x"))
        html = self.client.get("/brain/").content.decode()
        self.assertIn("a class key: no rule gate reads it, its readers ask "
                      "for mk_b; the trade debate still sees it as text",
                      html)
        self.assertEqual(html.count("a class key: no rule gate reads it"), 1)
        self.assertNotIn("blocks nothing", html)

    def test_the_prompt_still_carries_a_class_entry(self):
        """The words above are true: the Mind's block for the agents (the
        trade debate's included) prints the class entry as text."""
        from brain.context import context_for_prompt
        _report({"mk_bp/stock": "pause_recommended"},
                venues={"mk_bp/stock": "live"})
        with patch("brain.context._brain_trust_score", return_value=0.8):
            self.assertIn("mk_bp/stock: pause_recommended (live)",
                          context_for_prompt())

    def test_staff_get_no_propose_button_on_a_class_entry(self):
        """The actuator governs bare rule names only, so the page never
        offers a press it would refuse; the bare rule keeps its lever."""
        _report({"mk_pp/stock": "pause_recommended",
                 "mk_pp": "pause_recommended"},
                venues={"mk_pp/stock": "live", "mk_pp": "live"})
        self.client.force_login(User.objects.create_user(
            username="mk_staff", password="x", is_staff=True))
        r = self.client.get("/brain/")
        html = r.content.decode()
        self.assertNotIn('name="rule_name" value="mk_pp/stock"', html)
        self.assertIn('name="rule_name" value="mk_pp"', html)
        self.assertIn("a class key: nothing to propose; the lever is on "
                      "mk_pp", html)
        rows = {row["rule"]: row for row in r.context["overlay_rows"]}
        self.assertFalse(rows["mk_pp/stock"]["can_propose"])
        self.assertTrue(rows["mk_pp"]["can_propose"])
