"""Phase 49 — Earnings Reviewer agent.

Modeled after Anthropic's May-2026 Earnings Reviewer template: a deep-dive
AI agent that reads an earnings event for a held instrument and produces
structured analysis (themes, risks, direction, suggested action).

Uses our existing BaseAgent / Opus 4.7 infrastructure rather than the
Managed Agents API — keeps cost in our budget and lets the agent read
our own database directly (positions, news, AI sentiment, regime context)
instead of going through MCP connectors that require enterprise data
licenses we don't have.

Architecture stays consistent with the brain/strategist/critic/generator:
  _build_review_snapshot()  → gathers inputs
  EarningsReviewerAgent     → BaseAgent subclass, deep tier
  _persist_review()         → clamps + stores
  scan_due_earnings_now()   → top-level: walks held symbols × recent earnings

Trigger discipline (avoid noise / cost):
  1. Only events from the last 48h whose title matches a HELD symbol
  2. Skip if a review already exists for the same (instrument, event_datetime)
  3. Hard cap MAX_REVIEWS_PER_PASS = 5 to bound Opus cost per cycle
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


# ── Trigger / scope tunables ─────────────────────────────────────────────

EARNINGS_LOOKBACK_HOURS = 48
MAX_REVIEWS_PER_PASS = 5
NEWS_LOOKBACK_DAYS = 5
NEWS_MAX_ARTICLES = 12
PRICE_LOOKBACK_DAYS = 7


# ── Held-symbol detection ────────────────────────────────────────────────

def _held_symbols() -> set[str]:
    """Symbols currently held across AssetBotTrade (open) + portfolio Position
    (open). Returns a set of uppercase strings for the matching loop."""
    out: set[str] = set()
    try:
        from bot_program.models import AssetBotTrade
        for s in AssetBotTrade.objects.filter(status__in=("OPEN", "CLOSE_PENDING")).values_list(
                "symbol", flat=True):
            if s:
                out.add(s.upper())
    except Exception:
        pass
    try:
        from portfolio.models import Position
        for s in (Position.objects.filter(closed_at__isnull=True)
                   .select_related("instrument")
                   .values_list("instrument__symbol", flat=True)):
            if s:
                out.add(s.upper())
    except Exception:
        pass
    return out


def _instrument_for_symbol(symbol: str):
    try:
        from instruments.models import Instrument
        return Instrument.objects.filter(symbol__iexact=symbol).first()
    except Exception:
        return None


# ── Snapshot for the agent ───────────────────────────────────────────────

def _build_review_snapshot(instrument, event) -> dict:
    """Aggregate all inputs the reviewer needs into one JSON-serializable dict."""
    snap: dict = {
        "as_of": timezone.now().isoformat(),
        "instrument": {
            "symbol": instrument.symbol,
            "name": getattr(instrument, "name", ""),
            "asset_class": getattr(instrument, "asset_class", ""),
        },
        "earnings_event": {
            "title": event.title,
            "datetime": event.datetime.isoformat() if event.datetime else None,
            "actual": event.actual or "",
            "forecast": event.forecast or "",
            "previous": event.previous or "",
            "impact": event.impact,
        },
    }

    # Recent news for this symbol.
    try:
        from scraping.models import NewsArticle
        from django.db.models import Q
        cutoff = timezone.now() - timedelta(days=NEWS_LOOKBACK_DAYS)
        q = (Q(title__icontains=instrument.symbol)
             | Q(content_summary__icontains=instrument.symbol)
             | Q(ai_summary__icontains=instrument.symbol))
        articles = list(
            NewsArticle.objects.filter(q, published_at__gte=cutoff)
            .order_by("-published_at")[:NEWS_MAX_ARTICLES]
            .values("title", "source", "published_at",
                     "ai_sentiment_score", "ai_summary")
        )
        for a in articles:
            a["published_at"] = (
                a["published_at"].isoformat() if a["published_at"] else None)
        snap["news"] = articles
    except Exception:
        snap["news"] = []

    # Price reaction (1d, 5d before/after the event).
    try:
        from market_data.models import PriceData
        days_ahead = max(1, PRICE_LOOKBACK_DAYS)
        bars = list(
            PriceData.objects.filter(
                instrument=instrument, timeframe="1d",
                timestamp__gte=timezone.now() - timedelta(days=days_ahead * 2),
            ).order_by("-timestamp")[:days_ahead * 2]
            .values("timestamp", "open", "close", "volume")
        )
        for b in bars:
            b["timestamp"] = b["timestamp"].isoformat()
            b["open"] = float(b["open"]) if b["open"] is not None else None
            b["close"] = float(b["close"]) if b["close"] is not None else None
        snap["price_bars"] = bars
        # Compute pct move since the event for the agent's convenience.
        if event.datetime and bars:
            pre = next((b for b in bars if b["timestamp"] < event.datetime.isoformat()), None)
            post = bars[0]
            if pre and post and pre["close"]:
                snap["price_move_pct"] = round(
                    (post["close"] - pre["close"]) / pre["close"] * 100, 4)
            else:
                snap["price_move_pct"] = None
        else:
            snap["price_move_pct"] = None
    except Exception:
        snap["price_bars"] = []
        snap["price_move_pct"] = None

    # Brain context (regime + theme pressures + relevant rule overlay).
    try:
        from .context import get_brain_context
        brain_ctx = get_brain_context() or {}
        snap["brain_context"] = {
            "regime_label": brain_ctx.get("regime_label"),
            "regime_confidence": brain_ctx.get("regime_confidence"),
            "theme_pressures": brain_ctx.get("theme_pressures") or {},
        }
    except Exception:
        snap["brain_context"] = {}

    # Holdings — what trades / positions reference this symbol?
    try:
        from bot_program.models import AssetBotTrade
        snap["open_bot_trades"] = list(
            AssetBotTrade.objects.filter(
                symbol__iexact=instrument.symbol, status__in=("OPEN", "CLOSE_PENDING"),
            ).values("id", "side", "qty", "entry_price",
                      "stop_loss", "take_profit", "rule_name")
        )
        for t in snap["open_bot_trades"]:
            for k in ("qty", "entry_price", "stop_loss", "take_profit"):
                if t.get(k) is not None:
                    t[k] = float(t[k])
    except Exception:
        snap["open_bot_trades"] = []

    return snap


# ── The agent ─────────────────────────────────────────────────────────────

REVIEWER_SCHEMA = """{
  "summary_md": "2-4 paragraphs in markdown. Open with the most important sentence. Cover: what happened, market reaction, why it matters for the held position(s).",
  "key_themes": [
    {"kind": "growth|margin|guidance|management|other",
     "text": "concrete observation",
     "severity": 0.0..1.0}
  ],
  "risk_signals": [
    "specific bear-case bullets — empty list if none"
  ],
  "implied_direction": "bullish | bearish | neutral",
  "implied_confidence": 0.0..1.0,
  "suggested_action": "one short sentence operator nudge — e.g. 'reduce size 50% pending follow-up news', 'hold and tighten stop to entry'"
}"""


class EarningsReviewerAgent(BaseAgent):
    """Deep-dive earnings analysis for a held instrument."""

    agent_name = "earnings_reviewer"
    default_tier = "deep"  # Opus 4.7

    def get_system_prompt(self) -> str:
        return (
            "You are the Sauron Vision Earnings Reviewer. An earnings event "
            "just hit for one of our held positions. You receive the event "
            "details, recent news flow, the price reaction, the current "
            "macro regime per Sauron's Mind, and any open trades on this "
            "symbol.\n\n"
            "Your job:\n"
            "1. Summarize what happened in 2-4 paragraphs of plain English. "
            "Open with the most important sentence. NO preambles.\n"
            "2. Surface 3-5 KEY THEMES — what stood out (growth, margin, "
            "guidance, management commentary). Each cites a concrete "
            "observation, not generic 'beat estimates'.\n"
            "3. Flag RISK SIGNALS — specific bear-case items (e.g. "
            "'guidance cut for next quarter', 'inventory buildup'). Empty "
            "list is acceptable if there are none.\n"
            "4. Implied direction (bullish / bearish / neutral) + "
            "confidence (0..1). Calibrated, not aspirational.\n"
            "5. SUGGESTED ACTION — one operator-actionable sentence. "
            "Examples: 'reduce size 50% pending follow-up news', 'hold and "
            "tighten stop to entry', 'no change'.\n\n"
            "Important constraints:\n"
            "- This is for a TRADER reviewing an OPEN POSITION. Not "
            "investment advice for new entries.\n"
            "- If news flow is sparse or contradicts price action, surface "
            "that explicitly — divergences matter more than alignment.\n"
            "- If the macro regime contradicts the fundamental signal "
            "(e.g. great earnings into a risk-off regime), say so.\n\n"
            f"Respond ONLY with valid JSON in this schema:\n{REVIEWER_SCHEMA}\n\n"
            "No code fences, no surrounding text."
        )

    def build_context(self, **kwargs) -> str:
        snap = kwargs.get("snapshot") or {}
        return (
            "Earnings review snapshot (JSON):\n\n"
            f"{json.dumps(snap, indent=2, default=str)}\n\n"
            "Produce the EarningsReview JSON now."
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
            raise ValueError(f"non-JSON earnings reviewer output: {e}: {text[:200]}")
        if not isinstance(data, dict):
            raise ValueError("earnings reviewer returned non-dict")
        return data


# ── Persistence ───────────────────────────────────────────────────────────

ALLOWED_DIRECTIONS = {"bullish", "bearish", "neutral"}


def _persist_review(instrument, event, parsed: dict, snapshot: dict, *,
                     model: str, tokens_in: int, tokens_out: int,
                     cost_usd: float, error: str = "") -> "EarningsReview":
    from .earnings_models import EarningsReview

    direction = parsed.get("implied_direction") or "unknown"
    if direction not in ALLOWED_DIRECTIONS:
        direction = "unknown"

    try:
        confidence = max(0.0, min(1.0, float(parsed.get("implied_confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5

    themes = parsed.get("key_themes")
    if not isinstance(themes, list):
        themes = []
    themes = [t for t in themes if isinstance(t, dict)][:6]

    risks = parsed.get("risk_signals")
    if not isinstance(risks, list):
        risks = []
    risks = [str(r)[:300] for r in risks][:8]

    summary = parsed.get("summary_md") or ""
    if not isinstance(summary, str):
        summary = ""
    suggested = (parsed.get("suggested_action") or "")[:300]

    return EarningsReview.objects.create(
        instrument=instrument,
        event_title=event.title[:300],
        event_datetime=event.datetime,
        summary_md=summary[:8000],
        key_themes=themes,
        risk_signals=risks,
        implied_direction=direction,
        implied_confidence=confidence,
        suggested_action=suggested,
        input_news_count=len(snapshot.get("news") or []),
        input_price_move_pct=snapshot.get("price_move_pct"),
        model_used=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=Decimal(str(round(cost_usd, 6))),
        error=error,
    )


# ── Scanner: find due earnings, dispatch agent ───────────────────────────

def _earnings_events_for_held(*, lookback_hours: int = EARNINGS_LOOKBACK_HOURS):
    """Find recent EconomicEvents whose title contains a held symbol AND
    looks earnings-related. Returns list of (instrument, event) tuples,
    deduped by (instrument_id, event.id).
    """
    out = []
    try:
        from market_data.models import EconomicEvent
    except Exception:
        return out

    held = _held_symbols()
    if not held:
        return out

    cutoff = timezone.now() - timedelta(hours=lookback_hours)
    qs = EconomicEvent.objects.filter(
        datetime__gte=cutoff, datetime__lte=timezone.now(),
    )
    # Heuristic title match for earnings events.
    earnings_qs = qs.filter(title__iregex=r"earnings|EPS|results")
    for ev in earnings_qs:
        title_upper = ev.title.upper()
        for sym in held:
            if sym in title_upper:
                inst = _instrument_for_symbol(sym)
                if inst is None:
                    continue
                out.append((inst, ev))
                break  # one match per event is enough
    return out


def _review_already_exists(instrument, event) -> bool:
    """Skip if we already produced a review for this (instrument, event_datetime)."""
    try:
        from .earnings_models import EarningsReview
        if event.datetime is None:
            return False
        return EarningsReview.objects.filter(
            instrument=instrument,
            event_datetime=event.datetime,
            error="",
        ).exists()
    except Exception:
        return False


def review_one_event(instrument, event) -> Optional[dict]:
    """Run the agent on one earnings event. Returns a summary dict or None
    on irrecoverable error."""
    snapshot = _build_review_snapshot(instrument, event)
    try:
        agent = EarningsReviewerAgent()
        system_prompt = agent.get_system_prompt()
        context = agent.build_context(snapshot=snapshot)
        raw, usage = agent.provider.complete(
            system_prompt=system_prompt, user_message=context,
            model=agent.model,
            agent_name=agent.agent_name,
        )
        parsed = agent.parse_response(raw)
    except Exception as e:
        logger.warning("[earnings-reviewer] failed for %s: %s",
                        instrument.symbol, e)
        review = _persist_review(
            instrument, event, parsed={}, snapshot=snapshot,
            model="error", tokens_in=0, tokens_out=0, cost_usd=0.0,
            error=str(e)[:1000],
        )
        return {"ok": False, "review_id": review.id, "error": str(e)}

    review = _persist_review(
        instrument, event, parsed=parsed, snapshot=snapshot,
        model=agent.model,
        tokens_in=usage.get("input_tokens", 0),
        tokens_out=usage.get("output_tokens", 0),
        cost_usd=float(usage.get("cost_usd", 0)),
    )
    return {
        "ok": True, "review_id": review.id,
        "instrument": instrument.symbol,
        "implied_direction": review.implied_direction,
        "tokens_in": review.tokens_in, "tokens_out": review.tokens_out,
        "cost_usd": float(review.cost_usd),
    }


def scan_due_earnings_now(*,
                            max_reviews: int = MAX_REVIEWS_PER_PASS,
                            lookback_hours: int = EARNINGS_LOOKBACK_HOURS) -> dict:
    """One full pass: find held + recent earnings events, skip dups, dispatch
    agent for up to `max_reviews`. Always returns a dict; never raises."""
    candidates = _earnings_events_for_held(lookback_hours=lookback_hours)
    done = []
    skipped_dup = 0
    for inst, ev in candidates:
        if len(done) >= max_reviews:
            break
        if _review_already_exists(inst, ev):
            skipped_dup += 1
            continue
        result = review_one_event(inst, ev)
        if result is not None:
            done.append(result)

    return {
        "ok": True,
        "n_candidates": len(candidates),
        "n_skipped_existing": skipped_dup,
        "n_reviewed": len(done),
        "reviews": done,
    }
