"""THE PROVING GROUND (2026-10-02): backtests that can say no.

The operator: "a generation and backtests much more ferocious, solid — not
empty of data, above all in the backtest". The survey of that night found
six backtest paths and not one that could be believed:

  - the nightly retention deleted every 1h/4h bar older than 90 days, so
    the only walk-forward evaluator (300 4h bars older than 180 days) had
    an empty universe and scored every candidate on zero trades;
  - no engine replayed what the live bot does with real costs: fills at
    the signal bar's own close, fixed-percent levels, no break-even, no
    trailing, no time stop, costs zero by default;
  - no holdout, no confidence bound, no correction for the number of
    variants tried, no regime split;
  - and the rules went to real money without any backtest being asked.

This package is one engine and one judge, built to refuse:

  data.py      every stored bar, oldest first, and a refusal when the
               history is too short to say anything (MIN_SPAN_DAYS,
               MIN_BARS) — never a verdict on a quarter of data; THE BAR
               SANITY (2026-10-06): bad bars and spikes past the class's
               jump bar dropped and counted, a series whose level shifts
               and holds (an unadjusted split) left out of the run, said
  families.py  the live rules re-expressed bar by bar with no look-ahead
               (a signal on bar t uses bars <= t), mirrored long AND short,
               plus the base techniques a generator may search: Donchian
               breakout, RSI reversion, EMA pullback, ICT fair-value-gap
               retest, ICT liquidity-sweep reversal; each optionally
               filtered by the SMA200 trend or the ICT premium/discount
  simulate.py  what the bot does: entry at the NEXT bar's open, ATR stop
               and target (1.5 / 3.0, the stop band per class), the round
               trip charged (DEFAULT_COST_BPS), a gap through the stop
               filled at the open, stop first when a bar touches both,
               position care's break-even and trail, the no-progress time
               stop, one position at a time; a stop under half the class's
               floor on the signal bar's close (a broken entry) is skipped
               and counted
  judge.py     the verdict: a 70/30 time split with the last 30% never
               used to choose, five time folds, a bootstrap confidence
               bound corrected (Sidak) for the number of candidates tried,
               the expectancy at DOUBLE costs, and the regimes it was
               earned in. PROVEN only when all of them agree. A trade past
               PROVING_MAX_TRADE_R (20R) is excluded and counted; past 2% of
               a run excluded, the verdict is INSUFFICIENT, said.
  run.py       the universe, the pooling per asset class, the generator,
               and the saved verdicts (backtester.models_proving)

`manage.py prove` is its door; `run_proving_ground` its nightly beat.
"""
