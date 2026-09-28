"""The three trader personalities from the shell — the /personas/ page,
as a command.

A persona is a COHERENT PRESET of knobs that already exist (timeframe,
entry bar, ATR multiples, hold ceiling, concurrency, risk fraction,
breakers), plus a grading window matched to its holding period, a share
band in the account allocator and a weight on the horizon prior. It is
not a new engine, and it changes NO capital and NO account share.

NO PERSONALITY BORROWS TO FUND A POSITION — scoped deliberately, because
`AssetBotConfig` carries no `leverage` and no `margin_mode` field for a
persona to set, while the dormant `BotConfig` futures engine carries
both. The short-term "leverage" a persona does control is the notional
fraction the risk sizer may reach and the number of concurrent
positions: cash on every class but forex, where the class default stays
at 4.0 and the leverage is carried by the broker.

`apply` prints the plan and every warning and WRITES NOTHING. `--yes` is
this command's stand-in for the PIN the page asks for: applying a persona
to a LIVE config re-sizes real risk on the next entry.

`mix` is THE MATRIX: three personalities × six regimes, each cell the
factor that regime puts on that personality's SHARE BAND and the lane
that spoke — measured evidence, an unproven prior, or neutral. Nobody
knows yet which personality suits which tape, so the table never states a
factor without saying where it came from, and it counts how many of the
eighteen cells are still guesses.

    python manage.py persona list
    python manage.py persona show scalp
    python manage.py persona apply 14 swing         # plan only, writes nothing
    python manage.py persona apply 14 swing --yes   # writes
    python manage.py persona grade
    python manage.py persona mix                    # the matrix + the recorded regime
    python manage.py persona mix --venue paper --regime trending
"""
from django.core.management.base import BaseCommand, CommandError


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value == int(value):
        return f"{int(value)}"
    return str(value)


def _r(lane) -> str:
    """Σ R for a lane, '—' when nothing was measured. Never 0.00."""
    if not lane or lane.get("r_sum") is None:
        return "—"
    return f"{float(lane['r_sum']):+.2f}"


def _wr(lane) -> str:
    if not lane or lane.get("win_rate") is None:
        return "—"
    return f"{float(lane['win_rate']) * 100:.0f}%"


class Command(BaseCommand):
    help = ("The three trader personalities: list them, show one, apply one "
            "to a config (--yes writes), grade them over their own windows, "
            "or print the regime mix matrix.")

    def add_arguments(self, parser):
        parser.add_argument("action",
                            choices=["list", "show", "apply", "grade", "mix"])
        parser.add_argument("args", nargs="*")
        parser.add_argument("--yes", action="store_true",
                            help="Write. Without it `apply` only prints the "
                                 "plan (the page asks the trading PIN here).")
        parser.add_argument("--venue", choices=["live", "paper"],
                            default="live",
                            help="Which venue `mix` reads. Live and paper "
                                 "are never pooled — a paper fill is charged "
                                 "a modelled half-spread and has no resting "
                                 "stop at a broker.")
        parser.add_argument("--regime", default="",
                            help="Which regime `mix` explains in full. "
                                 "Defaults to the one the platform is "
                                 "recording right now.")

    def handle(self, *args, **opts):
        action = opts["action"]
        # `args` is the one dest name call_command() takes away: it POPS
        # "args" out of the parsed options and re-sends it as *args
        # (django.core.management.call_command). So the shell fills
        # opts["args"] and every in-process caller — the tests, and any
        # page that ever shells this in — fills *args, and reading only
        # one of the two raises KeyError for exactly half the callers
        # (2026-09-12).
        rest = [str(a) for a in (opts.get("args") or args or [])]
        if action == "list":
            return self._list()
        if action == "show":
            return self._show(rest[0] if rest else "")
        if action == "grade":
            return self._grade()
        if action == "mix":
            return self._mix(venue=opts.get("venue") or "live",
                             regime=str(opts.get("regime") or ""))
        return self._apply(rest, yes=opts["yes"])

    # ── list ────────────────────────────────────────────────────────────

    def _list(self):
        from bot_program.personas import PERSONAS, knob_matrix, persona_of
        from bot_program.models import AssetBotConfig

        keys = list(PERSONAS)
        self.stdout.write("THE THREE PERSONALITIES — a preset, a grading "
                          "window, a share band, a horizon weight.")
        self.stdout.write("No personality borrows to fund a position: the "
                          "lever a persona sets is the notional cap and "
                          "the number of concurrent positions, not a loan. "
                          "Forex is the exception — the class default "
                          "stays at 4.0 notional and that leverage is "
                          "carried by the broker.")
        self.stdout.write("")
        self.stdout.write(f"  {'knob':<26}" + "".join(f"{k:<16}" for k in keys))
        self.stdout.write("  " + "-" * (26 + 16 * len(keys)))
        for row in knob_matrix():
            mark = " " if row["differs"] else "="
            cells = "".join(f"{_fmt(row['values'][k]):<16}" for k in keys)
            self.stdout.write(f" {mark}{row['knob']:<26}{cells}")
        self.stdout.write("  " + "-" * (26 + 16 * len(keys)))
        for name, attr in (("grading window (days)", "evidence_days"),
                           ("horizon weight", "horizon_weight"),
                           ("share floor %", "share_floor_pct"),
                           ("share ceiling %", "share_ceiling_pct")):
            cells = "".join(f"{_fmt(getattr(PERSONAS[k], attr)):<16}"
                            for k in keys)
            self.stdout.write(f"  {name:<26}{cells}")
        self.stdout.write("")
        wearing = {k: [] for k in keys}
        unworn = []
        for cfg in AssetBotConfig.objects.select_related("user").order_by("pk"):
            key = persona_of(cfg)
            (wearing[key] if key in wearing else unworn).append(cfg)
        for key in keys:
            cfgs = wearing[key]
            if not cfgs:
                self.stdout.write(
                    f"  {key}: no config wears it — "
                    f"`persona apply <config_id> {key} --yes` gives one this "
                    f"personality.")
                continue
            self.stdout.write(f"  {key}: " + "; ".join(
                f"[{c.pk}] {c.name} ({c.asset_class}/{c.mode})" for c in cfgs))
        if unworn:
            self.stdout.write(
                f"  (no persona): " + "; ".join(
                    f"[{c.pk}] {c.name}" for c in unworn[:20])
                + ("" if len(unworn) <= 20 else f" (+{len(unworn) - 20} more)"))

    # ── show ────────────────────────────────────────────────────────────

    def _show(self, key):
        from bot_program.personas import PERSONAS, PERSONA_KEYS
        persona = PERSONAS.get(str(key or "").strip().lower())
        if persona is None:
            raise CommandError(
                f"no persona named {key!r} — the three are "
                f"{', '.join(PERSONA_KEYS)} (see `persona list`).")
        self.stdout.write(f"{persona.key.upper()} — {persona.purpose}")
        self.stdout.write(f"  holding period: {persona.holding}")
        self.stdout.write(f"  grading window: {persona.evidence_days} days")
        self.stdout.write(f"  share band:     {persona.share_floor_pct:g}%"
                          f"–{persona.share_ceiling_pct:g}% of the account")
        self.stdout.write(f"  horizon weight: ×{persona.horizon_weight:g} "
                          f"on the 5-10 year prior")
        self.stdout.write(f"  asset classes:  "
                          f"{', '.join(persona.asset_classes)}")
        self.stdout.write("")
        self.stdout.write("  config fields")
        for name, value in persona.fields.items():
            self.stdout.write(f"    {name:<26} {_fmt(value):<10} "
                              f"{persona.why.get(name, '')}")
        self.stdout.write("  extras")
        for name, value in persona.extras.items():
            self.stdout.write(f"    {name:<26} {_fmt(value):<10} "
                              f"{persona.why.get(name, '')}")

    # ── apply ───────────────────────────────────────────────────────────

    def _apply(self, rest, *, yes):
        from bot_program.models import AssetBotConfig
        from bot_program.personas import PERSONA_KEYS, apply_persona, plan_for

        if len(rest) < 2:
            raise CommandError(
                "persona apply <config_id> <key> [--yes] — give a config id "
                f"(see `persona list`) and one of {', '.join(PERSONA_KEYS)}.")
        try:
            cfg_id = int(rest[0])
        except (TypeError, ValueError):
            raise CommandError(f"{rest[0]!r} is not a config id.")
        key = str(rest[1]).strip().lower()
        cfg = AssetBotConfig.objects.filter(pk=cfg_id).first()
        if cfg is None:
            raise CommandError(f"no config with id {cfg_id} (see "
                               f"`persona list`).")

        plan = plan_for(cfg, key)
        self.stdout.write(f"[{cfg.pk}] {cfg.name} ({cfg.asset_class}/"
                          f"{cfg.mode}) → persona {key}")
        if not plan["ok"]:
            self.stdout.write(self.style.ERROR(f"  refused: {plan['reason']}"))
            return
        if not plan["changes"] and not plan["extras"] and not plan.get("drops"):
            self.stdout.write("  every knob is already at this persona's "
                              "value — only the persona stamp would change.")
        for name, (old, new) in plan["changes"].items():
            self.stdout.write(f"  field  {name:<26} {_fmt(old)} -> {_fmt(new)}")
        for name, (old, new) in plan["extras"].items():
            self.stdout.write(f"  extra  {name:<26} {_fmt(old)} -> {_fmt(new)}")
        # A dropped key is a change like any other and has to print like
        # one: it is the difference between a swing book that still sizes
        # off a scalp's notional cap and one that does not.
        for name, old in (plan.get("drops") or {}).items():
            self.stdout.write(f"  drop   {name:<26} {_fmt(old)} -> removed "
                              f"(the platform default applies again)")
        for w in plan["warnings"]:
            self.stdout.write(self.style.WARNING(f"  ! {w}"))
        self.stdout.write("  capital and account share are NOT touched; the "
                          "bot is neither enabled nor disabled.")
        if not yes:
            self.stdout.write("(plan only — add --yes to write; --yes is "
                              "this command's stand-in for the page's PIN)")
            return
        result = apply_persona(cfg, key, user=None, force=True)
        if not result["ok"]:
            self.stdout.write(self.style.ERROR(f"  refused: "
                                               f"{result['reason']}"))
            return
        self.stdout.write(self.style.SUCCESS(
            f"written — [{cfg.pk}] {cfg.name} now wears {result['key']}: "
            f"{len(result['changes'])} field(s), {len(result['extras'])} "
            f"extra(s), {len(result.get('drops') or {})} dropped"))

    # ── mix ─────────────────────────────────────────────────────────────

    def _mix(self, *, venue, regime):
        """THE MATRIX as text — the same eighteen cells the page prints.

        One `current_mix` call builds every cell, so the page, the plan
        and this command can never disagree about what the tape is or
        what it is worth. A measured cell is marked with a `*`: the
        operator must be able to tell evidence from a guess in a terminal
        that has no bold.
        """
        from bot_program.persona_mix import (MAX_BAND_SHIFT_PCT, REGIMES,
                                             current_mix, mix_factor,
                                             shift_band)
        from bot_program.personas import PERSONA_KEYS, PERSONAS

        mix = current_mix(None, venue=venue)
        cells = mix.get("cells") or {}
        age = mix.get("age_minutes")
        self.stdout.write(
            "THE MIX MOVES WITH THE MARKET — which personality this tape "
            "rewards.")
        self.stdout.write(
            f"  recorded regime: {mix['regime']} "
            f"(confidence {float(mix.get('confidence') or 0.0):.2f}, "
            + (f"{float(age):.0f} minutes old" if age is not None
               else "no reading") + ")")
        self.stdout.write(f"  source:          {mix.get('source') or '—'}")
        self.stdout.write(f"  venue:           {venue} — live and paper are "
                          f"never pooled")
        self.stdout.write("")
        # 16, not 13: "mean_reverting" is fourteen characters and a
        # narrower column ran its header into the next one.
        width = 16
        self.stdout.write(f"  {'persona':<10}"
                          + "".join(f"{r:<{width}}" for r in REGIMES))
        self.stdout.write("  " + "-" * (10 + width * len(REGIMES)))
        lanes = []
        for key in PERSONA_KEYS:
            line = f"  {key:<10}"
            for reg in REGIMES:
                f = mix_factor(key, reg, venue=venue,
                               record=(cells.get(key) or {}).get(reg))
                lanes.append(f["lane"])
                mark = "*" if f["lane"] == "measured" else " "
                cell = f"{f['factor']:.2f}{mark}"
                if f["lane"] == "measured":
                    cell += f"n{f['n']}"
                elif f["lane"] == "prior":
                    cell += "prior"
                line += f"{cell:<{width}}"
            self.stdout.write(line)
        self.stdout.write("  " + "-" * (10 + width * len(REGIMES)))
        measured = lanes.count("measured")
        self.stdout.write(
            f"  {len(lanes) - measured} of the {len(lanes)} cells are still "
            f"guesses — {measured} measured (*), {lanes.count('prior')} on an "
            f"UNPROVEN prior, {lanes.count('neutral')} neutral.")
        self.stdout.write(
            f"  The factor moves the persona's SHARE BAND: the centre "
            f"shifts, the width never does, and the move is capped at "
            f"{MAX_BAND_SHIFT_PCT:g} points of the account. Risk per trade "
            f"and the notional cap are NOT touched.")
        self.stdout.write("")

        # The column the operator asked about — or the one the tape is in
        # — in full sentences. A factor with no reason beside it is a
        # number nobody can argue with, and a number nobody can argue with
        # is a prior nobody can retire.
        want = (regime or mix["regime"]).strip().lower()
        if want not in REGIMES:
            raise CommandError(
                f"no regime named {regime!r} — the platform records "
                f"{', '.join(REGIMES)}.")
        self.stdout.write(f"  {want.upper()}"
                          + (" (recorded now)" if want == mix["regime"]
                             else " (a what-if — not the current tape)"))
        for key in PERSONA_KEYS:
            persona = PERSONAS[key]
            f = mix_factor(key, want, venue=venue,
                           record=(cells.get(key) or {}).get(want))
            lo, hi = shift_band(persona.share_floor_pct,
                                persona.share_ceiling_pct, f["factor"])
            self.stdout.write(
                f"    {key:<9} ×{f['factor']:.2f}  band "
                # '->' and not '→': a Windows console runs cp1252 and
                # U+2192 raises UnicodeEncodeError there, which would
                # turn a read-only command into a traceback on the one
                # machine the operator reads it from (2026-09-12).
                f"{persona.share_floor_pct:g}-{persona.share_ceiling_pct:g}% "
                f"-> {lo:.1f}-{hi:.1f}%  — {f['reason']}")

    # ── grade ───────────────────────────────────────────────────────────

    def _grade(self):
        from bot_program.evidence import MIN_EVIDENCE_N, persona_rows
        rows = persona_rows()
        self.stdout.write("PERSONA GRADE — each over ITS OWN window. Paper "
                          "and live are never pooled; '—' is unmeasured, "
                          f"and the floor is {MIN_EVIDENCE_N} graded fills.")
        self.stdout.write(f"  {'persona':<10}{'window':<9}{'configs':<9}"
                          f"{'live n':<8}{'live R':<9}{'live wr':<9}"
                          f"{'paper n':<9}{'paper R':<9}{'paper wr':<9}")
        for r in rows:
            self.stdout.write(
                f"  {r['key']:<10}{str(r['evidence_days']) + 'd':<9}"
                f"{r['n_configs']:<9}"
                f"{r['live']['n']:<8}{_r(r['live']):<9}{_wr(r['live']):<9}"
                f"{r['paper']['n']:<9}{_r(r['paper']):<9}"
                f"{_wr(r['paper']):<9}")
        self.stdout.write("")
        for r in rows:
            self.stdout.write(f"  {r['sentence']}")
