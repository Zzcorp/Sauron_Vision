"""The proving ground (backtester/proving): backtests that can say no.

    python manage.py prove data                    # how much history there is to judge on
    python manage.py prove data --class forex
    python manage.py prove rules                   # every live rule and its short mirror
    python manage.py prove rules --class crypto --save
    python manage.py prove generate --class forex  # the generator's shortlist for a class
    python manage.py prove generate --families tsmom,rsi2_pullback --save
    python manage.py prove exits --class crypto    # every exit policy on the live rules' signals
    python manage.py prove exits --families tsmom --policies care,chandelier3,scale_half_1r
    python manage.py prove memory rsi_bull_divergence --class forex --symbols EURUSD
    python manage.py prove show                    # the saved verdicts, newest run first
    python manage.py prove show --run gen-ab12cd34ef

`--save` writes ProvingVerdict rows; without it nothing is written. No
broker is touched either way.
"""
from django.core.management.base import BaseCommand, CommandError


def _r(x):
    return "—" if x is None else f"{x:+.3f}R"


def _pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


class Command(BaseCommand):
    help = "Judge the live rules and generated candidates on real history."

    def add_arguments(self, parser):
        parser.add_argument("action",
                            choices=["data", "rules", "generate", "exits",
                                     "memory", "show"])
        parser.add_argument("rule", nargs="?", default="",
                            help="memory: the live rule name.")
        parser.add_argument("--class", dest="asset_class", default=None)
        parser.add_argument("--symbols", default="",
                            help="Comma-separated, platform spelling.")
        parser.add_argument("--timeframe", default="4h",
                            choices=["1h", "4h", "1d"])
        parser.add_argument("--families", default="",
                            help="generate: comma-separated family keys.")
        parser.add_argument("--policies", default="",
                            help="exits: comma-separated exit policies.")
        parser.add_argument("--save", action="store_true")
        parser.add_argument("--run", default="", help="show: one run id.")

    def handle(self, *args, **opts):
        from backtester.proving import run as pr
        symbols = [s.strip() for s in opts["symbols"].split(",") if s.strip()]
        kw = {"asset_class": opts["asset_class"],
              "timeframe": opts["timeframe"], "symbols": symbols or None}
        if opts["action"] == "data":
            return self._data(pr.data_report(**kw))
        if opts["action"] == "memory":
            from backtester.proving.memory import memory_for
            if not opts["rule"] or not opts["asset_class"]:
                raise CommandError("prove memory RULE --class CLASS "
                                   "[--symbols SYMBOL]")
            sym = (symbols or [""])[0]
            mem = memory_for(opts["rule"], sym, opts["asset_class"],
                             timeframe=opts["timeframe"])
            self.stdout.write(mem["words"] or mem.get("reason", ""))
            return
        if opts["action"] == "rules":
            rows = pr.prove_live_rules(save=opts["save"], **kw)
            return self._rows(rows, "LIVE RULES AND THEIR MIRRORS",
                              opts["save"])
        from backtester.proving.families import FAMILIES
        fams = [f.strip() for f in opts["families"].split(",") if f.strip()]
        unknown = [f for f in fams if f not in FAMILIES]
        if unknown:
            raise CommandError(f"unknown families {unknown}; known: "
                               f"{', '.join(FAMILIES)}")
        if opts["action"] == "generate":
            rows = pr.generate(families=fams or None, save=opts["save"],
                               **kw)
            return self._rows(rows, "GENERATED CANDIDATES", opts["save"])
        if opts["action"] == "exits":
            from backtester.proving.simulate import EXIT_POLICIES
            pols = [x.strip() for x in opts["policies"].split(",")
                    if x.strip()]
            bad = [x for x in pols if x not in EXIT_POLICIES]
            if bad:
                raise CommandError(f"unknown exit policies {bad}; known: "
                                   f"{', '.join(EXIT_POLICIES)}")
            rows = pr.compare_exits(families=fams or None,
                                    policies=pols or None,
                                    save=opts["save"], **kw)
            return self._rows(rows, "EXIT POLICIES ON THE SAME SIGNALS",
                              opts["save"])
        return self._show(opts["run"])

    def _data(self, report):
        w = self.stdout.write
        from backtester.proving.data import MIN_BARS, MIN_SPAN_DAYS
        w("PROVING GROUND · history on hand")
        if not report:
            w("  no instrument has bars at this timeframe — run "
              "backfill_bars first")
            return
        for cls, part in report.items():
            broken = part.get("broken") or []
            dropped = part.get("dropped") or {}
            w(f"── {cls} ─ {len(part['ok'])} judged, {len(part['short'])} "
              f"short" + (f", {len(broken)} broken" if broken else ""))
            for sym, bars, days in part["ok"]:
                w(f"  {sym:12} {bars:6} bars  {days:7.0f} days"
                  + (f"  · {dropped[sym]} bar(s) dropped"
                     if dropped.get(sym) else ""))
            for sym, why in part["short"]:
                w(f"  {sym:12} SHORT: {why}"
                  + (f" ({dropped[sym]} bar(s) dropped)"
                     if dropped.get(sym) else ""))
            for sym, why in broken:
                w(f"  {sym:12} BROKEN: {why}")
        w(f"Needed per symbol: {MIN_SPAN_DAYS} days, {MIN_BARS} bars.")

    def _rows(self, rows, title, saved):
        w = self.stdout.write
        w(f"PROVING GROUND · {title}" + ("  (saved)" if saved else ""))
        if not rows:
            w("  nothing to judge: no instrument with bars at this "
              "timeframe")
            return
        for r in rows:
            self._row(r)

    def _row(self, r):
        w = self.stdout.write
        name = r["live_rule"] or f"{r['family']} {r['params']}"
        w(f"  {r['verdict'].upper():12} {r['asset_class']:9} {name} · "
          f"{r['direction']} · filter {r['filter']} · exit "
          f"{r.get('policy') or 'care'}")
        payoff = "—" if r["payoff"] is None else f"{r['payoff']:.2f}"
        w(f"               {r['trades_n']} trades over {r['symbols_n']} "
          f"symbol(s), {r['holdout_n']} in the holdout · win "
          f"{_pct(r['win_rate'])} · payoff {payoff}")
        w(f"               expectancy {_r(r['expectancy'])} · holdout "
          f"{_r(r['holdout_expectancy'])} · lower bound "
          f"{_r(r['lower_bound'])} · at double costs "
          f"{_r(r['stressed_expectancy'])} · folds "
          f"{r['positive_folds']}/5 · worst run {_r(r['max_dd_r'])}")
        regimes = (r.get("detail") or {}).get("regimes") or {}
        if regimes:
            w("               regimes: " + " · ".join(
                f"{k} {_r(v['expectancy'])} ({v['n']})"
                for k, v in regimes.items()))
        # what was not read (2026-10-06): bars dropped, trades skipped or
        # excluded, symbols left out — said on the verdict, never silent
        from backtester.proving.run import data_words
        said = data_words((r.get("detail") or {}).get("data"))
        if said:
            w(f"               data: {said}")
        w(f"               → {r['why']}")

    def _show(self, run_id):
        from backtester.models_proving import ProvingVerdict
        qs = ProvingVerdict.objects.all()
        if run_id:
            qs = qs.filter(run_id=run_id)
        else:
            latest = qs.values_list("run_id", flat=True).first()
            if latest is None:
                self.stdout.write("no saved verdict yet — prove rules "
                                  "--save or prove generate --save")
                return
            qs = qs.filter(run_id=latest)
        rows = list(qs.order_by("asset_class", "-lower_bound"))
        self.stdout.write(f"PROVING GROUND · run {rows[0].run_id} · "
                          f"{rows[0].created_at:%Y-%m-%d %H:%M} UTC · "
                          f"{len(rows)} verdict(s)")
        for v in rows:
            self._row({
                "live_rule": v.live_rule, "family": v.family,
                "params": v.params, "verdict": v.verdict,
                "asset_class": v.asset_class, "direction": v.direction,
                "filter": v.filter, "policy": v.policy,
                "trades_n": v.trades_n,
                "symbols_n": v.symbols_n, "holdout_n": v.holdout_n,
                "win_rate": v.win_rate, "payoff": v.payoff,
                "expectancy": v.expectancy,
                "holdout_expectancy": v.holdout_expectancy,
                "lower_bound": v.lower_bound,
                "stressed_expectancy": v.stressed_expectancy,
                "positive_folds": v.positive_folds, "max_dd_r": v.max_dd_r,
                "detail": v.detail, "why": v.why,
            })
