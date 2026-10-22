"""manage.py council — THE COUNCIL's record from the shell (2026-10-08).

  manage.py council show [--days N]   the record matrix and recent sittings
  manage.py council --grade           run the grader by hand (grade_due)
  manage.py council --backfill-debates
                                      record every closed live row the
                                      debate argued (metadata["debate"]) that
                                      has no sitting yet, so its two voices
                                      are graded at once. Idempotent.

Read and record only: nothing here sends, closes or resizes anything.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "THE COUNCIL: show the record, grade by hand, backfill the debate"

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="show",
                            choices=["show"])
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--grade", action="store_true")
        parser.add_argument("--backfill-debates", action="store_true",
                            dest="backfill")

    def handle(self, *args, **opts):
        if opts["backfill"]:
            n = backfill_debates()
            self.stdout.write(f"backfilled {n} debated trade(s)")
            return
        if opts["grade"]:
            from ai_agents.council_grading import grade_due
            self.stdout.write(f"graded: {grade_due()}")
            return
        self._show(opts["days"])

    def _show(self, days):
        from ai_agents.agents import council as C
        from ai_agents.council_grading import record_matrix
        from ai_agents.council_models import CouncilSession
        rec = record_matrix()
        self.stdout.write("THE COUNCIL: the record (live, "
                          f"{C.COUNCIL_RECORD_DAYS} days)")
        for v in rec["voices"]:
            self.stdout.write(
                f"  {v['name']:<16} weight {v['factor']:.2f} ({v['lane']}, "
                f"n {v['n']}) right {v['right']} of {v['right'] + v['wrong']}"
                f" · {v['specialty']}")
        for b in rec["benchmarks"]:
            self.stdout.write(
                f"  {b['name']}: " + (f"Brier {b['brier']:.3f} over {b['n']} "
                                      f"graded sittings" if b["brier"] is not None
                                      else "no graded sitting yet"))
        a = rec["against_hand"]
        self.stdout.write(
            f"  The Emperor against his Hand: {a['graded']} graded, the "
            f"Emperor right {a['emperor_right']}, the Hand right "
            f"{a['hand_right']}; {a['unresolved']} inside a quarter R, "
            f"{a['pending']} not graded yet; overruled without a reason "
            f"{a['no_reason']}")
        since = timezone.now() - timedelta(days=days)
        self.stdout.write(f"Recent sittings ({days} days)")
        for s in (CouncilSession.objects.filter(created_at__gte=since)
                  .order_by("-created_at")[:50]):
            if s.truth_r is not None:
                graded = f"{s.truth_r:+.2f}R ({s.truth})"
            elif s.graded_at:
                graded = (f"not measured "
                          f"({s.grade_notes or 'nothing to grade'})")
            else:
                graded = "not graded yet"
            self.stdout.write(f"  #{s.id} {s.created_at:%Y-%m-%d %H:%M} "
                              f"{s.origin} {s.symbol} {s.side} [{s.status}] "
                              f"{graded}")


def backfill_debates() -> int:
    """A record for every closed LIVE row the debate argued and no sitting
    covers: the levels the row opened with (the initial stop, as
    grade_bot_trade reads it), the regime recorded when it opened (ONE
    query and a bisect, persona_mix.regime_series), the two voices copied
    from metadata["debate"], linked by FK. Idempotent."""
    from django.db.models import Q

    from ai_agents.agents import council as C
    from ai_agents.council_models import CouncilSession, CouncilVoice
    from bot_program.models import AssetBotTrade
    from bot_program.persona_mix import labels_in_series, regime_series

    rows = list(AssetBotTrade.objects
                .filter(paper=False, status="CLOSED",
                        metadata__has_key="debate",
                        council_sessions__isnull=True)
                .exclude(Q(metadata__has_key="broker_env")
                         & Q(metadata__broker_env="paper"))
                .select_related("config").order_by("opened_at"))
    rows = [t for t in rows if isinstance((t.metadata or {}).get("debate"),
                                          dict)]
    if not rows:
        return 0
    series = regime_series(rows[0].opened_at)
    labels = labels_in_series(series, [t.opened_at for t in rows])
    n = 0
    for t, regime in zip(rows, labels):
        meta = t.metadata or {}
        debate = meta["debate"]

        def f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        stop = f(meta.get("initial_stop_loss")) or f(t.stop_loss)
        session = CouncilSession.objects.create(
            origin="bot", venue="live", status=CouncilSession.RECORD,
            user=getattr(t.config, "user", None), config=t.config, trade=t,
            linked_by="meta", symbol=t.symbol, asset_class=t.asset_class,
            side=t.side, rule_name=t.rule_name or "",
            entry=f(t.entry_price), stop=stop, target=f(t.take_profit),
            qty=f(t.qty),
            cost_fraction=f(meta.get("cost_fraction_charged")) or 0.0,
            horizon_hours=C._horizon_hours(t.config), regime=regime,
            facts={"backfilled": True}, brief="",
            schema_version=C.COUNCIL_SCHEMA_VERSION)
        CouncilSession.objects.filter(id=session.id).update(
            created_at=t.opened_at)
        session.created_at = t.opened_at
        m = C._meta(session)
        for side, agent in (("executioner", "debate_executioner"),
                            ("champion", "debate_champion")):
            ans = debate.get(side)
            if isinstance(ans, dict) and ans.get("verdict"):
                p, conv = C.p_and_conviction(side, ans)
                row = CouncilVoice.objects.create(
                    session=session, voice=side, agent=agent, wave=0,
                    status=CouncilVoice.COPIED,
                    verdict=str(ans.get("verdict"))[:20], p_work=p,
                    conviction=conv, answer=C._jsonable(ans))
                C._save_claims(m, row, C.claims_for(side, ans))
            else:
                CouncilVoice.objects.create(
                    session=session, voice=side, agent=agent, wave=0,
                    status=CouncilVoice.SILENT,
                    why=str(debate.get("why") or "silent")[:200])
        n += 1
    return n
