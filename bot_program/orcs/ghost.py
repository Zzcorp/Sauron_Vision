"""THE ARMS (spec §6.1, §3.3): each idea's mechanical twins, stepped on the
same marks as the real row, on their OWN state. Nothing here writes an
AssetBotTrade, moves a stop, sends an order or calls a model: every arm is
a JSON state on its OrcTrack row.

  care         G, the care ghost: the root at its birth size under exactly
               the mechanics the row would have had (the care's plan() with
               the inputs the real care used this tick, the engine's knobs,
               the paper replay of resting levels, the mirror assumed
               accepted), on its own care state, seeded once at birth
  playbook     P: the care ghost plus the playbook's code (§5.4): the
               structure trail on each close of its bar, the draw trim on
               paper, the thesis exit. Versioned PLAYBOOK_VERSION
  orc_shadow   O: the real row, recorded tick by tick (its marks, its stop
               path, the best and worst closing-side R); after a HAND ACT
               (a hand close on the platform or in the broker's app, a hand
               levels edit, the kill switch) it carries on as a shadow from
               the previous tick's record, as the care would (§6.4)
  chandelier3, staged
               the multi-ghost: simulate.EXIT_POLICIES on 4h venue bars
               (_locks, _engine_constants), locks moved at a bar's close and
               binding from the next, the engine target, the no-progress
               clock in market hours, the config's ceiling

THE CARE GHOST NEVER READS THE ROW'S CARE STATE AFTER ITS SEED. A ghost on
the row's state would follow every Orc tightening and price a noise stop at
a delta of zero. What it shares with the row is what the real care was
given this tick (trade._care_tick: the posture, the kind, the manual flag,
the crowd read, the scale-out flag, the event), the mark, and what the row
carries that the care only reads (the thesis check's structure stop, the
cost charged, the leverage).

PRICES. Every exit is priced by bot_program/orcs/pricing.py, never by a
booked price: a plan close at market_exit_px of its tick, a stop at
stop_exit_px, a target at target_exit_px, a level a bar traded at
level_exit_px.

ONE WRITER PER PHASE (2026-10-22). While the row is open, the tick
alone steps the arms (the multi-ghost walks its 4h bars there too, catching
up on every bar it missed); once the row is closed or cancelled, the
track_ghosts task alone does. The two never write one idea's arms in the
same phase, so neither overwrites the other's step.

FORWARD ONLY (§6.2). An arm is seeded at its birth and walks only what
comes after it: a policy arm the bars that open at or after its seed, never
the history of an adopted row.

AFTER THE ROW CLOSES (step_bars, the track_ghosts task): the shared
mechanical events first (a time stop at the same frozen ceiling, a venue or
engine stop or target at a level equal to the arm's own: the arm takes the
same event at the same price, so the difference is exactly zero), then the
tail on complete venue 1h bars with the proving ground's discipline (a gap
fills at the open, a tie goes to the stop, a lock binds from the next bar),
from the first bar that opens at or after the arm's last tick, until the
tail cap, where the arm is marked to market at the close of the bar that
spans the cap and flagged. The care-like arms run the care's plan() there
with the context the tick last gave them, else the row's own (the manual
lane's care is the manual lane's); the playbook arm runs its own code
there too, every frame cut at the bar's close: X-THESIS, the structure
trail, and K-DRAW on paper. Each arm walks on its own, and every arm still
open a bar past the cap is closed: no idea outlives its cap.

THE SEAMS (O3): the playbook arm runs no Orc power (no trail ownership, no
lock waiver); plan(orc=) and the effective stop arrive with O3.
"""
import copy
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from typing import Optional

from bot_program.orcs import pricing
from bot_program.orcs.bars import BAR_FINAL_AFTER
from bot_program.orcs.constants import (ARM_CARE, ARM_ORC, ARM_PLAYBOOK,
                                        DIVERGE_HOLD, DIVERGE_REDUCE,
                                        GHOST_ARMS, KDRAW_FRACTION,
                                        LEG_DONE_STATUSES,
                                        MULTI_GHOST_POLICIES,
                                        MULTI_GHOST_TF, PLAYBOOK_VERSION,
                                        SEED_ADOPT, SEED_BIRTH, SEED_LATE,
                                        STOP_PATH_MAX, TAIL_CAP_MANUAL_DAYS,
                                        TAIL_CAP_NO_PROGRESS_X, TAIL_TF,
                                        UNMANAGED_TICK_GAP_MIN)

logger = logging.getLogger(__name__)

CARE_LIKE = (ARM_CARE, ARM_PLAYBOOK, ARM_ORC)
ARM_NAMES = {ARM_CARE: "care ghost", ARM_PLAYBOOK: "playbook arm",
             ARM_ORC: "Orc arm", "chandelier3": "chandelier3 arm",
             "staged": "staged arm"}
#: The care's own keys the care-like arms carry (position_care.plan).
CARE_KEYS = ("peak", "worst", "since", "soft_stop", "soft_why", "mfe_r",
             "mae_r", "r_now", "event", "scaled_out")
#: Row metadata a shadow never inherits: the care's and the mirror's own
#: state, the Orc's keys, the replay's stamp, the close's records.
DROP_META = ("care", "care_exit", "orc", "orc_stop", "effective_stop",
             "effective_why", "trail_owner", "venue_stop_why", "scale_out",
             "paper_replay", "paper_exit", "breakeven_armed",
             "initial_stop_loss")
#: The context keys the tail keeps from the last tick (the crowd is read
#: per tick and is not kept; the event is read again at each bar).
CTX_KEYS = ("posture_level", "kind", "live", "manual", "scale")
#: What a care-like arm reads that O1a's care track never held: static
#: keys, from the row and its config, filled in place by `seed_tracks`.
UPGRADE_KEYS = ("cf", "rpu", "ceiling", "target", "paper", "protected",
                "opened_at", "symbol", "asset_class", "root", "knobs", "ctx",
                "manual")
#: The row's replay stamp counts as this tick's within this many seconds.
SAME_TICK_S = 120
HAND_WORDS = {"hand_close": "closed the position",
              "app_close": "closed it in the broker's app",
              "edit": "edited the levels",
              "kill": "pressed the kill switch"}


# ── small helpers ────────────────────────────────────────────────────────

def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _iso(t):
    return t.isoformat() if hasattr(t, "isoformat") else t


def _parse(s):
    if s is None or isinstance(s, datetime):
        return s
    from django.utils.dateparse import parse_datetime
    t = parse_datetime(str(s))
    if t is not None and t.tzinfo is None:
        t = t.replace(tzinfo=dt_tz.utc)
    return t


def _dec(x):
    v = _f(x)
    return None if v is None else Decimal(str(v))


def _same(a, b) -> bool:
    a, b = _f(a), _f(b)
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(1e-8, abs(a) * 1e-9)


def _tighter(sign, *levels):
    """The tightest of the given stop levels for a side (None ignored)."""
    xs = [x for x in (_f(v) for v in levels) if x is not None]
    if not xs:
        return None
    return max(xs) if sign > 0 else min(xs)


# ── the shadow row ───────────────────────────────────────────────────────

@dataclass
class ShadowRow:
    """What plan(), the engine's trailing arithmetic and the paper replay
    read of a row, and nothing else: a dataclass, never a model copy, so
    there is no save() to call and no row it could write."""
    pk: object
    symbol: str
    side: str
    asset_class: str
    entry_price: object
    stop_loss: object
    take_profit: object
    qty: object
    metadata: dict = field(default_factory=dict)
    opened_at: object = None
    paper: bool = True
    config: object = None
    status: str = "OPEN"

    @property
    def id(self):
        return self.pk


def shadow_of(state, *, base_meta=None, config=None, stop=None,
              soft=None) -> ShadowRow:
    """The arm as a row: the row's metadata as the care reads it (the
    thesis check's stop, the cost charged, the leverage), the arm's OWN
    care state, stop, target, size and replay stamp."""
    meta = {k: v for k, v in (base_meta or {}).items() if k not in DROP_META}
    care = {k: state.get(k) for k in CARE_KEYS if state.get(k) is not None}
    if soft is not None:
        care["soft_stop"] = soft
    meta["care"] = care
    if state.get("init_in_meta") and state.get("initial_stop") is not None:
        meta["initial_stop_loss"] = state["initial_stop"]
    if state.get("breakeven_armed"):
        meta["breakeven_armed"] = True
    if isinstance(state.get("replay"), dict):
        meta["paper_replay"] = dict(state["replay"])
    if state.get("protected"):
        meta["protected"] = True
    return ShadowRow(
        pk=state.get("root"), symbol=str(state.get("symbol") or ""),
        side=str(state.get("side") or ""),
        asset_class=str(state.get("asset_class") or ""),
        entry_price=_dec(state.get("entry")),
        stop_loss=_dec(stop if stop is not None else state.get("venue_stop")),
        take_profit=_dec(state.get("target")),
        qty=_dec(state.get("qty_open")) or Decimal(0), metadata=meta,
        opened_at=_parse(state.get("opened_at")),
        paper=bool(state.get("paper")), config=config)


# ── seeding ──────────────────────────────────────────────────────────────

def _knobs(cfg) -> dict:
    extras = getattr(cfg, "extras", None) or {}

    def num(key):
        try:
            return float(extras.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return {"be_at": num("breakeven_at_r"),
            "be_buffer": num("breakeven_buffer_r"),
            "trail_pct": num("trail_pct"), "trail_start": num("trail_start_r")}


def _cf(row, cfg) -> float:
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    charged = _f(meta.get("cost_fraction_charged"))
    if charged is not None:
        return charged
    try:
        from bot_program.asset_engine.risk_levels import \
            round_trip_cost_fraction
        return float(round_trip_cost_fraction(cfg, row.symbol))
    except Exception:  # noqa: BLE001 — no cost model is no cost
        return 0.0


def _ceiling(row, cfg):
    try:
        setting = cfg.time_stop_setting()
        if setting.get("enabled") and setting.get("hours") \
                and row.opened_at is not None:
            return row.opened_at + timedelta(hours=float(setting["hours"]))
    except Exception:  # noqa: BLE001 — no ceiling read is no ceiling
        pass
    return None


def _common(row, cfg, *, now, seed) -> dict:
    from bot_program.orcs.facts import initial_stop
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    so = meta.get("scale_out") if isinstance(meta.get("scale_out"),
                                             dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    entry, init = _f(row.entry_price), initial_stop(row)
    qty_open = _f(row.qty)
    qty = _f(so.get("original_qty")) or qty_open
    banked = []
    if care.get("scaled_out") and so and _f(so.get("qty")):
        banked.append({"qty": _f(so.get("qty")), "px": _f(so.get("price")),
                       "at": so.get("at"), "why": "scale-out before birth"})
    ceiling = _ceiling(row, cfg)
    return {
        "root": row.pk, "symbol": str(row.symbol or ""),
        "asset_class": str(row.asset_class or ""),
        "side": str(row.side or "").upper(), "entry": entry,
        "initial_stop": init,
        "rpu": abs(entry - init) if entry and init else None,
        "qty": qty, "qty_open": qty_open, "banked": banked,
        "cf": _cf(row, cfg), "ceiling": _iso(ceiling),
        "target": _f(row.take_profit), "paper": bool(row.paper),
        "protected": bool(meta.get("protected")),
        "opened_at": _iso(row.opened_at), "seed": seed,
        "seeded_at": _iso(now), "last_tick_at": None, "ticks_missed": 0,
        "bar_sources": [],
    }


def seed_care_like(orc, row, cfg, *, now, seed) -> dict:
    """A care-like arm: the care's own state taken ONCE from the row
    (tracks.seed_care), with the arm's size, price model and frozen
    config."""
    from bot_program.orcs.tracks import seed_care
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    state = seed_care(orc, row)
    common = _common(row, cfg, now=now, seed=seed)
    common.pop("banked", None)
    state.update(common)
    state["banked"] = [{"qty": b.get("qty"), "px": b.get("price"),
                        "at": None, "why": "scale-out before birth"}
                       for b in state.get("banked") or []
                       if isinstance(b, dict) and b.get("qty")]
    for key in ("mfe_r", "mae_r", "r_now", "event"):
        state[key] = care.get(key)
    state.update({
        "knobs": _knobs(cfg),
        "breakeven_armed": bool(meta.get("breakeven_armed")),
        "init_in_meta": meta.get("initial_stop_loss") is not None,
        "replay": (dict(meta["paper_replay"])
                   if isinstance(meta.get("paper_replay"), dict) else None),
        "replay_own": False, "ctx": None,
        # the care's lane, frozen: the tail runs the manual lane's care for
        # a hand ticket even when no tick ever gave it a context
        "manual": bool(getattr(orc, "manual", False)),
    })
    return state


def _seed_playbook(orc, row, cfg, *, now, seed):
    state = seed_care_like(orc, row, cfg, now=now, seed=seed)
    state.update({"version": PLAYBOOK_VERSION, "orc_stop": None,
                  "orc_why": "", "tstruct_bar": None, "kdraw_bar": None,
                  "kdraw_done": []})
    return state


def _last_edit_at(meta) -> str:
    edits = meta.get("level_edits") if isinstance(meta, dict) else None
    if isinstance(edits, list) and edits and isinstance(edits[-1], dict):
        return str(edits[-1].get("at") or "")
    return ""


def _seed_orc(orc, row, cfg, *, now, seed):
    state = seed_care_like(orc, row, cfg, now=now, seed=seed)
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    care = meta.get("care") if isinstance(meta.get("care"), dict) else {}
    state.update({
        "mode": "real", "last": None, "last_care": dict(care),
        "last_stop": _f(row.stop_loss), "last_target": _f(row.take_profit),
        "best_m_r": None, "worst_m_r": None, "best_bar_at": None,
        "path": [], "pending_exit": None, "crossed": None,
        "first_divergence": None,
        "faith": {"ticks": 0, "soft_mismatch": 0, "venue_mismatch": 0,
                  "first": None},
        "basis": [], "basis_at": None, "hand_edit_at": _last_edit_at(meta),
        "hand": None,
    })
    return state


def _seed_policy(name):
    def seed(orc, row, cfg, *, now, seed):
        meta = row.metadata if isinstance(row.metadata, dict) else {}
        care = meta.get("care") if isinstance(meta.get("care"),
                                              dict) else {}
        state = _common(row, cfg, now=now, seed=seed)
        stop = _f(row.stop_loss) or state["initial_stop"]
        state.update({
            "policy": name, "soft": stop, "soft_why": "stop",
            "mfe": max(0.0, _f(care.get("mfe_r")) or 0.0),
            "extreme": _f(care.get("peak")) or state["entry"],
            "since": care.get("since") or state["opened_at"],
            # FORWARD ONLY (§6.2): the walk takes the bars that open at
            # or after the seed (simulate's "entry at the open of the bar
            # after"); the tick covers the rest of the bar it was born in
            "bar_at": _iso(now), "entry_bar": False,
        })
        return state
    return seed


SEEDERS = {ARM_CARE: seed_care_like, ARM_PLAYBOOK: _seed_playbook,
           ARM_ORC: _seed_orc,
           **{p: _seed_policy(p) for p in MULTI_GHOST_POLICIES}}


def _upgraded(old, fresh, now) -> dict:
    """An O1a care-like track brought to the arms' format IN PLACE:
    the static keys from the row and its config (UPGRADE_KEYS), the keys
    the old track never had from a fresh seed, but never a care-state key
    (CARE_KEYS) from the row's care: the track's own state is kept, and
    what it never held stays unset. Marked "late"."""
    state = dict(old or {})
    for key in UPGRADE_KEYS:
        state[key] = fresh.get(key)
    for key, value in fresh.items():
        if key not in state and key not in CARE_KEYS:
            state[key] = value
    # O1a's banked parts carry "price"; the arms read "px"
    state["banked"] = [{"qty": b.get("qty"),
                        "px": b.get("px", b.get("price")),
                        "at": b.get("at"),
                        "why": b.get("why") or "scale-out before birth"}
                       for b in state.get("banked") or []
                       if isinstance(b, dict) and b.get("qty")]
    state["seed"], state["seeded_at"] = SEED_LATE, _iso(now)
    return state


def upgrade_old(orc, row, tracks, *, now) -> list:
    """O1a's open care-like tracks (no `cf`) brought to the arms' format in
    place (_upgraded), in memory; returns them for the caller's write."""
    cfg = getattr(row, "config", None)
    old = [t for t in tracks
           if t.arm in CARE_LIKE and t.open and "cf" not in (t.state or {})]
    for t in old:
        t.state = _upgraded(t.state, SEEDERS[t.arm](
            orc, row, cfg, now=now, seed=SEED_LATE), now)
    return old


def seed_tracks(orc, row, *, now=None, seed=SEED_BIRTH) -> list:
    """Every arm of the idea, created once (get_or_create): a second call
    writes nothing. The census seeds an Orc born before its arms existed
    with seed "late", which never counts for a seat, and brings O1a's care
    track (no `cf`) up to the arms' format in place (_upgraded)."""
    from django.utils import timezone

    from bot_program.orcs.models import OrcTrack
    now = now or timezone.now()
    existing = {t.arm: t for t in OrcTrack.objects.filter(orc=orc)}
    cfg = getattr(row, "config", None)
    old = upgrade_old(orc, row, list(existing.values()), now=now)
    if old:
        OrcTrack.objects.bulk_update(old, ["state"])
    missing = [a for a in GHOST_ARMS if a not in existing]
    if not missing:
        return list(existing.values())
    for arm in missing:
        state = SEEDERS[arm](orc, row, cfg, now=now, seed=seed)
        track, _ = OrcTrack.objects.get_or_create(
            orc=orc, arm=arm, defaults={"state": state, "open": True})
        existing[arm] = track
    return [existing[a] for a in GHOST_ARMS if a in existing]


# ── R and the exits ──────────────────────────────────────────────────────

def arm_r(state, exit_px):
    """The arm's R per its BIRTH size: what it banked plus what it closed,
    over qty x risk per unit. None without an R."""
    sign = pricing.d(state.get("side"))
    entry, rpu = _f(state.get("entry")), _f(state.get("rpu"))
    qty = _f(state.get("qty"))
    if not entry or not rpu or not qty:
        return None
    total = 0.0
    for b in state.get("banked") or []:
        q, px = _f(b.get("qty")), _f(b.get("px"))
        if q and px:
            total += q * sign * (px - entry)
    open_q = _f(state.get("qty_open")) or 0.0
    if exit_px is not None and open_q:
        total += open_q * sign * (float(exit_px) - entry)
    return total / (qty * rpu)


def _exit(kind, px, at, why, **extra) -> dict:
    return {"kind": kind, "px": float(px), "at": _iso(at),
            "why": str(why)[:200], **extra}


def _close_track(track, state, out) -> None:
    track.open = False
    track.exit_price = Decimal(str(round(out["px"], 8)))
    track.exit_at = _parse(out["at"])
    track.exit_why = out["why"][:200]
    track.exit_r = arm_r(state, out["px"])
    track.mfe_r = (_f(state.get("best_m_r")) if track.arm == ARM_ORC
                   else _f(state.get("mfe_r")) if track.arm in CARE_LIKE
                   else _f(state.get("mfe")))
    if out.get("tail_capped"):
        track.tail_capped = True
    state["exit"] = out


def exit_line(track, row) -> str:
    from bot_program.orcs.facts import px
    name = ARM_NAMES.get(track.arm, track.arm)
    r = track.exit_r
    rr = f"{r:+.2f}R" if r is not None else "its R is not measured"
    if track.tail_capped:
        return (f"The {name} reached its tail cap and was marked to market "
                f"at {rr}.")
    return (f"The {name} exited: {track.exit_why} at "
            f"{px(row, track.exit_price)} ({rr}).")


def _journal_exits(orc, row, closed) -> None:
    from bot_program.orcs import journal
    for track in closed:
        try:
            journal.append(orc, "fact", exit_line(track, row),
                           body={"arm": track.arm, "exit_r": track.exit_r,
                                 "why": track.exit_why,
                                 "tail_capped": track.tail_capped},
                           fact=True)
        except Exception as e:  # noqa: BLE001 — a lost line, never the arm
            logger.warning("[orcs] Orc %s: the %s's exit not journaled: %s",
                           orc.pk, track.arm, e)


# ── the tick ─────────────────────────────────────────────────────────────

def tick_of(bot, trade, price, now) -> pricing.Tick:
    """The tick the row was managed on: its price, and the venue's bid and
    ask when the tick carried them (base._mark_price keeps the ticker)."""
    tk = {}
    try:
        tk = (getattr(bot, "_last_ticks", None) or {}).get(trade.symbol) or {}
    except Exception:  # noqa: BLE001
        tk = {}
    tk = tk if isinstance(tk, dict) else {}
    return pricing.Tick(at=now, p=float(price), bid=_f(tk.get("bid")),
                        ask=_f(tk.get("ask")))


def _tick_dict(tick) -> dict:
    return {"at": _iso(tick.at), "p": tick.p, "bid": tick.bid,
            "ask": tick.ask}


def _tick_from(d) -> Optional[pricing.Tick]:
    if not isinstance(d, dict) or _f(d.get("p")) is None:
        return None
    return pricing.Tick(at=_parse(d.get("at")), p=float(d["p"]),
                        bid=_f(d.get("bid")), ask=_f(d.get("ask")))


class _Env:
    """What one tick hands every arm."""

    def __init__(self, orc, row, bot, tick, ctx, now, cache, cared,
                 results):
        self.orc, self.row, self.bot, self.tick = orc, row, bot, tick
        self.ctx, self.now, self.cache, self.cared = ctx, now, cache, cared
        self.results = results or []
        self.meta = row.metadata if isinstance(row.metadata, dict) else {}
        # the bot's own config: never a query on the row's foreign key
        self.config = getattr(bot, "cfg", None)
        self.care_state = None
        # the care ghost's venue stop as the real row shows it to the hook:
        # the engine's knobs run after the hook (asset_engine/base.py)
        self.care_venue_at_hook = None
        # the O arm's hourly basis samples, read before any arm steps: the
        # playbook's menu shifts platform levels by them
        self.basis = None
        self.facts = []
        self._frames = {}

    def frame(self, tf):
        if tf not in self._frames:
            from bot_program.orcs import bars
            self._frames[tf] = bars.frame(self.row.symbol, tf,
                                          asset_class=self.row.asset_class,
                                          now=self.now, cache=self.cache)
        return self._frames[tf]


def _missed(state, now) -> None:
    """Count a stretch of more than UNMANAGED_TICK_GAP_MIN minutes of OPEN
    market with no step (the switch OFF, the tick stopped): a flag on the
    grade, never an exclusion (§6.4 names none)."""
    last = _parse(state.get("last_tick_at"))
    if last is not None and (now - last) > timedelta(
            minutes=UNMANAGED_TICK_GAP_MIN):
        from bot_program.orcs.bars import open_seconds
        limit = UNMANAGED_TICK_GAP_MIN * 60
        try:
            gap = open_seconds(last, now, state.get("asset_class"),
                               state.get("symbol"), limit=limit)
        except Exception:  # noqa: BLE001
            gap = 0
        if gap > limit:
            state["ticks_missed"] = int(state.get("ticks_missed") or 0) + 1
    state["last_tick_at"] = _iso(now)


def _resting(state, env, *, soft):
    """A paper arm's resting levels over the bars since its last tick. While
    its levels equal the ones the row's own replay tested this tick (run
    before the care, stamped in metadata["paper_replay"]), that replay
    stands for it: its stamp is copied and nothing is read. Once they
    differ the arm replays its own levels from then on."""
    from bot_program import paper_exits
    sign = pricing.d(state.get("side"))
    care_on = env.ctx is not None
    mine = _tighter(sign, state.get("venue_stop"), soft) if care_on \
        else _f(state.get("venue_stop"))
    st = env.meta.get("paper_replay")
    st = st if isinstance(st, dict) else {}
    tick_at = _parse(st.get("tick_at"))
    # written moments before this row's care, in this same pass (the next
    # pass is minutes away)
    this_tick = tick_at is not None and abs(
        (env.now - tick_at).total_seconds()) <= SAME_TICK_S
    if not state.get("replay_own") and this_tick \
            and _same(mine, st.get("stop")) \
            and _same(state.get("target"), st.get("target")):
        state["replay"] = dict(st)
        return None
    state["replay_own"] = True
    shadow = shadow_of(state, base_meta=env.meta, config=env.config,
                       soft=soft)
    ceiling = _parse(state.get("ceiling"))
    result = paper_exits.replay(shadow, now=env.now, care_on=care_on,
                                ceiling=ceiling)
    if result is None:
        return None
    state["replay"] = paper_exits.stamp_value(result, now=env.now)
    hit = result.get("hit")
    if not hit:
        return None
    # the bar the replay hit is the arm's evidence: a public feed's bar
    # grades the idea "platform"
    _note_source(state, hit.get("source"))
    words = {"SL": "its stop rested and was hit",
             "TP": "its target rested and was hit",
             "TIME": "the config's time stop, read on the bars"}
    return _exit("resting", pricing.level_exit_px(hit["level"],
                                                  state["side"],
                                                  state["cf"]),
                 hit.get("at") or env.now, words.get(hit["reason"],
                                                     hit["reason"]))


def _take_care(state, care) -> None:
    for key in CARE_KEYS:
        state[key] = care.get(key)


def _bank(state, shadow, tick, now, fraction=None, why="scale-out"):
    from bot_program.position_care import SCALE_OUT_FRACTION, scale_out_qty
    q = scale_out_qty(shadow, fraction or SCALE_OUT_FRACTION)
    if not q or q <= 0:
        return False
    px = pricing.market_exit_px(tick, state["side"], state["cf"])
    state.setdefault("banked", []).append({"qty": float(q), "px": px,
                                           "at": _iso(now), "why": why})
    state["qty_open"] = float(Decimal(str(state.get("qty_open") or 0)) - q)
    return True


def _mirror(state, p, *, extra=None) -> None:
    """A protected live arm: the venue's stop follows the soft stop (and the
    playbook's own stop), tighten-only, on the right side of the mark, at
    the instrument's printed precision; every PATCH assumed accepted."""
    from core.price_format import price_decimals
    sign = pricing.d(state.get("side"))
    eff = _tighter(sign, state.get("soft_stop"), extra)
    if eff is None or eff <= 0:
        return
    venue = _f(state.get("venue_stop"))
    if venue is not None and sign * (venue - eff) >= -1e-12:
        return
    cand = round(eff, price_decimals(eff, state.get("asset_class"),
                                     state.get("symbol")))
    if sign * (p - cand) <= 0:
        state["mirror_refused"] = int(state.get("mirror_refused") or 0) + 1
        return
    if not state.get("init_in_meta"):
        # the mirror stamps the risk denominator from the sent stop first
        state["init_in_meta"] = True
        if venue is not None:
            state["initial_stop"] = venue
    state["venue_stop"] = cand


def _engine_knobs(state, env, p) -> None:
    """The config's break-even and trail knobs, on the arm's own stop: the
    broker-held path (_manage_broker_stop: the tighter of the two) on a
    protected live arm, the bot-side path (_update_trailing_stop:
    break-even first, then the trail) otherwise."""
    knobs = state.get("knobs") or {}
    be_at, trail = _f(knobs.get("be_at")) or 0.0, _f(knobs.get("trail_pct")) \
        or 0.0
    if (be_at <= 0 and trail <= 0) or _f(state.get("venue_stop")) is None:
        return
    from bot_program.engine.trailing import (_adjusted, breakeven_candidate,
                                             is_improvement, trail_candidate,
                                             unrealised_r)
    shadow = shadow_of(state, base_meta=env.meta if env else None)
    price = Decimal(str(p))
    adjust = None
    if env is not None and env.bot is not None:
        try:
            from bot_program.smart_money import lock_adjuster
            adjust = lock_adjuster(env.bot, shadow, price)
        except Exception:  # noqa: BLE001 — no crowd read is the plain lock
            adjust = None
    if state.get("protected") and not state.get("paper"):
        options = []
        if be_at > 0:
            options.append(("breakeven", breakeven_candidate(
                shadow, price, be_at, _f(knobs.get("be_buffer")) or 0.0)))
        if trail > 0:
            options.append(("trail", trail_candidate(
                shadow, price, trail, _f(knobs.get("trail_start")) or 0.0)))
        if adjust is not None:
            options = [(w, c) if c is None else tuple(reversed(adjust(c, w)))
                       for w, c in options]
        viable = [(w, c) for w, c in options
                  if c is not None and is_improvement(shadow, c, price)]
        if not viable:
            return
        why, cand = (max(viable, key=lambda wc: wc[1])
                     if shadow.side == "BUY"
                     else min(viable, key=lambda wc: wc[1]))
        state["venue_stop"] = float(cand)
        if why == "breakeven":
            state["breakeven_armed"] = True
        return
    if be_at > 0:
        cand = breakeven_candidate(shadow, price, be_at,
                                   _f(knobs.get("be_buffer")) or 0.0)
        if cand is not None:
            cand, note = _adjusted(adjust, cand, "breakeven")
            if is_improvement(shadow, cand, price):
                state["venue_stop"] = float(cand)
                shadow.stop_loss = cand
                if note == "breakeven":
                    state["breakeven_armed"] = True
    if trail > 0:
        entry = shadow.entry_price
        in_profit = (price > entry) if shadow.side == "BUY" else (price < entry)
        start = _f(knobs.get("trail_start")) or 0.0
        if not in_profit:
            return
        if start > 0:
            r_now = unrealised_r(shadow, price)
            if r_now is None or r_now < Decimal(str(start)):
                return
        step = Decimal(str(trail)) / Decimal("100")
        cand = (price * (Decimal("1") - step) if shadow.side == "BUY"
                else price * (Decimal("1") + step))
        cand, _note = _adjusted(adjust, cand, "trail")
        if is_improvement(shadow, cand, price):
            state["venue_stop"] = float(cand)


def _crossings(state, tick, *, extra_stop=None):
    """A tick through the arm's stop or target (the venue's own, or the
    engine's bot-side check)."""
    sign = pricing.d(state.get("side"))
    p = tick.p
    stop = _f(state.get("venue_stop"))
    if stop is not None and sign * (p - stop) <= 0:
        return _exit("stop", pricing.stop_exit_px(stop, tick, state["side"],
                                                  state["cf"]),
                     tick.at, f"its stop at {stop:g} was crossed")
    target = _f(state.get("target"))
    if target is not None and sign * (p - target) >= 0:
        return _exit("target", pricing.target_exit_px(target, state["side"],
                                                      state["cf"]),
                     tick.at, f"its target at {target:g} was reached")
    return None


def _care_step(state, env, *, extra_stop=None, extra_why="", seen=None):
    """One tick of a care-like arm, in the order the real tick runs it:
    the config's ceiling, the paper replay of resting levels, plan() with
    the care's own inputs, a scale-out, the mirror, the engine's knobs,
    then the tick's crossing of its stop or target. `seen` (a dict) gets
    the venue stop as it stood before the knobs: the real row's stop at
    the Orc hook, which runs before them."""
    from bot_program.position_care import plan
    tick, now = env.tick, env.now
    side, cf = state["side"], state["cf"]
    sign = pricing.d(side)
    _missed(state, now)
    ceiling = _parse(state.get("ceiling"))
    if ceiling is not None and now >= ceiling:
        return _exit("time", pricing.market_exit_px(tick, side, cf), now,
                     "the config's time stop")
    if state.get("paper"):
        hit = _resting(state, env, soft=_tighter(sign, state.get("soft_stop"),
                                                 extra_stop))
        if hit:
            return hit
    ctx = env.ctx
    if ctx is not None:
        state["ctx"] = {k: ctx.get(k) for k in CTX_KEYS}
        shadow = shadow_of(state, base_meta=env.meta, config=env.config)
        decision = plan(shadow, tick.p, now=ctx.get("now") or now,
                        posture_level=ctx.get("posture_level", "calm"),
                        kind=ctx.get("kind", "neutral"),
                        live=bool(ctx.get("live")),
                        manual=bool(ctx.get("manual")),
                        crowd=ctx.get("crowd"), scale=bool(ctx.get("scale")),
                        event=ctx.get("event"))
        care = dict(decision.get("care") or {})
        why = str(care.pop("exit", "") or "its soft stop")
        _take_care(state, care)
        if decision.get("action") == "close":
            waits = (ctx.get("venue_listed") is False
                     and _same(state.get("venue_stop"), env.row.stop_loss)
                     and _same(state.get("target"), env.row.take_profit))
            if not waits:
                return _exit("care", pricing.market_exit_px(tick, side, cf),
                             now, f"the care's {why}")
            # the venue no longer lists the row: its own stop or target
            # filled there, and the arm, on the same levels, takes that
            # event when the reconcile books it (step_bars)
            state["waits_for_venue"] = True
            return None
        if decision.get("scale_out") and state.get("paper") \
                and ctx.get("scale"):
            _bank(state, shadow, tick, now)
            state["scaled_out"] = True
    if extra_stop is not None and sign * (tick.p - extra_stop) <= 0:
        return _exit("playbook", pricing.market_exit_px(tick, side, cf),
                     now, extra_why or "the playbook's stop")
    if not state.get("paper") and state.get("protected"):
        _mirror(state, tick.p, extra=extra_stop)
    if seen is not None:
        seen["venue"] = state.get("venue_stop")
    _engine_knobs(state, env, tick.p)
    return _crossings(state, tick)


# ── the arms' tick steppers ──────────────────────────────────────────────

def _step_care(state, env):
    seen = {}
    out = _care_step(state, env, seen=seen)
    env.care_state = state
    env.care_venue_at_hook = seen.get("venue", state.get("venue_stop"))
    return out


def _playbook_bars(state, env) -> None:
    """On each close of the trail bar, T-STRUCT; on each 4h close, the draw
    (K-DRAW, a paper trim of half, once per draw)."""
    from bot_program.orcs import menu as menus
    from bot_program.orcs import playbook
    sign = pricing.d(state["side"])
    mfe = _f(state.get("mfe_r"))
    if mfe is not None and mfe >= playbook.STRUCTURE_FROM_R:
        tf = playbook.trail_tf(mfe)
        f = env.frame(tf)
        if f is not None and f.fresh and f.newest_end is not None:
            closed = _closed_end(f, env.now)
            if closed is not None and closed != state.get("tstruct_bar"):
                state["tstruct_bar"] = closed
                m = pricing.closing_mark(env.tick, state["side"],
                                         state["cf"])
                key = ("orcs:menu", env.row.symbol)
                mn = env.cache.get(key) if isinstance(env.cache, dict) \
                    else None
                if mn is None:
                    mn = menus.symbol_levels(env.row.symbol,
                                             env.row.asset_class,
                                             now=env.now, mark=m,
                                             cache=env.cache,
                                             basis_samples=env.basis)
                    if isinstance(env.cache, dict):
                        env.cache[key] = mn
                rows = menus.for_idea(mn, side=state["side"],
                                      entry=state["entry"],
                                      risk_per_unit=state["rpu"], mark=m,
                                      care_state=state, cf=state["cf"])
                eff = _tighter(sign, state.get("soft_stop"),
                               state.get("venue_stop"), state.get("orc_stop"))
                ts = playbook.t_struct(rows, side=state["side"], mfe_r=mfe,
                                       p=env.tick.p, m=m, effective=eff,
                                       atr=mn.atr)
                if ts:
                    state["orc_stop"] = ts["stop"]
                    state["orc_why"] = f"T-STRUCT {ts['level_id']}"
                    _note_source(state, mn.source)
    if not state.get("paper"):
        return
    f4 = env.frame("4h")
    if f4 is None or not f4.venue or not f4.fresh:
        return
    closed = _closed_end(f4, env.now)
    if closed is None or closed == state.get("kdraw_bar"):
        return
    state["kdraw_bar"] = closed
    _k_draw(state, f4, symbol=env.row.symbol, tick=env.tick, now=env.now,
            meta=env.meta)


def _k_draw(state, f4, *, symbol, tick, now, meta, final_at=None) -> None:
    """K-DRAW on a 4h close (a paper trim of KDRAW_FRACTION, once per
    draw): the draw on liquidity read on the FINAL 4h bars only (as they
    stand at `final_at`, else `now`)."""
    from bot_program.orcs import playbook
    from bot_program.orcs.bars import _swings, final_df
    df = final_df(f4, final_at or now)
    if df is None or not len(df):
        return
    try:
        from brain.thesis_check import structure_read
        read = structure_read(symbol, state["side"], tick.p, now=now,
                              bars=(df, _swings(df)))
    except Exception:  # noqa: BLE001 — no read, no draw
        return
    m = pricing.closing_mark(tick, state["side"], state["cf"])
    kd = playbook.k_draw(side=state["side"], m=m, draw=read.get("draw"),
                         atr4h=f4.atr, paper=True,
                         done=state.get("kdraw_done") or [])
    if kd:
        shadow = shadow_of(state, base_meta=meta)
        if _bank(state, shadow, tick, now, fraction=KDRAW_FRACTION,
                 why="K-DRAW"):
            state.setdefault("kdraw_done", []).append(kd["level_id"])


def _step_playbook(state, env):
    from bot_program.orcs import playbook
    out = _care_step(state, env, extra_stop=_f(state.get("orc_stop")),
                     extra_why=f"the playbook's {state.get('orc_why') or 'stop'}")
    if out:
        return out
    xt = playbook.x_thesis(env.meta.get("thesis"),
                           [r.as_dict() if hasattr(r, "as_dict") else r
                            for r in env.results], env.now)
    if xt:
        return _exit("playbook", pricing.market_exit_px(
            env.tick, state["side"], state["cf"]), env.now,
            f"X-THESIS: {xt['why']}")
    try:
        _playbook_bars(state, env)
    except Exception as e:  # noqa: BLE001 — the code trail waits a bar
        logger.info("[orcs] playbook bars unread: %s", e)
    return None


def _closed_end(frame, now):
    """The end of the frame's newest FINAL bar, as ISO text, or None: a bar
    that just ended counts once the refresh rewrote it (bars.final_bar),
    so T-STRUCT and K-DRAW never act on a snapshot of it."""
    from bot_program.orcs.bars import final_end
    end = final_end(frame, now)
    return end.isoformat() if end is not None else None


def _note_source(state, source) -> None:
    label = "etoro" if source in ("etoro",) else ("platform" if source
                                                   else "")
    if label and label not in (state.get("bar_sources") or []):
        state.setdefault("bar_sources", []).append(label)


def _to_shadow(state, how, at, *, replay=None) -> None:
    """The O arm leaves the real legs: from the previous tick's record it
    carries on as the care would (§6.4). Its replay starts from the row's
    stamp as the hand found it."""
    last_care = state.get("last_care") or {}
    state["mode"] = "shadow"
    state["hand"] = {"how": how, "at": _iso(at)}
    for key in CARE_KEYS:
        state[key] = last_care.get(key)
    state["venue_stop"] = _f(state.get("last_stop"))
    state["target"] = _f(state.get("last_target"))
    last = state.get("last") or {}
    if _f(last.get("qty")):
        state["qty_open"] = _f(last.get("qty"))
    state["replay"] = dict(replay) if isinstance(replay, dict) else None
    state["replay_own"] = True


def hand_line(how, at) -> str:
    from bot_program.orcs.facts import _hhmm
    return (f"The operator's hand acted ({HAND_WORDS.get(how, how)}) at "
            f"{_hhmm(at)} UTC: the Orc arm continues as a shadow from here.")


def _root_mark(state, tick) -> float:
    """The root's closing-side mark on this tick, and its best and worst R
    (§6.3: r_avail is the root leg's best mark over [entry, the latest
    exit]). The root's mark does not depend on the O arm's mode: after a
    hand levels edit the row is still open and still marked."""
    side, cf = state["side"], state["cf"]
    m = pricing.closing_mark(tick, side, cf)
    entry, rpu = _f(state.get("entry")), _f(state.get("rpu"))
    if entry and rpu:
        r_m = pricing.d(side) * (m - entry) / rpu
        state["best_m_r"] = r_m if state.get("best_m_r") is None \
            else max(state["best_m_r"], r_m)
        state["worst_m_r"] = r_m if state.get("worst_m_r") is None \
            else min(state["worst_m_r"], r_m)
    return m


def _step_orc(state, env):
    """The O arm: the real row, recorded. After a hand act, a shadow."""
    m = _root_mark(state, env.tick)
    if state.get("mode") == "shadow":
        return _care_step(state, env)
    row, tick, now = env.row, env.tick, env.now
    side = state["side"]
    sign = pricing.d(side)
    edit_at = _last_edit_at(env.meta)
    if edit_at and edit_at != (state.get("hand_edit_at") or ""):
        state["hand_edit_at"] = edit_at
        _to_shadow(state, "edit", now, replay=env.meta.get("paper_replay"))
        env.facts.append((hand_line("edit", now), {"hand": "edit"}))
        return _care_step(state, env)
    _missed(state, now)
    if env.ctx is not None:
        # the context its shadow will run the care with after a hand act
        # (else the tail ran a manual idea on the bot's rules)
        state["ctx"] = {k: env.ctx.get(k) for k in CTX_KEYS}
    care = env.meta.get("care") if isinstance(env.meta.get("care"),
                                              dict) else {}
    soft, stop = _f(care.get("soft_stop")), _f(row.stop_loss)
    path = list(state.get("path") or [])
    point = [_iso(now), soft, stop]
    if not path or path[-1][1:] != point[1:]:
        path.append(point)
        state["path"] = path[-STOP_PATH_MAX:]
    if env.cared in ("closed", "attempted") and not state.get("pending_exit"):
        state["pending_exit"] = {
            **_tick_dict(tick),
            "why": str(env.meta.get("care_exit") or care.get("exit")
                       or "the care")}
    so = env.meta.get("scale_out") if isinstance(env.meta.get("scale_out"),
                                                 dict) else {}
    if so and care.get("scaled_out") and not state.get("scale_seen") \
            and not any(b.get("why") == "scale-out before birth"
                        for b in state.get("banked") or []):
        state["scale_seen"] = True
        state.setdefault("banked", []).append({
            "qty": _f(so.get("qty")),
            "px": pricing.market_exit_px(tick, side, state["cf"]),
            "at": _iso(now), "why": "scale-out"})
        state["qty_open"] = _f(row.qty)
    target = _f(row.take_profit)
    if state.get("crossed") is None and (
            (stop is not None and sign * (tick.p - stop) <= 0)
            or (target is not None and sign * (tick.p - target) >= 0)):
        state["crossed"] = _tick_dict(tick)
    ghost = env.care_state
    if ghost is not None:
        faith = dict(state.get("faith") or {})
        faith["ticks"] = int(faith.get("ticks") or 0) + 1
        # the hook sees the row before the engine's knobs move it
        g_soft, g_venue = _f(ghost.get("soft_stop")), _f(
            env.care_venue_at_hook if env.care_venue_at_hook is not None
            else ghost.get("venue_stop"))
        soft_off = not _same(g_soft, soft)
        venue_off = not _same(g_venue, stop)
        faith["soft_mismatch"] = int(faith.get("soft_mismatch") or 0) + \
            int(soft_off)
        faith["venue_mismatch"] = int(faith.get("venue_mismatch") or 0) + \
            int(venue_off)
        faith["differ"] = int(faith.get("differ") or 0) + int(
            soft_off or venue_off)
        if (soft_off or venue_off) and not faith.get("first"):
            faith["first"] = {"at": _iso(now), "ghost": g_soft
                              if soft_off else g_venue,
                              "care": soft if soft_off else stop,
                              "what": "soft" if soft_off else "venue"}
        state["faith"] = faith
        if not state.get("first_divergence"):
            mine = _tighter(sign, soft, stop)
            theirs = _tighter(sign, g_soft, g_venue)
            if mine is not None and theirs is not None \
                    and not _same(mine, theirs):
                state["first_divergence"] = {
                    "kind": DIVERGE_REDUCE if sign * (mine - theirs) > 0
                    else DIVERGE_HOLD, "at": _iso(now)}
    _basis_sample(state, env, m)
    state["last"] = {**_tick_dict(tick), "soft": soft, "venue_stop": stop,
                     "qty": _f(row.qty)}
    state["last_care"] = dict(care)
    state["last_stop"], state["last_target"] = stop, target
    return None


def _basis_sample(state, env, m) -> None:
    """Once an hour, the mark less the last 1h platform close, while the
    venue holds no 1h frame (the menu's basis fallback reads them). The
    1h frame is read here (memoised per pass), whatever the playbook arm
    read this tick: the samples are hourly from the birth, so the menu is
    measured by the time T-STRUCT needs it."""
    last = _parse(state.get("basis_at"))
    if last is not None and env.now - last < timedelta(hours=1):
        return
    f = env.frame("1h")
    if f is None or f.venue or not f.last_close:
        return
    xs = list(state.get("basis") or [])
    xs.append(round(m - f.last_close, 10))
    from bot_program.orcs.constants import BASIS_SAMPLES
    state["basis"] = xs[-BASIS_SAMPLES * 3:]
    state["basis_at"] = _iso(env.now)


# ── the multi-ghost ──────────────────────────────────────────────────────

def _policy_bar(state, bar, a_j, k, *, entry_bar=False):
    """One bar of a simulate.EXIT_POLICIES arm, the proving ground's
    discipline (simulate.simulate's loop): gaps at the open, a tie to the
    stop, the target, then the clock and the locks at the close, binding
    from the next bar. Returns an exit or None."""
    from backtester.proving.simulate import EXIT_POLICIES, _locks
    from bot_program.position_care import market_hours
    policy = EXIT_POLICIES[state["policy"]]
    side, cf = state["side"], state["cf"]
    sign = pricing.d(side)
    entry, rpu = float(state["entry"]), float(state["rpu"])
    soft, target = _f(state.get("soft")), _f(state.get("target"))
    o, h, lo, c = bar["open"], bar["high"], bar["low"], bar["close"]
    at = bar["end"]
    if not entry_bar:
        if soft is not None and sign * (o - soft) <= 0:
            return _exit("gap", pricing.level_exit_px(o, side, cf), bar["ts"],
                         f"a gap through its {state.get('soft_why')}",
                         level=o, reason=f"gap {state.get('soft_why')}")
        if target is not None and sign * (o - target) >= 0:
            return _exit("target", pricing.target_exit_px(target, side, cf),
                         bar["ts"], "a gap through its target", level=o,
                         reason="gap target")
    adverse = lo if sign > 0 else h
    favour = h if sign > 0 else lo
    if soft is not None and sign * (adverse - soft) <= 0:
        return _exit("stop", pricing.level_exit_px(soft, side, cf), at,
                     f"its {state.get('soft_why')} at {soft:g}", level=soft,
                     reason=str(state.get("soft_why")))
    if target is not None and sign * (favour - target) >= 0:
        return _exit("target", pricing.target_exit_px(target, side, cf), at,
                     f"its target at {target:g}", level=target,
                     reason="target")
    state["mfe"] = max(_f(state.get("mfe")) or 0.0,
                       sign * (favour - entry) / rpu)
    ext = _f(state.get("extreme")) or entry
    state["extreme"] = max(ext, favour) if sign > 0 else min(ext, favour)
    held = market_hours(_parse(state.get("since")), at,
                        state.get("asset_class"))
    r_now = sign * (c - entry) / rpu
    if held >= k["no_progress_h"] and state["mfe"] < k["be_at"] \
            and r_now < k["no_progress_max"]:
        return _exit("no progress", pricing.market_exit_px(
            pricing.Tick(at=at, p=c), side, cf), at,
            f"no progress: {held:.0f} market hours, best "
            f"{state['mfe']:+.2f}R", level=c, reason="no progress")
    for lvl, why in _locks(policy, k, sign, entry, rpu, state["mfe"],
                           a_j if a_j is not None else float("nan"),
                           state["extreme"], None):
        if soft is None or sign * (lvl - soft) > 0:
            soft = lvl
            state["soft"], state["soft_why"] = lvl, why
    return None


def _policy_walk(state, frame, now, *, cap=None):
    """Every FINAL 4h bar of `frame` (bars.final_bar) that opens at or
    after the arm's `bar_at` (its seed, then the end of the last bar it
    walked): forward only, never a bar from before its birth."""
    from backtester.proving.families import atr as fam_atr
    from backtester.proving.simulate import _engine_constants
    from bot_program.orcs.bars import final_end, span_of
    if not _f(state.get("rpu")):
        # a row with no stop has no R: the policy has no unit to walk in
        # and its R is never measured; resolved at once, flat (2026-10-22)
        return _exit("no R", _f(state.get("entry")) or 0.0, now,
                     "no R: the row has no stop")
    if frame is None or frame.df is None or not len(frame.df):
        return None
    k = _engine_constants(state.get("asset_class"))
    a = fam_atr(frame.df).to_numpy()
    span = span_of(frame.tf)
    # FINAL bars only (2026-10-22): a bar that just ended is a snapshot
    # until the refresh rewrites it, and a walked bar is never walked again
    last_final = final_end(frame, now)
    if last_final is None:
        return None
    after = _parse(state.get("bar_at"))
    ceiling = _parse(state.get("ceiling"))
    df = frame.df
    for i, (ts, row) in enumerate(zip(df.index, df.itertuples())):
        t = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt_tz.utc)
        end = t + span
        if end > last_final:
            break
        if after is not None and t < after:
            continue
        bar = {"ts": t, "end": end, "open": float(row.open),
               "high": float(row.high), "low": float(row.low),
               "close": float(row.close)}
        a_j = float(a[i]) if a[i] == a[i] else None
        first = bool(state.get("entry_bar"))
        state["entry_bar"] = False
        out = _policy_bar(state, bar, a_j, k, entry_bar=first)
        state["bar_at"] = _iso(end)
        _note_source(state, frame.source)
        if out:
            return out
        if ceiling is not None and end >= ceiling:
            return _exit("time", pricing.market_exit_px(
                pricing.Tick(at=end, p=bar["close"]), state["side"],
                state["cf"]), end, "the config's time stop")
        if cap is not None and end >= cap:
            out = _exit("tail cap", pricing.market_exit_px(
                pricing.Tick(at=end, p=bar["close"]), state["side"],
                state["cf"]), end, "its tail cap", tail_capped=True)
            return out
    return None


def _step_policy(state, env):
    _missed(state, env.now)
    side, cf = state["side"], state["cf"]
    ceiling = _parse(state.get("ceiling"))
    if ceiling is not None and env.now >= ceiling:
        return _exit("time", pricing.market_exit_px(env.tick, side, cf),
                     env.now, "the config's time stop")
    out = _policy_walk(state, env.frame(MULTI_GHOST_TF), env.now)
    if out:
        return out
    sign = pricing.d(side)
    soft, target = _f(state.get("soft")), _f(state.get("target"))
    p = env.tick.p
    if soft is not None and sign * (p - soft) <= 0:
        return _exit("stop", pricing.stop_exit_px(soft, env.tick, side, cf),
                     env.now, f"its {state.get('soft_why')} at {soft:g}")
    if target is not None and sign * (p - target) >= 0:
        return _exit("target", pricing.target_exit_px(target, side, cf),
                     env.now, f"its target at {target:g}")
    return None


STEPPERS = {ARM_CARE: _step_care, ARM_PLAYBOOK: _step_playbook,
            ARM_ORC: _step_orc,
            **{p: _step_policy for p in MULTI_GHOST_POLICIES}}
#: The care ghost first: the O arm compares the row against it.
ORDER = (ARM_CARE, ARM_PLAYBOOK, ARM_ORC) + MULTI_GHOST_POLICIES


def step_tick(orc, trade, *, bot, price, cared="", now=None,
              results=None) -> dict:
    """Every open arm of the idea, one tick, right after the real care: one
    read of the tracks and one bulk update. Never writes the row."""
    from django.utils import timezone

    from bot_program.orcs.models import OrcTrack
    p = _f(price)
    if not p or p <= 0:
        return {}
    open_ = [t for t in OrcTrack.objects.filter(orc_id=orc.pk) if t.open]
    if not open_:
        return {}
    ctx = getattr(trade, "_care_tick", None)
    ctx = ctx if isinstance(ctx, dict) else None
    now = (ctx or {}).get("now") or now or timezone.now()
    env = _Env(orc, trade, bot, tick_of(bot, trade, p, now), ctx, now,
               getattr(bot, "_tick_broker_cache", None), cared, results)
    by_arm = {t.arm: t for t in open_}
    o = by_arm.get(ARM_ORC)
    env.basis = list(((o.state or {}).get("basis") or [])) if o else None
    changed, closed = [], []
    for arm in ORDER:
        track = by_arm.get(arm)
        if track is None:
            continue
        state = copy.deepcopy(track.state or {})
        try:
            out = STEPPERS[arm](state, env)
        except Exception as e:  # noqa: BLE001 — one arm never stops another
            logger.warning("[orcs] Orc %s: the %s did not step: %s", orc.pk,
                           arm, e)
            continue
        if out:
            _close_track(track, state, out)
            closed.append(track)
        track.state = state
        changed.append(track)
    if changed:
        OrcTrack.objects.bulk_update(changed, [
            "state", "open", "exit_price", "exit_at", "exit_why", "exit_r",
            "mfe_r", "tail_capped"])
    if env.facts:
        from bot_program.orcs import journal
        for line, body in env.facts:
            try:
                journal.append(orc, "fact", line, author="operator",
                               body=body, fact=True,
                               fields={"hand_touched": True})
            except Exception as e:  # noqa: BLE001
                logger.warning("[orcs] Orc %s: hand act not journaled: %s",
                               orc.pk, e)
    if closed:
        _journal_exits(orc, trade, closed)
    return {"stepped": len(changed), "exited": [t.arm for t in closed]}


# ── the real exit ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RealExit:
    kind: str                 # care | engine_sl | engine_tp | venue_stop |
    #                           venue_target | paper_resting | time | hand |
    #                           kill | orc | other
    level: object = None
    at: object = None
    why: str = ""
    hand: str = ""            # the hand act's key (HAND_WORDS), or ""
    inferred: bool = False


def real_exit_of(orc, row) -> Optional[RealExit]:
    """How the root actually closed, from what the row recorded (the reason
    tags, care_exit, paper_exit, exit_fill_source, Orc.killed). None while
    it is open."""
    if row is None or row.status not in LEG_DONE_STATUSES:
        return None
    from bot_program.pending_closes import (EXIT_FILL_SOURCE_KEY,
                                            EXIT_SOURCE_VENUE_STOP,
                                            EXIT_SOURCE_VENUE_TARGET)
    from bot_program.scorecard import (HAND_CLOSE_TAG, HIT_TARGET,
                                       RECONCILED_TAG, STOPPED_OUT, TIME_STOP)
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    reason, outcome = row.reason or "", row.outcome or ""
    at = row.closed_at
    if orc.killed:
        return RealExit("kill", None, at, "the kill switch", "kill")
    if HAND_CLOSE_TAG in reason:
        return RealExit("hand", None, at, "a hand close", "hand_close")
    if RECONCILED_TAG in reason and outcome == "manual_close":
        return RealExit("hand", None, at, "a hand close in the broker's app",
                        "app_close", inferred=True)
    if isinstance(meta.get("orc_exit"), dict):
        return RealExit("orc", None, at, str(meta["orc_exit"].get("action")
                                             or "orc"))
    pe = meta.get("paper_exit")
    if isinstance(pe, dict) and _f(pe.get("level")) is not None:
        return RealExit("paper_resting", _f(pe["level"]), at,
                        f"a resting {pe.get('reason') or 'level'}")
    if meta.get("care_exit"):
        return RealExit("care", None, at, f"the care's {meta['care_exit']}")
    src = meta.get(EXIT_FILL_SOURCE_KEY)
    if src == EXIT_SOURCE_VENUE_STOP:
        return RealExit("venue_stop", _f(row.stop_loss), at,
                        "the venue's stop", inferred=True)
    if src == EXIT_SOURCE_VENUE_TARGET:
        return RealExit("venue_target", _f(row.take_profit), at,
                        "the venue's target", inferred=True)
    if outcome == TIME_STOP or "closed:TIME" in reason:
        return RealExit("time", None, at, "the config's time stop")
    venue = (not row.paper) and bool(meta.get("protected"))
    if outcome == STOPPED_OUT or "closed:SL" in reason:
        return RealExit("venue_stop" if venue else "engine_sl",
                        _f(row.stop_loss), at, "its stop")
    if outcome == HIT_TARGET or "closed:TP" in reason:
        return RealExit("venue_target" if venue else "engine_tp",
                        _f(row.take_profit), at, "its target")
    return RealExit("other", None, at, outcome or "an unread close",
                    inferred=True)


def _recovered_mark(row, state):
    """The mark a close was booked from: a paper exit's modelled fill taken
    back off (paper_fill_price), a live close's booked mark as it is."""
    px = _f(row.exit_price)
    if px is None:
        return None
    if row.paper:
        sign = pricing.d(state.get("side"))
        cf = _f(state.get("cf")) or 0.0
        return px / (1.0 - sign * cf / 2.0)
    return px


def price_real_exit(rx, state, row) -> Optional[float]:
    """The real exit priced by the one pricing function (§6.1), by kind."""
    side, cf = state.get("side"), _f(state.get("cf")) or 0.0
    last = _tick_from(state.get("last"))
    if rx.kind in ("care", "orc"):
        tick = _tick_from(state.get("pending_exit")) or last
        if tick is not None:
            return pricing.market_exit_px(tick, side, cf)
    if rx.kind in ("venue_stop", "engine_sl") and rx.level is not None:
        tick = _tick_from(state.get("crossed")) or last
        return pricing.stop_exit_px(rx.level, tick, side, cf)
    if rx.kind in ("venue_target", "engine_tp") and rx.level is not None:
        return pricing.target_exit_px(rx.level, side, cf)
    if rx.kind == "paper_resting" and rx.level is not None:
        return pricing.level_exit_px(rx.level, side, cf)
    mark = _recovered_mark(row, state)
    if mark is None:
        return None
    return pricing.market_exit_px(pricing.Tick(at=rx.at, p=mark), side, cf)


def _arm_stop(state, arm):
    sign = pricing.d(state.get("side"))
    if arm in MULTI_GHOST_POLICIES:
        return _f(state.get("soft"))
    return _tighter(sign, state.get("venue_stop"), state.get("soft_stop")
                    if state.get("paper") else None,
                    state.get("orc_stop"))


def _shares(rx, state, arm, row) -> bool:
    """Does the arm take the real row's mechanical event at the same price:
    a time stop at the same frozen ceiling, a stop or a target at a level
    equal to its own."""
    if rx.kind == "time":
        # the arm's ceiling was frozen from the same config at its seed: the
        # row's clock fired at it (a config changed since reads apart)
        ceiling = _parse(state.get("ceiling"))
        return (ceiling is not None and rx.at is not None
                and rx.at >= ceiling - timedelta(minutes=15))
    if rx.kind in ("venue_stop", "engine_sl"):
        return _same(_arm_stop(state, arm), rx.level)
    if rx.kind in ("venue_target", "engine_tp"):
        return _same(state.get("target"), rx.level)
    if rx.kind == "paper_resting":
        if _same(state.get("target"), rx.level):
            return True
        from bot_program import paper_exits
        stop, _target = paper_exits.levels(row, care_on=True)
        return _same(_arm_stop(state, arm), stop)
    return False


# ── after the row closes: the tail ───────────────────────────────────────

def add_market_hours(start, hours, asset_class):
    """The moment `hours` market hours after `start`, by the care's own
    clock (position_care.market_hours: the weekends of a market that shuts
    do not count)."""
    from bot_program.position_care import NEVER_SHUTS
    if start is None:
        return None
    if str(asset_class) in NEVER_SHUTS:
        return start + timedelta(hours=hours)
    from bot_program.position_care import market_hours
    t = start + timedelta(hours=hours)
    for _ in range(60):
        got = market_hours(start, t, asset_class)
        if got >= hours - 1e-6:
            return t
        t += timedelta(hours=hours - got)
    return t


def tail_cap(orc, row, now=None):
    """Bot ideas: the later of the root's close and birth + 1.5 x the
    class's no-progress hours (market hours); manual ideas: the root's
    close + 30 days (position_review_agent.GRADE_MAX_WAIT_DAYS)."""
    from bot_program.position_care import (NO_PROGRESS_DEFAULT_HOURS,
                                           NO_PROGRESS_HOURS)
    closed = getattr(row, "closed_at", None) or now
    if orc.manual:
        return closed + timedelta(days=TAIL_CAP_MANUAL_DAYS) if closed \
            else None
    limit = NO_PROGRESS_HOURS.get(str(orc.asset_class),
                                  NO_PROGRESS_DEFAULT_HOURS)
    cap = add_market_hours(orc.born_at, limit * TAIL_CAP_NO_PROGRESS_X,
                           orc.asset_class)
    if closed is None:
        return cap
    return max(closed, cap) if cap else closed


def _events_between(start, end):
    """The calendar rows the care's event window can reach over [start,
    end], as position_care.upcoming_events returns them."""
    try:
        from django.db.models import Q

        from bot_program.position_care import (EARNINGS_BEFORE_HOURS,
                                               EVENT_AFTER_MINUTES,
                                               EVENT_IMPACT, EVENT_SOURCES)
        from market_data.models import EconomicEvent
        qs = (EconomicEvent.objects
              .filter(datetime__gte=start - timedelta(
                  minutes=EVENT_AFTER_MINUTES),
                      datetime__lte=end + timedelta(
                          hours=EARNINGS_BEFORE_HOURS))
              .filter(Q(source__in=EVENT_SOURCES,
                        impact__iexact=EVENT_IMPACT)
                      | Q(title__icontains="earnings"))
              .order_by("datetime")
              .values("datetime", "title", "currency_affected"))
        return [{"at": r["datetime"], "title": str(r["title"] or ""),
                 "currency": str(r["currency_affected"] or "").upper(),
                 "earnings": "earnings" in str(r["title"] or "").lower()}
                for r in qs]
    except Exception:  # noqa: BLE001 — no calendar, no window
        return []


def _tail_bar(state, bar, *, base_meta, events, cap):
    """One complete 1h bar for a care-like arm after the row closed."""
    from bot_program.position_care import event_for, plan
    side, cf = state["side"], state["cf"]
    sign = pricing.d(side)
    o, h, lo, c = bar["open"], bar["high"], bar["low"], bar["close"]
    stop = _tighter(sign, state.get("venue_stop"), state.get("soft_stop"),
                    state.get("orc_stop"))
    target = _f(state.get("target"))
    if stop is not None and sign * (o - stop) <= 0:
        return _exit("gap", pricing.level_exit_px(o, side, cf), bar["ts"],
                     "a gap through its stop")
    if target is not None and sign * (o - target) >= 0:
        return _exit("target", pricing.target_exit_px(target, side, cf),
                     bar["ts"], "a gap through its target")
    adverse = lo if sign > 0 else h
    favour = h if sign > 0 else lo
    if stop is not None and sign * (adverse - stop) <= 0:
        return _exit("stop", pricing.level_exit_px(stop, side, cf),
                     bar["end"], f"its stop at {stop:g}")
    if target is not None and sign * (favour - target) >= 0:
        return _exit("target", pricing.target_exit_px(target, side, cf),
                     bar["end"], f"its target at {target:g}")
    # the bar's extreme first, then plan() at its close: a lock it moves
    # binds from the next bar
    peak, worst = _f(state.get("peak")), _f(state.get("worst"))
    if peak is not None:
        state["peak"] = max(peak, favour) if sign > 0 else min(peak, favour)
    if worst is not None:
        state["worst"] = min(worst, adverse) if sign > 0 \
            else max(worst, adverse)
    # the context the tick last gave the arm, else the row's own: a calm
    # posture, a neutral kind, its world, ITS LANE (a hand ticket is never
    # cut on the bot's clock), no scale-out
    ctx = state.get("ctx") or {
        "posture_level": "calm", "kind": "neutral",
        "live": not state.get("paper"), "manual": bool(state.get("manual")),
        "scale": False}
    shadow = shadow_of(state, base_meta=base_meta)
    event = event_for(shadow, bar["end"], events)
    decision = plan(shadow, c, now=bar["end"],
                    posture_level=ctx.get("posture_level", "calm"),
                    kind=ctx.get("kind", "neutral"),
                    live=bool(ctx.get("live", not state.get("paper"))),
                    manual=bool(ctx.get("manual", state.get("manual"))),
                    crowd=None, scale=bool(ctx.get("scale")), event=event)
    care = dict(decision.get("care") or {})
    why = str(care.pop("exit", "") or "its soft stop")
    _take_care(state, care)
    tick = pricing.Tick(at=bar["end"], p=c)
    if decision.get("action") == "close":
        return _exit("care", pricing.market_exit_px(tick, side, cf),
                     bar["end"], f"the care's {why}")
    if decision.get("scale_out") and state.get("paper") and ctx.get("scale"):
        if _bank(state, shadow, tick, bar["end"]):
            state["scaled_out"] = True
    if not state.get("paper") and state.get("protected"):
        _mirror(state, c, extra=state.get("orc_stop"))
    _engine_knobs(state, None, c)
    ceiling = _parse(state.get("ceiling"))
    if ceiling is not None and bar["end"] >= ceiling:
        return _exit("time", pricing.market_exit_px(tick, side, cf),
                     bar["end"], "the config's time stop")
    if cap is not None and bar["end"] >= cap:
        return _exit("tail cap", pricing.market_exit_px(tick, side, cf),
                     bar["end"], "its tail cap", tail_capped=True)
    return None


def _best_on_bar(o_state, bar) -> None:
    sign = pricing.d(o_state.get("side"))
    entry, rpu = _f(o_state.get("entry")), _f(o_state.get("rpu"))
    if not entry or not rpu:
        return
    favour = bar["high"] if sign > 0 else bar["low"]
    m = favour - sign * pricing.half_spread(favour, o_state.get("cf") or 0)
    r = sign * (m - entry) / rpu
    o_state["best_m_r"] = r if o_state.get("best_m_r") is None \
        else max(o_state["best_m_r"], r)
    o_state["best_bar_at"] = _iso(bar["end"])


def _rx_source(row):
    """The bar source of the real row's resting-level exit (its paper
    replay's hit), or None."""
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    pe = meta.get("paper_exit")
    return pe.get("source") if isinstance(pe, dict) else None


def _tail_tstruct(state, bar, *, symbol, asset_class, basis, cache):
    """THE PLAYBOOK ARM'S STRUCTURE TRAIL AFTER THE ROW CLOSED (2026-10-22):
    at the close of each bar of its trail timeframe, T-STRUCT on the menu
    as it stood at that close, every frame CUT there (bars.frame `until`:
    no bar that closed later, no look-ahead); a stop it moves binds from
    the next bar, as on the tick (_playbook_bars)."""
    from bot_program.orcs import menu as menus
    from bot_program.orcs import playbook
    from bot_program.orcs.bars import frame
    mfe = _f(state.get("mfe_r"))
    if mfe is None or mfe < playbook.STRUCTURE_FROM_R:
        return
    end = bar["end"]
    f = frame(symbol, playbook.trail_tf(mfe), asset_class=asset_class,
              now=end, until=end, cache=cache)
    if f is None or not f.fresh or f.newest_end != end:
        return                # no bar of the trail timeframe closed here
    if end.isoformat() == state.get("tstruct_bar"):
        return
    state["tstruct_bar"] = end.isoformat()
    sign = pricing.d(state["side"])
    m = pricing.closing_mark(pricing.Tick(at=end, p=bar["close"]),
                             state["side"], state["cf"])
    mn = menus.symbol_levels(symbol, asset_class, now=end, mark=m,
                             cache=cache, basis_samples=basis, until=end)
    rows = menus.for_idea(mn, side=state["side"], entry=state["entry"],
                          risk_per_unit=state["rpu"], mark=m,
                          care_state=state, cf=state["cf"])
    eff = _tighter(sign, state.get("soft_stop"), state.get("venue_stop"),
                   state.get("orc_stop"))
    ts = playbook.t_struct(rows, side=state["side"], mfe_r=mfe,
                           p=bar["close"], m=m, effective=eff, atr=mn.atr)
    if ts:
        state["orc_stop"] = ts["stop"]
        state["orc_why"] = f"T-STRUCT {ts['level_id']}"
        _note_source(state, mn.source)


def _tail_x_thesis(state, bar, *, orc, row, since_birth, meta, cache):
    """THE PLAYBOOK ARM'S THESIS EXIT AFTER THE ROW CLOSED (2026-10-22), at
    each tail bar's close, as on the tick (_step_playbook): the thesis's
    bar predicates read on frames CUT at the bar's end (only a frame whose
    newest bar closes there: no bar that closed later), from the birth
    (forward only), or the thesis check's fresh "exit". Returns an exit or
    None."""
    from bot_program.orcs import playbook, predicates
    from bot_program.orcs.bars import frame
    end = bar["end"]
    tick = pricing.Tick(at=end, p=bar["close"])
    results = []
    for pred in (orc.thesis or {}).get("invalidation") or []:
        if not isinstance(pred, dict) \
                or pred.get("kind") not in (predicates.BOS, predicates.CLOSE):
            continue
        tf = str(pred.get("tf") or predicates.DEFAULT_TF)
        f = frame(row.symbol, tf, asset_class=row.asset_class, now=end,
                  until=end, cache=cache)
        if f is None or f.newest_end != end:
            continue              # no bar of that timeframe closed here
        # the tail walks final bars only: the bar closing here is final too
        results.append(predicates.evaluate(
            pred, frames={tf: f}, side=row.side, asset_class=row.asset_class,
            start=since_birth, mfe_r=None, now=end + BAR_FINAL_AFTER,
            symbol=row.symbol, mark=bar["close"]))
    xt = playbook.x_thesis(meta.get("thesis"), results, end)
    if xt:
        return _exit("playbook", pricing.market_exit_px(tick, state["side"],
                                                        state["cf"]),
                     end, f"X-THESIS: {xt['why']}")
    return None


def _tail_k_draw(state, bar, *, row, meta, cache) -> None:
    """K-DRAW after the row closed, on paper, at each 4h close (the frame
    cut at the bar's end), as on the tick (_playbook_bars)."""
    from bot_program.orcs.bars import frame
    if not state.get("paper"):
        return
    end = bar["end"]
    f4 = frame(row.symbol, "4h", asset_class=row.asset_class, now=end,
               until=end, cache=cache)
    if f4 is None or not f4.venue or f4.newest_end != end \
            or end.isoformat() == state.get("kdraw_bar"):
        return
    state["kdraw_bar"] = end.isoformat()
    # the tail walks final bars only: the 4h bar closing here is final too
    _k_draw(state, f4, symbol=row.symbol,
            tick=pricing.Tick(at=end, p=bar["close"]), now=end, meta=meta,
            final_at=end + BAR_FINAL_AFTER)


def _cap_mark(row, o_state, cap):
    """The price an arm still open past its cap is marked at: the close of
    the newest stored 1h bar that opened at or before the cap (the bar
    that spans it, else the last before it), unless the O arm's last tick
    is newer; then that tick; then the row's exit, then the entry."""
    from bot_program.orcs.bars import complete_bars_after, span_of
    last = (o_state or {}).get("last") or {}
    tick = _tick_from(last)
    got, _source = complete_bars_after(row.symbol, TAIL_TF, None,
                                       cap + span_of(TAIL_TF), newest=True,
                                       limit=1)
    if got and (tick is None or tick.at is None
                or got[-1]["end"] >= tick.at):
        return got[-1]["close"]
    if tick is not None:
        return tick.p
    return _f(row.exit_price) or _f((o_state or {}).get("entry"))


def step_bars(orc, *, now=None) -> dict:
    """The track_ghosts body for one idea, once its row is closed or
    cancelled: idempotent and catch-up safe (each arm keeps the end of the
    last bar it walked).

    ONE WRITER PER PHASE (2026-10-22). While the row is open the tick
    alone steps the arms (step_tick; the multi-ghost walks every 4h bar it
    missed there): this reads no track and writes nothing. The two used to
    read and bulk-write the same arms with no lock, and a tick landing
    between this read and its write was lost.

    EVERY IDEA ENDS (2026-10-22). Each arm walks on its own: one that
    raises is logged and left where it stood, never the others. Past the
    cap, whatever is still open is marked and closed (below), so no idea
    outlives its cap by more than a bar, and none holds a bar request for
    ever."""
    from django.utils import timezone

    from bot_program.models import AssetBotTrade
    from bot_program.orcs.bars import complete_bars_after, frame
    from bot_program.orcs.models import OrcTrack
    now = now or timezone.now()
    row = AssetBotTrade.objects.filter(pk=orc.root_trade_id).first()
    if row is None or row.status not in LEG_DONE_STATUSES:
        return {"stepped": 0}
    tracks = list(OrcTrack.objects.filter(orc=orc))
    if not any(t.open for t in tracks):
        return {"stepped": 0}
    # an O1a care track (no `cf`) on an Orc that died before the census
    # upgraded it: brought to the arms' format here, in place
    upgrade_old(orc, row, tracks, now=now)
    by = {t.arm: t for t in tracks}
    states = {t.arm: copy.deepcopy(t.state or {}) for t in tracks}
    closed_now, facts = [], []

    def fenced(arm, step):
        """One arm's step; on a raise its state is put back as it stood
        and the arm waits (the cap below closes it in the end)."""
        saved = copy.deepcopy(states[arm])
        try:
            return True, step()
        except Exception as e:  # noqa: BLE001 — one arm never stops another
            # in place: the O arm's state is also read through `os_`
            states[arm].clear()
            states[arm].update(saved)
            logger.warning("[orcs] Orc %s: the %s did not walk its bars: "
                           "%s", orc.pk, arm, e)
            return False, None

    if row.status == "CANCELED":
        # never filled: no position, nothing to grade but a flat line
        for t in tracks:
            if t.open:
                entry = _f(states[t.arm].get("entry")) or 0.0
                _close_track(t, states[t.arm], _exit(
                    "cancelled", entry, row.closed_at or now,
                    "the order was cancelled before it filled"))
                closed_now.append(t)
    else:
        rx = real_exit_of(orc, row)
        o = by.get(ARM_ORC)
        os_ = states.get(ARM_ORC)
        px = price_real_exit(rx, os_, row) if (rx and os_) else None
        if o is not None and o.open and os_.get("mode") == "real" and rx:
            if rx.hand:
                _to_shadow(os_, rx.hand, rx.at or now)
                facts.append((hand_line(rx.hand, rx.at or now),
                              {"hand": rx.hand}, "operator"))
            elif px is not None:
                if rx.kind == "paper_resting":
                    _note_source(os_, _rx_source(row))
                _close_track(o, os_, _exit(rx.kind, px, rx.at or now,
                                           rx.why, inferred=rx.inferred))
                closed_now.append(o)
        if rx and not rx.hand and px is not None:
            for arm in (ARM_CARE, ARM_PLAYBOOK) + MULTI_GHOST_POLICIES:
                t = by.get(arm)
                if t is None or not t.open or states[arm].get("shared"):
                    continue
                states[arm]["shared"] = True
                if _shares(rx, states[arm], arm, row):
                    if rx.kind == "paper_resting":
                        # the replay's bar is this arm's evidence too
                        _note_source(states[arm], _rx_source(row))
                    _close_track(t, states[arm], _exit(
                        rx.kind, px, rx.at or now,
                        f"the same event as the row: {rx.why}"))
                    closed_now.append(t)
        cap = tail_cap(orc, row, now)
        base_meta = row.metadata if isinstance(row.metadata, dict) else {}
        # the policies on their 4h bars
        f4 = frame(row.symbol, MULTI_GHOST_TF, asset_class=row.asset_class,
                   now=now)
        for arm in MULTI_GHOST_POLICIES:
            t = by.get(arm)
            if t is None or not t.open:
                continue
            _ok, out = fenced(arm, lambda arm=arm: _policy_walk(
                states[arm], f4, now, cap=cap))
            if out:
                _close_track(t, states[arm], out)
                closed_now.append(t)
        # the care-like arms on 1h bars, and the O arm's best mark until the
        # last arm is out. AN ARM'S FIRST TAIL BAR OPENS AT OR AFTER ITS
        # LAST TICK: the bar holding that tick was stepped on its marks,
        # and its open and extremes came before the levels that tick set
        # (a lock binds from the next bar, §6.1)
        starts = {}
        for arm in CARE_LIKE:
            if arm not in by:
                continue
            starts[arm] = (_parse(by[arm].last_bar_at)
                           or _parse(states[arm].get("last_tick_at"))
                           or row.closed_at or now)
        best_after = _parse((os_ or {}).get("best_bar_at"))
        since = min(list(starts.values()) + (
            [best_after] if best_after else []), default=None)
        bars, source = complete_bars_after(row.symbol, TAIL_TF, since, now,
                                           final=True)
        events = _events_between(bars[0]["ts"], bars[-1]["end"]) \
            if bars else []
        policy_out = [_parse(by[a].exit_at) for a in MULTI_GHOST_POLICIES
                      if a in by and not by[a].open and by[a].exit_at]
        basis = list((os_ or {}).get("basis") or []) or None
        menus_cache = {}
        opened = row.opened_at or orc.born_at
        since_birth = max(t for t in (opened, orc.born_at) if t is not None) \
            if (opened or orc.born_at) else None
        stuck = set()
        for bar in bars:
            any_open = False
            for arm in CARE_LIKE:
                t = by.get(arm)
                if t is None or not t.open or arm in stuck:
                    continue
                if arm == ARM_ORC and states[arm].get("mode") == "real":
                    continue
                after = _parse(t.last_bar_at)
                if after is not None and bar["end"] <= after:
                    any_open = True
                    continue
                if after is None and bar["ts"] < starts[arm]:
                    continue
                any_open = True

                def walk(arm=arm, t=t):
                    out = _tail_bar(states[arm], bar, base_meta=base_meta,
                                    events=events, cap=cap)
                    if out or arm != ARM_PLAYBOOK:
                        return out
                    out = _tail_x_thesis(states[arm], bar, orc=orc, row=row,
                                         since_birth=since_birth,
                                         meta=base_meta, cache=menus_cache)
                    if out:
                        return out
                    try:
                        _tail_tstruct(states[arm], bar, symbol=row.symbol,
                                      asset_class=row.asset_class,
                                      basis=basis, cache=menus_cache)
                    except Exception as e:  # noqa: BLE001 — a bar's wait
                        logger.info("[orcs] Orc %s: the tail's structure "
                                    "trail unread: %s", orc.pk, e)
                    _tail_k_draw(states[arm], bar, row=row, meta=base_meta,
                                 cache=menus_cache)
                    return None
                ok, out = fenced(arm, walk)
                if not ok:
                    stuck.add(arm)
                    continue
                t.last_bar_at = bar["end"]
                _note_source(states[arm], source)
                if out:
                    _close_track(t, states[arm], out)
                    closed_now.append(t)
            policy_open = any(by[a].open for a in MULTI_GHOST_POLICIES
                              if a in by) or any(
                e is not None and bar["ts"] < e for e in policy_out)
            if os_ is not None and (any_open or policy_open):
                ba = _parse(os_.get("best_bar_at"))
                if ba is None or bar["end"] > ba:
                    _best_on_bar(os_, bar)
        if cap is not None and now >= cap:
            _close_past_cap(tracks, states, closed_now, rx=rx, row=row,
                            os_=os_, cap=cap, now=now)
    for t in tracks:
        t.state = states[t.arm]
    OrcTrack.objects.bulk_update(tracks, [
        "state", "open", "exit_price", "exit_at", "exit_why", "exit_r",
        "mfe_r", "tail_capped", "last_bar_at"])
    if facts:
        from bot_program.orcs import journal
        for line, body, author in facts:
            try:
                journal.append(orc, "fact", line, author=author, body=body,
                               fact=True, fields={"hand_touched": True})
            except Exception as e:  # noqa: BLE001
                logger.warning("[orcs] Orc %s: hand act not journaled: %s",
                               orc.pk, e)
    if closed_now:
        _journal_exits(orc, row, closed_now)
    return {"stepped": len(tracks), "exited": [t.arm for t in closed_now]}


def _close_past_cap(tracks, states, closed_now, *, rx, row, os_, cap,
                    now) -> None:
    """THE CAP (2026-10-22). An arm still open is marked by its own walk at
    the close of the bar that spans its cap (_tail_bar's and _policy_walk's
    `end >= cap`), so this waits one bar of the arm's timeframe past the
    cap (and the refresh's pass that makes it final), then marks what is
    still open (no bar came, or the arm could not walk) at _cap_mark,
    never at the price the row closed at while a stored bar is newer. An O arm still recording a real exit nobody
    priced (the row's exit price unknown) is closed at the cap on its last
    tick, flagged inferred."""
    from bot_program.orcs.bars import span_of
    mark = None
    for t in tracks:
        if not t.open:
            continue
        st = states[t.arm]
        if t.arm == ARM_ORC and st.get("mode") == "real":
            tick = _tick_from(st.get("last"))
            px = (pricing.market_exit_px(tick, st["side"],
                                         st.get("cf") or 0.0)
                  if tick is not None else _f(st.get("entry")))
            if px is None:
                continue
            _close_track(t, st, _exit(
                "unpriced", px, (rx.at if rx else None) or row.closed_at
                or cap, "the row's exit was never priced: its last tick",
                inferred=True))
            closed_now.append(t)
            continue
        tf = MULTI_GHOST_TF if t.arm in MULTI_GHOST_POLICIES else TAIL_TF
        if now < cap + span_of(tf) + BAR_FINAL_AFTER:
            continue
        if mark is None:
            mark = _cap_mark(row, os_, cap)
        if mark is None:
            continue
        _close_track(t, st, _exit(
            "tail cap", pricing.market_exit_px(
                pricing.Tick(at=cap, p=mark), st["side"],
                st.get("cf") or 0.0), cap, "its tail cap",
            tail_capped=True))
        closed_now.append(t)


# ── the readers ──────────────────────────────────────────────────────────

def compare_line(tracks) -> dict:
    """{orc_r, care_r, t}: the O arm against the care ghost, closed or not
    (an open arm reads its last R)."""
    by = {t.arm: t for t in tracks or ()}

    def r_of(t):
        if t is None:
            return None
        if not t.open:
            return t.exit_r
        st = t.state or {}
        if t.arm == ARM_ORC:
            last = st.get("last") or {}
            tick = _tick_from(last)
            if tick is None:
                return None
            return arm_r(st, pricing.closing_mark(tick, st.get("side"),
                                                  st.get("cf") or 0))
        return _f(st.get("r_now"))
    return {"orc_r": r_of(by.get(ARM_ORC)), "care_r": r_of(by.get(ARM_CARE)),
            "t": _iso(max((t.exit_at for t in tracks or () if t.exit_at),
                          default=None))}


def faithfulness(orc) -> dict:
    """The care ghost against the care (§6.1): the O arm's tick counts, its
    first mismatch, and the two exits."""
    from bot_program.orcs.models import OrcTrack
    by = {t.arm: t for t in OrcTrack.objects.filter(orc=orc)}
    o, g = by.get(ARM_ORC), by.get(ARM_CARE)
    faith = dict(((o.state or {}).get("faith") if o else None) or {})
    out = {"ticks": int(faith.get("ticks") or 0),
           "differed": int(faith.get("differ") or 0),
           "first": faith.get("first"),
           "ghost_exit": (g.exit_why if g and not g.open else None),
           "real_exit": (o.exit_why if o and not o.open else None),
           "ghost_r": g.exit_r if g and not g.open else None,
           "orc_r": o.exit_r if o and not o.open else None,
           "hand": (o.state or {}).get("hand") if o else None,
           "mirror_refused": int(((g.state or {}) if g else {}).get(
               "mirror_refused") or 0)}
    out["matched"] = (out["differed"] == 0 and out["ghost_r"] is not None
                      and out["orc_r"] is not None
                      and math.isclose(out["ghost_r"], out["orc_r"],
                                       abs_tol=1e-9))
    return out


def faith_line(f) -> str:
    from bot_program.orcs.facts import _hhmm
    if f.get("differed"):
        first = f.get("first") or {}
        return (f"Faithfulness: the care ghost differed on {f['differed']} "
                f"of {f['ticks']} ticks, first at {_hhmm(first.get('at'))} "
                f"UTC (ghost {first.get('ghost')}, care {first.get('care')}).")
    if f.get("matched"):
        return (f"Faithfulness: the care ghost matched the care on "
                f"{f['ticks']} ticks and exited with it "
                f"({f.get('ghost_exit') or 'its exit'}).")
    return (f"Faithfulness: the care ghost matched the care on {f['ticks']} "
            f"ticks; the exits differ (ghost: {f.get('ghost_exit') or 'open'}"
            f"; the row: {f.get('real_exit') or 'open'}).")


# keep the seeds' names importable where the census reads them
__all__ = ["seed_tracks", "step_tick", "step_bars", "real_exit_of",
           "price_real_exit", "compare_line", "faithfulness", "ShadowRow",
           "SEED_BIRTH", "SEED_ADOPT", "SEED_LATE"]
