"""The signals page as a command — the same filters, the same six answers.

/signals/ carried one filter (?active=1) and its rows carried no stage, no
rule record, no conditions and no outcome, so a 0.85 signal from a RESEARCH
rule that no bot will ever act on read exactly like one a bot was about to
trade live. This is that page's repair, in the shell: the same queryset
narrowings (never a Python pass over an unbounded queryset) and the same six
blocks, off `dashboard.signal_surface` — so the page and the command cannot
give different answers about the same row.

The six blocks `signals show` prints:

    (a) can anything act on it   stage_policy + is_rule_active, nothing else
    (b) what is this rule worth  the evidence ledger, at its own sample floor
    (c) why did it fire          the linked flag's conditions, or sub_scores
    (d) what would it cost       the levels, and — where --config names a
                                 pool — the verdict of passes_cost_filter,
                                 the same gate every bot entry goes through
    (e) did anyone act           the rule+symbol+time join, captioned as one
    (f) its own grade            outcome, realized R, time to outcome

    python manage.py signals list
    python manage.py signals list --stage research --min-score 0.7
    python manage.py signals list --rule starter_forex_breakout --active
    python manage.py signals list --class crypto --direction bullish --acted no
    python manage.py signals show 4211
    python manage.py signals show 4211 --config "Crypto Paper"
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List signals with the page's own filters, or show one in full."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "show"])
        parser.add_argument("signal_id", nargs="?", type=int)
        parser.add_argument("--rule", default="")
        parser.add_argument("--stage", default="",
                            help="research | paper | live_small | live_full | unregistered")
        parser.add_argument("--class", dest="asset_class", default="")
        parser.add_argument("--direction", default="")
        parser.add_argument("--min-score", type=float, default=None)
        parser.add_argument("--active", action="store_true",
                            help="Only signals still open.")
        parser.add_argument("--acted", default="",
                            help="yes | no — whether a trade matches this rule and symbol after it.")
        parser.add_argument("--limit", type=int, default=40)
        # (d) is answerable only against a config, because the round trip
        # belongs to the pool that would take the trade and not to the
        # signal. The page reads the viewing user's enabled pools; a command
        # has no viewer, so the context is named here or the block refuses —
        # which is the same refusal the page gives, not a different one.
        parser.add_argument("--config", default="",
                            help="Name of an enabled bot config to price the "
                                 "levels against (block d). Without it, "
                                 "`show` says 'no config context' rather "
                                 "than inventing one.")

    def handle(self, *args, **opts):
        if opts["action"] == "show":
            if opts["signal_id"] is None:
                raise CommandError("signals show: give a signal id "
                                   "(see `signals list`).")
            return self._show(opts["signal_id"], opts.get("config") or "")
        return self._list(opts)

    # ── list ───────────────────────────────────────────────────────────
    def _list(self, opts):
        from django.http import QueryDict

        from dashboard import signal_surface
        from signals.models import Signal

        # The PAGE's own filter builder, fed a QueryDict — so a narrowing that
        # works here works there, and neither can drift into a Python pass.
        params = QueryDict(mutable=True)
        for key, value in (("rule", opts["rule"]), ("stage", opts["stage"]),
                           ("asset_class", opts["asset_class"]),
                           ("direction", opts["direction"]),
                           ("acted", opts["acted"])):
            if value:
                params[key] = value
        if opts["min_score"] is not None:
            params["score_min"] = str(opts["min_score"])
        if opts["active"]:
            params["state"] = "active"

        base = Signal.objects.select_related("instrument").order_by("-created_at")
        n_total = base.count()
        qs, _chips, active = signal_surface.apply_filters(base, params)
        n_shown = qs.count()
        rows = list(qs[:max(1, opts["limit"])])
        badges = signal_surface.badges_for([s.rule_name or "" for s in rows])
        records = signal_surface.rule_records([s.rule_name or "" for s in rows])

        self.stdout.write(f"{n_shown} of {n_total} signals"
                          + (f" · filters: {active}" if active else "")
                          + f" · showing {len(rows)}")
        if not rows:
            if active:
                self.stdout.write("No signal matches these filters — that is a "
                                  "FILTER, not an empty platform. Drop one and "
                                  "run it again.")
            else:
                self.stdout.write("No signal has ever been written. "
                                  "`python manage.py setups diagnose` says why "
                                  "a setup is producing none.")
            return
        self.stdout.write(f"{'id':>7} {'when':16} {'symbol':10} "
                          f"{'act?':12} {'dir':8} {'score':>5} {'rule':26} grade")
        for s in rows:
            badge = badges.get(s.rule_name or "", {})
            rec = records.get(s.rule_name or "")
            if s.outcome and s.realized_r is not None:
                grade = f"{s.outcome} {s.realized_r:+.2f}R"
            elif not s.is_active:
                grade = "UNGRADED (invisible to the ladder)"
            else:
                grade = "open"
            self.stdout.write(
                f"{s.pk:>7} {s.created_at:%Y-%m-%d %H:%M} "
                f"{s.instrument.symbol[:10]:10} "
                f"{(badge.get('label') or '—')[:12]:12} {s.direction[:8]:8} "
                f"{float(s.score or 0):>5.2f} {(s.rule_name or '—')[:26]:26} "
                f"{grade}")
            if rec is not None and not rec["measured"]:
                self.stdout.write(f"{'':>7} rule record: {rec['text']}")
        self.stdout.write("\n`signals show <id>` prints one of these in full.")

    def _configs(self, name):
        """The named enabled config(s), or [] — the context for block (d).

        Named, never guessed: picking "the first enabled config" for an
        operator who runs several pools would price the trade against a book
        that would never take it, and the number would look just as
        authoritative as a right one.
        """
        if not name:
            return []
        from bot_program.models import AssetBotConfig
        found = list(AssetBotConfig.objects.filter(name__iexact=name,
                                                   enabled=True))
        if not found:
            raise CommandError(
                f"no ENABLED bot config named {name!r}. A disabled pool would "
                f"not take the trade, so its cost table is not the one that "
                f"would be paid.")
        return found

    # ── show ───────────────────────────────────────────────────────────
    def _show(self, pk, config_name=""):
        from dashboard import signal_surface
        from signals.models import OpportunityFlag, Signal

        s = (Signal.objects.select_related("instrument")
             .filter(pk=pk).first())
        if s is None:
            raise CommandError(f"no signal with id {pk} (see `signals list`).")
        flag = (OpportunityFlag.objects.filter(signal_id=s.pk)
                .select_related("setup").order_by("-scanned_at").first())
        badge = signal_surface.stage_badge(s.rule_name or "")
        rec = signal_surface.rule_records([s.rule_name or ""]).get(
            s.rule_name or "")
        why = signal_surface.why_block(s, flag)
        trades = signal_surface.acted_index([s]).get(s.pk) or []

        self.stdout.write(f"#{s.pk}  {s.instrument.symbol}  "
                          f"{s.direction.upper()}  score {float(s.score or 0):.2f}  "
                          f"{s.signal_type}  urgency {s.urgency}")
        self.stdout.write(f"  {s.title}")
        self.stdout.write(f"  rule {s.rule_name or '—'} · created "
                          f"{s.created_at:%Y-%m-%d %H:%M} UTC")

        self.stdout.write("\n(a) CAN ANYTHING ACT ON IT?")
        self.stdout.write(f"    {badge['label']} — {badge['reason']}")

        self.stdout.write("\n(b) WHAT IS THIS RULE WORTH?")
        self.stdout.write(f"    {rec['text'] if rec else 'unmeasured — this rule has no row in the evidence ledger at all'}")

        self.stdout.write(f"\n(c) WHY DID IT FIRE?  [{why['source']}]")
        self.stdout.write(f"    {why['caption']}")
        for row in why["rows"]:
            mark = "—" if row["matched"] is None else ("yes" if row["matched"] else "no ")
            self.stdout.write(f"    {mark:4} {str(row['label'])[:28]:28} {row['value']}")
        if not why["rows"]:
            self.stdout.write("    (nothing recorded)")

        self.stdout.write("\n(d) WHAT WOULD IT COST?")
        self.stdout.write(f"    entry {s.suggested_entry or '—'} · stop "
                          f"{s.suggested_stop or '—'} · target "
                          f"{s.suggested_target or '—'} · R:R "
                          f"{s.risk_reward_ratio if s.risk_reward_ratio is not None else '—'}")
        cost = signal_surface.cost_block(s, self._configs(config_name))
        if cost["answerable"]:
            self.stdout.write(
                f"    {cost['verdict'].upper()} — {cost['reason']}; "
                f"{cost['cost_pct']}% round trip against {cost['config']}")
            if not cost["trades_symbol"]:
                self.stdout.write(f"    {signal_surface.COST_SYMBOL_CAVEAT}")
        else:
            self.stdout.write(f"    {cost['reason']}")
            if not config_name:
                self.stdout.write("    (pass --config <name> to price these "
                                  "levels against a pool)")

        self.stdout.write("\n(e) DID ANYONE ACT?")
        for t in trades:
            # NULL realized_r is UNMEASURED, and a 0.00R there would read as a
            # break-even trade that never happened.
            r_text = ("unmeasured R" if t["realized_r"] is None
                      else f"{t['realized_r']:+.2f}R")
            self.stdout.write(f"    trade #{t['id']}  {t['venue']} {t['side']} "
                              f"{t['qty']}  {t['status']}  "
                              f"{t['outcome'] or 'open'}  {r_text}  "
                              f"opened {t['opened_at']:%Y-%m-%d %H:%M}")
        if not trades:
            self.stdout.write("    no trade matches this rule and symbol after "
                              "this signal")
        self.stdout.write(f"    {signal_surface.ACTED_CAPTION}")

        self.stdout.write("\n(f) ITS OWN GRADE")
        if s.outcome and s.realized_r is not None:
            hours = (round(s.time_to_outcome_seconds / 3600.0, 1)
                     if s.time_to_outcome_seconds else None)
            self.stdout.write(f"    {s.outcome}  {s.realized_r:+.2f}R"
                              + (f"  after {hours}h" if hours else ""))
        elif not s.is_active:
            self.stdout.write("    CLOSED AND UNGRADED — no realized_r, so this "
                              "signal is invisible to the promotion ladder and "
                              "to every evidence lane. It cost a scan and "
                              "taught nothing.")
        else:
            self.stdout.write("    still open — not graded yet")
