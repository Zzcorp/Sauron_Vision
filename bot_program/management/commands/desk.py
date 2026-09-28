"""The capital desk's page (/desk/), as a command.

The page shows what the desk ranked on the last tick, what it took, what it
refused and why. This is that page without a browser, plus the two things a
page cannot do: run the grade now, and ask the desk what it would say about
ONE config and ONE symbol right this minute.

`desk explain` is READ-ONLY BY CONSTRUCTION. It calls `propose_entry` with
pricing='data', which reads the ticker through the market-data session and
never touches the exclusive trading client; it stops at the candidate and
prints the evidence lane behind it. Nothing here sends an order, and nothing
here changes a size — the desk itself may only ever shrink one, and only from
the fleet pass (2026-09-12).

    python manage.py desk list                    # the last plans, newest first
    python manage.py desk list --user alice
    python manage.py desk show                    # the newest plan's decisions
    python manage.py desk show 42                 # one plan by id
    python manage.py desk grade                   # resolve counterfactuals + score plans
    python manage.py desk explain 14 EURUSD       # what the desk would say, no order
"""
from django.core.management.base import BaseCommand, CommandError


def _money(value) -> str:
    """A stored amount, or an em dash when the plan never recorded it.

    new_risk_marginal is NULL on every plan written before the column
    existed; printing 0.00 there would claim the desk committed nothing
    (2026-09-12)."""
    return "—" if value is None else f"{float(value):.2f}"


class Command(BaseCommand):
    help = ("List, read and grade capital-desk plans, or explain one "
            "config/symbol (the /desk/ page as a command).")

    def add_arguments(self, parser):
        parser.add_argument("action",
                            choices=["list", "show", "grade", "explain"])
        # NOT "args": django.core.management.call_command uses that
        # dest for its own *args, and a positional of that name is
        # swallowed before handle() ever sees it.
        parser.add_argument("params", nargs="*",
                            help="show: a plan id. explain: a config id and a symbol.")
        parser.add_argument("--user", default="",
                            help="Username: whose plans to list.")
        parser.add_argument("--limit", type=int, default=20,
                            help="list: how many plans (default 20).")

    def handle(self, *args, **opts):
        act = opts["action"]
        if act == "list":
            return self._list(opts["user"], opts["limit"])
        if act == "show":
            rest = list(opts["params"])
            return self._show(int(rest[0]) if rest else None)
        if act == "grade":
            return self._grade()
        rest = list(opts["params"])
        if len(rest) < 2:
            raise CommandError("desk explain: give a CONFIG_ID and a SYMBOL, "
                               "e.g. `desk explain 14 EURUSD`.")
        return self._explain(rest[0], rest[1])

    # ── helpers ──────────────────────────────────────────────────────────
    def _mode(self) -> str:
        from bot_program.capital_desk import is_desk_enabled, is_live_mode
        if not is_desk_enabled():
            return ("OFF — pipeline_capital_desk is off, so the fleet pass is "
                    "the legacy loop and no plan is written")
        return ("LIVE (the fleet obeys the plan)" if is_live_mode()
                else "SHADOW (the plan is recorded, the fleet is unchanged)")

    def _write(self, line=""):
        self.stdout.write(line)

    # ── list ─────────────────────────────────────────────────────────────
    def _list(self, username, limit):
        from bot_program.models import DeskPlan

        self._write(f"desk mode: {self._mode()}")
        qs = DeskPlan.objects.select_related("user")
        if username:
            qs = qs.filter(user__username=username)
        rows = list(qs[:max(1, limit)])
        if not rows:
            self._write("no plans — the desk has written nothing yet.")
            return
        self._write("")
        self._write(f"{'ID':>5}  {'WHEN':<20} {'USER':<12} {'VENUE':<6} "
                    f"{'MODE':<7} {'CAND':>5} {'CHOSE':>6} {'MARGINAL':>10} "
                    f"{'EDGE R':>9}")
        for p in rows:
            # An ungraded plan prints an em dash. A 0.00 would read as "the
            # ranking made no difference", which nobody measured.
            edge = ("—" if p.edge_r is None
                    else f"{p.edge_r:+.3f}")
            if p.edge_r is None and p.graded_at:
                edge = "ungradeable"
            self._write(
                f"{p.pk:>5}  {p.created_at:%Y-%m-%d %H:%M}     "
                f"{p.user.username[:12]:<12} {p.venue:<6} {p.mode:<7} "
                f"{p.n_candidates:>5} {p.n_chosen + p.n_resized:>6} "
                f"{_money(p.new_risk_marginal):>10} {edge:>9}"
                + ("  ERROR" if p.error else ""))

    # ── show ─────────────────────────────────────────────────────────────
    # (module-level helper below the class would read worse here; see _money)
    def _show(self, plan_id):
        from bot_program.models import DeskPlan

        plan = (DeskPlan.objects.filter(pk=plan_id).first() if plan_id
                else DeskPlan.objects.select_related("user").first())
        if plan is None:
            raise CommandError("no such plan (see `desk list`)."
                               if plan_id else "no plans yet.")
        self._write(f"plan #{plan.pk}  {plan.venue}/{plan.mode}  "
                    f"{plan.created_at:%Y-%m-%d %H:%M}  tick {plan.tick_id}")
        # Two different quantities, and the budget was spent in the first:
        # the marginal risk each pick ADDED once its correlation with the
        # book and with the other picks was counted, against the raw sum of
        # risk-at-stop the account carries if every stop is hit. The page
        # names both; so does this (2026-09-12).
        self._write(f"  budget {float(plan.budget):.2f} left after a book of "
                    f"{float(plan.book_risk):.2f}; the plan committed "
                    f"{_money(plan.new_risk_marginal)} of it (marginal risk), "
                    f"raw risk at stop {float(plan.new_risk_chosen):.2f}")
        self._write(f"  {plan.n_candidates} candidates: {plan.n_chosen} chosen, "
                    f"{plan.n_resized} resized, {plan.n_displaced} displaced, "
                    f"{plan.n_duplicate} duplicate, "
                    f"{plan.n_not_desked} not desked")
        self._write(f"  matrix: {plan.matrix_pairs_measured} of "
                    f"{plan.matrix_pairs_total} pairs measured")
        if plan.error:
            self._write(f"  ERROR — the fleet ran undesked: {plan.error}")
        if plan.graded_at:
            edge = "—" if plan.edge_r is None else f"{plan.edge_r:+.4f}"
            self._write(f"  graded {plan.graded_at:%Y-%m-%d %H:%M}: "
                        f"edge {edge} R  {plan.edge_detail}")
        self._write("")
        self._write(f"{'#':>3} {'SYMBOL':<10} {'DIR':<5} {'OUTCOME':<20} "
                    f"{'MULT':>5} {'E[R]':>8} {'N':>4} {'LANE':<12} "
                    f"{'MARGINAL':>9} {'CF R':>8}  WHY")
        for d in plan.decisions.select_related("config").all():
            e_r = "—" if d.e_r is None else f"{d.e_r:+.3f}"
            cf = "—" if d.counterfactual_r is None else f"{d.counterfactual_r:+.3f}"
            if d.counterfactual_r is None and d.resolved_at:
                cf = d.counterfactual_outcome or "—"
            self._write(
                f"{d.rank:>3} {d.symbol[:10]:<10} {d.direction:<5} "
                f"{d.outcome:<20} {d.size_mult:>5.2f} {e_r:>8} {d.n:>4} "
                f"{d.lane:<12} {float(d.marginal_risk):>9.2f} {cf:>8}  "
                f"{d.reason}")

    # ── grade ────────────────────────────────────────────────────────────
    def _grade(self):
        from bot_program import capital_desk

        resolved = capital_desk.resolve_counterfactuals()
        graded = capital_desk.grade_plans()
        self._write(f"resolved {resolved} decision(s), graded {graded} plan(s).")
        self._write("A displaced entry is priced by walking its own bars over "
                    "its own horizon; a taken one by its trade's realized R. "
                    "edge_r is the desk's set minus the set the fleet would "
                    "have booked undesked.")

    # ── explain ──────────────────────────────────────────────────────────
    def _explain(self, config_id, symbol):
        from bot_program.asset_engine.base import make_bot
        from bot_program.capital_desk import expected_r, planned_net_rr
        from bot_program.models import AssetBotConfig

        try:
            cfg = AssetBotConfig.objects.get(pk=int(config_id))
        except (AssetBotConfig.DoesNotExist, ValueError):
            raise CommandError(f"no config #{config_id} (see `bot list`).")
        symbol = str(symbol).strip().upper()

        bot = make_bot(cfg)
        if not getattr(bot, "DESKED", True):
            self._write(f"{cfg.name} is an options bot — that lane trades "
                        f"through scan_symbol whole and the desk never "
                        f"displaces or resizes it.")
            return
        # pricing='data': the market-data session, never the exclusive
        # trading client. Nothing below can place an order.
        cand = bot.propose_entry(symbol, pricing="data")
        if cand is None:
            from bot_program.asset_engine import skips
            last = (skips.last_by_symbol(cfg).get(symbol) or {})
            self._write(f"{cfg.name} would propose nothing for {symbol}"
                        + (f" — {last.get('code')}: {last.get('detail')}"
                           if last else "."))
            return

        self._write(f"{cfg.name} would propose {symbol} {cand.direction} "
                    f"on {cand.venue}")
        self._write(f"  rule        {cand.rule_name or '(unnamed)'} "
                    f"(score {float(cand.decision.score):.2f})")
        self._write(f"  entry/stop  {cand.price:.6f} / {cand.stop:.6f}  "
                    f"target {cand.target:.6f}")
        self._write(f"  size        {cand.qty_default} units, risking "
                    f"{cand.risk_dollars_default:.2f} {cfg.base_currency} "
                    f"at the stop")
        self._write(f"  horizon     {cand.horizon_hours:.0f}h")
        self._write(f"  planned RR  {planned_net_rr(cand):.2f} net of the "
                    f"round trip")

        ev = expected_r(cand, user=cfg.user)
        self._write("")
        if ev["measured"]:
            self._write(f"  expected R  {ev['e_r']:+.3f} on the {ev['lane']} "
                        f"lane, n={ev['n']}, win rate "
                        f"{(ev['p_win'] or 0) * 100:.0f}%")
        else:
            # No lane cleared the floor. There is NO expected R, and the rank
            # falls back to conviction x planned net RR — said out loud
            # rather than printed as a confident 0.000.
            self._write(f"  expected R  — (unmeasured)")
        self._write(f"  ranked on   {ev['rank_key']:+.4f}  ({ev['reason']})")
        if ev["decaying"]:
            self._write("  DECAYING    the rule's recent expectancy has fallen "
                        "against its own baseline — its rank is halved")
        self._write("")
        self._write("Read-only: this ran propose_entry through the market-data "
                    "session and stopped. Nothing was sent.")
