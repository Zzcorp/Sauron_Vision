"""HORIZON — the 5-10 year sector synthesis (2026-09-12).

The operator's ask: "syntheses of sectors and their development over
5-10 years, to guard against those risks." Every other agent on the
platform looks hours to weeks ahead. This one looks years ahead, once a
month, on the frontier tier, and is held to account exactly like the
rest: no prose without a gradable claim. Each sector thesis ends in
direction calls at 6 and 12 months (4380 h / 8760 h) that the existing
calibration resolver grades against the first bar at or after the
deadline, and the agent's Brier score and trust adjustment are built
from those grades like every other agent's.

What reads it: the share allocator (bot_program.share_allocator
.horizon_for) folds the asset-class tilt in as a FIFTH factor, 5% per
tilt point scaled by confidence — ±10% at most. A weak prior by
construction: a structural view must never out-vote graded evidence.

Deterministic-first persistence (the position reviewer's precedent): the
HorizonView row is written BEFORE the model call; on success it is
filled; on a garbled answer it is `rejected` with the raw text kept (the
operator paid for it and gets to read it); on a provider error it is
`error`. A garbled answer is an error row, never a view.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# ── The universe ─────────────────────────────────────────────────────────
# (key, name, symbol) — US sector ETFs and the platform's own catalogue
# spellings. The key is the vocabulary the model must answer in; a sector
# key outside this list is a parse error, not a new sector.
HORIZON_UNIVERSE = [
    ("technology", "Technology", "XLK"),
    ("energy", "Energy", "XLE"),
    ("financials", "Financials", "XLF"),
    ("health", "Health care", "XLV"),
    ("industrials", "Industrials", "XLI"),
    ("consumer_discretionary", "Consumer discretionary", "XLY"),
    ("consumer_staples", "Consumer staples", "XLP"),
    ("utilities", "Utilities", "XLU"),
    ("materials", "Materials", "XLB"),
    ("real_estate", "Real estate", "XLRE"),
    ("communication", "Communication services", "XLC"),
    ("gold", "Gold", "GLD"),
    ("oil", "Oil", "USO"),
    ("bonds", "Long Treasuries", "TLT"),
    ("dollar", "US dollar", "UUP"),
    ("bitcoin", "Bitcoin", "BTCUSD"),
]
SECTOR_KEYS = {k for k, _n, _s in HORIZON_UNIVERSE}
SECTOR_NAMES = {k: n for k, n, _s in HORIZON_UNIVERSE}
# The catalogue holds GLD on some deployments and GLDM on others (the
# research fleet seeds GLDM). The snapshot prefers whichever Instrument
# row exists; GLD when neither does, so the universe is never silently
# one sector short.
GOLD_CANDIDATES = ("GLD", "GLDM")
HORIZON_ASSET_CLASSES = ("stock", "forex", "commodity", "crypto", "options",
                         "cfd")
HORIZON_YEARS = (5, 10)
# 6 and 12 months, in hours. The only horizons a call may carry.
CALL_HORIZONS_H = (4380, 8760)
# The clamp ceiling handed to the calibration — a year, for this agent
# only. Every other caller keeps DIRECTION_MAX_HORIZON_H (sixty days).
HORIZON_MAX_H = 8760
# Fewer daily bars than this and a 1y/3y return would be a guess: the
# snapshot says 'no daily history' instead of fabricating one.
MIN_DAILY_BARS = 200
# The oldest daily close a call may be measured from when no fresh
# mark exists: Friday's bar on a Monday (a long weekend, a holiday) is
# a reference; a close from a feed that died a month ago is not — the
# call would be measured from a price the market left long before the
# claim was made, and its grade would be noise (2026-09-12).
REFERENCE_MAX_AGE_DAYS = 7
RAW_KEEP_CHARS = 20000
AGENT_NAME = "horizon"


# ── Snapshot ─────────────────────────────────────────────────────────────

def _stamp(block: dict, newest=None) -> dict:
    """as_of / age_hours on every block: the model is told how old each
    number is, and a block whose data is a month stale says so itself."""
    now = timezone.now()
    block["as_of"] = now.isoformat()
    block["age_hours"] = (round((now - newest).total_seconds() / 3600, 1)
                          if newest is not None else None)
    return block


def _guarded(name: str, reader) -> dict:
    """Run one snapshot reader; a reader that raises yields a block that
    says so and the run proceeds. One dead table must not cost the month's
    synthesis — the strategy generator's snapshot has the same shape."""
    try:
        return reader()
    except Exception as e:  # noqa: BLE001 — the block degrades, the run goes on
        logger.warning("[horizon] snapshot block %s failed: %s", name, e)
        return _stamp({"error": f"{name} unreadable: {e}"[:300]})


def gold_symbol() -> str:
    from instruments.models import Instrument
    for sym in GOLD_CANDIDATES:
        if Instrument.objects.filter(symbol=sym).exists():
            return sym
    return GOLD_CANDIDATES[0]


def universe_symbols() -> dict:
    """{sector key: catalogue symbol} with the gold spelling resolved."""
    out = {}
    try:
        gold = gold_symbol()
    except Exception:  # noqa: BLE001 — no catalogue, the constant's spelling
        gold = GOLD_CANDIDATES[0]
    for key, _name, sym in HORIZON_UNIVERSE:
        out[key] = gold if key == "gold" else sym
    return out


def _return_from(bars, days: int):
    """Fractional return over `days` calendar days from a newest-first
    list of (timestamp, close), or None when the window is not covered."""
    if not bars:
        return None
    last_ts, last_px = bars[0]
    target = last_ts - timedelta(days=days)
    base = None
    for ts, px in bars:
        if ts <= target:
            base = px
            break
    if base is None or not base or not last_px:
        return None
    return round((float(last_px) - float(base)) / float(base), 4)


def _read_universe() -> dict:
    from instruments.models import Instrument
    from market_data.models import PriceData

    symbols = universe_symbols()
    rows, newest = [], None
    known = {i.symbol: i for i in Instrument.objects.filter(
        symbol__in=list(symbols.values()))}
    for key, name, _s in HORIZON_UNIVERSE:
        sym = symbols[key]
        inst = known.get(sym)
        row = {"key": key, "name": name, "symbol": sym,
               "in_catalogue": inst is not None,
               "asset_class": getattr(inst, "asset_class", None)}
        if inst is None:
            row["history"] = "not in the catalogue"
            rows.append(row)
            continue
        qs = (PriceData.objects.filter(instrument=inst, timeframe="1d")
              .order_by("-timestamp").values_list("timestamp", "close"))
        n = qs.count()
        if n < MIN_DAILY_BARS:
            row["history"] = "no daily history"
            row["daily_bars"] = n
            rows.append(row)
            continue
        bars = list(qs[:1200])
        row["daily_bars"] = n
        row["last_close"] = float(bars[0][1])
        row["last_bar"] = bars[0][0].isoformat()
        row["return_1y"] = _return_from(bars, 365)
        row["return_3y"] = _return_from(bars, 3 * 365)
        if newest is None or bars[0][0] > newest:
            newest = bars[0][0]
        rows.append(row)
    return _stamp({"sectors": rows}, newest)


def _read_macro() -> dict:
    from core.constants import FRED_SERIES
    from market_data.models import MacroIndicator, MacroObservation

    series, newest = {}, None
    by_id = {m.series_id: m for m in MacroIndicator.objects.filter(
        series_id__in=list(FRED_SERIES))}
    for sid, label in FRED_SERIES.items():
        ind = by_id.get(sid)
        obs = (MacroObservation.objects.filter(indicator=ind)
               .order_by("-date").first()) if ind is not None else None
        if obs is None:
            series[sid] = {"name": label, "value": "absent"}
            continue
        series[sid] = {"name": label, "value": float(obs.value),
                       "date": obs.date.isoformat()}
        ts = timezone.make_aware(
            timezone.datetime.combine(obs.date, timezone.datetime.min.time()))
        if newest is None or ts > newest:
            newest = ts
    return _stamp({"series": series}, newest)


def _read_evidence() -> dict:
    from bot_program.evidence import config_evidence, rule_rows

    rows = sorted(rule_rows(), key=lambda r: -int(r.get("sig_n") or 0))[:15]
    ledger = [{k: r.get(k) for k in ("rule", "stage", "sig_n", "sig_hit",
                                     "sig_avg", "sig_r", "paper_n", "paper_r",
                                     "live_n", "live_r", "regret_r")}
              for r in rows]
    lanes = []
    try:
        from bot_program.models import AssetBotConfig
        for cfg in AssetBotConfig.objects.filter(enabled=True)[:40]:
            ev = config_evidence(cfg)
            lanes.append({"config": cfg.name, "asset_class": cfg.asset_class,
                          "mode": cfg.mode, "lane": ev.get("lane"),
                          "n": ev.get("n"), "win_rate": ev.get("win_rate"),
                          "avg_r": ev.get("avg_r"),
                          # The window this lane was measured over. It is
                          # the config's PERSONA window since 2026-09-12
                          # (21 / 90 / 365 days), so lanes in this list no
                          # longer share one — an n of 4 over 21 days and
                          # an n of 4 over a year are different facts and
                          # the agent must not read them as the same.
                          "window_days": ev.get("days"),
                          "measured": bool(ev.get("measured"))})
    except Exception as e:  # noqa: BLE001 — the rule ledger still stands
        lanes = [{"error": f"config lanes unreadable: {e}"[:200]}]
    return _stamp({"rules_by_signals": ledger, "config_lanes": lanes})


def _read_brain() -> dict:
    from brain.context import get_brain_context
    from brain.models import BrainReport

    ctx = get_brain_context(max_age_minutes=180)
    reports = list(BrainReport.objects.filter(error="")
                   .order_by("-created_at")[:2])
    summaries = [{"created_at": r.created_at.isoformat(),
                  "regime": r.regime_label,
                  "regime_confidence": r.regime_confidence,
                  "themes": r.theme_pressures,
                  "narrative": (r.narrative_md or "")[:800]}
                 for r in reports]
    newest = reports[0].created_at if reports else None
    return _stamp({"context": ctx or "absent (no fresh brain context)",
                   "recent_reports": summaries}, newest)


def _read_previous() -> dict:
    """The agent confronts its own record: the last OK view's tilts and
    how its calls have graded so far."""
    from ai_agents.calibration import brier_score, trust_adjustment_for
    from ai_agents.models import AgentPrediction
    from .horizon_models import HorizonView

    prev = (HorizonView.objects.filter(status=HorizonView.STATUS_OK)
            .order_by("-created_at").first())
    calls = AgentPrediction.objects.filter(agent=AGENT_NAME,
                                           prediction_type="direction")
    graded = calls.filter(was_correct__isnull=False)
    record = {
        "calls_total": calls.count(),
        "calls_graded": graded.count(),
        "calls_correct": graded.filter(was_correct=True).count(),
        "brier_score": brier_score(AGENT_NAME, lookback_days=400),
        "trust_adjustment": trust_adjustment_for(AGENT_NAME,
                                                 lookback_days=400),
        "recent_grades": [
            {"symbol": p.instrument_symbol, "called": p.predicted_value,
             "actual": p.actual_value, "correct": p.was_correct,
             "move": p.score, "horizon_hours": p.horizon_hours}
            for p in graded.order_by("-evaluated_at")[:20]],
    }
    if prev is None:
        return _stamp({"view": "absent (first run)", "record": record})
    return _stamp({
        "view": {"id": prev.pk, "created_at": prev.created_at.isoformat(),
                 "horizon_years": prev.horizon_years,
                 "summary_md": (prev.summary_md or "")[:1500],
                 "sector_tilts": {s.get("key"): {"tilt": s.get("tilt"),
                                                  "confidence": s.get("confidence")}
                                  for s in (prev.sectors or [])
                                  if isinstance(s, dict)},
                 "asset_class_tilts": prev.asset_class_tilts},
        "record": record}, prev.created_at)


def _build_horizon_snapshot() -> dict:
    """Pure DB reads; every block wrapped and stamped."""
    return {
        "as_of": timezone.now().isoformat(),
        "universe": _guarded("universe", _read_universe),
        "macro": _guarded("macro", _read_macro),
        "evidence": _guarded("evidence", _read_evidence),
        "brain": _guarded("brain", _read_brain),
        "previous_view": _guarded("previous_view", _read_previous),
    }


# ── The agent ────────────────────────────────────────────────────────────

HORIZON_SCHEMA = """{
  "as_of": "YYYY-MM-DD",
  "horizon_years": 5 | 10,
  "summary_md": "the structural picture in 5-12 sentences, citing the snapshot's numbers",
  "sectors": [
    {
      "key": "one of: technology energy financials health industrials consumer_discretionary consumer_staples utilities materials real_estate communication gold oil bonds dollar bitcoin",
      "thesis_md": "2-5 sentences on the 5-10 year development of this sector",
      "structural_drivers": ["..."],
      "risks": ["..."],
      "catalysts": ["..."],
      "tilt": -2 | -1 | 0 | 1 | 2,
      "confidence": 0.0..1.0,
      "calls": [
        {"symbol": "the sector's symbol from the snapshot", "direction": "up" | "down",
         "horizon_hours": 4380 | 8760, "confidence": 0.0..1.0, "why": "one line"}
      ]
    }
  ],
  "asset_classes": [
    {"asset_class": "stock" | "forex" | "commodity" | "crypto" | "options" | "cfd",
     "tilt": -2 | -1 | 0 | 1 | 2, "confidence": 0.0..1.0, "why": "one line"}
  ],
  "regime_claims": [
    {"claim": "a falsifiable sentence about the regime", "horizon_hours": 4380 | 8760,
     "confidence": 0.0..1.0}
  ]
}"""


class HorizonAgent(BaseAgent):
    """The monthly 5-10 year sector synthesis."""

    agent_name = AGENT_NAME          # ≤ 30 chars: AgentTask.agent
    # Frontier, like the strategy generator: one call a month where the
    # quality of the structural reasoning is the product.
    default_tier = "frontier"

    def get_system_prompt(self) -> str:
        return (
            "You are the Sauron Vision Horizon agent. Once a month you write "
            "the platform's STRUCTURAL view: how each sector in the snapshot "
            "develops over the next 5 to 10 years, the risks that view must "
            "guard against, and what it implies for each asset class the "
            "platform trades.\n\n"
            "The platform's doctrine, which you must follow:\n"
            "1. No prose without a gradable claim. Every sector entry ends in "
            "`calls` — direction calls on the sector's own symbol at 4380 h "
            "(6 months) or 8760 h (12 months). Each is graded against the "
            "price at its horizon and your trust score is built from those "
            "grades. A thesis with no call is a thesis nobody can check.\n"
            "2. Cite the snapshot's numbers. 'Energy has run' is rejected; "
            "'XLE return_1y +0.18 against a 3y of -0.05, DCOILWTICO at 71' "
            "is a claim. Use only the symbols in `universe`.\n"
            "3. Unknown is unknown. A block marked 'absent', 'no daily "
            "history' or 'unreadable' is not a number — never invent one. "
            "Lower the confidence instead and say what is missing.\n"
            "4. `tilt` is an integer from -2 (structural headwind) to +2 "
            "(structural tailwind); 0 is a real answer. `confidence` is "
            "0..1 and will be scored. The share allocator reads "
            "`asset_classes` as a WEAK prior — 5% per tilt point times "
            "confidence, ±10% at most — so tilt only what the evidence "
            "supports.\n"
            "5. `previous_view` is your own last answer and how its calls "
            "have graded. Confront it: say what changed, what was wrong, "
            "and do not restate a view the market has already refuted.\n"
            "6. `regime_claims` are falsifiable sentences about the macro "
            "regime at 6 or 12 months, for the record.\n\n"
            f"Respond ONLY with valid JSON in this schema:\n{HORIZON_SCHEMA}\n\n"
            "No code fences, no surrounding text."
        )

    def build_context(self, **kwargs) -> str:
        snap = kwargs.get("snapshot") or _build_horizon_snapshot()
        return (
            "Snapshot for the 5-10 year synthesis (JSON):\n\n"
            f"{json.dumps(snap, indent=2, default=str)}\n\n"
            "Write the Horizon view now."
        )

    def parse_response(self, raw_response: str) -> dict:
        text = (raw_response or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"non-JSON horizon output: {e}: {text[:200]}")
        if not isinstance(data, dict):
            raise ValueError("horizon returned non-dict")
        return validate_view(data)


# ── Validation ───────────────────────────────────────────────────────────

def _int_tilt(value, where: str) -> int:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: tilt {value!r} is not a number")
    # isfinite first: json.loads accepts `Infinity` and `1e999`, and
    # int(inf) raises OverflowError — not the ValueError the run's
    # rejection path catches — which left a `running` row with the paid
    # text lost (2026-09-12). An infinite tilt is a garbled answer.
    if not math.isfinite(f) or f != int(f):
        raise ValueError(f"{where}: tilt {value!r} is not an integer")
    t = int(f)
    if not (-2 <= t <= 2):
        raise ValueError(f"{where}: tilt {t} outside -2..2")
    return t


def _conf(value, where: str) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: confidence {value!r} is not a number")
    if c != c or not (0.0 <= c <= 1.0):
        raise ValueError(f"{where}: confidence {value!r} outside 0..1")
    return c


def _horizon_h(value, where: str) -> int:
    try:
        h = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: horizon_hours {value!r} is not a number")
    for allowed in CALL_HORIZONS_H:
        if abs(h - allowed) < 1e-6:
            return allowed
    raise ValueError(f"{where}: horizon_hours {value!r} not in "
                     f"{set(CALL_HORIZONS_H)}")


def _str_list(value) -> list:
    if not isinstance(value, list):
        return []
    return [str(v)[:300] for v in value if isinstance(v, (str, int, float))][:12]


def validate_view(data: dict) -> dict:
    """The validated, normalised view, or ValueError naming the field.

    Strict on purpose: a tilt of 3, a confidence of 1.4, a sector the
    universe does not hold, a horizon that is not 6 or 12 months — each
    is a garbled answer, and a garbled answer is an error row, never a
    view the allocator reads.
    """
    from ai_agents.calibration import normalise_direction

    try:
        years = int(data.get("horizon_years"))
    except (TypeError, ValueError, OverflowError):   # 1e999 -> inf
        raise ValueError(f"horizon_years {data.get('horizon_years')!r} "
                         f"is not an integer")
    if years not in HORIZON_YEARS:
        raise ValueError(f"horizon_years {years} not in {set(HORIZON_YEARS)}")

    sectors_in = data.get("sectors")
    if not isinstance(sectors_in, list):
        raise ValueError("sectors is not a list")
    sectors, seen_keys = [], set()
    for i, s in enumerate(sectors_in):
        where = f"sectors[{i}]"
        if not isinstance(s, dict):
            raise ValueError(f"{where}: not an object")
        key = str(s.get("key") or "")
        if key not in SECTOR_KEYS:
            raise ValueError(f"{where}: unknown sector key {key!r}")
        if key in seen_keys:
            raise ValueError(f"{where}: sector {key!r} listed twice")
        seen_keys.add(key)
        calls_in = s.get("calls")
        if calls_in is None:
            calls_in = []
        if not isinstance(calls_in, list):
            raise ValueError(f"{where}: calls is not a list")
        calls = []
        for j, c in enumerate(calls_in):
            cw = f"{where}.calls[{j}]"
            if not isinstance(c, dict):
                raise ValueError(f"{cw}: not an object")
            sym = str(c.get("symbol") or "").strip().upper()
            if not sym:
                raise ValueError(f"{cw}: no symbol")
            d = normalise_direction(c.get("direction"))
            if d is None:
                raise ValueError(f"{cw}: direction {c.get('direction')!r} "
                                 f"is not up/down")
            calls.append({"symbol": sym, "direction": d,
                          "horizon_hours": _horizon_h(c.get("horizon_hours"), cw),
                          "confidence": _conf(c.get("confidence", 0.5), cw),
                          "why": str(c.get("why") or "")[:300]})
        sectors.append({
            "key": key,
            "thesis_md": str(s.get("thesis_md") or "")[:4000],
            "structural_drivers": _str_list(s.get("structural_drivers")),
            "risks": _str_list(s.get("risks")),
            "catalysts": _str_list(s.get("catalysts")),
            "tilt": _int_tilt(s.get("tilt", 0), where),
            "confidence": _conf(s.get("confidence", 0.5), where),
            "calls": calls,
        })

    classes_in = data.get("asset_classes")
    if classes_in is None:
        classes_in = []
    if not isinstance(classes_in, list):
        raise ValueError("asset_classes is not a list")
    classes = []
    for i, a in enumerate(classes_in):
        where = f"asset_classes[{i}]"
        if not isinstance(a, dict):
            raise ValueError(f"{where}: not an object")
        ac = str(a.get("asset_class") or "")
        if ac not in HORIZON_ASSET_CLASSES:
            raise ValueError(f"{where}: unknown asset_class {ac!r}")
        classes.append({"asset_class": ac,
                        "tilt": _int_tilt(a.get("tilt", 0), where),
                        "confidence": _conf(a.get("confidence", 0.5), where),
                        "why": str(a.get("why") or "")[:300]})

    claims_in = data.get("regime_claims")
    if claims_in is None:
        claims_in = []
    if not isinstance(claims_in, list):
        raise ValueError("regime_claims is not a list")
    claims = []
    for i, r in enumerate(claims_in):
        where = f"regime_claims[{i}]"
        if not isinstance(r, dict):
            raise ValueError(f"{where}: not an object")
        claims.append({"claim": str(r.get("claim") or "")[:400],
                       "horizon_hours": _horizon_h(r.get("horizon_hours"), where),
                       "confidence": _conf(r.get("confidence", 0.5), where)})

    return {
        "as_of": str(data.get("as_of") or "")[:40],
        "horizon_years": years,
        "summary_md": str(data.get("summary_md") or "")[:8000],
        "sectors": sectors,
        "asset_classes": classes,
        "regime_claims": claims,
    }


# ── Persistence and the run ──────────────────────────────────────────────

def _reference_for(symbol: str, universe_block: dict):
    """The price a call is measured from: the platform's fresh mark, else
    the universe's last daily close.

    mark_for_symbol wants a quote under 6 h old or a bar under 48 h; a
    monthly run at 04:45 on the 1st can land on a Monday, when the newest
    daily bar is Friday's — 60+ hours old — and every sector call would
    be refused for want of a price. For a 6-12 month claim, Friday's
    close is the right reference; nothing about it is fabricated.
    """
    from ai_agents.calibration import mark_for_symbol
    mark = mark_for_symbol(symbol)
    if mark:
        return mark
    now = timezone.now()
    for row in (universe_block or {}).get("sectors") or []:
        if row.get("symbol") != symbol or not row.get("last_close"):
            continue
        # Only a close under REFERENCE_MAX_AGE_DAYS old: a daily feed
        # that stopped a month ago must not hand a year-long call a
        # reference the market left long before the claim. Refused,
        # the call is counted as dropped and shows 'not registered'.
        try:
            last_bar = datetime.fromisoformat(str(row.get("last_bar")))
        except (TypeError, ValueError):
            return None
        if last_bar.tzinfo is None:
            last_bar = timezone.make_aware(last_bar)
        if (now - last_bar).total_seconds() > REFERENCE_MAX_AGE_DAYS * 86400:
            return None
        return float(row["last_close"])
    return None


# ── The display contract for a call ─────────────────────────────────────
# Every display of a call (the page, the shell) reads the annotation
# register_view_calls writes onto the call dict — `registered` and, when
# False, `drop_reason`. Nothing else may decide whether a call is graded.
NOT_REGISTERED = "not registered"


def _months(horizon_hours) -> int:
    """4380 h -> 6, 8760 h -> 12: the month label every display prints."""
    try:
        return int(round(float(horizon_hours or 0) / 730.0))
    except (TypeError, ValueError):
        return 0


def _horizon_key(horizon_hours):
    """The horizon rounded to the hour, or None. AgentPrediction stores a
    float (clamp_horizon returns one); a call dict carries an int."""
    try:
        return int(round(float(horizon_hours)))
    except (TypeError, ValueError):
        return None


def call_key(call) -> tuple:
    """The (SYMBOL, hours) key a call dict and its AgentPrediction match on.

    The symbol ALONE was the key, and the operator read this on the first
    live view:

        call XLK UP 12m conf 0.58 — pending until 2027-09-12
        call XLK UP  6m conf 0.52 — pending until 2027-09-12

    One of those calls exists. The unregistered 6-month call was matched
    to the registered 12-month call's row and printed its deadline as its
    own — an unmeasured quantity shown as a confident date, the one thing
    tests/test_ui_honesty.py forbids (2026-09-12).
    """
    c = call or {}
    return (str(c.get("symbol") or "").strip().upper(),
            _horizon_key(c.get("horizon_hours")))


def view_predictions(view) -> dict:
    """{call_key: the newest 'horizon' prediction this view registered}.

    Keyed by (symbol, horizon) and filtered to rows created at or after
    the view: a call with no row here was NOT registered and must render
    as such — never with another call's deadline.
    """
    from ai_agents.models import AgentPrediction

    out = {}
    for p in (AgentPrediction.objects
              .filter(agent=AGENT_NAME, prediction_type="direction",
                      created_at__gte=view.created_at)
              .order_by("instrument_symbol", "-created_at")):
        out.setdefault((str(p.instrument_symbol or "").strip().upper(),
                        _horizon_key(p.horizon_hours)), p)
    return out


def call_drop_reason(call) -> str:
    """The annotated reason this call was not registered, without the
    'not registered — ' prefix the displays add themselves.

    '' for a view written before 2026-09-12, whose calls carry no
    annotation at all: the display then says the bare 'not registered'
    rather than raising a KeyError on a view the operator paid for.
    """
    reason = str((call or {}).get("drop_reason") or "").strip()
    prefix = f"{NOT_REGISTERED} — "
    if reason.startswith(prefix):
        reason = reason[len(prefix):]
    return reason


def call_not_registered_label(call) -> str:
    """'not registered — <reason>' — the whole line, for the shell."""
    reason = call_drop_reason(call)
    return f"{NOT_REGISTERED} — {reason}" if reason else NOT_REGISTERED


def register_view_calls(parsed: dict, *, universe_block=None) -> dict:
    """Register every sector call under agent 'horizon', one per symbol,
    and ANNOTATE each call dict in place with what happened to it.

    The second call on a symbol inside one view is dropped here; a call
    on a symbol the agent already has a LIVE call on (last month's
    12-month call) is dropped by the calibration's own one-live-call rule.
    Both are counted, so the run result says what it did not register.

    Two rules the first live view broke (2026-09-12):

    1. SHORTEST HORIZON FIRST. The calibration allows one live call per
       (agent, symbol), so a symbol carrying both a 6- and a 12-month
       call gets exactly one of them registered. Registering the 6-month
       one means the agent's first graded feedback lands in six months
       instead of twelve — which is the whole point of registering calls
       at all. The sort is stable and spans the view, so calls of equal
       horizon keep the model's own order.
    2. THE ANNOTATION IS THE ONLY SOURCE OF TRUTH FOR A DISPLAY.
       `c["registered"]` on every call, `c["drop_reason"]` on every
       dropped one. The mutation is in place, on the dicts the caller
       persists onto the HorizonView — see run_horizon_now, which
       re-saves `sectors` because registration runs after the row is
       written.
    """
    from ai_agents.calibration import log_direction_prediction

    registered, dropped_dup, dropped_unreg = 0, 0, 0
    # symbol -> the horizon (hours) actually registered on it, so a
    # dropped duplicate can name the call that superseded it. Only a
    # SUCCESSFUL registration lands here: naming a call that was itself
    # refused would be a second fiction.
    taken = {}
    pairs = sorted(((s, c) for s in parsed.get("sectors") or []
                    for c in s.get("calls") or []),
                   key=lambda sc: float(sc[1].get("horizon_hours") or 0))
    for sector, c in pairs:
        sym = c["symbol"]
        if sym in taken:
            dropped_dup += 1
            c["registered"] = False
            c["drop_reason"] = (f"superseded by the {_months(taken[sym])}m "
                                f"call on {sym} — one live call per symbol")
            continue
        pred = log_direction_prediction(
            AGENT_NAME, sym, c["direction"],
            horizon_hours=c["horizon_hours"],
            confidence=c["confidence"],
            reference_price=_reference_for(sym, universe_block),
            notes=f"{sector['key']}: {c.get('why', '')}"[:300],
            max_horizon_hours=HORIZON_MAX_H)
        if pred is None:
            dropped_unreg += 1
            c["registered"] = False
            # log_direction_prediction also returns None when a live call
            # from an earlier view still stands on the symbol; that call
            # is on the /calibration/ ledger, and this reason names the
            # two causes the operator can act on.
            c["drop_reason"] = (f"{NOT_REGISTERED} — no instrument row or no "
                                f"usable price for {sym}")
        else:
            registered += 1
            taken[sym] = c["horizon_hours"]
            c["registered"] = True
    return {"registered": registered, "dropped": dropped_dup + dropped_unreg,
            "dropped_duplicate": dropped_dup,
            "dropped_unregistered": dropped_unreg}


def run_horizon_now() -> dict:
    """One synthesis. Always returns a dict; never raises.

    The row first, the model second, the calls third. The budget is the
    task decorator's (brain.tasks.run_horizon): this function is the
    model-only body the page and the shell twin both call.
    """
    from .horizon_models import HorizonView

    snapshot = _build_horizon_snapshot()
    view = HorizonView.objects.create(status=HorizonView.STATUS_RUNNING,
                                      snapshot_as_of=timezone.now())
    agent = None
    try:
        agent = HorizonAgent()
        raw, usage = agent.provider.complete(
            system_prompt=agent.get_system_prompt(),
            user_message=agent.build_context(snapshot=snapshot),
            model=agent.model,
            agent_name=agent.agent_name,
            # The tier's effort (catalog: frontier -> high), as
            # BaseAgent.run passes it; a direct provider call without
            # it ran the one call where reasoning depth is the product
            # at the model's default (2026-09-12).
            effort=getattr(agent, "effort", None),
            # The row exists before the call: the ref keeps a
            # timestamp-cut backfill from booking this cost twice.
            source_ref=f"HorizonView:{view.pk}",
        )
    except Exception as e:  # noqa: BLE001 — provider/config error: an error row
        logger.warning("[horizon] model call failed: %s", e)
        billed = getattr(e, "usage", None) or {}
        view.status = HorizonView.STATUS_ERROR
        view.error = str(e)[:2000]
        view.model_used = (getattr(agent, "model", "") or "")[:80]
        view.tokens_in = int(billed.get("input_tokens", 0) or 0)
        view.tokens_out = int(billed.get("output_tokens", 0) or 0)
        view.cost_usd = Decimal(str(round(float(billed.get("cost_usd", 0) or 0), 6)))
        view.save()
        return {"ok": False, "status": "error", "outcome": "error",
                "view_id": view.pk, "error": str(e)[:300]}

    view.model_used = (agent.model or "")[:80]
    view.tokens_in = int(usage.get("input_tokens", 0) or 0)
    view.tokens_out = int(usage.get("output_tokens", 0) or 0)
    view.cost_usd = Decimal(str(round(float(usage.get("cost_usd", 0) or 0), 6)))

    try:
        parsed = agent.parse_response(raw)
    except Exception as e:  # noqa: BLE001 — see below
        # ValueError is the parser's contract, but ANY failure here
        # (an OverflowError from `Infinity`, a RecursionError from a
        # pathological nesting) must land the same way: a narrower
        # catch left the row `running` forever and the paid text
        # unsaved (2026-09-12). Paid output stays visible: the operator
        # reads what came back and why the platform refused it
        # (_record_rejection precedent).
        logger.warning("[horizon] answer rejected: %s", e)
        view.status = HorizonView.STATUS_REJECTED
        view.error = str(e)[:2000]
        view.raw = (raw or "")[:RAW_KEEP_CHARS]
        view.save()
        return {"ok": False, "status": "error", "outcome": "rejected",
                "view_id": view.pk, "error": str(e)[:300],
                "cost_usd": float(view.cost_usd)}

    view.horizon_years = parsed["horizon_years"]
    view.summary_md = parsed["summary_md"]
    view.sectors = parsed["sectors"]
    view.asset_class_tilts = {
        a["asset_class"]: {"tilt": a["tilt"], "confidence": a["confidence"],
                           "why": a["why"]}
        for a in parsed["asset_classes"]}
    view.regime_claims = parsed["regime_claims"]
    view.status = HorizonView.STATUS_OK
    view.save()

    calls = {"registered": 0, "dropped": 0, "dropped_duplicate": 0,
             "dropped_unregistered": 0}
    try:
        calls = register_view_calls(parsed,
                                    universe_block=snapshot.get("universe"))
    except Exception as e:  # noqa: BLE001 — the view stands, the calls are noted
        logger.warning("[horizon] call registration failed: %s", e)
        view.error = f"calls not registered: {e}"[:2000]
    view.calls_registered = calls["registered"]
    view.calls_dropped = calls["dropped"]
    # `sectors` again: register_view_calls annotates each call dict in
    # place (registered / drop_reason) and runs AFTER the row above was
    # written, so the JSON on disk still held un-annotated calls and every
    # display fell back to a bare 'not registered' — or, worse, to another
    # call's deadline. view.sectors IS parsed["sectors"], the dicts the
    # annotation mutated, so one cheap re-save persists it (2026-09-12).
    view.save(update_fields=["calls_registered", "calls_dropped", "error",
                             "sectors"])

    return {"ok": True, "status": "ok", "outcome": "ok", "view_id": view.pk,
            "horizon_years": view.horizon_years,
            "n_sectors": len(view.sectors),
            "n_asset_classes": len(view.asset_class_tilts),
            "calls_registered": calls["registered"],
            "calls_dropped": calls["dropped"],
            "calls_dropped_duplicate": calls["dropped_duplicate"],
            "calls_dropped_unregistered": calls["dropped_unregistered"],
            "model": view.model_used, "cost_usd": float(view.cost_usd)}


def grade_record(lookback_days: int = 400) -> dict:
    """{brier, trust, n_graded, n_total, n_correct, measured} for the page
    and the shell. `measured` is False under MIN_SAMPLE_FOR_TRUST graded
    calls — the page prints '—' rather than a trust built on three grades."""
    from ai_agents.calibration import (MIN_SAMPLE_FOR_TRUST, brier_score,
                                       trust_adjustment_for)
    from ai_agents.models import AgentPrediction

    calls = AgentPrediction.objects.filter(agent=AGENT_NAME,
                                           prediction_type="direction")
    graded = calls.filter(was_correct__isnull=False)
    n_graded = graded.count()
    return {"n_total": calls.count(), "n_graded": n_graded,
            "n_correct": graded.filter(was_correct=True).count(),
            "n_pending": calls.filter(evaluated_at__isnull=True).count(),
            "brier": brier_score(AGENT_NAME, lookback_days=lookback_days),
            "trust": trust_adjustment_for(AGENT_NAME,
                                          lookback_days=lookback_days),
            "measured": n_graded >= MIN_SAMPLE_FOR_TRUST,
            "min_sample": MIN_SAMPLE_FOR_TRUST}
