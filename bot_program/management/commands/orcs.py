"""The Orcs, from the shell (O1: journals of code facts, no model).

    python manage.py orcs                          # the switch, every live Orc, its last facts
    python manage.py orcs adopt --open             # plan: the open rows that would be adopted
    python manage.py orcs adopt --open --yes       # ... and adopt them
    python manage.py orcs adopt --open --user NAME --yes
    python manage.py orcs shadow-audit [--days 7] [--journal]
    python manage.py orcs shadow-audit --days 7       # the care ghost against the care's own exits
    python manage.py orcs actuals --days 14           # how many past prints carry an actual
    python manage.py orcs actuals --days 14 --record  # ... and record it
    python manage.py orcs dossier ROOT_ID             # a wake's dossier, replayed from its blocks
    python manage.py orcs dossier ROOT_ID --wake 2    # ... the wake before

`adopt --open` lists every OPEN row with no Orc and says, row by row, the
Orc it would get or why it gets none (an entry still working at the venue,
an options row, a config no tick manages, the cap on the Orcs outside
real money: paper and eToro demo rows, oldest first, as the census takes
them). It writes nothing without --yes, and --yes is refused while the
`orcs` switch is OFF (`manage.py component on orcs`). The census adopts
the same rows within five minutes of the switch going ON; this command
does it now. An adopted real-money row sends one line to its owner's
channel; a paper or demo row, none. No order is sent, no stop moved and no
model called.

`shadow-audit` (O1b, spec §6.1) checks the care ghost of every idea that
died in the last N days against the care's own exits and prints one line
per idea; it writes nothing unless --journal, which journals each line as
a fact on its idea, once.

`actuals` (O1c, spec §5.2a item 7) measures how many past high-impact
prints carry an actual, per calendar source; `--record` stores it (the day
roll records it daily). `dossier` (O1c) prints the dossier of an Orc's
wake (the latest; `--wake 2` the one before), replayed from its blocks.
Both read only, but for `actuals --record`.
"""

from django.core.management.base import BaseCommand, CommandError

from bot_program.orcs.constants import VENUE_DEMO, VENUE_LIVE, VENUE_PAPER

#: How each money world is named in the command's lines.
WORLD_WORDS = {VENUE_LIVE: "real", VENUE_DEMO: "demo", VENUE_PAPER: "paper"}


class Command(BaseCommand):
    help = "The Orcs: status, and the adoption of the open rows."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status",
                            choices=["status", "adopt", "shadow-audit",
                                     "actuals", "dossier"])
        parser.add_argument("ident", nargs="?", default="",
                            help="dossier: the Orc's root trade id")
        parser.add_argument("--open", action="store_true",
                            help="adopt: every open row with no Orc")
        parser.add_argument("--yes", action="store_true")
        parser.add_argument("--user", default="",
                            help="adopt: only this user's rows")
        parser.add_argument("--days", type=int, default=None,
                            help="shadow-audit (7) and actuals (14): the "
                                 "window, in days")
        parser.add_argument("--record", action="store_true",
                            help="actuals: store the measurement")
        parser.add_argument("--wake", type=int, default=1,
                            help="dossier: 1 the latest wake, 2 the one "
                                 "before")
        parser.add_argument("--journal", action="store_true",
                            help="shadow-audit: journal each line as a fact")

    def handle(self, *args, **opts):
        if opts["action"] == "adopt":
            return self._adopt(opts)
        if opts["action"] == "shadow-audit":
            return self._audit(opts)
        if opts["action"] == "actuals":
            return self._actuals(opts)
        if opts["action"] == "dossier":
            return self._dossier(opts)
        return self._status()

    # ── actuals ────────────────────────────────────────────────────────
    def _actuals(self, opts):
        from django.utils import timezone

        from bot_program.orcs.models import OrcSetting
        from bot_program.orcs.sources import actuals_measurement
        m = actuals_measurement(max(1, int(opts["days"] or 14)),
                                timezone.now())
        self.stdout.write(m["words"])
        for src, slot in sorted(m["by_source"].items()):
            self.stdout.write(f"  {src}: {slot['with_actual']} of "
                              f"{slot['n']}")
        if opts["record"]:
            OrcSetting.objects.update_or_create(
                key="calendar_actuals",
                defaults={"value": m, "updated_by": "manage.py orcs"})
            self.stdout.write("Recorded.")

    # ── dossier ────────────────────────────────────────────────────────
    def _dossier(self, opts):
        from bot_program.orcs.dossier import text_of
        from bot_program.orcs.models import Orc, OrcWake
        try:
            root = int(opts["ident"])
        except (TypeError, ValueError):
            raise CommandError("dossier needs the Orc's root trade id.")
        orc = Orc.objects.filter(root_trade_id=root).first()
        if orc is None:
            raise CommandError(f"No Orc on trade #{root}.")
        wakes = list(OrcWake.objects.filter(orc=orc)
                     .order_by("-created_at", "-id"))
        n = max(1, int(opts["wake"] or 1))
        if len(wakes) < n:
            self.stdout.write(f"Orc #{root} has no wake {n} (it has "
                              f"{len(wakes)}).")
            return
        w = wakes[n - 1]
        when = w.created_at.strftime("%Y-%m-%d %H:%M")
        why = ", ".join(str(r.get("t") or "") for r in w.reasons or [])
        score = f"{w.score:.0f}" if w.score is not None else "unscored"
        self.stdout.write(f"Orc #{root}, wake of {when} UTC ({w.status}): "
                          f"{why}; score {score}, {w.band}, the day "
                          f"{w.day_class}; {len(w.block_hashes)} blocks.")
        self.stdout.write(text_of(w.block_hashes))

    # ── shadow-audit ───────────────────────────────────────────────────
    def _audit(self, opts):
        from bot_program.orcs.grading import shadow_audit
        for line in shadow_audit(days=max(1, int(opts["days"] or 7)),
                                 journal=bool(opts["journal"])):
            self.stdout.write(line)

    # ── status ─────────────────────────────────────────────────────────
    def _status(self):
        from bot_program.orcs.army import name_of
        from bot_program.orcs.constants import STATE_DEAD
        from bot_program.orcs.models import Orc
        from bot_program.orcs.switches import orcs_on
        w = self.stdout.write
        w(f"The orcs switch is {'ON' if orcs_on() else 'OFF'}.")
        live = list(Orc.objects.exclude(state=STATE_DEAD)
                    .select_related("seat").order_by("root_trade_id"))
        dead = Orc.objects.filter(state=STATE_DEAD).count()
        w(f"{len(live)} live Orc(s), {dead} dead.")
        for orc in live:
            side = "long" if orc.side == "BUY" else "short"
            venue = WORLD_WORDS.get(orc.seat.venue, orc.seat.venue)
            overlay = " + Corsairs" if (orc.army_why or {}).get("overlay") \
                else ""
            w(f"  Orc #{orc.root_trade_id} {orc.symbol} {side} ({venue}, "
              f"{orc.state}, L{orc.seat.level} {orc.commission}, "
              f"{name_of(orc.army_type)}{overlay})")
            for line in (orc.card or {}).get("journal") or []:
                w(f"      {str(line.get('at') or '')[:16]}  {line.get('t')}")

    # ── adopt ──────────────────────────────────────────────────────────
    def _adopt(self, opts):
        from django.contrib.auth import get_user_model

        from bot_program.models import AssetBotTrade
        from bot_program.orcs import birth
        from bot_program.orcs.switches import orcs_on
        if not opts["open"]:
            raise CommandError("adopt needs --open: the open rows with no "
                               "Orc are the only rows it adopts.")
        on = orcs_on()
        if opts["yes"] and not on:
            raise CommandError("The orcs switch is OFF: nothing adopted. "
                               "`manage.py component on orcs` first.")
        rows = (AssetBotTrade.objects.select_related("config", "config__user")
                .filter(status="OPEN", orc_leg__isnull=True)
                .order_by("opened_at", "id"))
        if opts["user"]:
            user = get_user_model().objects.filter(
                username=opts["user"]).first()
            if user is None:
                raise CommandError(f"No user {opts['user']!r}.")
            rows = rows.filter(config__user=user)
        w = self.stdout.write
        if not on:
            w("The orcs switch is OFF: this is the plan only; --yes is "
              "refused until `manage.py component on orcs`.")
        elif not opts["yes"]:
            w("A plan only: nothing is written without --yes.")
        adopted = skipped = 0
        # the plan counts the cap as the adoption will spend it: once, in
        # the census's order (oldest first), so it never promises a row
        # the cap will refuse
        cap, room = birth.paper_cap(), birth.paper_left()
        for row in rows:
            side = "long" if str(row.side).upper() == "BUY" else "short"
            world = birth.world(row)
            label = (f"#{row.pk} {row.symbol} {side} "
                     f"({WORLD_WORDS.get(world, world)})")
            why = birth.skip_reason(row, row.config)
            if why:
                skipped += 1
                w(f"  {label}: no Orc: {why}.")
                continue
            if not opts["yes"]:
                if world != VENUE_LIVE:
                    if room <= 0:
                        skipped += 1
                        w(f"  {label}: no Orc: the paper cap is full "
                          f"({cap} at most outside real money).")
                        continue
                    room -= 1
                manual = birth.fail_toward_manual(row, row.config)
                w(f"  {label}: would be adopted "
                  f"({'advise, a hand idea' if manual else 'bot idea, shadow'}).")
                continue
            orc = birth.ensure(row, adopted=True)
            if orc is not None and getattr(orc, "just_born", False):
                adopted += 1
                w(f"  {label}: adopted as Orc #{orc.root_trade_id}.")
            else:
                skipped += 1
                w(f"  {label}: not adopted (the paper cap, or born "
                  f"meanwhile).")
        if opts["yes"]:
            w(f"Done: adopted {adopted}, left {skipped}.")
