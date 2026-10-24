"""What "the Mind says X" means right now, read-only (2026-10-24).

The Mind's word reaches money in two places: its fresh report (the
overlay, younger than the contract's window, a pause softened to watch
when its trust band is low) and its memory (the rule_state nodes the
consolidation writes; only the scheduled 03:00 pass releases one). A pause in either blocks every bot
entry of that rule, paper and live (bot_program/asset_engine/base.py, the
BRAIN_PAUSED skip). This prints both side by side through the functions
the readers themselves use (brain/context.py), the two trust numbers, and
the crisis switch. It writes nothing and prints names, statuses, ages,
bands and counts only.

    python manage.py mind_contract           # the Mind's report, its rule_state nodes and its trust, side by side
    python manage.py mind_contract nodes     # each rule_state node: status, age, venue, effect on bot entries
    python manage.py mind_contract trust     # both trust numbers, n graded, the band, rows the two graders disagree on

There is no shell clear on purpose (core/switch_pin.py): a node is
cleared on /knowledge/ by a superuser with the trading PIN.

A class key ("<rule>/stock", "<rule>:forex": brain.context.split_rule_key)
is read by no rule gate, since every reader asks with the bare rule name:
its line says so, and what the bare rule's entries get and where it trades
(2026-10-24). manual_take's pause is counted apart: no bot trades it, and
on the ticket it is a warning, never a block.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

LAST_LINE = "Clear a node at /knowledge/ with your trading PIN."


class Command(BaseCommand):
    help = ("The Mind's report, its rule_state nodes and its trust, side by "
            "side: what blocks bot entries now. Read-only.")

    def add_arguments(self, parser):
        parser.add_argument("section", nargs="?", default="all",
                            choices=["all", "report", "nodes", "trust"])

    def handle(self, *args, **opts):
        section = opts["section"]
        self.now = timezone.now()
        self.stdout.write("THE MIND'S CONTRACT (read-only; names, statuses, "
                          "ages and counts)")
        if section in ("all", "report"):
            self._report()
        if section in ("all", "nodes"):
            self._nodes()
        if section in ("all", "trust"):
            self._trust()
        if section == "all":
            self._crisis()
        self.stdout.write(LAST_LINE)

    def w(self, line=""):
        self.stdout.write(line)

    # ── the report ───────────────────────────────────────────────────────
    def _report(self):
        from brain.context import (MIND_BEAT_KEY, MIND_GRACE_MINUTES,
                                   brain_rule_advisory, get_brain_context,
                                   mind_fresh_minutes, split_rule_key)
        from brain.models import BrainReport
        window = mind_fresh_minutes()
        self.w("== The report ==")
        self.w(f"beat {MIND_BEAT_KEY}: a clean report is the Mind's word "
               f"for {window} min (its widest gap + {MIND_GRACE_MINUTES} min "
               f"of grace)")
        rep = (BrainReport.objects.filter(error="")
               .order_by("-created_at").first())
        if rep is None:
            self.w("  no clean report at all: no report pause binds")
            return
        age = int((self.now - rep.created_at).total_seconds() // 60)
        read = get_brain_context() is not None
        self.w(f"  latest clean report: {age} min old, regime "
               f"{rep.regime_label}: {'READ now' if read else 'past the window, not read'}")
        overlay = rep.rule_status_overlay if isinstance(
            rep.rule_status_overlay, dict) else {}
        venues = rep.rule_status_venue if isinstance(
            rep.rule_status_venue, dict) else {}
        shown = 0
        for rule, status in sorted(overlay.items()):
            if status not in ("watch", "pause_recommended", "active"):
                continue
            # A class key is read by no rule gate: say what the bare rule's
            # entries get instead. The Mind's text block (context_for_prompt)
            # still shows it to the agents, the trade debate included
            # (2026-10-24).
            bare, _, read = split_rule_key(rule)
            now_status, _ = brain_rule_advisory(bare)
            self.w(f"  overlay {rule}: {status} "
                   f"({venues.get(rule) or 'no venue'}) -> "
                   + ("the rule now: " if read else
                      f"a class key, read by no rule gate (the trade debate "
                      f"sees it as text); the rule {bare} now: ")
                   + now_status)
            shown += 1
        if not shown:
            self.w("  overlay: names no rule")

    # ── the nodes ────────────────────────────────────────────────────────
    def _nodes(self):
        from brain.consolidation import RELEASE_AFTER_MISSES, rule_reach
        from brain.context import (_brain_trust_score, brain_rule_advisory,
                                   brain_trust_band, rule_state_view)
        from brain.knowledge_models import KnowledgeNode
        self.w("== The memory: rule_state nodes ==")
        self.w(f"  written by the consolidation from a fresh report (the "
               f"03:00 pass, or the staff button, which only adds and "
               f"re-affirms), from the last report of the past day when "
               f"none is fresh (adding or tightening only), and by a "
               f"superuser's clear")
        self.w(f"  released by the 03:00 pass on an 'active', or a 'watch' "
               f"for a paused rule, in a fresh report, or on the "
               f"{RELEASE_AFTER_MISSES}rd fresh night in a row that no "
               f"longer names it (one miss a night), or by a superuser's "
               f"clear; never aged out by the reader")
        self.w(f"  a class key ('<rule>/stock') is never re-affirmed: it "
               f"takes a miss every fresh night, named or not, and is "
               f"released on the {RELEASE_AFTER_MISSES}rd")
        nodes = list(KnowledgeNode.objects
                     .filter(kind=KnowledgeNode.KIND_RULE_STATE,
                             superseded_by__isnull=True).order_by("key"))
        if not nodes:
            self.w("  none")
        try:
            from bot_program.manual_trade import MANUAL_RULE
        except Exception:  # noqa: BLE001 — a read, never a crash
            MANUAL_RULE = "manual_take"
        soften = n_read = binding = 0
        manual_paused = False
        class_keys = []
        for n in nodes:
            v = rule_state_view(n, now=self.now)
            # What the rule's entries get is asked by the BARE name, as the
            # readers ask it; the stage too: a class node of a live_full rule
            # is no "paper venue only" (2026-10-24).
            now_status, why = brain_rule_advisory(v["rule"])
            reach = rule_reach(v["rule"])
            age = (f"{v['age_hours']:.0f} h" if v["age_hours"] is not None
                   else "unknown")
            self.w(f"  {n.key}: {v['status']} v{v['version']}, last affirmed "
                   f"{age} ago, missed {v['misses']} of "
                   f"{RELEASE_AFTER_MISSES}, venue {v['venue'] or 'none'}, "
                   f"source {v['source'] or 'none'}")
            rule_now = ("the rule now" if v["read_by_gates"] else
                        f"the class node itself is read by no gate; the rule "
                        f"{v['rule']} now")
            self.w(f"      node: {v['effect']}; {rule_now}: {now_status}"
                   + (f" ({why})" if why else "") + f"; {reach['words']}")
            if not v["read_by_gates"]:
                class_keys.append(n.key)
                continue
            n_read += 1
            if v["status"] == "pause_recommended":
                soften += 1
                # No bot trades manual_take: its pause is the ticket's
                # warning, never a block (bot_program/manual_trade.py).
                if n.key == MANUAL_RULE:
                    manual_paused = True
                else:
                    binding += 1
        band = brain_trust_band(_brain_trust_score())
        self.w(f"  if D2 shipped (a low band softens node pauses too): "
               f"{soften if band == 'low' else 0} node pause(s) would "
               f"soften to watch at today's band ({band})")
        self.w(f"  summary: {n_read} node(s) a gate reads, {binding} "
               f"pause(s) among them bind bot entries"
               + (f" ({MANUAL_RULE}'s pause is a warning on the ticket, "
                  f"never a block)" if manual_paused else "")
               + f"; {len(class_keys)} class-suffixed node(s) block nothing"
               + (f": {', '.join(class_keys)}" if class_keys else ""))

    # ── trust ────────────────────────────────────────────────────────────
    def _trust(self):
        from brain.calibration import projected_mind_trust, trust_disagreements
        from brain.context import (_brain_trust_score, brain_trust_band,
                                   get_brain_context, split_rule_key)
        from brain.hypotheses import agent_trust_score
        self.w("== Trust ==")
        score = _brain_trust_score()
        band = brain_trust_band(score)
        proj = projected_mind_trust()
        self.w(f"  the bots' number (_brain_trust_score, AgentPrediction): "
               f"{score} band {band}; graded n={proj['current_n']}, newest "
               f"graded {proj['newest_graded_hours']} h ago")
        self.w(f"  the briefing's number (agent_trust_score, Hypothesis): "
               f"{agent_trust_score('sauron_mind')}")
        self.w(f"  linked rows whose grade disagrees with their hypothesis: "
               f"{trust_disagreements()}")
        self.w(f"  projected bots' number (one grader per row): "
               f"{proj['score']} band {proj['band']} (n={proj['n']}); it "
               f"moves at the 03:00 passes, not at deploy")
        ctx = get_brain_context() or {}
        overlay = ctx.get("rule_status_overlay") or {}
        # a class key's pause binds nothing, softened or not
        pauses = sorted(r for r, s in overlay.items()
                        if s == "pause_recommended" and split_rule_key(r)[2])
        if band != "low" and proj["band"] == "low" and pauses:
            self.w("  report pauses the projected band would soften to "
                   "watch (released): " + ", ".join(pauses))
        elif band == "low" and proj["band"] != "low" and pauses:
            self.w("  report pauses the projected band would stop "
                   "softening (blocked): " + ", ".join(pauses))
        else:
            self.w("  no fresh report pause changes under the projected band")

    # ── crisis mode ──────────────────────────────────────────────────────
    def _crisis(self):
        self.w("== Crisis mode (the stress score reads the Mind's regime) ==")
        try:
            from bot_program.market_stress import current
            from core.platform_control import is_component_enabled
            on = is_component_enabled("crisis_mode")
            self.w(f"  crisis_mode switch: {'ON' if on else 'off'}; posture "
                   f"now: {current(self.now).get('level')}")
        except Exception as e:  # noqa: BLE001 — a read, never a crash
            self.w(f"  unreadable ({type(e).__name__})")
