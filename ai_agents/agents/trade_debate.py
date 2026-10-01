"""The trade debate: the Executioner and the Champion (2026-10-01).

The operator: "a personality that depicts why every position will fail,
and the opposite of it for the second one". Every LIVE bot candidate,
just before its order, is argued twice:

  THE EXECUTIONER  argues why this position will fail — regime, news,
                   the rule's own record, the levels, the crowding — and
                   returns a verdict: pass, cut (a size scale) or veto.
  THE CHAMPION     argues why it will work, and returns back or neutral.

He chose a SHADOW start: for its first DEBATE_SHADOW_N graded live trades
the debate is recorded on the row (metadata["debate"]) and changes
nothing; the outcome of each graded trade is what it is judged on. From
then on it BINDS:
  - the Executioner may cut a size (never below DEBATE_MIN_SCALE) or veto
    an entry; it never raises one;
  - past the day's loss limit, an elite entry also needs the Champion to
    win the debate (back, with more conviction than the Executioner).
An unavailable debate (switch off, budget spent, an API error, an answer
that does not parse) changes nothing on an ordinary entry and keeps the
elite door shut: the Executioner never vetoes by silence, the Champion
never unlocks by silence.

Paper candidates are never debated: the debate exists for real money.
"""
import json
import logging

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

#: The PlatformComponent that runs the debate at all (OFF by default).
DEBATE_SWITCH = "trade_debate"
#: Graded live trades the debate is recorded on before it binds.
DEBATE_SHADOW_N = 30
#: The smallest share of its size the Executioner may cut a trade to.
DEBATE_MIN_SCALE = 0.25
#: The model both sides answer on unless the operator sets one per agent
#: on /ai-models/. A per-candidate call at low effort.
DEBATE_MODEL = "claude-opus-5-5"
#: What one side's call is estimated to cost, for the daily AI budget.
DEBATE_EST_USD = 0.03
#: Seconds the order waits for a side before it counts as silent.
DEBATE_TIMEOUT_S = 90

_SCHEMA_EXECUTIONER = """{
  "verdict": "pass" | "cut" | "veto",
  "conviction": 0.0 to 1.0,     // how sure you are this trade fails
  "size_scale": 0.25 to 1.0,    // with "cut": the share of the size to keep
  "killer": string,             // the single most likely way it fails
  "reasons": [string, ...]      // at most 5 short bullets
}"""

_SCHEMA_CHAMPION = """{
  "verdict": "back" | "neutral",
  "conviction": 0.0 to 1.0,     // how sure you are this trade works
  "edge": string,               // the single best reason it works
  "reasons": [string, ...]      // at most 5 short bullets
}"""


def _clean_json(raw: str) -> dict:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def _unit(value, default=0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v)) if v == v else default


def _agent_model(agent_name: str) -> str:
    """The operator's per-agent model on /ai-models/, else DEBATE_MODEL."""
    try:
        from ai_agents.catalog import known_model
        from ai_agents.models import AIModelSetting
        row = AIModelSetting.objects.filter(scope="agent",
                                            key=agent_name).first()
        if row and row.model_id and known_model(row.model_id):
            return row.model_id
    except Exception:  # noqa: BLE001 — the table may not exist yet
        pass
    return DEBATE_MODEL


class _DebateAgent(BaseAgent):
    default_tier = "fast"   # budget class and effort: low, per candidate

    def __init__(self, provider: str = None, model: str = None):
        super().__init__(provider=provider,
                         model=model or _agent_model(self.agent_name))

    def build_context(self, **kwargs) -> str:
        return kwargs.get("brief", "")


class ExecutionerAgent(_DebateAgent):
    agent_name = "debate_executioner"

    def get_system_prompt(self) -> str:
        return f"""You are THE EXECUTIONER, Sauron Vision's prosecutor of trades.

A live trade with real money is about to open. Your only job is to find
why it will FAIL: a regime it fights, news against it, a rule whose real
record is thin or decaying, a stop that sits where the market routinely
reaches, a target that needs a move the instrument rarely makes, costs
that eat the edge, a crowded side, a correlated book. Be specific to THIS
trade; never argue in generalities.

Then judge honestly. Most trades the platform proposes have passed many
gates already: "pass" is right when your case is weak. "cut" (with a
size_scale) when the case is real but not decisive. "veto" only when the
trade is clearly wrong today.

Return JSON ONLY, no prose, in this schema:
{_SCHEMA_EXECUTIONER}"""

    def parse_response(self, raw_response: str) -> dict:
        data = _clean_json(raw_response)
        verdict = str(data.get("verdict", "pass")).lower()
        if verdict not in ("pass", "cut", "veto"):
            raise ValueError(f"unknown verdict {verdict!r}")
        scale = 1.0
        if verdict == "cut":
            scale = max(DEBATE_MIN_SCALE, _unit(data.get("size_scale"), 1.0))
        return {"verdict": verdict, "conviction": _unit(data.get("conviction")),
                "size_scale": round(scale, 4),
                "killer": str(data.get("killer", ""))[:300],
                "reasons": [str(r)[:200] for r in
                            list(data.get("reasons") or [])[:5]]}


class ChampionAgent(_DebateAgent):
    agent_name = "debate_champion"

    def get_system_prompt(self) -> str:
        return f"""You are THE CHAMPION, Sauron Vision's advocate of trades.

A live trade with real money is about to open. Your only job is to make
the strongest honest case that it will WORK: the rule's measured edge,
the regime behind it, the levels, the reward against the risk, the
timing. Be specific to THIS trade; never argue in generalities.

Then judge honestly: "back" when the case is genuinely strong, "neutral"
when it is not. Your conviction is weighed against a prosecutor's; an
inflated one is worth nothing.

Return JSON ONLY, no prose, in this schema:
{_SCHEMA_CHAMPION}"""

    def parse_response(self, raw_response: str) -> dict:
        data = _clean_json(raw_response)
        verdict = str(data.get("verdict", "neutral")).lower()
        if verdict not in ("back", "neutral"):
            raise ValueError(f"unknown verdict {verdict!r}")
        return {"verdict": verdict, "conviction": _unit(data.get("conviction")),
                "edge": str(data.get("edge", ""))[:300],
                "reasons": [str(r)[:200] for r in
                            list(data.get("reasons") or [])[:5]]}


# ── the brief both sides read ─────────────────────────────────────────────

def candidate_brief(bot, cand, qty: float) -> str:
    """One plain-text brief of a candidate: the trade, the rule's real
    record, the decision's own reasons, the regime and the class's news.
    Every read is fenced: a missing piece is said, never invented."""
    lines = []
    price, stop, target = (float(cand.price), float(cand.stop),
                           float(cand.target))
    risk = abs(price - stop) / price if price else 0.0
    reward = abs(target - price) / price if price else 0.0
    cost = float((getattr(cand, "cost", None) or {}).get("fraction") or 0.0)
    net_rr = (max(0.0, reward - cost) / (risk + cost)) if risk > 0 else 0.0
    decision = cand.decision
    lines.append("THE TRADE")
    lines.append(f"  {cand.symbol} ({cand.asset_class}) "
                 f"{getattr(decision, 'direction', '?')} — real money, eToro")
    lines.append(f"  entry {price:g}, stop {stop:g} ({risk:.2%} away), "
                 f"target {target:g} ({reward:.2%} away)")
    lines.append(f"  round-trip cost {cost:.3%}, net reward:risk {net_rr:.2f}")
    lines.append(f"  size {qty:g} units, risk at the stop "
                 f"{qty * abs(price - stop) * float(cand.value_per_unit or 1):,.2f}")
    lines.append(f"  rule {getattr(decision, 'rule_name', '') or '?'}, "
                 f"score {float(getattr(decision, 'score', 0) or 0):.3f}")
    reasons = list(getattr(decision, "reasons", None) or [])[:6]
    if reasons:
        lines.append("  the platform's reasons: " + " | ".join(
            str(r)[:160] for r in reasons))
    try:
        from bot_program.bot_grading import VENUE_LIVE, bot_track_record_detail
        rec = bot_track_record_detail(
            getattr(decision, "rule_name", "") or "",
            bot._instrument_class(cand.symbol), min_n=1, venue=VENUE_LIVE)
        if isinstance(rec, dict) and rec:
            lines.append(f"  the rule's REAL record on this class: n "
                         f"{rec.get('n')}, win rate {rec.get('win_rate')}, "
                         f"average R {rec.get('expectancy')}")
        else:
            lines.append("  the rule's real record on this class: none yet")
    except Exception as e:  # noqa: BLE001
        lines.append(f"  the rule's record could not be read ({type(e).__name__})")
    elite = getattr(cand, "elite", None)
    if isinstance(elite, dict) and elite.get("elite"):
        lines.append("  NOTE: the day is past its loss limit; this is an "
                     "elite entry at half size")
    try:
        from bot_program.news_risk import news_risk_by_class
        news = (news_risk_by_class() or {}).get(cand.asset_class) or {}
        if news:
            lines.append(f"\nNEWS, {cand.asset_class}, 24h: average sentiment "
                         f"{news.get('avg_sent')}, urgent {news.get('n_urgent')}, "
                         f"high-impact events ahead {news.get('events_24h')}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from brain.context import context_for_prompt
        brain = context_for_prompt()
        if brain:
            lines.append("\nTHE BRAIN'S READ OF THE MARKET\n" + brain[:3000])
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


# ── the debate ────────────────────────────────────────────────────────────

def graded_count() -> int:
    """Live trades that carry a debate and have closed with a P&L: what
    the shadow period counts."""
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.filter(
        paper=False, status="CLOSED", pnl__isnull=False,
        metadata__has_key="debate").count()


def debate_candidate(bot, cand, qty: float) -> dict:
    """Run both sides on one live candidate. Never raises.

    {"ran", "binding", "graded", "why", "executioner", "champion",
     "champion_wins", "veto", "scale"}

    `veto` / `scale` are what the Executioner WOULD do; the caller applies
    them only when `binding`. `champion_wins` is False whenever the debate
    did not run in full — the elite door stays shut by silence.
    """
    out = {"ran": False, "binding": False, "graded": 0, "why": "",
           "executioner": None, "champion": None, "champion_wins": False,
           "veto": False, "scale": 1.0}
    try:
        from core.platform_control import is_component_enabled
        if not is_component_enabled(DEBATE_SWITCH):
            out["why"] = f"{DEBATE_SWITCH} is OFF"
            return out
        out["graded"] = graded_count()
        out["binding"] = out["graded"] >= DEBATE_SHADOW_N
        from ai_agents.spend import can_spend
        allowed, reason = can_spend(tier="fast",
                                    estimated_usd=2 * DEBATE_EST_USD)
        if not allowed:
            out["why"] = f"AI budget: {reason}"
            return out
        brief = candidate_brief(bot, cand, qty)
    except Exception as e:  # noqa: BLE001 — the debate is beside the order
        out["why"] = f"debate unavailable ({type(e).__name__}: {e})"[:200]
        return out
    # Both sides at once: the order waits on the slower one, not the sum.
    # Each thread closes its own DB connection (run() writes an AgentTask
    # row); a side that has not answered in DEBATE_TIMEOUT_S is silent.
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _Timeout

    def _side(cls):
        from django.db import connection
        try:
            return cls().run(brief=brief)
        finally:
            connection.close()

    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="debate")
    futures = {side: pool.submit(_side, cls) for side, cls in (
        ("executioner", ExecutionerAgent), ("champion", ChampionAgent))}
    for side, fut in futures.items():
        try:
            out[side] = fut.result(timeout=DEBATE_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 — one side's silence is said
            name = "timeout" if isinstance(e, _Timeout) else type(e).__name__
            out["why"] = (out["why"] + f"; {side} unavailable "
                          f"({name})").lstrip("; ")[:200]
    pool.shutdown(wait=False)
    ex, ch = out["executioner"], out["champion"]
    out["ran"] = ex is not None and ch is not None
    if ex is not None:
        out["veto"] = ex["verdict"] == "veto"
        out["scale"] = ex["size_scale"] if ex["verdict"] == "cut" else 1.0
    if out["ran"]:
        out["champion_wins"] = (ch["verdict"] == "back"
                                and ch["conviction"] > ex["conviction"])
    logger.info("[debate] %s %s: executioner %s (%.2f), champion %s (%.2f) "
                "— %s", cand.symbol, getattr(cand.decision, "direction", "?"),
                (ex or {}).get("verdict"), (ex or {}).get("conviction", 0),
                (ch or {}).get("verdict"), (ch or {}).get("conviction", 0),
                "BINDING" if out["binding"] else
                f"shadow {out['graded']}/{DEBATE_SHADOW_N}")
    return out
