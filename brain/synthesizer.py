"""Phase 37.2 — Sauron's Mind synthesizer.

Every 30 minutes:
  1. Gather a structured "world snapshot" — recent observations, portfolio
     state, exposure, rule track records, regime probes (Hurst/GARCH on
     top holdings).
  2. Call Claude with a tight system prompt + JSON schema in the response.
  3. Parse to a BrainReport row.
  4. Mark the consumed observations.
  5. Emit 1-3 falsifiable AgentPredictions for Phase-6 calibration.

Designed to **never block** — any exception becomes an error-stamped
BrainReport row so downstream agents see "no fresh report" and degrade.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


# The window realized-R evidence is measured over. Named because the note
# below has to quote the same number the query used — a note that says "no
# closes in 14 days" while the query looked at 30 is worse than no note.
TRACK_RECORD_WINDOW_DAYS = 14


def _no_track_record_reason() -> str:
    """Why there is no realized-R evidence — in the terms an operator acts on.

    The distinction that matters is between "nothing has closed yet" (wait,
    or close something) and "things closed but could not be graded" (a real
    fault, in the stop that was never recorded or the rule tag that was never
    written). Both produce an empty table; only one is a bug, and a briefing
    that cannot tell them apart escalates a young book as broken telemetry.
    """
    from datetime import timedelta as _td
    try:
        from bot_program.models import AssetBotTrade
    except Exception:  # pragma: no cover - app not installed
        return "NOT MEASURED — the bot trade book is unavailable."

    since = timezone.now() - _td(days=TRACK_RECORD_WINDOW_DAYS)
    closed = AssetBotTrade.objects.filter(status="CLOSED", closed_at__gte=since)
    n_closed = closed.count()
    if not n_closed:
        n_open = AssetBotTrade.objects.filter(
            status__in=("OPEN", "CLOSE_PENDING")).count()
        return (
            f"NO REALIZED R YET — nothing has closed in the last "
            f"{TRACK_RECORD_WINDOW_DAYS} days ({n_open} position(s) still "
            f"open). The measurement pipeline is not broken; a book that has "
            f"not closed a trade has produced no evidence to measure. Rules "
            f"cannot be promoted or paused on evidence until it does, and "
            f"every status call is inference rather than realized R — but "
            f"that is the age of the book, not a fault to fix.")

    n_untagged = closed.filter(rule_name="").count()
    n_ungraded = closed.exclude(rule_name="").filter(
        realized_r__isnull=True).count()
    faults = []
    if n_untagged:
        faults.append(f"{n_untagged} closed with no rule_name, so there is "
                      f"nothing to attribute them to")
    if n_ungraded:
        faults.append(f"{n_ungraded} closed without a realized R, which "
                      f"happens when the trade carried no stop to denominate "
                      f"one")
    if faults:
        return (f"GRADING GAP — {n_closed} trade(s) closed in the last "
                f"{TRACK_RECORD_WINDOW_DAYS} days but none reached this "
                f"table: {'; '.join(faults)}. This one IS a fault.")
    return (f"{n_closed} trade(s) closed in the last "
            f"{TRACK_RECORD_WINDOW_DAYS} days but none carried a gradable "
            f"outcome. Unexpected — worth looking at directly.")


# ── Snapshot builder (no Claude call) ─────────────────────────────────────


def _held_symbols() -> set:
    """Every symbol open in either book, across users.

    The regime probe is a PLATFORM read — `_build_world_snapshot` takes no
    user — so it asks both books for what is currently carried rather than
    scoping to one operator. A symbol nobody holds can wait; a symbol that
    is 36% of somebody's book cannot.

    Never raises: a probe that cannot list the book falls back to the
    watchlist ordering rather than costing the whole snapshot.
    """
    symbols = set()
    try:
        from bot_program.models import AssetBotTrade
        symbols.update(
            AssetBotTrade.objects
            .filter(status__in=("OPEN", "CLOSE_PENDING"))
            .values_list("symbol", flat=True))
    except Exception:  # noqa: BLE001
        logger.warning("regime probe: could not read the bot book",
                       exc_info=True)
    try:
        from portfolio.models import Position
        symbols.update(
            Position.objects.filter(closed_at__isnull=True)
            .values_list("instrument__symbol", flat=True))
    except Exception:  # noqa: BLE001
        logger.warning("regime probe: could not read the legacy book",
                       exc_info=True)
    return {s for s in symbols if s}


def _build_world_snapshot(*, max_obs: int = 80) -> dict:
    """Compact JSON-ready dict the synthesizer reads from.

    Designed to fit in ~3-4K input tokens at typical workloads.
    """
    from .models import BrainObservation
    from instruments.models import Instrument

    snap: dict[str, Any] = {
        "as_of": timezone.now().isoformat(),
    }

    # 1. Unconsumed observations, grouped by kind, capped per kind.
    obs_qs = (BrainObservation.objects
              .filter(consumed_by_brain_at__isnull=True)
              .order_by("-created_at")[:max_obs])
    obs_list = list(obs_qs.values("id", "kind", "payload", "source_agent",
                                    "created_at"))
    snap["observations"] = [
        {**o, "created_at": o["created_at"].isoformat()} for o in obs_list
    ]
    snap["observations_count_by_kind"] = {}
    for o in obs_list:
        snap["observations_count_by_kind"][o["kind"]] = (
            snap["observations_count_by_kind"].get(o["kind"], 0) + 1)

    # 2. Open positions across all users — keep it light, just the shape.
    # BOTH books: the legacy Position table AND the AssetBotTrades that
    # every interactive and bot path actually writes. The brain used to
    # read only the former, so a manual TAKE TRADE produced trade_open
    # audit events against an "empty" positions table — and the brain
    # escalated its own blind spot as a ledger desync ("your risk number
    # is fiction"). The desync was in this function.
    # Bot book FIRST and CLOSE_PENDING before all: it is the actively
    # managed ledger, and an in-flight failed close is the row the brain
    # most needs to see. Appending it after the legacy book meant the cap
    # silently dropped bot rows first — partially recreating the blind
    # spot this union exists to close. The cap is per-book and the counts
    # are stated, so truncation reads as truncation, never as "flat".
    bot_rows: list[dict] = []
    pf_rows: list[dict] = []
    n_bot = n_pf = 0
    try:
        from bot_program.models import AssetBotTrade
        qs_bot = AssetBotTrade.objects.filter(
            status__in=("OPEN", "CLOSE_PENDING"))
        n_bot = qs_bot.count()
        for t in qs_bot.order_by("status", "-opened_at")[:20]:
            # "CLOSE_PENDING" < "OPEN" lexically — pendings sort first.
            bot_rows.append({
                "symbol": t.symbol,
                "asset_class": t.asset_class,
                "side": (t.side or "").upper(),
                "rule_name": t.rule_name or "",
                "paper": bool(t.paper),
                "status": t.status,
                "book": "bot",
            })
    except Exception:
        pass
    try:
        from portfolio.models import Position
        qs_pf = Position.objects.filter(closed_at__isnull=True)
        n_pf = qs_pf.count()
        for p in (qs_pf.select_related("instrument", "strategy")
                  .order_by("-opened_at")[:20]):
            pf_rows.append({
                "symbol": p.instrument.symbol,
                "asset_class": getattr(p.instrument, "asset_class", ""),
                "side": getattr(p, "side", ""),
                "rule_name": getattr(p.strategy, "name", "") if p.strategy else "",
                "unrealized_r": float(p.unrealized_pnl or 0),
                "book": "portfolio",
            })
    except Exception:
        pass
    snap["open_positions"] = bot_rows + pf_rows
    snap["open_positions_total"] = n_bot + n_pf
    if n_bot + n_pf > len(snap["open_positions"]):
        snap["open_positions_truncated"] = True

    # 3. Per-rule recent track record.
    #
    # An empty list is THREE different situations, and the strategist read
    # them as one. A briefing called this "the highest-leverage fix on the
    # list" and told the operator the telemetry was broken, when the true
    # answer was that a young book had simply not closed anything yet:
    # nothing was broken, there was nothing to measure. So the emptiness now
    # states its own cause, and states the window it was measured over —
    # "no closes in 14 days" and "the query failed" are opposite instructions
    # to whoever reads this next.
    snap["rule_track_records_window_days"] = TRACK_RECORD_WINDOW_DAYS
    try:
        from bot_program.bot_grading import bot_performance_summary
        rows = bot_performance_summary(days=TRACK_RECORD_WINDOW_DAYS, min_n=1)
        snap["rule_track_records"] = [
            {
                "rule_name": r["rule_name"],
                "asset_class": r["asset_class"],
                "n": r["n"],
                "win_rate": round(float(r["win_rate"] or 0), 4),
                "avg_r": round(float(r["avg_r"] or 0), 4),
                "expectancy": round(float(r.get("expectancy") or 0), 4),
            }
            for r in rows[:30]
        ]
        if not snap["rule_track_records"]:
            snap["rule_track_records_note"] = _no_track_record_reason()
    except Exception as e:  # noqa: BLE001
        snap["rule_track_records"] = []
        snap["rule_track_records_note"] = (
            f"NOT MEASURED — the track-record query itself failed ({e}). "
            f"This is a platform fault, not an empty book.")

    # 4. Regime probes for top tracked instruments — sample to keep tokens low.
    try:
        from signals.quant_primitives import (
            hurst_exponent, hurst_regime_label, garch_lite_forecast,
        )
        from market_data.models import PriceData
        # HELD FIRST, then watchlist, then the rest.
        #
        # Watchlist-first was already an improvement on an arbitrary slice,
        # and it still measured the wrong universe: with nothing starred —
        # which is the shipped state — "-is_watchlist, symbol" degenerates
        # to ALPHABETICAL, so the probe read AAPL, AAVEUSD, ABBV, ADAUSD,
        # AGG, ALUMUSD, AMD, AMZN out of 177 instruments and reported on
        # none of the eight the operator was actually carrying.
        #
        # That is how the briefing came to say, three days running, that
        # 36% of the book sat in an asset with "zero regime probe
        # coverage": the brain was measuring the alphabet. A regime read
        # that skips the positions is answering a question nobody asked.
        held = _held_symbols()
        ordered = sorted(
            Instrument.objects.filter(is_active=True),
            key=lambda i: (0 if i.symbol in held else 1,
                           0 if i.is_watchlist else 1,
                           i.symbol),
        )
        candidates = ordered[:max(8, min(len(held), 16))]
        regime_probes = []
        for inst in candidates:
            # Do NOT hardcode a timeframe: this deployment holds 4h and
            # 1h bars and no daily ones at all, so probing "1d" found
            # nothing for ANY instrument and the brain read six straight
            # regime-unknown reports as a telemetry blackout — while
            # diagnosing its own hardcoded filter as a dead scheduler.
            # (The realized-vol headband cell hit this exact trap first.)
            closes = []
            probe_tf = None
            for tf in ("1d", "4h", "1h"):
                rows = list(PriceData.objects
                            .filter(instrument=inst, timeframe=tf)
                            .order_by("-timestamp")
                            .values_list("close", flat=True)[:150])
                if len(rows) >= 30:
                    closes = [float(c) for c in reversed(rows)]
                    probe_tf = tf
                    break
            if not closes:
                continue
            h = hurst_exponent(closes, max_lag=20)
            sigma = garch_lite_forecast(closes)
            regime_probes.append({
                "symbol": inst.symbol,
                "asset_class": inst.asset_class,
                "timeframe": probe_tf,
                "hurst": round(h, 3) if h is not None else None,
                "regime": hurst_regime_label(h),
                "vol_forecast_pct": round(sigma * 100, 3) if sigma is not None else None,
                "n_closes": len(closes),
            })
        snap["regime_probes"] = regime_probes
    except Exception:
        snap["regime_probes"] = []

    # 5. Recent decay alerts.
    try:
        from bot_program.track_record_models import RuleTrackRecordAlert
        decay_qs = (RuleTrackRecordAlert.objects
                    .filter(resolved_at__isnull=True)
                    .order_by("-detected_at")[:10])
        snap["unresolved_decay_alerts"] = [
            {
                "rule_name": a.rule_name,
                "asset_class": a.asset_class,
                "triggers": a.triggers,
                "recent_avg_r": float(a.recent_avg_r or 0),
                "baseline_avg_r": float(a.baseline_avg_r or 0),
                "detected_at": a.detected_at.isoformat(),
            }
            for a in decay_qs
        ]
    except Exception:
        snap["unresolved_decay_alerts"] = []

    return snap


# ── The agent ─────────────────────────────────────────────────────────────

SCHEMA_HINT = """{
  "regime_label": "risk_on|risk_off|mean_reverting|trending|blow_off|unknown",
  "regime_confidence": 0.0..1.0,
  "portfolio_health_score": 0.0..1.0,
  "top_concerns": [
    {"kind": "string", "severity": 0.0..1.0, "ref": "string", "text": "string"}
  ],
  "theme_pressures": {"<theme_name>": 0.0..1.0},
  "rule_status_overlay": {"<rule_name>": "active|watch|pause_recommended"},
  "narrative_md": "1-3 short paragraphs in markdown. Tell, don't lecture.",
  "predictions": [
    {"prediction_type": "regime_persistence|rule_decay_continues|rule_recovers|...",
     "predicted_value": "string concise label",
     "confidence": 0.0..1.0,
     "horizon_hours": int,
     "rationale": "one sentence"}
  ]
}"""


class SauronMindAgent(BaseAgent):
    """Central coordination synthesizer.

    Uses the `deep` tier (Opus 4.7) — this agent is THE central coordinator;
    every downstream agent inherits its mistakes. Quality > frequency-
    optimized cost. ~$15-20/day at 30-min cadence; cheap insurance against
    one bad correlated decision propagating across all rules.
    """

    agent_name = "sauron_mind"
    default_tier = "deep"  # Opus 4.7

    def get_system_prompt(self) -> str:
        return (
            "You are Sauron's Mind — the central synthesizer for Sauron Vision, "
            "an autonomous multi-asset trading platform.\n\n"
            "You receive a structured snapshot of: recent system observations "
            "(gate rejects, fills, decay alerts, mutations), open positions, "
            "per-rule recent track records, regime probes (Hurst exponent + "
            "GARCH-lite vol forecasts) on tracked instruments, and unresolved "
            "decay alerts.\n\n"
            "Your job:\n"
            "1. Read the macro/regime context from the regime_probes — most "
            "Hurst < 0.45 across the book = mean-reverting; > 0.55 = trending.\n"
            "2. Cross-reference with rule track records: if trend rules are "
            "decaying AND regime is mean-reverting, the rules aren't broken, "
            "the regime shifted.\n"
            "3. Identify the 3 most actionable concerns. Examples: a theme is "
            "saturated, a rule is decaying for regime reasons (recommend WATCH "
            "not pause), a rule is decaying outright (recommend PAUSE).\n"
            "4. Emit 1-3 falsifiable predictions the platform can grade later. "
            "Bad: 'markets will be volatile'. Good: 'rule X continues decaying "
            "(recent_avg_r < 0) over next 48h, confidence 0.65'.\n\n"
            "Tone: terse, concrete, ZERO hedging. You are Sauron, not a "
            "weather forecaster.\n\n"
            "Respond ONLY with valid JSON in this exact schema:\n"
            f"{SCHEMA_HINT}\n\n"
            "Do not include code fences. Do not include any text before or "
            "after the JSON."
        )

    def build_context(self, **kwargs) -> str:
        snap = kwargs.get("snapshot") or _build_world_snapshot()
        return (
            "World snapshot (JSON):\n\n"
            f"{json.dumps(snap, indent=2, default=str)}\n\n"
            "Synthesize the BrainReport JSON now."
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
        # The prompt forbids prose around the JSON, and the model still
        # occasionally appends commentary — or a second object — after a
        # perfectly valid report. A strict loads() threw the whole
        # synthesis away over the tail ("Extra data: char 1476", live,
        # 2026-08-18). Parse the FIRST complete object; log what follows.
        start = text.find("{")
        if start == -1:
            raise ValueError(f"non-JSON brain output: no object: {text[:200]}")
        try:
            data, end = json.JSONDecoder().raw_decode(text, start)
        except json.JSONDecodeError as e:
            raise ValueError(f"non-JSON brain output: {e}: {text[:200]}")
        tail = text[end:].strip()
        if tail:
            logger.warning("[brain] ignored %d chars of trailing output "
                           "after the report JSON: %.120s", len(tail), tail)
        if not isinstance(data, dict):
            raise ValueError(f"brain returned non-dict: {type(data).__name__}")
        return data


# ── Persistence + calibration ─────────────────────────────────────────────

ALLOWED_REGIMES = {
    "risk_on", "risk_off", "mean_reverting", "trending", "blow_off", "unknown",
}
ALLOWED_RULE_STATUSES = {"active", "watch", "pause_recommended"}


def _persist_report(parsed: dict, snapshot: dict, *, model: str,
                     tokens_in: int, tokens_out: int, cost_usd: float,
                     n_consumed: int, error: str = "") -> "BrainReport":
    """Write a BrainReport row, validating + clamping the parsed payload.

    Always succeeds — bad fields fall back to safe defaults rather than raise.
    """
    from .models import BrainReport

    regime = parsed.get("regime_label") or "unknown"
    if regime not in ALLOWED_REGIMES:
        regime = "unknown"
    try:
        regime_conf = max(0.0, min(1.0, float(parsed.get("regime_confidence", 0))))
    except (TypeError, ValueError):
        regime_conf = 0.0
    try:
        health = max(0.0, min(1.0, float(parsed.get("portfolio_health_score", 0.5))))
    except (TypeError, ValueError):
        health = 0.5

    concerns = parsed.get("top_concerns")
    if not isinstance(concerns, list):
        concerns = []
    concerns = [c for c in concerns if isinstance(c, dict)][:5]

    pressures = parsed.get("theme_pressures")
    if not isinstance(pressures, dict):
        pressures = {}
    # Clamp values 0..1; drop non-floatable.
    cleaned_pressures = {}
    for k, v in pressures.items():
        try:
            cleaned_pressures[str(k)] = max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            continue

    overlay = parsed.get("rule_status_overlay")
    if not isinstance(overlay, dict):
        overlay = {}
    cleaned_overlay = {
        str(k): v for k, v in overlay.items()
        if isinstance(v, str) and v in ALLOWED_RULE_STATUSES
    }

    narrative = parsed.get("narrative_md") or ""
    if not isinstance(narrative, str):
        narrative = ""

    valid_until = timezone.now() + timedelta(minutes=45)  # 30min cadence + grace

    report = BrainReport.objects.create(
        regime_label=regime,
        regime_confidence=regime_conf,
        portfolio_health_score=health,
        top_concerns=concerns,
        theme_pressures=cleaned_pressures,
        rule_status_overlay=cleaned_overlay,
        narrative_md=narrative[:8000],
        model_used=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=Decimal(str(round(cost_usd, 6))),
        n_observations_consumed=n_consumed,
        valid_until=valid_until,
        error=error,
    )
    return report


def _emit_predictions(report, parsed: dict) -> int:
    """Convert the parsed predictions into AgentPrediction rows for Phase-6
    calibration AND Phase-38 Hypothesis rows for the market.

    Each prediction gets:
      - one AgentPrediction (calibration grading)
      - one Hypothesis linked back to the AgentPrediction so resolve_due()
        in the hypothesis market mirrors the outcome both ways

    Mapping prediction_type → hypothesis resolution_criteria:
      regime_persistence    → {kind: regime_holds, regime: predicted_value}
      rule_decay_continues  → {kind: rule_avg_r, rule_name: predicted_value,
                                 comparator: "<", threshold: 0}
      rule_recovers         → {kind: rule_avg_r, rule_name: predicted_value,
                                 comparator: ">=", threshold: 0}
    """
    try:
        from ai_agents.models import AgentPrediction
    except Exception:
        return 0

    try:
        from .hypotheses import post_hypothesis
    except Exception:
        post_hypothesis = None

    preds = parsed.get("predictions")
    if not isinstance(preds, list):
        return 0

    n = 0
    now = timezone.now()
    for p in preds[:5]:
        if not isinstance(p, dict):
            continue
        try:
            ptype = str(p.get("prediction_type") or "brain_call")[:30]
            pval = str(p.get("predicted_value") or "")[:100]
            try:
                conf = max(0.0, min(1.0, float(p.get("confidence", 0.5))))
            except (TypeError, ValueError):
                conf = 0.5
            try:
                horizon_hours = max(1, int(p.get("horizon_hours", 12)))
            except (TypeError, ValueError):
                horizon_hours = 12
            rationale = (p.get("rationale") or "")[:500]
            ap = AgentPrediction.objects.create(
                agent="sauron_mind",
                prediction_type=ptype,
                predicted_value=pval,
                confidence=conf,
                expected_resolution_at=now + timedelta(hours=horizon_hours),
                evaluation_notes=rationale,
            )

            # Mirror as a Hypothesis where we can grade it.
            if post_hypothesis is not None:
                criteria = _prediction_to_hypothesis_criteria(ptype, pval)
                if criteria:
                    try:
                        post_hypothesis(
                            claim_text=f"[{ptype}] {pval}",
                            source_agent="sauron_mind",
                            claim_payload={"prediction_type": ptype,
                                            "predicted_value": pval,
                                            "rationale": rationale},
                            resolution_criteria=criteria,
                            confidence=conf,
                            horizon_hours=horizon_hours,
                            brain_report=report,
                            agent_prediction=ap,
                        )
                    except Exception:  # pragma: no cover
                        pass
            n += 1
        except Exception:  # pragma: no cover
            continue
    return n


def _prediction_to_hypothesis_criteria(ptype: str, pval: str) -> Optional[dict]:
    """Translate a brain prediction type → hypothesis resolution_criteria.

    Returns None when the prediction can't be auto-graded by the existing
    resolvers — the AgentPrediction still gets created, but no Hypothesis
    is posted.
    """
    if ptype == "regime_persistence" and pval:
        return {"kind": "regime_holds", "regime": pval}
    if ptype == "rule_decay_continues" and pval:
        return {"kind": "rule_avg_r", "rule_name": pval,
                "comparator": "<", "threshold": 0.0, "window_days": 7}
    if ptype == "rule_recovers" and pval:
        return {"kind": "rule_avg_r", "rule_name": pval,
                "comparator": ">=", "threshold": 0.0, "window_days": 7}
    return None


# ── Top-level entry point ─────────────────────────────────────────────────

def synthesize_now() -> dict:
    """Run one synthesis cycle. Always returns a dict summary; never raises.

    Used by both the Celery beat and the admin "Run now" button.
    """
    from .models import BrainObservation

    snapshot = _build_world_snapshot()
    obs_ids = [o["id"] for o in snapshot.get("observations", [])]

    try:
        agent = SauronMindAgent()
        # We run the agent manually (not via .run()) because we want to
        # control persistence + handle errors as data, not exceptions.
        system_prompt = agent.get_system_prompt()
        context = agent.build_context(snapshot=snapshot)
        raw, usage = agent.provider.complete(
            system_prompt=system_prompt,
            user_message=context,
            model=agent.model,
        )
        parsed = agent.parse_response(raw)
    except Exception as e:
        logger.warning("[brain] synthesis failed: %s", e)
        report = _persist_report(
            parsed={}, snapshot=snapshot, model="error",
            tokens_in=0, tokens_out=0, cost_usd=0.0,
            n_consumed=0, error=str(e)[:1000],
        )
        # Phase-46 — staff alert on streak of consecutive failures.
        try:
            from .health import maybe_alert_brain_failures
            maybe_alert_brain_failures()
        except Exception:  # pragma: no cover
            pass
        return {"ok": False, "error": str(e), "report_id": report.id}

    # Mark consumed.
    if obs_ids:
        BrainObservation.objects.filter(id__in=obs_ids).update(
            consumed_by_brain_at=timezone.now())

    report = _persist_report(
        parsed=parsed, snapshot=snapshot,
        model=agent.model,
        tokens_in=usage.get("input_tokens", 0),
        tokens_out=usage.get("output_tokens", 0),
        cost_usd=float(usage.get("cost_usd", 0)),
        n_consumed=len(obs_ids),
    )
    n_predictions = _emit_predictions(report, parsed)

    # Publish the regime to the knowledge graph NOW rather than waiting for
    # the 03:00 consolidation. The graph labels its node CURRENT, and a node
    # that only moves once a day spent the whole of 2026-08-19 announcing
    # "unknown, confidence 0.00" — the blackout reading from 02:56 — while
    # this very function had already concluded "trending, 0.78" at 05:56.
    # The upsert no-ops when the label and confidence have not moved, so
    # this cannot spam versions; the nightly pass still owns everything else.
    try:
        from .consolidation import _consolidate_regime
        _consolidate_regime()
    except Exception:  # noqa: BLE001 — the graph must never fail a synthesis
        logger.warning("[brain] regime node publish failed", exc_info=True)

    return {
        "ok": True, "report_id": report.id,
        "regime": report.regime_label,
        "regime_confidence": report.regime_confidence,
        "n_observations_consumed": len(obs_ids),
        "n_predictions": n_predictions,
        "tokens_in": report.tokens_in,
        "tokens_out": report.tokens_out,
        "cost_usd": float(report.cost_usd),
    }
