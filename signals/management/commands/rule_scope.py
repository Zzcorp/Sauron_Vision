"""Where each rule may fire and how often — read it, or set it.

The weekly review of 2026-10-02 asked for two things the engine had no
knob for: a cooldown between signals of one rule on one symbol, and the
RSI bullish divergence kept off commodities and mining stocks. Both live
in signals/rule_scope: code defaults (the review's ask) that a rule's
RuleControl row overrides through its `scope` JSON. This is that JSON,
read and written in words.

    python manage.py rule_scope
    python manage.py rule_scope show rsi_bull_divergence
    python manage.py rule_scope set rsi_bull_divergence --exclude-class commodity --exclude-group miners
    python manage.py rule_scope set rsi_bull_divergence --cooldown 12
    python manage.py rule_scope set golden_cross --exclude-symbol TSLA --exclude-symbol NIO
    python manage.py rule_scope set rsi_bull_divergence --lift
    python manage.py rule_scope clear rsi_bull_divergence

`set` writes the whole exclusion list you give (so repeat every entry you
want kept); `--lift` writes explicit empty lists, which switches the code
defaults OFF for that rule; `clear` empties the row's scope, which switches
them back ON. A `set` on a rule with no RuleControl row creates the row at
the PAPER stage, so nothing is promoted by naming it here. Nothing here
touches a position or a venue.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Read or set where a signal rule may fire and its cooldown (RuleControl.scope)."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="list",
                            choices=["list", "show", "set", "clear"])
        parser.add_argument("rule", nargs="?", default="")
        parser.add_argument("--exclude-class", action="append", default=[],
                            metavar="CLASS", help="asset class to keep the rule off (repeatable)")
        parser.add_argument("--exclude-sector", action="append", default=[],
                            metavar="SECTOR", help="Instrument.sector to keep the rule off (repeatable)")
        parser.add_argument("--exclude-symbol", action="append", default=[],
                            metavar="SYMBOL", help="symbol to keep the rule off (repeatable)")
        parser.add_argument("--exclude-group", action="append", default=[],
                            metavar="GROUP", help="named group to keep the rule off: miners")
        parser.add_argument("--cooldown", type=float, default=None,
                            metavar="HOURS", help="hours between two signals of this rule on one symbol; 0 switches it off")
        parser.add_argument("--lift", action="store_true",
                            help="write explicit empty exclusions: the code defaults no longer apply to this rule")

    def handle(self, *args, **opts):
        act = opts["action"]
        if act == "list":
            return self._list()
        rule = (opts["rule"] or "").strip()
        if not rule:
            raise CommandError(f"rule_scope {act}: name the rule.")
        if act == "show":
            return self._show(rule)
        if act == "clear":
            return self._clear(rule)
        return self._set(rule, opts)

    # ── read ──────────────────────────────────────────────────────────────
    def _names(self):
        from signals.models_control import RuleControl
        from signals.rule_scope import DEFAULT_RULE_SCOPE
        names = set(RuleControl.objects.values_list("rule_name", flat=True))
        names |= set(DEFAULT_RULE_SCOPE)
        return sorted(n for n in names if n)

    def _line(self, rule):
        from signals.rule_scope import (SIGNAL_COOLDOWN_HOURS, cooldown_hours,
                                        effective_scope)
        scope = effective_scope(rule)
        ex = scope["exclude"]
        parts = []
        for key, label in (("asset_classes", "classes"), ("sectors", "sectors"),
                           ("symbols", "symbols"), ("groups", "groups")):
            if ex[key]:
                parts.append(f"off {label} {', '.join(ex[key])}")
        hours = cooldown_hours(rule)
        parts.append(f"cooldown {hours:g}h"
                     + ("" if scope["cooldown_hours"] is not None
                        else f" (platform default {SIGNAL_COOLDOWN_HOURS:g}h)"))
        source = {"row": "the row's scope", "default": "code default — the row says nothing",
                  "none": "no scope — fires everywhere"}[scope["source"]]
        return f"{rule:<36} {' · '.join(parts)}  [{source}]"

    def _list(self):
        names = self._names()
        if not names:
            self.stdout.write("no rules with a RuleControl row or a default scope")
            return
        for rule in names:
            self.stdout.write(self._line(rule))

    def _show(self, rule):
        from signals.rule_actuator import _control_for
        self.stdout.write(self._line(rule))
        ctrl = _control_for(rule)
        if ctrl is None:
            self.stdout.write("  no RuleControl row — `set` creates one at the paper stage")
        else:
            self.stdout.write(f"  row: status {ctrl.status} · stage {ctrl.promotion_stage} "
                              f"· scope {ctrl.scope or {}}")

    # ── write ─────────────────────────────────────────────────────────────
    def _row(self, rule):
        from django.utils import timezone
        from signals.models_control import RuleControl
        # A row created here must not promote the rule: no row means
        # PAPER (rule_actuator.stage_policy), so the row says paper too.
        ctrl, created = RuleControl.objects.get_or_create(
            rule_name=rule,
            defaults={"status": RuleControl.STATUS_ACTIVE, "weight_multiplier": 1.0,
                      "promotion_stage": RuleControl.STAGE_PAPER,
                      "stage_entered_at": timezone.now(),
                      "notes": "Created by rule_scope; paper stage, as a rule with no row."})
        return ctrl, created

    def _set(self, rule, opts):
        from signals.rule_scope import GROUPS
        bad = [g for g in opts["exclude_group"] if g.lower() not in GROUPS]
        if bad:
            raise CommandError(f"unknown group(s) {', '.join(bad)} — known: {', '.join(GROUPS)}")
        if opts["cooldown"] is not None and opts["cooldown"] < 0:
            raise CommandError("--cooldown is hours, zero or more")
        ctrl, created = self._row(rule)
        scope = dict(ctrl.scope or {})
        exclude = dict(scope.get("exclude") or {})
        given = {"asset_classes": [c.lower() for c in opts["exclude_class"]],
                 "sectors": [s.lower() for s in opts["exclude_sector"]],
                 "symbols": [s.upper() for s in opts["exclude_symbol"]],
                 "groups": [g.lower() for g in opts["exclude_group"]]}
        if opts["lift"]:
            exclude = {k: [] for k in given}
        elif any(given.values()):
            exclude = {k: sorted(set(v)) for k, v in given.items()}
        if exclude:
            scope["exclude"] = exclude
        if opts["cooldown"] is not None:
            scope["cooldown_hours"] = float(opts["cooldown"])
        if not exclude and opts["cooldown"] is None and not opts["lift"]:
            raise CommandError("rule_scope set: give --exclude-*, --cooldown or --lift")
        ctrl.scope = scope
        ctrl.save(update_fields=["scope", "updated_at"])
        self.stdout.write(self.style.SUCCESS(
            f"{'created' if created else 'updated'} {rule}: scope {scope}"))
        self.stdout.write(self._line(rule))

    def _clear(self, rule):
        from signals.rule_actuator import _control_for
        ctrl = _control_for(rule)
        if ctrl is None:
            self.stdout.write(f"{rule}: no row — nothing to clear; the code defaults apply")
            return
        ctrl.scope = {}
        ctrl.save(update_fields=["scope", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"cleared {rule}: the code defaults apply"))
        self.stdout.write(self._line(rule))
