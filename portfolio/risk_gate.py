"""Unified pre-trade risk gate — Phase 2.

Single function `evaluate_proposed_trade()` that combines every Phase-1 + Phase-2
check a proposed trade should pass:

  - position-size cap vs. portfolio max_single_position_pct
  - correlation to the existing open book (PositionSizer.correlation_aware_scale)
  - signal-rule decay (signals.performance.decay_flag), if a rule_name is given
  - portfolio risk metrics snapshot (RiskEngine.calculate_var)
  - a unified scale factor (product of correlation + future per-check scales)

Returns a dict the caller can act on:

    {
      "ok": bool,                  # True iff no hard block
      "scale": 0..1,               # multiplicative size scale to apply
      "intended_size_usd": float,
      "approved_size_usd": float,  # intended * scale, capped to position limit
      "reasons": [str, ...],       # human-readable explanations (always non-empty)
      "checks": {
          "position_cap":       {...},
          "correlation":        {...},
          "decay":              {...},   # only present if rule_name supplied
          "var_snapshot":       {...},
      },
    }
"""
from __future__ import annotations


def evaluate_proposed_trade(
    portfolio,
    instrument,
    intended_size_usd: float,
    *,
    rule_name: str | None = None,
    side: str = "long",
    use_ai_check: bool = False,
    ai_context: dict | None = None,
) -> dict:
    """Run every gate check and return a single decision dict.

    `use_ai_check=True` adds a Phase-3 PreTradeSanityAgent call (slow, costs
    Claude tokens). Off by default — the bot's hot path should not block on
    a network round-trip without explicit opt-in.
    """
    from portfolio.position_sizing import PositionSizer
    from portfolio.risk_engine import RiskEngine

    reasons: list[str] = []
    checks: dict = {}
    scale = 1.0

    intended_size_usd = float(intended_size_usd)
    portfolio_value = float(portfolio.current_value or 0)
    sizer = PositionSizer(portfolio)

    # ── 1. position-size cap ────────────────────────────────────────────────
    max_pct = float(portfolio.max_single_position_pct or 100) / 100.0
    cap_usd = portfolio_value * max_pct
    capped = intended_size_usd
    over_cap = False
    if portfolio_value > 0 and intended_size_usd > cap_usd:
        capped = cap_usd
        over_cap = True
        reasons.append(
            f"intended ${intended_size_usd:,.0f} exceeds position cap "
            f"${cap_usd:,.0f} ({max_pct:.0%} of book) — capping"
        )
    checks["position_cap"] = {
        "intended_usd": intended_size_usd,
        "cap_usd": round(cap_usd, 2),
        "max_pct": max_pct,
        "over_cap": over_cap,
    }

    # ── 2. correlation to open book ────────────────────────────────────────
    corr_result = sizer.correlation_aware_scale(instrument)
    checks["correlation"] = corr_result
    scale *= float(corr_result["scale"])
    if corr_result["scale"] < 1.0:
        reasons.append(corr_result["reason"])

    # ── 3. signal-rule decay (Phase 1 → Phase 2 link) ──────────────────────
    if rule_name:
        from signals.performance import decay_flag
        decay = decay_flag(rule_name)
        checks["decay"] = decay
        if decay["is_decaying"]:
            scale *= 0.5
            reasons.append(
                f"rule '{rule_name}' is decaying "
                f"(recent {decay['recent_expectancy']:+.2f}R vs baseline "
                f"{decay['baseline_expectancy']:+.2f}R) — halving size"
            )

    # ── 4. portfolio-level risk snapshot ───────────────────────────────────
    try:
        engine = RiskEngine(portfolio)
        var = engine.calculate_var()
    except Exception as e:
        var = {"error": str(e)}
    checks["var_snapshot"] = var

    # ── 5. (optional) Phase-3 AI sanity check ──────────────────────────────
    if use_ai_check:
        try:
            from ai_agents.agents.pretrade_sanity import check_proposed_trade
            from ai_agents.calibration import trust_adjustment_for
            ai_kwargs = ai_context or {}
            verdict = check_proposed_trade(
                symbol=instrument.symbol,
                direction=side,
                entry=ai_kwargs.get("entry"),
                stop=ai_kwargs.get("stop"),
                target=ai_kwargs.get("target"),
                rule_name=rule_name,
                regime_summary=ai_kwargs.get("regime_summary", ""),
                news_summary=ai_kwargs.get("news_summary", ""),
                rule_perf_summary=ai_kwargs.get("rule_perf_summary", ""),
            )

            # Phase-6 calibration: dampen the AI scale by the agent's
            # historical reliability. Untrusted agents have less influence.
            raw_scale = float(verdict.get("scale", 1.0))
            trust = trust_adjustment_for("pretrade_sanity")
            # Scale toward 1.0 when trust is low (agent has less ability
            # to push the gate away from "go").
            adjusted_scale = 1.0 - (1.0 - raw_scale) * trust

            verdict["raw_scale"] = raw_scale
            verdict["trust_adjustment"] = trust
            verdict["adjusted_scale"] = round(adjusted_scale, 4)
            checks["ai_sanity"] = verdict
            scale *= adjusted_scale

            if verdict.get("verdict") == "abort" and trust >= 1.0:
                reasons.append(f"AI sanity check ABORT: {verdict.get('rationale', '')}")
            elif adjusted_scale < 1.0:
                trust_note = f" (trust ×{trust:.2f})" if abs(trust - 1.0) > 0.01 else ""
                reasons.append(
                    f"AI sanity scale {adjusted_scale:.2f}{trust_note}: "
                    f"{verdict.get('rationale', '')}"
                )

            # Phase-6: log the prediction itself for calibration. We tie it
            # to the linked Signal if the caller passed one in ai_context.
            linked_signal = (ai_context or {}).get("linked_signal")
            if linked_signal is not None:
                try:
                    from ai_agents.calibration import log_trade_prediction
                    # Confidence: scale of 1.0 = strong "go" (high prob hit_target);
                    # scale of 0.0 = strong "abort". Map linearly.
                    log_trade_prediction(
                        agent="pretrade_sanity",
                        signal=linked_signal,
                        predicted_outcome="hit_target" if raw_scale >= 0.5 else "stopped_out",
                        confidence=raw_scale if raw_scale >= 0.5 else 1.0 - raw_scale,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "[risk_gate] log_trade_prediction failed: %s", e
                    )
        except Exception as e:
            checks["ai_sanity"] = {"error": str(e), "verdict": "go", "scale": 1.0}
            # Best-effort: AI failure must not block trading.

    # ── final composite ────────────────────────────────────────────────────
    approved = round(capped * scale, 2)
    ok = approved > 0  # the gate itself does not hard-block; it sizes down.

    if not reasons:
        reasons.append("no risk constraints triggered")

    return {
        "ok": ok,
        "scale": round(scale, 4),
        "intended_size_usd": round(intended_size_usd, 2),
        "approved_size_usd": approved,
        "reasons": reasons,
        "checks": checks,
    }
