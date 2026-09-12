"""The Horizon page (/horizon/) as a shell command — the 5-10 year view.

`/horizon/` shows the latest 5-10 year sector synthesis, the calls it is
held to and how they graded, the asset-class tilts the share allocator
reads as a ±10% prior, and a Run now button for superusers. This is that
page without the browser, through the same functions: `run` calls the
`run_horizon_now` the button calls (~1.5 USD on the frontier model), and
without `--yes` it prints the cost and does nothing — the deliberate act
here is the flag, as it is for `shares apply`.

    python manage.py horizon list             # runs: status, model, cost, calls, age
    python manage.py horizon show             # the latest OK view: sectors, tilts, calls, grades
    python manage.py horizon show 12          # one view by id
    python manage.py horizon run              # prints the cost, does nothing
    python manage.py horizon run --yes        # one synthesis now (~1.5 USD, frontier tier)
    python manage.py horizon grade            # brier / trust for agent 'horizon'
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("List, show, run or grade the 5-10 year sector synthesis "
            "(the /horizon/ page).")

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "show", "run", "grade"])
        parser.add_argument("id", nargs="?", type=int)
        parser.add_argument("--yes", action="store_true",
                            help="run: spend ~1.5 USD on the frontier model. "
                                 "Without it the command only prints the cost.")

    def handle(self, *args, **opts):
        act = opts["action"]
        if act == "list":
            return self._list()
        if act == "show":
            return self._show(opts.get("id"))
        if act == "run":
            return self._run(yes=opts["yes"])
        return self._grade()

    # ── list ─────────────────────────────────────────────────────────────
    def _list(self):
        from brain.horizon_models import HorizonView
        from bot_program.share_allocator import HORIZON_MAX_AGE_DAYS
        rows = list(HorizonView.objects.all().order_by("-created_at")[:30])
        self.stdout.write(f"HORIZON — runs ({len(rows)}); a view older than "
                          f"{HORIZON_MAX_AGE_DAYS}d is neutral to the allocator")
        if not rows:
            self.stdout.write("  none yet — `horizon run --yes`, or turn "
                              "agent_horizon on for the monthly beat")
            return
        for v in rows:
            self.stdout.write(
                f"  #{v.pk:<4} {v.status.upper():<9} {v.created_at:%Y-%m-%d %H:%M}  "
                f"age {v.age_days:5.1f}d  {v.horizon_years:>2}y  "
                f"model {v.model_used or '-':<22} cost {float(v.cost_usd):.3f} USD  "
                f"calls {v.calls_registered} registered / {v.calls_dropped} dropped")
            if v.error:
                self.stdout.write(f"        {v.error[:160]}")

    # ── show ─────────────────────────────────────────────────────────────
    def _show(self, pk):
        from types import SimpleNamespace

        from ai_agents.models import AgentPrediction
        from brain.horizon import SECTOR_NAMES
        from brain.horizon_models import HorizonView
        from bot_program.share_allocator import horizon_for

        if pk is not None:
            view = HorizonView.objects.filter(pk=pk).first()
            if view is None:
                raise CommandError(f"no horizon view #{pk}")
        else:
            view = (HorizonView.objects.filter(status=HorizonView.STATUS_OK)
                    .order_by("-created_at").first())
            if view is None:
                self.stdout.write("no OK view yet (see `horizon list`)")
                return
        self.stdout.write(
            f"#{view.pk} {view.status.upper()} {view.created_at:%Y-%m-%d %H:%M} "
            f"({view.age_days:.1f}d old) {view.horizon_years}y  model "
            f"{view.model_used or '-'}  cost {float(view.cost_usd):.3f} USD")
        if view.error:
            self.stdout.write(f"  error: {view.error[:300]}")
        if view.status == HorizonView.STATUS_REJECTED and view.raw:
            self.stdout.write("  raw output (first 1500 chars):")
            self.stdout.write("  " + view.raw[:1500].replace("\n", "\n  "))
            return
        if view.summary_md:
            self.stdout.write("\nSUMMARY")
            self.stdout.write("  " + view.summary_md.replace("\n", "\n  "))

        preds = {}
        for p in (AgentPrediction.objects
                  .filter(agent="horizon", prediction_type="direction",
                          created_at__gte=view.created_at)
                  .order_by("instrument_symbol", "-created_at")):
            preds.setdefault(p.instrument_symbol, p)

        self.stdout.write("\nSECTORS")
        for s in view.sectors or []:
            key = s.get("key")
            self.stdout.write(
                f"  {SECTOR_NAMES.get(key, key):<24} tilt {int(s.get('tilt') or 0):+d}  "
                f"conf {float(s.get('confidence') or 0):.2f}")
            thesis = (s.get("thesis_md") or "").replace("\n", " ").strip()
            if thesis:
                self.stdout.write(f"      {thesis[:240]}")
            for c in s.get("calls") or []:
                p = preds.get(str(c.get("symbol") or "").upper())
                if p is None:
                    state = "not registered"
                elif p.was_correct is True:
                    state = f"RIGHT ({p.actual_value}, move {p.score:+.4f})"
                elif p.was_correct is False:
                    state = f"WRONG ({p.actual_value}, move {p.score:+.4f})"
                elif p.evaluated_at:
                    state = p.actual_value
                else:
                    state = f"pending until {p.expected_resolution_at:%Y-%m-%d}"
                months = round(float(c.get("horizon_hours") or 0) / 730.0)
                self.stdout.write(
                    f"      call {c.get('symbol')} {str(c.get('direction')).upper()} "
                    f"{months}m conf {float(c.get('confidence') or 0):.2f} — {state}")

        self.stdout.write("\nASSET-CLASS TILTS (the allocator's fifth factor)")
        tilts = view.asset_class_tilts or {}
        if not tilts:
            self.stdout.write("  none — factor 1.00")
        for ac in sorted(tilts):
            hz = horizon_for(SimpleNamespace(asset_class=ac), view)
            slot = tilts[ac] or {}
            self.stdout.write(
                f"  {ac:<10} tilt {int(slot.get('tilt') or 0):+d}  conf "
                f"{float(slot.get('confidence') or 0):.2f}  -> factor "
                f"x{hz['factor']:.3f}  {slot.get('why', '')[:120]}")
        if view.regime_claims:
            self.stdout.write("\nREGIME CLAIMS")
            for c in view.regime_claims:
                self.stdout.write(f"  {c.get('claim')} ({c.get('horizon_hours')}h, "
                                  f"conf {float(c.get('confidence') or 0):.2f})")

    # ── run ──────────────────────────────────────────────────────────────
    def _run(self, *, yes):
        from ai_agents.spend import can_spend
        if not yes:
            allowed, reason = can_spend(tier="frontier", estimated_usd=1.5)
            self.stdout.write(
                "horizon run: one 5-10 year synthesis on the frontier model, "
                "~1.5 USD; budget now: " + reason)
            self.stdout.write("(nothing run — add --yes to spend it)")
            return
        from brain.horizon import run_horizon_now
        out = run_horizon_now()
        if out.get("ok"):
            self.stdout.write(self.style.SUCCESS(
                f"view #{out['view_id']} OK — {out['n_sectors']} sector(s), "
                f"{out['calls_registered']} call(s) registered, "
                f"{out['calls_dropped']} dropped; {float(out.get('cost_usd') or 0):.3f} USD "
                f"on {out.get('model')}"))
            self._show(out["view_id"])
        else:
            self.stdout.write(self.style.ERROR(
                f"view #{out.get('view_id', '?')} {out.get('outcome', 'error').upper()} "
                f"— {out.get('error', '')} ({float(out.get('cost_usd') or 0):.3f} USD)"))

    # ── grade ────────────────────────────────────────────────────────────
    def _grade(self):
        from brain.horizon import grade_record
        r = grade_record()
        brier = (f"{r['brier']:.4f}" if r["measured"] and r["brier"] is not None
                 else "— (needs %d graded calls)" % r["min_sample"])
        trust = f"x{r['trust']:.2f}" if r["measured"] else "— (unmeasured)"
        self.stdout.write(
            f"agent 'horizon': {r['n_total']} call(s), {r['n_graded']} graded "
            f"({r['n_correct']} right), {r['n_pending']} pending")
        self.stdout.write(f"  brier {brier}   trust {trust}")
