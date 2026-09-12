"""The three trader personalities — coherent presets, not new engines.

The operator's ask, in their words: "We should have a system of 3 trader
personalities: one short-term, short exposure in time and large in volume
and leverage; one swing trader, which is what Sauron is today; and the
long-termist, 'horizons'."

THE HONEST TRANSLATION. A personality is NOT a new engine. Every knob a
personality needs already decides how a bot behaves — the timeframe it
reads, the ATR multiples its stop and target are cut from, how long a
thesis may live, how many bets run at once, how much of the book one
stop-out costs. What was missing is that those knobs were set ONE AT A
TIME, with no coherence between them: a config could read 1h bars, place
a 2.5 ATR stop, hold for thirty days and still be graded over the same
90-day window as everything else, and allocated out of the same
2%–60% band as everything else. Nothing in the platform ever said which
of those combinations was a trading style and which was a typo.

So a persona is four things and nothing more:

  1. a COHERENT PRESET of knobs that already exist and are already read
     (see `PERSONAS` — every extras key below is grepped by the tests
     against the module that reads it, because a preset key nothing reads
     is a lie);
  2. a GRADING WINDOW matched to its holding period (bot_program.evidence
     .config_evidence, persona_rows) — 21 days of scalps is a sample, 21
     days of position trades is one trade;
  3. a SHARE BAND in the account allocator (share_allocator.bounds_for);
  4. a WEIGHT on the horizon prior (share_allocator.horizon_for) — the
     5-10 year view should move a position book and must not move a
     book that is flat by lunchtime.

THE LEVERAGE CORRECTION, which the operator must read here, on /personas/
and in the RUNBOOK: NO PERSONALITY BORROWS TO FUND A POSITION. The claim
is scoped on purpose. An earlier draft of this paragraph said "this
platform never borrows — there is no margin knob anywhere in this code",
and the wall review falsified every clause: `BotConfig` carries BOTH
`leverage` and `margin_mode`, `engine/risk.py` multiplies the position
dollars by the first, and `engine/runner.py` POSTs both at the Binance
futures venue through `ensure_config`. That engine is dormant, not
absent, and it is hand-triggerable from `views.run_tick_now`. Scoped to
personalities the claim is STRONGER than the sweeping one it replaces:
`AssetBotConfig` — the only config a persona can be worn by — does not
carry either field at all, so no persona can set what it does not have.

The honest short-term lever is (a) the NOTIONAL FRACTION the risk sizer
is allowed to reach — how much position one fixed risk budget buys when
the stop is tight — and (b) the NUMBER OF CONCURRENT POSITIONS. On
stock, ETF, index, commodity, crypto and options both are cash and
neither is a loan. FOREX IS THE EXCEPTION, AND IT IS REAL: this module's
own forex path (see THE FOREX EXEMPTION in `plan_persona`) keeps
`sizing.MAX_NOTIONAL_FRACTION` at 4.0 there — 400% of the pool in
notional, carried by the broker's CFD margin, which the sizing module
states outright: "the leverage is at the broker". "Large in volume and
leverage" is delivered as eight concurrent bets at a 35% notional cap on
a 0.15% risk budget everywhere else, and by the venue on FX.

A persona changes NO capital and NO account share by itself. It never
enables or disables a config. Applying one to a LIVE config re-sizes real
risk, so `apply_persona` refuses a live config unless `force=True` — the
page's PIN and the command's --yes are what supply that force.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import MappingProxyType

logger = logging.getLogger(__name__)

# The extras key `apply_persona` stamps, and the ISO timestamp beside it.
PERSONA_EXTRAS_KEY = "persona"
PERSONA_AT_EXTRAS_KEY = "persona_at"

# THE LEGACY TIME-STOP INLET. `AssetBotConfig.time_stop_setting()` reads
# extras["max_hold_hours"] BEFORE the column of the same name — deliberately,
# so an install that set it years ago keeps the ceiling it chose. Both of the
# platform's own writers (the migration that introduced the field and the
# settings form) LIFT it into the column and delete it, so it drains rather
# than accumulating. A persona writes the COLUMN; on a config that still
# carries the legacy key the preset's hold ceiling would be outranked and the
# one knob that would silently do nothing is the one that decides when a
# position is closed. apply_persona therefore drains it exactly as the other
# two writers do, and plan_for says so before the write (2026-09-12).
LEGACY_HOLD_EXTRAS_KEY = "max_hold_hours"

# AuditLogEntry.kind is a CharField(max_length=20) and Postgres ENFORCES it
# (SQLite does not, so a longer kind would pass every test here and raise on
# the deployment). 'persona_apply' is 13.
AUDIT_KIND = "persona_apply"

# Options are the one class no persona may wear. OptionsBot overrides
# scan_symbol wholesale (it is not even desked), prices its stops off
# premium rather than ATR, and has its own expiry gate that already
# truncates a thesis — a preset written in ATR multiples and hold-hours
# would describe a trade that class does not take.
PERSONA_ASSET_CLASSES = ("stock", "forex", "commodity", "crypto", "cfd")

# 1d bars are written by ONE task — market_data.tasks.fetch_eod_all_instruments
# — and it walks `public_feed.SUPPORTED_ASSET_CLASSES` only. Everything else
# in the platform writes 4h and 1h (market_data.bot_bars.DEFAULT_INTERVALS).
# So a daily timeframe on a crypto config has no history at all, and
# `plan_for` says so by name rather than letting decide() fall through to
# "no active signals" for ever.
EOD_ASSET_CLASSES = ("stock", "etf", "index", "commodity", "forex")


def _frozen(d: dict):
    return MappingProxyType(dict(d))


@dataclass(frozen=True)
class Persona:
    """One preset. Frozen: a persona is a constant, not a setting.

    `fields` are AssetBotConfig columns; `extras` are keys in the config's
    extras JSON, each read by a named module (see `why`). `asset_classes`
    is what may wear it at all; the BAR CAVEAT (whether the timeframe has
    any history for these symbols) is a warning from `plan_for`, not a
    refusal, because bars can be backfilled and a refusal would hide the
    one command that fixes it.
    """

    key: str
    label: str
    purpose: str
    holding: str
    fields: MappingProxyType
    extras: MappingProxyType
    evidence_days: int
    horizon_weight: float
    share_floor_pct: float
    share_ceiling_pct: float
    asset_classes: tuple = PERSONA_ASSET_CLASSES
    why: MappingProxyType = field(default_factory=lambda: _frozen({}))

    def knob(self, name):
        """The value this persona sets for `name`, field or extra, or None."""
        if name in self.fields:
            return self.fields[name]
        return self.extras.get(name)


# ── The three presets ────────────────────────────────────────────────────
#
# Every number below is a knob that already existed. What is new is that
# they are set TOGETHER, so the stop, the target, the signal age, the
# hold ceiling and the grading window describe one trade instead of five
# unrelated opinions.

SCALP = Persona(
    key="scalp",
    label="Scalp",
    purpose="Short-term: many small bets, hours not days",
    holding="hours — a thesis that has not moved in 8 hours is closed",
    fields=_frozen({
        "timeframe": "1h",
        "entry_score_min": 0.65,
        "min_signals_for_entry": 2,
        "cool_down_minutes": 15,
        "max_concurrent_positions": 8,
        "max_daily_loss_pct": 2.0,
        # The VISIBLE time-stop field, not extras['max_hold_hours'].
        # AssetBotConfig.time_stop_setting reads the legacy extras key
        # FIRST and both of the platform's own writers drain it into this
        # field — writing it back into extras would un-drain it and take
        # precedence over anything the operator later types into the form.
        "max_hold_hours": 8.0,
    }),
    extras=_frozen({
        # sizing.risk_fraction — percent, so 0.15 is 0.15% of equity at
        # risk per trade. SMALLER than the 0.25% default on purpose: eight
        # concurrent bets at 0.15% is 1.2% of the book at stake, which is
        # the same total the swing persona reaches with five at 0.25%.
        "risk_per_trade_pct": 0.15,
        # risk_levels.stop_and_target — a 1.0 ATR stop against a 2.0 ATR
        # target keeps the 2:1 planned geometry at a distance an hourly
        # bar can actually reach inside a session.
        "atr_stop_mult": 1.0,
        "atr_target_mult": 2.0,
        # risk_levels.atr_for — THE FRAME THE ATR ITSELF IS MEASURED ON,
        # and it is a SEPARATE key from the config's `timeframe` column:
        # `stop_and_target` reads extras.get("atr_timeframe", "4h") and
        # nothing else. Without this key every multiple above would be
        # cut from FOUR-HOUR volatility however fast the persona trades,
        # so a "1.0 ATR" scalp stop would be two to four times the hourly
        # range the 8-hour ceiling is written around — and the tight stop
        # that is the whole justification for the raised notional cap
        # would not exist. The preset would have described a trade this
        # platform never takes (2026-09-12).
        "atr_timeframe": "1h",
        # base.decide — a signal older than four hours is not a scalp
        # signal, it is yesterday's tape.
        "max_signal_age_hours": 4,
        # sizing.max_notional_fraction — THE HONEST LEVER, and it is cash,
        # not credit. A tight stop buys more position for the same risk
        # budget; raising the cap from 20% to 35% is what lets that
        # happen instead of the stop being widened to fit. NOT APPLIED TO
        # FOREX: that class already sits at 4.0 and 0.35 would be a
        # ninety-percent cut nobody asked for (see plan_for).
        "max_notional_fraction": 0.35,
        # safety.CircuitBreakers — three losses in a row on a book that
        # takes eight bets at once is a bad morning worth stopping.
        "max_loss_streak": 3,
        "max_drawdown_pct": 8,
    }),
    evidence_days=21,
    # The 5-10 year view has nothing to say about a position that will be
    # flat before dinner. Zero, and horizon_for prints exactly that.
    horizon_weight=0.0,
    share_floor_pct=5.0,
    share_ceiling_pct=25.0,
    why=_frozen({
        "timeframe": "1h bars: the frame a thesis measured in hours is read on.",
        "entry_score_min": "0.65 — a higher bar than swing, because a short hold has no time to be right late.",
        "min_signals_for_entry": "two confirmations: at 1h the single-signal false positive rate is what kills a fast book.",
        "cool_down_minutes": "15 minutes between entries on a symbol — enough to not re-enter the same bar, little enough to keep the volume.",
        "max_concurrent_positions": "eight at once. This, and the notional cap, are the whole of 'large in volume' — no personality borrows to fund one of them.",
        "max_daily_loss_pct": "2% of the pool in a day, which at 0.15% a trade is about thirteen stop-outs.",
        "max_hold_hours": "8 hours: past a session, a scalp thesis has been answered, and the answer is no.",
        "risk_per_trade_pct": "0.15% per trade — smaller than the default, because eight of them run at once.",
        "atr_stop_mult": "1.0 ATR stop: tight enough for an hourly frame to resolve it.",
        "atr_target_mult": "2.0 ATR target — the same 2:1 planned geometry as every other persona.",
        "atr_timeframe": "the ATR itself is measured on 1h bars. Without this key stop_and_target cuts every multiple from 4h volatility, and the stop above is not tight at all.",
        "max_signal_age_hours": "4 hours. Older than that is not a scalp signal.",
        "max_notional_fraction": "35% of the pool in one position (20% is the default). THE HONEST LEVER: a tight stop buys more position for the same cash risk. Never applied to forex, which already allows 4.0.",
        "max_loss_streak": "3 consecutive losses halts new entries.",
        "max_drawdown_pct": "8% from the peak of its own realised curve halts new entries.",
    }),
)

SWING = Persona(
    key="swing",
    label="Swing",
    purpose="What Sauron is today: the 4-hour trend, days not weeks",
    holding="days — the 72-hour ceiling is three sessions of patience",
    fields=_frozen({
        "timeframe": "4h",
        "entry_score_min": 0.60,
        "min_signals_for_entry": 1,
        "cool_down_minutes": 60,
        "max_concurrent_positions": 5,
        "max_daily_loss_pct": 2.0,
        "max_hold_hours": 72.0,
    }),
    extras=_frozen({
        "risk_per_trade_pct": 0.25,
        "atr_stop_mult": 1.5,
        "atr_target_mult": 3.0,
        # The frame stop_and_target already defaults to, WRITTEN DOWN
        # rather than inherited: the other two personas move it, and a
        # config that swings back from scalp must get 4h ATR again and
        # not keep the 1h ATR the previous style measured with.
        "atr_timeframe": "4h",
        "max_signal_age_hours": 24,
        "max_loss_streak": 4,
        "max_drawdown_pct": 10,
    }),
    evidence_days=90,
    horizon_weight=0.5,
    share_floor_pct=20.0,
    share_ceiling_pct=60.0,
    why=_frozen({
        "timeframe": "4h — the frame every technical rule and the SMC composite already read.",
        "entry_score_min": "0.60, the platform's shipped threshold.",
        "min_signals_for_entry": "one confirmation, as today.",
        "cool_down_minutes": "60 minutes, as today.",
        "max_concurrent_positions": "five, as today.",
        "max_daily_loss_pct": "2% of the pool in a day = exactly 8R at 0.25% a trade.",
        "max_hold_hours": "72 hours: three sessions is the longest a 4h trend thesis stays a thesis.",
        "risk_per_trade_pct": "0.25% — the default the whole sizing module was calibrated around.",
        "atr_stop_mult": "1.5 ATR stop / 3.0 ATR target: the platform's own 2:1 geometry.",
        "atr_target_mult": "3.0 ATR target.",
        "atr_timeframe": "4h ATR — the shipped default, written down so a config coming back from another persona is measured on this frame again.",
        "max_signal_age_hours": "24 hours, the shipped bound.",
        "max_loss_streak": "4 consecutive losses, the shipped breaker.",
        "max_drawdown_pct": "10% from the peak, the shipped breaker.",
    }),
)

POSITION = Persona(
    key="position",
    label="Position",
    purpose="The long view: weeks, few bets, the horizon's lane",
    holding="weeks — the 720-hour ceiling is thirty days",
    fields=_frozen({
        "timeframe": "1d",
        "entry_score_min": 0.65,
        "min_signals_for_entry": 2,
        # A day between entries on one symbol: a daily-bar thesis cannot
        # change twice in an afternoon, and a cooldown shorter than the
        # bar is no cooldown.
        "cool_down_minutes": 1440,
        "max_concurrent_positions": 3,
        "max_daily_loss_pct": 3.0,
        "max_hold_hours": 720.0,
    }),
    extras=_frozen({
        # Three bets at 0.40% is 1.2% of the book at stake — the same
        # total as the other two personas reach. The size per bet is
        # larger because there are fewer of them, not because the risk is.
        "risk_per_trade_pct": 0.40,
        "atr_stop_mult": 2.5,
        "atr_target_mult": 6.0,
        # A thirty-day thesis sized off four-hour noise is stopped out by
        # four-hour noise: 2.5 x ATR(4h) on a liquid equity is around 2%,
        # which an ordinary week clears twice. The multiple is only as
        # long as the frame it is measured on (2026-09-12).
        "atr_timeframe": "1d",
        "max_signal_age_hours": 72,
        "max_loss_streak": 5,
        "max_drawdown_pct": 15,
    }),
    evidence_days=365,
    # The only persona the 5-10 year view should actually move, and the
    # clamp in horizon_for still holds the factor inside 0.85..1.15.
    horizon_weight=1.5,
    share_floor_pct=15.0,
    share_ceiling_pct=50.0,
    why=_frozen({
        "timeframe": "1d bars — written only by the EOD task, and only for the classes Yahoo serves.",
        "entry_score_min": "0.65: three bets a quarter should each be a good one.",
        "min_signals_for_entry": "two confirmations.",
        "cool_down_minutes": "1440 minutes — one day, the length of the bar itself.",
        "max_concurrent_positions": "three. Few bets, each one deliberate.",
        "max_daily_loss_pct": "3% in a day: a 2.5 ATR stop on a daily bar is a wider single loss.",
        "max_hold_hours": "720 hours — thirty days is the horizon the longest seeded thesis declares.",
        "risk_per_trade_pct": "0.40% per trade, three at a time: the same 1.2% of the book at stake as the other two.",
        "atr_stop_mult": "2.5 ATR stop — a daily thesis has to survive a week of noise.",
        "atr_target_mult": "6.0 ATR target, still 2.4:1 planned.",
        "atr_timeframe": "the ATR is measured on 1d bars: 2.5 x a four-hour ATR is about 2% on an equity, which an ordinary week clears twice — the stop has to be as long as the hold.",
        "max_signal_age_hours": "72 hours: three daily bars.",
        "max_loss_streak": "5 consecutive losses.",
        "max_drawdown_pct": "15% from the peak — a wider curve needs a wider breaker or it halts on ordinary noise.",
    }),
)

#: The three, in the order a page and a table should print them: fastest
#: first. Ordinary dicts preserve insertion order, and `PERSONAS` is never
#: mutated — `plan_for` and `apply_persona` read it and copy.
PERSONAS = {p.key: p for p in (SCALP, SWING, POSITION)}
PERSONA_KEYS = tuple(PERSONAS)

#: Every knob any persona touches, fields first, in the order the page
#: prints them. Used by the page and the command so both compare the same
#: rows in the same order.
FIELD_KNOBS = ("timeframe", "entry_score_min", "min_signals_for_entry",
               "cool_down_minutes", "max_concurrent_positions",
               "max_daily_loss_pct", "max_hold_hours")
EXTRA_KNOBS = ("risk_per_trade_pct", "atr_stop_mult", "atr_target_mult",
               "atr_timeframe", "max_signal_age_hours",
               "max_notional_fraction", "max_loss_streak",
               "max_drawdown_pct")
ALL_KNOBS = FIELD_KNOBS + EXTRA_KNOBS


# ── Reading a config's persona ───────────────────────────────────────────

def _extras(cfg) -> dict:
    return getattr(cfg, "extras", None) or {}


def persona_of(cfg) -> str:
    """The persona key this config wears, or '' — never raises.

    Tolerates anything with (or without) an `extras` attribute: the share
    allocator calls this on a SimpleNamespace standing in for an asset
    class, and a page must not 500 because a stand-in has no extras.
    """
    key = _extras(cfg).get(PERSONA_EXTRAS_KEY)
    key = str(key or "").strip().lower()
    return key if key in PERSONAS else ""


def persona_for(cfg):
    """The `Persona` this config wears, or None."""
    return PERSONAS.get(persona_of(cfg))


def persona_evidence_days(cfg, default: int = 90) -> int:
    """The grading window this config's persona declares, else `default`."""
    p = persona_for(cfg)
    return int(p.evidence_days) if p is not None else int(default)


def persona_horizon_weight(cfg, default: float = 1.0) -> float:
    """How hard the 5-10 year prior may push this config. 1.0 with no
    persona, so a fleet that has never heard of personas is untouched."""
    p = persona_for(cfg)
    return float(p.horizon_weight) if p is not None else float(default)


def persona_band(cfg):
    """(floor_pct, ceiling_pct) from this config's persona, or None."""
    p = persona_for(cfg)
    if p is None:
        return None
    return float(p.share_floor_pct), float(p.share_ceiling_pct)


# ── The plan ─────────────────────────────────────────────────────────────

def _symbols(cfg) -> list:
    return [str(s) for s in (getattr(cfg, "symbols", None) or [])]


def _symbols_without_bars(symbols, timeframe) -> list:
    """Which of `symbols` have no stored bar at `timeframe`.

    A DB read, not an assumption about which classes get daily bars: the
    operator may have backfilled, and telling them to backfill something
    they already have is the kind of stale advice a runbook accumulates.
    Unreadable (no table, no database) answers [] — a plan must not claim
    a gap it could not measure.
    """
    if not symbols:
        return []
    try:
        from market_data.models import PriceData
        have = set(PriceData.objects
                   .filter(instrument__symbol__in=symbols,
                           timeframe=timeframe)
                   .values_list("instrument__symbol", flat=True)
                   .distinct())
    except Exception as e:  # noqa: BLE001 — unmeasurable is not "missing"
        logger.debug("[persona] bar check unavailable: %s", e)
        return []
    return [s for s in symbols if s not in have]


def _open_trades(cfg) -> list:
    """This config's OPEN / CLOSE_PENDING rows — the positions a changed
    exit rule would move UNDER. Empty on any read failure."""
    pk = getattr(cfg, "pk", None)
    if pk is None:
        return []
    try:
        from bot_program.models import AssetBotTrade
        return list(AssetBotTrade.objects
                    .filter(config=cfg,
                            status__in=("OPEN", "CLOSE_PENDING"))
                    .order_by("opened_at"))
    except Exception as e:  # noqa: BLE001
        logger.debug("[persona] open-trade check unavailable: %s", e)
        return []


def _current_field(cfg, name):
    return getattr(cfg, name, None)


def _drops_for(cfg, persona, ex) -> tuple:
    """({extras_key: old_value}, previous_persona_key) — keys the write must
    REMOVE rather than merge.

    Two of them, and both are keys that would otherwise OUTRANK the persona
    in silence, which is the one failure mode a preset cannot survive:

      max_hold_hours  the legacy time-stop inlet (see LEGACY_HOLD_EXTRAS_KEY).
                      time_stop_setting() reads it before the column this
                      preset writes, so a config still carrying it would keep
                      its old ceiling while the page printed the persona's.

      a knob the PREVIOUS persona set and this one does not. scalp writes
                      extras['max_notional_fraction']=0.35; swing does not set
                      that key at all, so scalp -> swing used to leave a
                      scalp's notional cap on a swing book — the preset that
                      is "coherent by construction" quietly incoherent, and
                      sizing.max_notional_fraction reads the leftover override
                      ahead of the class default for ever. Dropped ONLY when
                      the stored value is still EXACTLY what the previous
                      persona wrote: a number the operator typed themselves is
                      never removed by a change of style (2026-09-12).
    """
    drops: dict = {}
    if LEGACY_HOLD_EXTRAS_KEY in ex and LEGACY_HOLD_EXTRAS_KEY in persona.fields:
        drops[LEGACY_HOLD_EXTRAS_KEY] = ex.get(LEGACY_HOLD_EXTRAS_KEY)
    prev_key = persona_of(cfg)
    prev = PERSONAS.get(prev_key)
    if prev is not None and prev.key != persona.key:
        for name in EXTRA_KNOBS:
            if name in persona.extras or name not in prev.extras:
                continue
            if name in ex and not _differs(ex.get(name), prev.extras[name]):
                drops[name] = ex.get(name)
    return drops, prev_key


def plan_for(cfg, key: str) -> dict:
    """What applying persona `key` to `cfg` would change. PURE — no write.

    Returns {"ok", "reason", "key", "changes", "extras", "drops",
    "warnings"}:

      changes   {field_name: (old, new)}   AssetBotConfig columns
      extras    {extras_key: (old, new)}   keys in the extras JSON
      drops     {extras_key: old}          keys REMOVED from the extras
                                           JSON — a merge cannot express
                                           "this key must stop existing"
      warnings  [str]                      everything the operator should
                                           read BEFORE the write

    `ok` False means the persona cannot be applied at all (unknown key,
    an asset class no persona covers). Everything else is a warning: a
    missing bar history is fixable with one backfill command, and
    refusing there would hide that command behind an error.
    """
    persona = PERSONAS.get(str(key or "").strip().lower())
    if persona is None:
        return {"ok": False, "key": str(key or ""),
                "reason": (f"no persona named {key!r} — the three are "
                           f"{', '.join(PERSONA_KEYS)}"),
                "changes": {}, "extras": {}, "drops": {}, "warnings": []}

    ac = str(getattr(cfg, "asset_class", "") or "")
    if ac not in persona.asset_classes:
        return {"ok": False, "key": persona.key,
                "reason": (f"{persona.key} does not cover the {ac or '?'} "
                           f"class — it covers "
                           f"{', '.join(persona.asset_classes)}. Options "
                           f"price their stops off premium and carry their "
                           f"own expiry gate, so an ATR preset would "
                           f"describe a trade that class never takes."),
                "changes": {}, "extras": {}, "drops": {}, "warnings": []}

    warnings: list = []
    changes: dict = {}
    for name, new in persona.fields.items():
        old = _current_field(cfg, name)
        if _differs(old, new):
            changes[name] = (old, new)

    ex = dict(_extras(cfg))
    extras: dict = {}
    for name, new in persona.extras.items():
        # THE FOREX EXEMPTION. sizing.MAX_NOTIONAL_FRACTION already grants
        # forex 4.0 because 20% notional on a major is an economically
        # meaningless constraint — the stop floor it implies never binds.
        # Writing the scalp persona's 0.35 over it would cut a forex
        # config to a ninetieth of the size the platform's own sizing
        # module says it should take. No persona lowers it, ever.
        if name == "max_notional_fraction" and ac == "forex":
            warnings.append(
                f"forex: the notional fraction stays at the class default "
                f"(4.0) — {persona.key} would have written "
                f"{new:g}, which on an FX major is a size cut, not a risk "
                f"control. sizing.MAX_NOTIONAL_FRACTION keeps it.")
            continue
        old = ex.get(name)
        if _differs(old, new):
            extras[name] = (old, new)

    drops, prev_key = _drops_for(cfg, persona, ex)
    if LEGACY_HOLD_EXTRAS_KEY in drops:
        warnings.append(
            f"extras['{LEGACY_HOLD_EXTRAS_KEY}'] = "
            f"{drops[LEGACY_HOLD_EXTRAS_KEY]!r} is the LEGACY time-stop "
            f"inlet and AssetBotConfig.time_stop_setting() reads it BEFORE "
            f"the column — left in place it would outrank this persona's "
            f"{float(persona.fields['max_hold_hours']):g}h ceiling and "
            f"the preset's hold would silently do nothing. It is DRAINED on "
            f"apply, exactly as the migration and the settings form drain it.")
    stale = sorted(k for k in drops if k != LEGACY_HOLD_EXTRAS_KEY)
    if stale:
        warnings.append(
            f"{persona.key} does not set "
            f"{', '.join(stale)}, and the {prev_key} persona this config "
            f"wears wrote "
            + ", ".join(f"{k}={drops[k]!r}" for k in stale)
            + f". Removed on apply, so the config falls back to the "
              f"platform's own default rather than keeping a knob from a "
              f"style it no longer trades.")

    # (a) the timeframe has no bars for these symbols.
    tf = persona.fields["timeframe"]
    symbols = _symbols(cfg)
    missing = _symbols_without_bars(symbols, tf)
    if missing:
        shown = ", ".join(missing[:12]) + ("…" if len(missing) > 12 else "")
        extra = ""
        if tf == "1d" and ac not in EOD_ASSET_CLASSES:
            extra = (f" Nothing writes daily bars for the {ac} class — the "
                     f"EOD task covers {', '.join(EOD_ASSET_CLASSES)} only, "
                     f"and bot_bars writes 4h and 1h.")
        warnings.append(
            f"no {tf} bars stored for {len(missing)} of {len(symbols)} "
            f"symbol(s): {shown}.{extra} decide() will read no signals on "
            f"this frame until they exist — backfill first: "
            f"python manage.py backfill_bars --symbols "
            f"{','.join(missing[:6])} --intervals {tf} --bars 300")

    # (b) open positions whose EXIT moves under them — and, separately, the
    # knobs that do NOT move an open position. One sentence for both was
    # half false whichever way it fired: "their exit changes under them"
    # is true of the time stop, which manage_positions re-reads every tick
    # from time_stop_setting(), and false of the ATR multiples, which
    # stop_and_target applies ONCE at entry and never revisits. A warning
    # that is false in one of its two scenarios teaches the operator to
    # skim the warnings (2026-09-12).
    # (the column and the legacy extras key share a name; both move the
    # ceiling an open position is measured against)
    time_moves = ("max_hold_hours" in changes
                  or LEGACY_HOLD_EXTRAS_KEY in drops)
    atr_moves = [n for n in ("atr_stop_mult", "atr_target_mult",
                             "atr_timeframe") if n in extras]
    open_rows = _open_trades(cfg) if (time_moves or atr_moves) else []
    if open_rows:
        named = ", ".join(f"#{t.pk} {t.symbol} {t.side}"
                          for t in open_rows[:8])
        if len(open_rows) > 8:
            named += f" (+{len(open_rows) - 8} more)"
        if time_moves:
            warnings.append(
                f"{len(open_rows)} position(s) are OPEN and this persona "
                f"moves the time stop (max_hold_hours) to "
                f"{float(persona.fields['max_hold_hours']):g}h — their "
                f"exit changes under them: {named}. The ceiling is measured "
                f"from opened_at, not from now, so a shorter one can flatten "
                f"a position that is already older than it on the very next "
                f"tick.")
        if atr_moves:
            warnings.append(
                f"{len(open_rows)} position(s) are OPEN and this persona "
                f"moves {', '.join(atr_moves)} — the stops and targets "
                f"ALREADY PLACED do NOT move ({named}): stop_and_target runs "
                f"once, at entry. Only the next entry is cut from the new "
                f"multiples.")

    # (c) real money.
    if str(getattr(cfg, "mode", "") or "") == "live":
        warnings.append(
            "this config is LIVE — applying re-sizes REAL risk on the next "
            "entry (risk_per_trade_pct, the ATR stop distance and the "
            "notional cap all feed sizing.size_position). apply_persona "
            "refuses a live config without force.")

    # (d) forex, said even when no persona wanted to touch it, so the
    # operator reads the same sentence on every forex plan.
    if ac == "forex" and "max_notional_fraction" not in dict(extras):
        if not any("forex:" in w for w in warnings):
            warnings.append(
                "forex: the notional fraction stays at the class default "
                "(4.0). No persona lowers it — 20% notional on an FX major "
                "is an economically meaningless constraint.")

    return {"ok": True, "key": persona.key, "reason": "",
            "changes": changes, "extras": extras, "drops": drops,
            "warnings": warnings}


def _differs(old, new) -> bool:
    """True when `old` is not already `new`, tolerating 5 vs 5.0.

    A float compared to an int compared to a string out of hand-edited
    JSON: an over-eager 'changed' here writes a field for no reason and
    fills the audit log with no-ops.
    """
    if old is None:
        return True
    if isinstance(new, str) or isinstance(old, str):
        return str(old) != str(new)
    try:
        return abs(float(old) - float(new)) > 1e-9
    except (TypeError, ValueError):
        return old != new


# ── The write ────────────────────────────────────────────────────────────

def _drop_extras(cfg, keys) -> None:
    """Remove `keys` from the config's extras, re-reading the row first.

    The mirror of `safety._save_extras`, which can only MERGE. A key that
    must stop existing cannot be expressed as a merge, and writing a
    placeholder in its place is worse than leaving it: an override the
    class default can never reach again. Same select_for_update re-read and
    the same guarantee — only the keys this call names may move, everything
    else comes from the row as it stands now, so a tick that is holding the
    config in memory cannot be reverted by this write (2026-09-12).
    """
    keys = [k for k in (keys or ())]
    if not keys:
        return
    pk = getattr(cfg, "pk", None)
    if pk is None:  # unsaved config (tests, dry runs) — nothing to re-read
        cfg.extras = {k: v for k, v in _extras(cfg).items() if k not in keys}
        return
    merged = None
    try:
        from django.db import transaction
        with transaction.atomic():
            row = (cfg.__class__._default_manager
                   .select_for_update().filter(pk=pk).first())
            if row is None:
                cfg.extras = {k: v for k, v in _extras(cfg).items()
                              if k not in keys}
                return
            merged = {k: v for k, v in (getattr(row, "extras", None) or {}).items()
                      if k not in keys}
            row.extras = merged
            row.save(update_fields=["extras", "updated_at"])
        cfg.extras = merged
    except Exception as e:  # noqa: BLE001 — never break the caller
        logger.warning("[persona] could not drop %s from cfg %s extras: %s",
                       keys, pk, e)


def apply_persona(cfg, key: str, *, user=None, force: bool = False) -> dict:
    """Write the persona onto `cfg`. Returns what changed.

    {"ok", "reason", "key", "changes", "extras", "drops", "warnings"} —
    the same shape `plan_for` returns, so a caller prints one thing
    whether it wrote or not.

    Refusals: whatever `plan_for` refuses, and a LIVE config without
    `force`. `force` is what the page's PIN and the command's --yes
    supply — applying to a live config re-sizes real risk.

    What this NEVER touches, by construction: `cfg.capital`,
    `extras['account_share_pct']`, and `cfg.enabled`. A persona is a
    trading style. How much money a pool holds is the share allocator's
    question and the operator's; whether a bot runs is the toggle's.
    """
    plan = plan_for(cfg, key)
    if not plan["ok"]:
        logger.info("[persona] cfg %s: refused — %s",
                    getattr(cfg, "pk", "?"), plan["reason"])
        return plan

    if str(getattr(cfg, "mode", "") or "") == "live" and not force:
        plan = dict(plan)
        plan["ok"] = False
        plan["reason"] = (
            f"{getattr(cfg, 'name', '?')} is LIVE — applying a persona "
            f"re-sizes real risk. The page asks the trading PIN here and "
            f"the command asks for --yes.")
        logger.warning("[persona] cfg %s: %s", getattr(cfg, "pk", "?"),
                       plan["reason"])
        return plan

    from django.utils import timezone
    persona = PERSONAS[plan["key"]]
    changes, extras = plan["changes"], plan["extras"]
    drops = dict(plan.get("drops") or {})
    stamped_at = timezone.now().isoformat()

    pk = getattr(cfg, "pk", None)
    if pk is not None and changes:
        # The same re-read pattern safety._save_extras uses, and for the
        # same reason: a tick holds a config object for tens of seconds,
        # so writing the in-memory row back would revert whatever the
        # operator changed on a form in between.
        from django.db import transaction
        with transaction.atomic():
            row = (cfg.__class__._default_manager
                   .select_for_update().filter(pk=pk).first())
            target = row if row is not None else cfg
            for name, (_old, new) in changes.items():
                setattr(target, name, new)
            if row is not None:
                row.save(update_fields=sorted(changes) + ["updated_at"])
    for name, (_old, new) in changes.items():
        setattr(cfg, name, new)

    # The keys that must STOP existing first (the legacy time-stop inlet,
    # a knob the previous persona owned and this one does not), then the
    # merge. The two sets are disjoint by construction — `_drops_for` only
    # ever names keys this persona does not set — so the order is a
    # readability choice, not a correctness one.
    _drop_extras(cfg, list(drops))

    # extras through the house helper: it re-reads the row, merges ONLY
    # the keys handed to it, and leaves every other key (shadow_until,
    # account_share_pct, the heartbeat, risk knobs no persona owns)
    # exactly as it found them.
    from bot_program.asset_engine.safety import _save_extras
    merge = {name: new for name, (_old, new) in extras.items()}
    merge[PERSONA_EXTRAS_KEY] = persona.key
    merge[PERSONA_AT_EXTRAS_KEY] = stamped_at
    _save_extras(cfg, **merge)

    try:
        from bot_program.audit import record_event
        record_event(AUDIT_KIND, {
            "config_id": pk,
            "config": str(getattr(cfg, "name", "") or ""),
            "asset_class": str(getattr(cfg, "asset_class", "") or ""),
            "mode": str(getattr(cfg, "mode", "") or ""),
            "persona": persona.key,
            "persona_at": stamped_at,
            "forced": bool(force),
            "fields": {k: [v[0], v[1]] for k, v in changes.items()},
            "extras": {k: [v[0], v[1]] for k, v in extras.items()},
            "dropped": dict(drops),
            "warnings": list(plan["warnings"]),
        }, user=user)
    except Exception as e:  # noqa: BLE001 — an audit failure never blocks
        logger.warning("[persona] audit row failed: %s", e)

    logger.info("[persona] cfg %s (%s/%s) is now %s — %d field(s), "
                "%d extra(s) changed, %d dropped%s",
                pk, getattr(cfg, "name", "?"),
                getattr(cfg, "mode", "?"), persona.key,
                len(changes), len(extras), len(drops),
                "; ".join([""] + plan["warnings"]) if plan["warnings"] else "")
    return {"ok": True, "reason": "", "key": persona.key,
            "changes": changes, "extras": extras, "drops": drops,
            "warnings": list(plan["warnings"]),
            "persona_at": stamped_at}


# ── Presentation helpers shared by the page and the command ──────────────

def knob_matrix() -> list:
    """[{knob, kind, values: {key: value}, why: {key: str}, differs}] — the
    three presets side by side, one row per knob, in ALL_KNOBS order.

    `differs` is False only when all three personas set the SAME value:
    the page highlights the differences rather than re-printing a table
    the operator has to diff by eye.
    """
    rows = []
    for name in ALL_KNOBS:
        values = {k: p.knob(name) for k, p in PERSONAS.items()}
        seen = [v for v in values.values() if v is not None]
        differs = (len(seen) != len(values)
                   or len({str(v) for v in seen}) > 1)
        rows.append({
            "knob": name,
            "kind": "field" if name in FIELD_KNOBS else "extra",
            "values": values,
            "why": {k: p.why.get(name, "") for k, p in PERSONAS.items()},
            "differs": differs,
        })
    return rows
