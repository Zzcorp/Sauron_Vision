"""The Orcs, from the shell (O1: journals of code facts; O2a, 2026-11-05: the
minds' status, the smoke of one stored dossier, the smoke's verdicts and the
count of S; O2b, 2026-11-06: the smoke on a wake's routed rungs).

    python manage.py orcs                          # the switches, the Orcs line, the minds' queue, every live Orc
    python manage.py orcs adopt --open             # plan: the open rows that would be adopted
    python manage.py orcs adopt --open --yes       # ... and adopt them
    python manage.py orcs adopt --open --user NAME --yes
    python manage.py orcs shadow-audit [--days 7] [--journal]
    python manage.py orcs shadow-audit --days 7       # the care ghost against the care's own exits
    python manage.py orcs actuals --days 14           # how many past prints carry an actual
    python manage.py orcs actuals --days 14 --record  # ... and record it
    python manage.py orcs dossier ROOT_ID             # a wake's dossier, replayed from its blocks, with S and the answer
    python manage.py orcs dossier ROOT_ID --wake 2    # ... the wake before
    python manage.py orcs smoke --row ROOT_ID         # dry: the one call the Orc's latest stored dossier would make
    python manage.py orcs smoke --row ROOT_ID --yes   # ... sent once, on the Orcs line (the four gates ON)
    python manage.py orcs smoke --row ROOT_ID --rung h0 --yes
    python manage.py orcs smoke --row ROOT_ID --rung r2 --yes   # a routed rung: the router's switch ON too
    python manage.py orcs smoke-verdict --family sonnet --pass             # what claude_smoke --yes printed
    python manage.py orcs smoke-verdict --family opus --fail effort cache
    python manage.py orcs tokens --s                  # dry: what would be counted
    python manage.py orcs tokens --s --yes            # count S at the provider's free token count

`adopt --open` lists every OPEN row with no Orc and says, row by row, the
Orc it would get or why it gets none (an entry still working at the venue,
an options row, a config no tick manages, the cap on the Orcs outside
real money: paper and eToro demo rows, oldest first, as the census takes
them). It writes nothing without --yes, and --yes is refused while the
`orcs` switch is OFF (`manage.py component on orcs`). The census adopts
the same rows within five minutes of the switch going ON; this command
does it now. An adopted real-money row sends one line to its owner's
channel; a paper or demo row, none. No order is sent and no stop moved.

`shadow-audit` (O1b, spec §6.1) checks the care ghost of every idea that
died in the last N days against the care's own exits and prints one line
per idea; it writes nothing unless --journal, which journals each line as
a fact on its idea, once.

`actuals` (O1c, spec §5.2a item 7) measures how many past high-impact
prints carry an actual, per calendar source; `--record` stores it (the day
roll records it daily). `dossier` (O1c) prints the dossier of an Orc's
wake (the latest; `--wake 2` the one before), replayed from its blocks;
from O2a also S by its stored hash, the model's answer as kept with each
V-rule's verdict, the officer's verdicts and the booking, when a model
answered that wake. Both read only, but for `actuals --record`.

The status (no subcommand) shows both switches (`orcs` and `orcs_minds`),
the Orcs budget line, the model calls today, the wakes waiting for a model,
the money held for calls without a bill, the tickets in flight, the stall
alarm, the breaker and the ledger gaps. With the minds switch OFF and the
line at 0 it shows them OFF and at 0: no wake is read by a model then.

`smoke --row ROOT_ID` (O2a, the O2 spec A.60) reads the Orc's latest wake
with a stored dossier and prints, without --yes, the one call it would
make: the rung, its family, the tokens of the exact text, the bound, the
Orcs line's answer and the four gates. The rung is r0 by default, h0 with
--rung h0, or from O2b (2026-11-06, B.15a) one of a wake's rungs r1-r4,
answered as B.5 maps it (one effort per model until the smoke's PASS for
its family: r1 as r0, r3 and r4 as r2), both rungs printed. `--rung r5`
(O2b's frontier, 2026-11-06, B.15c, P35) goes only through Fable's gate,
read on that wake: it prints the clause that fails and refuses --yes with
it, nothing reserved or sent (in O2 the pair's bound is above the money
the Orcs may hold in flight, so a clause always fails); and since r5
answers only beside its blind twin, at a real-money extreme wake's own
claim, the smoke sends no Fable call even when every clause holds.
`--yes` is refused while any gate is OFF (the platform master, `orcs`,
`orcs_minds`, the Orcs line above 0), and for a rung above r0 while the
router's switch (`orcs_router`) is OFF, as a wake's would be. Otherwise it
reserves a ticket for the whole bound (no fallback: a ticket names none),
sends ONE call on the Orcs line (agent `orc`, source_ref
`Orc:<pk>:Smoke:<wake>:<rung>`, the rung that answered), prints the answer
and its validation, and writes nothing to the Orc: no journal entry,
plan, intent or counter.

`smoke-verdict` (A.61) records what `claude_smoke --yes` printed for one
model family: `--pass`, or `--fail` with one or more of call_a, call_b,
cache, effort. The effort rule of a wake's call reads the newest verdict.
It sends nothing. `tokens --s` counts S, the Orcs' doctrine, at the
provider's free token count: dry without --yes; with it, it needs the API
key only (no switch, no line) and records the count. Nothing else here
reaches a model.
"""

from django.core.management.base import BaseCommand, CommandError

from bot_program.orcs.constants import VENUE_DEMO, VENUE_LIVE, VENUE_PAPER

#: How each money world is named in the command's lines.
WORLD_WORDS = {VENUE_LIVE: "real", VENUE_DEMO: "demo", VENUE_PAPER: "paper"}
#: The smoke's caller row of §1.0.9, and the journal kind a model's answer
#: is kept under (O2a, 2026-11-05).
SMOKE = "smoke"
DECISION = "decision"


class Command(BaseCommand):
    help = ("The Orcs: status, adoption, the audits, the dossier, and the "
            "minds' smoke, verdicts and count of S.")

    def add_arguments(self, parser):
        from bot_program.orcs.constants import O2A_RUNG, SMOKE_FAIL_REASONS
        parser.add_argument("action", nargs="?", default="status",
                            choices=["status", "adopt", "shadow-audit",
                                     "actuals", "dossier", "smoke",
                                     "smoke-verdict", "tokens"])
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
        # O2a (2026-11-05): the smoke, its verdicts and the count of S
        parser.add_argument("--row", default="",
                            help="smoke: the Orc's root trade id")
        parser.add_argument("--rung", default=O2A_RUNG,
                            help="smoke: r0 (the default), h0, or a "
                                 "wake's rung r1-r4 (the router's switch "
                                 "ON); r5 only through Fable's gate, "
                                 "which refuses it in O2")
        parser.add_argument("--family", default="",
                            help="smoke-verdict: the model family the "
                                 "verdict is for")
        parser.add_argument("--pass", dest="verdict_pass",
                            action="store_true",
                            help="smoke-verdict: the smoke printed PASS")
        parser.add_argument("--fail", dest="verdict_fail", nargs="+",
                            choices=list(SMOKE_FAIL_REASONS), default=None,
                            help="smoke-verdict: the checks that failed")
        parser.add_argument("--s", dest="s", action="store_true",
                            help="tokens: count S, the Orcs' doctrine")

    def handle(self, *args, **opts):
        if opts["action"] == "adopt":
            return self._adopt(opts)
        if opts["action"] == "shadow-audit":
            return self._audit(opts)
        if opts["action"] == "actuals":
            return self._actuals(opts)
        if opts["action"] == "dossier":
            return self._dossier(opts)
        if opts["action"] == "smoke":
            return self._smoke(opts)
        if opts["action"] == "smoke-verdict":
            return self._smoke_verdict(opts)
        if opts["action"] == "tokens":
            return self._tokens(opts)
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
        self._mind_replay(orc, w)

    def _mind_replay(self, orc, w):
        """A.59 (O2a's arm, 2026-11-05): the wake's S by its stored hash,
        the model's answer as kept with each V-rule's verdict, the
        officer's verdicts on its proposals and the booking. Reads only."""
        import json

        from bot_program.orcs.dossier import family_of, text_of
        from bot_program.orcs.intents import STATUS_T, intent_words
        from bot_program.orcs.models import OrcIntent, OrcJournal
        out = self.stdout.write
        comps = w.components if isinstance(w.components, dict) else {}
        s = comps.get("s") if isinstance(comps.get("s"), dict) else {}
        if s.get("hash"):
            out(f"S {s.get('version') or '?'}, stored as "
                f"{str(s['hash'])[:12]}:")
            out(text_of([str(s["hash"])]))
        else:
            out("No S is stored for this wake: it was rendered while the "
                "minds were off.")
        decision = (OrcJournal.objects.filter(orc_id=orc.pk, wake_id=w.pk,
                                              kind=DECISION)
                    .order_by("-at", "-id").first())
        if decision is None:
            code = f": {w.skipped_reason}" if w.skipped_reason else ""
            out(f"No model answer for this wake ({w.status}{code}).")
        else:
            body = decision.body if isinstance(decision.body, dict) else {}
            out(f"The decision: {decision.headline}")
            out("The answer, as kept:")
            out(json.dumps(body.get("answer"), indent=2, sort_keys=True,
                           default=str))
            out(self._validation_words(body.get("status"), body.get("rule"),
                                       body.get("verdicts")))
            out(self._officer_words(body.get("officer")))
            family = (f" ({family_of(decision.model)} family)"
                      if decision.model else "")
            out(f"The booking: {decision.tokens_in} in, "
                f"{decision.tokens_out} out, cache read "
                f"{decision.cache_read}, cache written "
                f"{decision.cache_write}: "
                f"${float(decision.cost_usd or 0):.4f}{family}.")
        for it in OrcIntent.objects.filter(wake_id=w.pk).order_by(
                "created_at", "id"):
            words = intent_words(orc, {"kind": it.kind, "level": it.level,
                                       "event_id": it.event_id})
            officer = it.officer if isinstance(it.officer, dict) else {}
            rule = f" ({officer['rule']})" if officer.get("rule") else ""
            status_t = STATUS_T.get(it.status, it.status)
            why = (f" ({it.why})" if it.why and it.why != status_t else "")
            out(f"Proposed in shadow: {words}; the officer: "
                f"{officer.get('verdict') or 'not asked'}{rule}; "
                f"{status_t}{why}.")

    @staticmethod
    def _validation_words(status, rule, verdicts) -> str:
        """The validation in one line: its status, its rule when refused,
        then each V-rule's verdict ("V1 pass, V2 n/a, ...")."""
        verdicts = verdicts if isinstance(verdicts, dict) else {}
        listed = ", ".join(f"{k} {v}" for k, v in verdicts.items())
        head = f"The validation: {status or 'not judged'}"
        if rule:
            head += f" ({rule})"
        return f"{head}: {listed or 'no verdict kept'}."

    @staticmethod
    def _officer_words(officer) -> str:
        """The officer's would-verdict on the answer's proposal, if any."""
        officer = officer if isinstance(officer, dict) else {}
        if not officer.get("verdict"):
            return ("The officer: nothing to judge (the answer proposes no "
                    "step).")
        rule = f" ({officer['rule']})" if officer.get("rule") else ""
        words = f": {officer['words']}" if officer.get("words") else ""
        return f"The officer: {officer['verdict']}{rule}{words}."

    # ── shadow-audit ───────────────────────────────────────────────────
    def _audit(self, opts):
        from bot_program.orcs.grading import shadow_audit
        for line in shadow_audit(days=max(1, int(opts["days"] or 7)),
                                 journal=bool(opts["journal"])):
            self.stdout.write(line)

    # ── status ─────────────────────────────────────────────────────────
    def _status(self):
        from django.utils import timezone

        from bot_program.orcs.army import name_of
        from bot_program.orcs.constants import STATE_DEAD
        from bot_program.orcs.models import Orc
        from bot_program.orcs.switches import orcs_on
        w = self.stdout.write
        w(f"The orcs switch is {'ON' if orcs_on() else 'OFF'}.")
        self._minds_status(timezone.now())
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

    def _minds_status(self, now):
        """A.59 (O2a's arm, 2026-11-05): the minds switch, the Orcs line
        and the whole budget, the model calls today, the wakes waiting for
        a model, the money held for calls without a bill, the tickets in
        flight, the stall alarm, the breaker and the ledger gaps. Reads
        only; true with every switch OFF and the line at 0."""
        from datetime import datetime, timedelta
        from datetime import timezone as dt_tz

        from bot_program.orcs import mind_gateway, scheduler
        from bot_program.orcs.constants import (CODE_BACKLOG, HOLD_LEDGER_GAP,
                                                HOLD_ORPHAN, HOLD_TICKET,
                                                HOLD_UNBILLED, MINDS_SWITCH,
                                                STALL_MIN,
                                                WAKE_STATUS_PENDING,
                                                WAKE_STATUS_RUNNING,
                                                WAKE_STATUS_SKIPPED)
        from bot_program.orcs.models import Orc, OrcWake
        from bot_program.orcs.switches import minds_switch_on
        out = self.stdout.write
        out(f"The minds switch ({MINDS_SWITCH}) is "
            f"{'ON' if minds_switch_on() else 'OFF'}.")
        lines = mind_gateway.line_summary()
        if lines["orcs_enabled"]:
            out(f"The Orcs line: ${lines['orcs_spent']:.2f} of "
                f"${lines['orcs_cap']:.2f} today.")
        else:
            out("The Orcs line is off (ORC_DAILY_BUDGET_USD=0).")
        if lines["no_ceiling"]:
            out(f"The whole AI budget has no daily ceiling "
                f"(AI_DAILY_BUDGET_USD=0); ${lines['spent_total']:.2f} "
                f"spent today.")
        else:
            out(f"The whole AI budget: ${lines['spent_total']:.2f} of "
                f"${lines['total']:.2f} today; the core line "
                f"${lines['core_spent']:.2f} of ${lines['core_budget']:.2f} "
                f"({lines['core_formula']}).")
        day = scheduler.utc_day(now)
        calls = sum(int(n or 0) for n, seen in Orc.objects.values_list(
            "llm_wakes_today", "seen")
            if isinstance(seen, dict) and seen.get(scheduler.COUNTERS_DAY)
            == day)
        out(f"Model calls today: {calls}.")
        start = datetime.combine(now.astimezone(dt_tz.utc).date(),
                                 datetime.min.time(), tzinfo=dt_tz.utc)
        pending = OrcWake.objects.filter(status=WAKE_STATUS_PENDING).count()
        running = OrcWake.objects.filter(status=WAKE_STATUS_RUNNING).count()
        backlog = OrcWake.objects.filter(
            status=WAKE_STATUS_SKIPPED, skipped_reason=CODE_BACKLOG,
            created_at__gte=start).count()
        out(f"Wakes waiting for a model: {pending} pending, {running} "
            f"running; {backlog} answered by code after a backlog today.")
        held = mind_gateway.holds(now)

        def total(kinds):
            got = [e for e in held.values() if e.get("kind") in kinds]
            return len(got), sum(float(e.get("usd") or 0) for e in got)
        _n, unbilled = total((HOLD_UNBILLED, HOLD_ORPHAN))
        out(f"Held for calls without a bill: ${unbilled:.2f}.")
        n, usd = total((HOLD_TICKET,))
        out(f"Tickets in flight: {n} (${usd:.2f})." if n
            else "Tickets in flight: none.")
        stalled = OrcWake.objects.filter(
            status=WAKE_STATUS_PENDING,
            queued_at__lt=now - timedelta(minutes=STALL_MIN)).count()
        out(f"The stall alarm: {stalled} wake(s) waited over {STALL_MIN} "
            f"minutes for a model call." if stalled
            else "The stall alarm is quiet.")
        breaker = scheduler.breaker_state(now)
        if breaker:
            until = str(breaker.get("until") or "")[11:16]
            out(f"The breaker is open until {until} UTC: "
                f"{breaker.get('why') or 'model calls failed'}; the claims "
                f"pause.")
        else:
            out("The breaker is closed.")
        n, usd = total((HOLD_LEDGER_GAP,))
        out(f"Ledger gaps: {n} (${usd:.2f} held until 00:00 UTC)." if n
            else "Ledger gaps: none.")

    # ── smoke (A.60) ───────────────────────────────────────────────────
    def _smoke(self, opts):
        """A.60 (O2a's arm, 2026-11-05): the one command of O2a that sends
        a call. Dry by default; --yes refused while a gate is OFF; a
        ticket for the whole bound, ONE send on the Orcs line, the answer
        judged and printed; nothing written to the Orc. O2b (2026-11-06,
        B.15a, P34): a wake's rungs r1-r4 under a wake's gates, the
        router's switch among them, each answered as B.5 maps it."""
        from django.utils import timezone

        from bot_program.orcs import mind, mind_gateway, scheduler, switches
        from bot_program.orcs.constants import (CODE_UNBILLED, REPLY_UNBILLED,
                                                ROUTED_RUNGS, ROUTER_SWITCH,
                                                SMOKE_MAPPED_T,
                                                TICKET_CODE_WORDS,
                                                WAKE_CODE_WORDS)
        words = {**WAKE_CODE_WORDS, **TICKET_CODE_WORDS}
        orc = self._orc_of(opts["row"], "smoke --row")
        asked = str(opts["rung"] or "")
        from bot_program.orcs.constants import FRONTIER_RUNG
        if asked == FRONTIER_RUNG:
            # B.15c, P35 (O2b's frontier, 2026-11-06): r5 only through
            # Fable's gate
            return self._smoke_fable(orc, opts)
        try:
            mind.ticket_caller(SMOKE, asked)
        except ValueError as e:
            raise CommandError(f"{e}: nothing was reserved or sent.")
        # B.15a, B.5 (O2b, 2026-11-06): a wake's rung answers as the effort
        # map says (one effort per model until the smoke's PASS), and a
        # rung above r0 takes the router's switch, as a wake's does
        rung_name = mind.answering_rung(asked)
        routed = asked in ROUTED_RUNGS
        w = self._smoke_wake(orc)
        try:
            request = mind.build_request(w, rung_name)
        except (ValueError, KeyError, TypeError) as e:
            raise CommandError(f"Orc #{orc.root_trade_id}'s wake #{w.pk} "
                               f"cannot be sent: {e}.")
        step = mind_gateway.rung(rung_name)
        tokens = mind.ticket_tokens(w, rung_name)
        price = mind.ticket_price(rung_name, tokens)
        ref = mind.source_ref(w, rung_name, caller=SMOKE)
        out = self.stdout.write
        when = w.created_at.strftime("%Y-%m-%d %H:%M")
        effort = request.get("turn_effort") or request.get("effort")
        out(f"The smoke of Orc #{orc.root_trade_id} ({orc.symbol}): wake "
            f"#{w.pk} of {when} UTC, its stored dossier "
            f"({len(w.block_hashes or [])} blocks and S).")
        which = (SMOKE_MAPPED_T.format(asked=asked, rung=rung_name,
                                       family=step["family"]) + ":"
                 if rung_name != asked else f"rung {rung_name},")
        out(f"The call: {which} the {step['family']} family "
            f"({step['tier']} tier, effort {effort}), at most "
            f"{step['max_tokens']} tokens out, one send.")
        out(f"Its text: {tokens} tokens estimated; bound "
            f"${price['bound']:.4f} (every prompt token at the 1h cache "
            f"write on 1.35 x the estimate, plus the output).")
        allowed, code, why = mind.ask_line(rung_name=rung_name,
                                           bound_usd=price["bound"])
        out(f"The Orcs line: {'allowed' if allowed else f'refused ({code})'}"
            f": {why}.")
        gate = switches.gate_code()
        out(f"The four gates: {self._gates_words()}"
            + (": a call may be sent." if not gate
               else f": --yes is refused, {words.get(gate, gate)} ({gate})."))
        router = switches.router_on()
        if routed:
            out(f"The router's switch ({ROUTER_SWITCH}) is "
                f"{'ON' if router else 'OFF'}"
                + (": a rung above r0 may be sent." if router else
                   f": --yes is refused for rung {asked}, a rung above r0."))
        if not opts["yes"]:
            out("DRY RUN: nothing reserved, nothing sent. --yes sends ONE "
                "call on the Orcs line.")
            return
        if gate:
            raise CommandError(f"--yes is refused while a gate is OFF: "
                               f"{words.get(gate, gate)} ({gate}). Nothing "
                               f"was reserved or sent.")
        if routed and not router:
            raise CommandError(f"--yes is refused for rung {asked} while the "
                               f"router's switch is OFF ({ROUTER_SWITCH}): a "
                               f"rung above r0 is sent, as a wake's is, only "
                               f"with it ON (at /ops/, with the trading "
                               f"PIN). Nothing was reserved or sent.")
        got = scheduler.reserve_ticket(SMOKE, {"rung": rung_name,
                                               "tokens": tokens,
                                               "orc": orc.pk, "ref": ref})
        if not got["ok"]:
            code = got["code"]
            raise CommandError(f"The ticket was refused: "
                               f"{words.get(code, code)} ({code}). Nothing "
                               f"was sent.")
        # what the settle reads if the gateway itself raised: a call that
        # may have been sent, its bound held until 00:00 UTC
        reply = {"kind": REPLY_UNBILLED, "sent": True, "usage": None,
                 "code": CODE_UNBILLED}
        started = timezone.now()
        try:
            reply = mind_gateway.call(caller=SMOKE, rung_name=rung_name,
                                      request=request, source_ref=ref,
                                      bound_usd=got["bound"],
                                      exclude_key=got["key"])
        finally:
            # the ticket is settled whatever came back; the ledger's row
            # is looked up first, with no lock held (N8)
            usage = reply.get("usage") if isinstance(reply.get("usage"),
                                                     dict) else None
            found = (mind_gateway.ledger_row(ref, since=started)
                     if usage is not None else None)
            settled = scheduler.settle_ticket(got["key"],
                                              {**reply, "ledger": found})
        self._smoke_answer(w, reply, ref, found, settled)

    def _smoke_fable(self, orc, opts):
        """B.15c, P35 (O2b's frontier, 2026-11-06): `--rung r5` goes only
        through Fable's gate, its clauses read in their order on the Orc's
        latest stored wake (router.fable_gate): real money, the band
        extreme, a frontier quota left, the frontier's switch, the pair's
        money (scheduler.fable_money: priced at the dossier's size cap, in
        O2 above the money the Orcs may hold in flight), its stored
        dossier written for Fable within its cap. Dry, it prints the
        clause; --yes is refused with it, nothing reserved or sent. When
        every clause holds, --yes is refused too: r5 answers only beside
        its r4 blind twin, at a real-money extreme wake's own claim, and
        the smoke sends one call, never a pair."""
        from bot_program.orcs import mind, router, scheduler, switches
        from bot_program.orcs.constants import FRONTIER_RUNG
        w = self._smoke_wake(orc)
        comps = w.components if isinstance(w.components, dict) else {}

        def stored():
            if str(comps.get("family") or "") != "fable":
                return router.NOT_FABLE_STORED
            return router.FABLE_OVER if comps.get("over_budget") else ""
        clause = router.fable_gate(
            real=scheduler.is_real(orc), band=str(w.band or ""),
            quota=lambda: mind.frontier_left(orc.user_id),
            switch=switches.frontier_on,
            money=lambda: scheduler.fable_money(w.reasons), render=stored)
        pair = mind.pair_price()
        out = self.stdout.write
        when = w.created_at.strftime("%Y-%m-%d %H:%M")
        out(f"The smoke of Orc #{orc.root_trade_id} ({orc.symbol}): wake "
            f"#{w.pk} of {when} UTC, rung {FRONTIER_RUNG} (Fable), which "
            f"answers only beside its r4 blind twin: the pair is bounded at "
            f"${pair['weigh']:.4f} at the dossier's size cap.")
        out("Fable's gate: " + (f"closed, {clause}." if clause else
                                "every clause holds."))
        why = (f"{clause} (Fable's gate)" if clause else
               "r5 answers only beside its r4 blind twin, at a real-money "
               "extreme wake's own claim; the smoke sends no pair")
        if not opts["yes"]:
            out(f"DRY RUN: nothing reserved, nothing sent. --yes is refused "
                f"for rung {FRONTIER_RUNG!r}: {why}.")
            return
        raise CommandError(f"--yes is refused for rung {FRONTIER_RUNG!r}: "
                           f"{why}. Nothing was reserved or sent.")

    def _smoke_wake(self, orc):
        """The Orc's latest wake with a stored dossier: S by its hash and
        the blocks (rendered while the minds were on)."""
        from bot_program.orcs.models import OrcWake
        for w in OrcWake.objects.filter(orc_id=orc.pk).order_by(
                "-created_at", "-id")[:50]:
            comps = w.components if isinstance(w.components, dict) else {}
            s = comps.get("s") if isinstance(comps.get("s"), dict) else {}
            if s.get("hash") and w.block_hashes:
                return w
        raise CommandError(f"Orc #{orc.root_trade_id} has no wake with a "
                           f"stored dossier (S and its blocks, rendered while "
                           f"the minds were on): nothing to send.")

    def _smoke_answer(self, w, reply, ref, found, settled):
        """What the one send came back with, judged as a wake's answer is
        (the validator and the officer, no lock held) and printed; the
        ticket's settle; nothing written to the Orc."""
        import json

        from django.utils import timezone

        from bot_program.orcs import mind
        from bot_program.orcs.constants import (REPLY_ANSWER, REPLY_BILLED,
                                                REPLY_CLOSED, REPLY_UNSENT,
                                                WAKE_CODE_WORDS)
        out = self.stdout.write
        kind = reply.get("kind")
        if kind == REPLY_CLOSED:
            code = str(reply.get("code") or "")
            out(f"Not sent: {WAKE_CODE_WORDS.get(code, code)} ({code})"
                + (f": {reply['why']}" if reply.get("why") else "") + ".")
        elif kind == REPLY_UNSENT:
            out(f"Not sent: the request was refused before the send "
                f"({reply.get('error')}).")
        else:
            out(f"Sent once on the Orcs line: agent orc, source_ref {ref} "
                f"({float(reply.get('latency') or 0):.1f} s).")
        if kind in (REPLY_ANSWER, REPLY_BILLED):
            outcome = mind.judge(w, reply, now=timezone.now())
            verdict = outcome.get("verdict") if isinstance(
                outcome.get("verdict"), dict) else {}
            if kind == REPLY_BILLED:
                out(f"The call failed and was billed: {reply.get('error')}.")
            out("The answer, as kept:")
            out(json.dumps(outcome.get("kept"), indent=2, sort_keys=True,
                           default=str))
            out(self._validation_words(verdict.get("status"),
                                       verdict.get("rule"),
                                       verdict.get("verdicts")))
            intent = outcome.get("intent") if isinstance(
                outcome.get("intent"), dict) else {}
            out(self._officer_words(intent.get("officer")))
        elif kind not in (REPLY_CLOSED, REPLY_UNSENT):
            out(f"The call failed with no bill read: {reply.get('error')}.")
        usage = reply.get("usage") if isinstance(reply.get("usage"),
                                                 dict) else None
        if usage is not None:
            out(f"Booked: {int(usage.get('input_tokens') or 0)} in, "
                f"{int(usage.get('output_tokens') or 0)} out, cache read "
                f"{int(usage.get('cache_read_input_tokens') or 0)}, cache "
                f"written "
                f"{int(usage.get('cache_creation_input_tokens') or 0)}: "
                f"${float(usage.get('cost_usd') or 0):.4f} on the Orcs line"
                f"{'' if found else '; its ledger row was not found'}.")
        held = settled.get("held")
        out(f"The ticket: held until 00:00 UTC as {held}." if held
            else "The ticket: released.")
        out("Nothing was written to the Orc: no journal entry, no plan, no "
            "intent, no counter.")

    def _orc_of(self, ident, what):
        from bot_program.orcs.models import Orc
        try:
            root = int(ident)
        except (TypeError, ValueError):
            raise CommandError(f"{what} needs the Orc's root trade id.")
        orc = Orc.objects.filter(root_trade_id=root).first()
        if orc is None:
            raise CommandError(f"No Orc on trade #{root}.")
        return orc

    @staticmethod
    def _gates_words() -> str:
        """A.2's four gates, each ON or OFF."""
        from bot_program.orcs import mind_gateway, switches
        from bot_program.orcs.constants import MINDS_SWITCH, PLATFORM_MASTER

        def on(flag):
            return "ON" if flag else "OFF"
        try:
            line = mind_gateway.line_cap() > 0
        except Exception:  # noqa: BLE001 — an unread line is off
            line = False
        return (f"the platform master "
                f"{on(switches._component_on(PLATFORM_MASTER))}, "
                f"{MINDS_SWITCH} {on(switches.minds_switch_on())}, the Orcs "
                f"line {on(line)}, orcs {on(switches.orcs_on())}")

    # ── smoke-verdict and tokens (A.61) ────────────────────────────────
    def _smoke_verdict(self, opts):
        """A.61 (O2a's arm, 2026-11-05): what the operator read from
        claude_smoke --yes for one family, {verdict, reasons, at}, in
        OrcSetting "smoke_verdict". Sends nothing."""
        from django.utils import timezone

        from bot_program.orcs.constants import MK_FAMILIES, SMOKE_VERDICT_KEY
        from bot_program.orcs.models import OrcSetting
        family = str(opts["family"] or "").strip().lower()
        if family not in MK_FAMILIES:
            raise CommandError(f"smoke-verdict needs --family, one of "
                               f"{', '.join(MK_FAMILIES)}.")
        passed, failed = bool(opts["verdict_pass"]), opts["verdict_fail"]
        if passed == bool(failed):
            raise CommandError("smoke-verdict needs --pass, or --fail with "
                               "the checks that failed; not both.")
        reasons = list(dict.fromkeys(failed or []))
        value = OrcSetting.get(SMOKE_VERDICT_KEY)
        value = dict(value) if isinstance(value, dict) else {}
        value[family] = {"verdict": "pass" if passed else "fail",
                         "reasons": reasons,
                         "at": timezone.now().isoformat()}
        OrcSetting.objects.update_or_create(
            key=SMOKE_VERDICT_KEY,
            defaults={"value": value, "updated_by": "manage.py orcs"})
        out = self.stdout.write
        out(f"Recorded for the {family} family: "
            + ("PASS." if passed else f"FAIL ({', '.join(reasons)})."))
        out("The effort-only message and two efforts on one model are used "
            "for a family only while its newest verdict is PASS. Nothing "
            "was sent.")
        for fam in sorted(value):
            entry = value[fam] if isinstance(value[fam], dict) else {}
            why = ", ".join(entry.get("reasons") or [])
            out(f"  {fam}: {str(entry.get('verdict') or '?').upper()}"
                + (f" ({why})" if why else "")
                + f", {str(entry.get('at') or '')[:16]}")

    def _tokens(self, opts):
        """A.61 (O2a's arm, 2026-11-05): S counted at the provider's free
        token count through the gateway (N3's one exception): dry without
        --yes; with it, the API key only, no switch and no line; the count
        recorded in OrcSetting "s_tokens"."""
        from django.utils import timezone

        from bot_program.orcs import doctrine, mind_gateway
        from bot_program.orcs.constants import O2A_RUNG, S_TOKENS_KEY, \
            S_VERSION
        from bot_program.orcs.models import OrcSetting
        if not opts["s"]:
            raise CommandError("tokens needs --s: S, the Orcs' doctrine, is "
                               "what it counts.")
        step = mind_gateway.rung(O2A_RUNG)
        text = doctrine.S
        out = self.stdout.write
        out(f"S {S_VERSION}: {len(text)} characters, counted on rung "
            f"{O2A_RUNG}'s model ({step['family']} family), as the system "
            f"turn of a wake's call.")
        if not opts["yes"]:
            out("DRY RUN: nothing counted. --yes asks the provider's free "
                "token count once (no switch and no line: the API key "
                "only).")
            return
        if not mind_gateway.has_key():
            raise CommandError("tokens --s --yes needs the provider's API key "
                               "in this process: nothing was counted.")
        n = mind_gateway.measure_tokens(
            rung_name=O2A_RUNG, system_blocks=[{"text": text,
                                                "cache_ttl": "1h"}],
            user_message=".")
        value = {"version": S_VERSION, "family": step["family"],
                 "rung": O2A_RUNG, "tokens": int(n), "chars": len(text),
                 "at": timezone.now().isoformat()}
        OrcSetting.objects.update_or_create(
            key=S_TOKENS_KEY,
            defaults={"value": value, "updated_by": "manage.py orcs"})
        out(f"S {S_VERSION} counts {int(n)} input tokens on the "
            f"{step['family']} family (with a one-character user turn); "
            f"recorded. The count is free and never booked.")

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
