"""THE COUNCIL's pages (2026-10-08, ai_agents/agents/council.py).

  /council/               the record: each voice's weight, earned only by
                          its graded calls, the benchmark rows, the
                          Hand of the Emperor per cell and the Emperor
                          against his Hand, the people's mood and what the
                          trades returned under it, the weights by regime,
                          the recent sittings (staff).
  /council/ask/           POST: "Ask the council" on a LIVE TAKE TRADE
                          ticket. On demand only; it queues a sitting on
                          the ai worker and answers at once.
  /council/<id>/          GET: one sitting as the ticket polls it.

A hand trade is never blocked by a voice: nothing here is on the
preview's or the execution's path. link_ticket_session runs after a
trade was taken, to grade the sitting on it, and never raises.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from django.utils import timezone

logger = logging.getLogger(__name__)


def _number(body, field):
    """(value, None) or (None, reason), with _parse_trade_body's rules
    (dashboard/views.py): absent is None, a bool is not a number, and the
    value must be finite. Copied, not shared, so neither drifts the other."""
    raw = body.get(field)
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, bool):
        return None, f"{field} must be a number"
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None, f"{field} must be a number"
    if not math.isfinite(val):
        return None, f"{field} must be a finite number"
    return val, None


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))
    except (TypeError, ValueError):
        return False


@login_required
def council_ask(request):
    """POST {symbol, side, stop, target, qty?, entry?, leverage?,
    signal_id?} — ask the council about a LIVE ticket. Refusals answer
    {"ok": false, "why"} in words; a sitting answers 202 {"ok": true,
    "id"} and sits on the ai worker."""
    from ai_agents.agents import council as C
    from ai_agents.council_models import CouncilSession
    from bot_program.manual_trade import EXECUTABLE_CLASS, manual_config_if_any
    from core.platform_control import is_component_enabled
    from instruments.models import Instrument

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "why": "Body must be JSON"},
                            status=400)
    if not isinstance(body, dict):
        return JsonResponse({"ok": False, "why": "Body must be a JSON object"},
                            status=400)
    symbol = str(body.get("symbol") or "").strip().upper()
    inst = Instrument.objects.filter(symbol=symbol).first() if symbol else None
    if inst is None:
        return JsonResponse({"ok": False, "why": "unknown symbol"},
                            status=400)
    side = str(body.get("side") or "").strip().upper()
    if side not in ("BUY", "SELL"):
        return JsonResponse({"ok": False, "why": "side must be BUY or SELL"},
                            status=400)
    nums = {}
    for field in ("stop", "target", "qty", "entry", "leverage"):
        val, err = _number(body, field)
        if err:
            return JsonResponse({"ok": False, "why": err}, status=400)
        nums[field] = val
    for field in ("stop", "target"):
        if nums[field] is None or nums[field] <= 0:
            return JsonResponse({"ok": False,
                                 "why": f"{field} must be above 0"},
                                status=400)
    # A positive integer or None. Not `in (None, "", True, False)`: 1 == True
    # and 0 == False, so a membership test would drop signal #1.
    raw_signal = body.get("signal_id")
    signal_id = None
    if isinstance(raw_signal, (int, str)) and not isinstance(raw_signal, bool):
        try:
            signal_id = int(str(raw_signal).strip())
        except (TypeError, ValueError):
            signal_id = None
        if signal_id is not None and signal_id <= 0:
            signal_id = None

    user = request.user
    if not is_component_enabled(C.COUNCIL_TICKET_SWITCH):
        return JsonResponse({"ok": False, "why": C.OFF_WORDS})
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return JsonResponse({"ok": False, "why": C.NO_KEY_WORDS})
    cls = EXECUTABLE_CLASS.get(inst.asset_class)
    cfg = manual_config_if_any(user, cls) if cls else None
    if cfg is None or getattr(cfg, "mode", "paper") != "live":
        return JsonResponse({"ok": False, "why": C.PAPER_WORDS})
    # A live config whose eToro row has Demo ticked places on eToro's DEMO
    # portfolio (broker_router._etoro_client_for), and a Saxo SIM, OANDA
    # practice or Alpaca paper client on its venue's rehearsal world
    # (AssetBot.VENUE_WORLDS): never argued as real money
    # (AssetBot.rehearsal_client). Asked of the same router the ticket
    # fills through; a router that cannot answer refuses too, unbilled.
    try:
        from bot_program.asset_engine.base import AssetBot
        from bot_program.engine.broker_router import client_for_symbol
        demo = AssetBot.rehearsal_client(
            client_for_symbol(user, inst.symbol, cfg))
    except Exception as e:  # noqa: BLE001 — unsure is not real money
        logger.warning("[council] ticket venue unread: %s", e)
        demo = True
    if demo:
        return JsonResponse({"ok": False, "why": C.PAPER_WORDS})

    now = timezone.now()
    # The same ticket asked twice is one sitting: answered before the
    # in-flight and cap refusals, because a sitting already paid for costs
    # nothing to show again.
    for prev in CouncilSession.objects.filter(
            user=user, origin="ticket", symbol=inst.symbol, side=side,
            created_at__gte=now - timedelta(minutes=C.COUNCIL_ASK_REUSE_MIN)
    ).exclude(status=CouncilSession.SILENT).order_by("-created_at")[:5]:
        if _same(prev.stop, nums["stop"]) and _same(prev.target,
                                                    nums["target"]):
            return JsonResponse({"ok": True, "id": prev.id, "reused": True})
    busy = CouncilSession.objects.filter(
        user=user, origin="ticket",
        status__in=(CouncilSession.QUEUED, CouncilSession.SITTING),
        created_at__gte=now - timedelta(minutes=10)).exists()
    if busy:
        return JsonResponse({"ok": False, "why": C.BUSY_WORDS}, status=409)
    today = CouncilSession.objects.filter(
        user=user, origin="ticket",
        created_at__gte=now.replace(hour=0, minute=0, second=0,
                                    microsecond=0)).count()
    if today >= C.COUNCIL_TICKET_SITTINGS_PER_DAY:
        return JsonResponse({"ok": False, "why": C.cap_words(today)})
    from ai_agents.agents.trade_debate import DEBATE_EST_USD
    from ai_agents.spend import can_spend
    allowed, reason = can_spend(tier="balanced",
                                estimated_usd=6 * DEBATE_EST_USD,
                                line="core")
    if not allowed:
        return JsonResponse({"ok": False, "why": C.budget_words(reason)})

    from ai_agents.calibration import mark_for_symbol
    from django.db import transaction
    mark = None
    try:
        mark = mark_for_symbol(inst.symbol)
    except Exception:  # noqa: BLE001 — the ticket's own entry stands
        mark = None
    rep = C._regime()
    from bot_program.manual_trade import MANUAL_RULE
    session = CouncilSession.objects.create(
        origin="ticket", venue="live", status=CouncilSession.QUEUED,
        user=user, config=cfg, symbol=inst.symbol,
        # the lane's class (an ETF trades in the stock lane), as the bot
        # lane records it, so the two pool in one weight cell
        asset_class=str(cls)[:12], side=side,
        rule_name=MANUAL_RULE, entry=mark or nums["entry"],
        stop=nums["stop"], target=nums["target"], qty=nums["qty"],
        horizon_hours=C._horizon_hours(cfg),
        regime=rep.get("regime") or "unknown",
        regime_confidence=rep.get("confidence"),
        regime_report_id=rep.get("report_id"),
        facts={"signal_id": signal_id, "leverage": (
            int(nums["leverage"]) if nums["leverage"] else None),
            "entry_unverified": mark is None},
        schema_version=C.COUNCIL_SCHEMA_VERSION)
    sid = session.id
    transaction.on_commit(lambda: C._queue(sid, ticket=True))
    return JsonResponse({"ok": True, "id": sid}, status=202)


@login_required
def council_session(request, session_id: int):
    """GET — one sitting as the ticket polls it: its owner's or a staff
    member's, else 404."""
    from ai_agents.agents import council as C
    from ai_agents.council_models import CouncilSession
    s = CouncilSession.objects.filter(id=session_id).first()
    if s is None or (s.user_id != request.user.id
                     and not request.user.is_staff):
        raise Http404("no such sitting")
    return JsonResponse(C.session_payload(s))


def link_ticket_session(user, session_id, trade_id) -> None:
    """Link a ticket's sitting to the hand trade it preceded: its owner's,
    a ticket, not yet linked, the same symbol and side, asked within two
    hours. One fenced update; never raises; refuses nothing."""
    try:
        from bot_program.models import AssetBotTrade
        from ai_agents.council_models import CouncilSession
        from ai_agents.council_grading import _levels_match
        if not session_id or not trade_id:
            return
        trade = AssetBotTrade.objects.filter(
            id=trade_id, config__user=user).first()
        if trade is None:
            return
        meta = trade.metadata or {}
        if trade.paper or meta.get("broker_env") == "paper":
            return      # eToro's demo world: never graded as live
        s = CouncilSession.objects.filter(
            id=int(session_id), user=user, origin="ticket",
            trade__isnull=True, symbol=trade.symbol, side=trade.side,
            created_at__gte=timezone.now() - timedelta(hours=2)).first()
        if s is None:
            return
        CouncilSession.objects.filter(id=s.id, trade__isnull=True).update(
            trade=trade, linked_by="body",
            levels_match=_levels_match(s, trade))
    except Exception as e:  # noqa: BLE001 — a link is never a refusal
        logger.warning("[council] ticket sitting not linked: %s", e)


def _spend(now):
    from django.db.models import Count, Sum

    from ai_agents.agents import council as C
    from ai_agents.models import AgentTask
    # The council's ten ledger names: its own eight and the Executioner and
    # the Champion when the council asks them. A copied debate verdict was
    # billed once, by the debate, and is not the council's spend.
    names = C.COUNCIL_DEBATER_NAMES + C.COUNCIL_AGENT_NAMES
    today = AgentTask.objects.filter(
        agent__in=names, created_at__gte=now.replace(
            hour=0, minute=0, second=0, microsecond=0)).aggregate(
        c=Sum("cost_usd"), n=Count("id"))
    month = AgentTask.objects.filter(
        agent__in=names, created_at__gte=now - timedelta(days=30)).aggregate(
        c=Sum("cost_usd"))
    return {"today": float(today["c"] or 0), "calls": int(today["n"] or 0),
            "month": float(month["c"] or 0)}


def _emperor_words(session) -> str:
    from ai_agents.agents import council as C
    for v in session.voices.all():
        if v.voice == "emperor" and v.status == "spoke":
            return C.verdict_words("emperor", v.answer)
    return "silent"


def _hand_words(session) -> tuple:
    """(who held the Hand at the sitting, whether the chair overruled it)."""
    from ai_agents.agents import council as C
    hand = session.hand or {}
    if not hand:
        return "not read", False
    if not hand.get("voice"):
        if str(hand.get("why_empty") or "").startswith(C.SEAT_UNREAD):
            return C.SEAT_UNREAD, False
        return "no voice had earned it", False
    overruled = any(v.voice == "emperor" and v.status == "spoke"
                    and (v.answer or {}).get("hand_overruled")
                    for v in session.voices.all())
    return (hand.get("name") or C.VOICE_NAMES.get(hand["voice"],
                                                  hand["voice"]), overruled)


def _recent(limit=30):
    from ai_agents.council_models import CouncilSession
    out = []
    for s in (CouncilSession.objects.select_related("trade")
              .prefetch_related("voices").order_by("-created_at")[:limit]):
        if (s.venue or "live") != "live":
            # argued on a SIM, practice or paper client (2026-10-16)
            what = "a rehearsal: not real money"
        elif s.origin == "ticket":
            what = "your ticket"
        elif s.trade_id:
            what = "the bot's order"
        else:
            what = "not sent"
        if s.graded_at and s.truth_r is not None:
            graded = (f"{s.truth_r:+.2f}R "
                      f"({'realized' if s.truth == 'realized' else 'replayed'})")
        elif s.graded_at:
            # the grader is done with it (a repeat, no bars): never again
            graded = f"not measured ({s.grade_notes or 'nothing to grade'})"
        else:
            graded = "not graded yet"
        hand, overruled = _hand_words(s)
        out.append({"when": s.created_at, "what": what, "symbol": s.symbol,
                    "side": s.side, "emperor": _emperor_words(s),
                    "status": s.status, "graded": graded, "id": s.id,
                    "mood": s.mood or "not read", "hand": hand,
                    "overruled": overruled})
    return out


def _mood_now(user) -> dict:
    """THE PEOPLE'S MOOD for this page's reader, now: pure code, fenced."""
    from ai_agents import council_mood as M
    try:
        mood = M.people_mood(user)
    except Exception as e:  # noqa: BLE001 — the page says it
        logger.warning("[council] mood unread: %s", e)
        mood = M.unmeasured_mood(f"the gauge could not be read "
                                 f"({type(e).__name__})")
    inputs = mood.get("inputs") or {}
    return {"level": mood.get("level"), "measured_n": mood.get("measured_n"),
            "of": mood.get("of"), "why": mood.get("why", ""),
            "inputs": [inputs[k] for k in M.INPUTS if k in inputs],
            "caution": M.CAUTION_ONLY}


@staff_member_required
def council_dashboard(request):
    from ai_agents.council_grading import record_matrix
    from ai_agents.council_models import CouncilSession
    from core.platform_control import is_component_enabled
    now = timezone.now()
    cls = (request.GET.get("class") or "").strip()[:12]
    try:
        record = record_matrix(asset_class=cls, now=now)
        record_error = ""
    except Exception as e:  # noqa: BLE001 — the page says it
        logger.warning("[council] record unread: %s", e)
        record, record_error = None, f"The record could not be read ({type(e).__name__})."
    classes = sorted({c for c in CouncilSession.objects.values_list(
        "asset_class", flat=True).distinct() if c})
    from ai_agents.agents import council as C
    return render(request, "dashboard/council.html", {
        "page_id": "council",
        "switches": {"bots": is_component_enabled("council_bots"),
                     "ticket": is_component_enabled("council_ticket"),
                     "debate": is_component_enabled("trade_debate")},
        "spend": _spend(now),
        "record": record, "record_error": record_error,
        "recent": _recent(), "classes": classes, "class_filter": cls,
        "mood_now": _mood_now(request.user),
        "hand_min_n": C.COUNCIL_HAND_MIN_N,
        "hand_min_factor": f"{C.COUNCIL_HAND_MIN_FACTOR:.2f}",
    })
