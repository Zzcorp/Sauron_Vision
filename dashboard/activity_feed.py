"""Sauron's activity, as one log: what the bots, the gate, the agents, the
pipelines and the bell did, newest first.

The operator, 2026-09-28: "pour le système de print des logs de détail de
l'activité de Sauron, un bandeau latéral vertical qui se place sous le
bandeau des signaux et watchlist actuel, avec juste un bout dépassant."
This module is the log that drawer prints (templates/_partials/
activity_drawer.html, static/js/sv-activity.js, served as JSON by
dashboard.views_activity.activity_feed). It invents nothing: every line is
a row some part of the platform already writes.

    trade     AuditLogEntry trade_open / trade_close — the hash chain, the
              one record both the bots and TAKE TRADE write. AssetBotTrade
              is NOT read as well: one source per fact, never both.
    gate      OrchestratorEvent rejects. Every reject is kept; allows are a
              1-in-10 sample (bot_program.orchestrator._log_decision), so
              they are left out rather than printed as if they were all of
              them. The audit chain's gate_reject copy of the same refusal
              is skipped, and so is the bell's (below).
    ai        AgentTask — every LLM call, at the provider's choke point.
    pipeline  PlatformComponent — one line per component at its last run,
              for the components that ran in the last 24 h. The row keeps
              only its latest run, so older runs live in the drawer the
              browser already painted, not here.
    bot       AssetBotConfig.extras last_tick_at / last_tick_status /
              last_tick_note (bot_program.asset_engine.safety
              .write_heartbeat) — one line per enabled bot, its last tick.
    alert     The reader's own Notification rows, less the bell's copies of
              a fill or a gate refusal: those facts are already a trade or
              a gate line, and printing both is the duplicate this log
              exists not to have.
    system    The rest of the audit chain the operator acts on or should
              hear about: rules demoted and restored, setups armed, ops
              commands run, share plans, personas, desk plans that chose or
              displaced something.

Scope, as dashboard.views_day reads it: what belongs to an account (trades,
gates, bots, the bell) is the reader's own; what the platform does for
everyone (pipelines, agents, the audit rows written with no user) is
platform-wide. The drawer is staff-only (views_activity), so figures are
printed, but every title is a sentence and no row is a dict dump.

One bounded query per source, newest first and sliced: six in all, pinned
by tests/test_activity_drawer.py. Each source is fenced on its own — a
missing table or a builder that raises costs the log that source and a
WARNING, never the drawer.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta, timezone as dt_tz
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from dashboard.views_day import _ago

logger = logging.getLogger(__name__)

#: The seven kinds a line can be, in the order the drawer's chips list them.
KINDS = ("trade", "gate", "ai", "pipeline", "bot", "alert", "system")
#: The four levels, quietest first.
LEVELS = ("info", "ok", "warn", "error")

DEFAULT_LIMIT = 60
MAX_LIMIT = 200
#: A component whose last run is older than this is not "activity".
PIPELINE_WINDOW = timedelta(hours=24)
#: A bot tick that says RUNNING and is older than this died mid-tick
#: (bot_program.asset_engine.safety.HEARTBEAT_STALE_SECONDS, the health
#: page's own threshold).
TICK_STALE_S = 1800
#: Enabled bot configs read per call — a fleet is a few dozen.
MAX_BOTS = 200
TITLE_MAX = 160
DETAIL_MAX = 240

#: Audit kinds this log prints. gate_reject is the orchestrator's refusal a
#: second time (OrchestratorEvent is the source); desk_plan is a row per
#: desk tick and is admitted below only when the desk chose or displaced
#: something.
AUDIT_SKIP = ("gate_reject", "desk_plan")


# ── words ────────────────────────────────────────────────────────────────

def iso(at) -> str:
    """ISO-8601 in UTC with a Z, to the millisecond: '2026-09-29T10:04:12.345Z'.
    The Z rather than +00:00 so the value rides a query string unencoded."""
    if at is None:
        return ""
    if timezone.is_naive(at):
        at = timezone.make_aware(at, dt_tz.utc)
    return at.astimezone(dt_tz.utc).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


def _aware(raw):
    """An ISO-8601 string as an aware datetime (naive reads as UTC), or None."""
    try:
        at = parse_datetime(str(raw or "").strip())
    except (TypeError, ValueError):
        return None
    if at is None:
        return None
    if timezone.is_naive(at):
        at = timezone.make_aware(at, dt_tz.utc)
    return at


def parse_since(raw):
    """An ISO-8601 timestamp from a query string, aware, or None when it is
    not one. The '+' of an offset that a query string decoded to a space
    is put back ('...10:04:12 00:00' -> '...10:04:12+00:00')."""
    text = re.sub(r"(:\d\d(?:\.\d+)?) (\d\d:?\d\d)$", r"\1+\2",
                  str(raw or "").strip())
    return _aware(text) if text else None


def _clip(text, limit) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def _first_line(text) -> str:
    for line in str(text or "").splitlines():
        if line.strip():
            return line
    return ""


def _scrubbed(text, limit=DETAIL_MAX) -> str:
    """Free text written for a log, scrubbed of credentials and clipped."""
    from core.secret_scrub import scrub
    return _clip(scrub(_first_line(text)), limit)


def _num(value) -> str:
    """7900.00000000 -> '7,900'; 1.60725571 -> '1.60725571'; '' if none."""
    if value in (None, ""):
        return ""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not d.is_finite():
        return ""
    if d == d.to_integral_value():
        return f"{int(d):,}"
    return format(d.normalize(), ",f")


def _signed(value, places=2) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{n:+,.{places}f}"


def _is_long(side) -> bool:
    return str(side or "").strip().upper() not in ("SELL", "SHORT")


def _words(key) -> str:
    """'rule_demoted' -> 'Rule demoted'."""
    s = str(key or "").replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def _url(name, *args, query="") -> str:
    """A route's path, or '' when it has none for these arguments (a pair
    like BTC/USD cannot ride a <str:> segment)."""
    try:
        path = reverse(name, args=list(args))
    except NoReverseMatch:
        return ""
    return path + (("?" + query) if query else "")


def safe_link(url) -> str:
    """A link the drawer may follow: a same-site path or an http(s) URL.
    A protocol-relative '//host' or a 'javascript:' is no link at all."""
    u = str(url or "").strip()
    if u.startswith("/") and not u.startswith("//"):
        return u
    if u.startswith(("https://", "http://")):
        return u
    return ""


def _event(source, key, at, now, *, kind, level, title, detail="", url=""):
    return {
        "id": f"{source}:{key}",
        "at": iso(at),
        "ago": _ago(max(0.0, (now - at).total_seconds())),
        "kind": kind if kind in KINDS else "system",
        "level": level if level in LEVELS else "info",
        "title": _clip(title, TITLE_MAX),
        "detail": _clip(detail, DETAIL_MAX),
        "url": safe_link(url),
    }


# ── the sources ──────────────────────────────────────────────────────────

def _audit_line(row):
    """(kind, level, title, detail, url) for one audit row, or None."""
    k, d = row["kind"], row["data"] if isinstance(row["data"], dict) else {}
    sym = str(d.get("symbol") or "").upper()
    trade_url = (_url("forensics_detail", d["trade_id"])
                 if isinstance(d.get("trade_id"), int) else "") \
        or _url("positions_list")
    if k == "trade_open":
        verb = f"Bought {sym}" if _is_long(d.get("side")) else f"Sold {sym} short"
        bits = []
        if d.get("qty") not in (None, ""):
            bits.append(f"qty {_num(d.get('qty'))} at {_num(d.get('entry_price'))}")
        if d.get("stop_loss") not in (None, ""):
            bits.append(f"stop {_num(d.get('stop_loss'))}")
        if d.get("take_profit") not in (None, ""):
            bits.append(f"target {_num(d.get('take_profit'))}")
        if d.get("rule_name"):
            bits.append(f"rule {d['rule_name']}")
        return ("trade", "info", f"{verb} · {d.get('mode') or 'paper'}",
                " · ".join(bits), trade_url)
    if k == "trade_close":
        r, pnl = d.get("realized_r"), d.get("pnl")
        try:
            pnl_n = float(pnl) if pnl not in (None, "") else None
        except (TypeError, ValueError):
            pnl_n = None
        result = (f"{float(r):+.2f}R" if isinstance(r, (int, float))
                  else _signed(pnl_n) if pnl_n is not None else "result unknown")
        level = ("ok" if pnl_n and pnl_n > 0 else
                 "warn" if pnl_n and pnl_n < 0 else "info")
        bits = []
        if d.get("exit_price") not in (None, ""):
            bits.append(f"exit {_num(d.get('exit_price'))}")
        if pnl_n is not None:
            bits.append(f"P&L {_signed(pnl_n)}")
        if d.get("outcome"):
            bits.append(str(d["outcome"]).replace("_", " "))
        if isinstance(d.get("duration_minutes"), (int, float)):
            bits.append(f"held {int(d['duration_minutes'])} min")
        if d.get("mode"):
            bits.append(str(d["mode"]))
        return ("trade", level, f"Closed {sym} · {result}", " · ".join(bits),
                trade_url)
    if k == "brain_soft_block":
        return ("gate", "warn", f"The brain held back an entry on {sym}",
                " · ".join(x for x in (
                    f"rule {d['rule_name']}" if d.get("rule_name") else "",
                    str(d.get("advisory_status") or "").replace("_", " "),
                    str(d.get("advisory_source") or "")) if x),
                _url("audit_dashboard"))
    if k == "desk_plan":
        chosen, displaced = d.get("n_chosen") or 0, d.get("n_displaced") or 0
        cands = d.get("n_candidates") or 0
        title = f"The capital desk chose {chosen} of {cands} entries"
        if displaced:
            title += f", displaced {displaced}"
        return ("bot", "error" if d.get("error") else "info", title,
                " · ".join(x for x in (
                    str(d.get("venue") or ""), str(d.get("mode") or ""),
                    f"budget {_num(d.get('budget'))}" if d.get("budget") else "",
                    _scrubbed(d.get("error")) if d.get("error") else "") if x),
                _url("audit_dashboard"))
    if k == "rule_demoted":
        return ("system", "warn", f"Rule {d.get('rule_name') or '?'} demoted",
                " · ".join(x for x in (str(d.get("criterion") or "").replace("_", " "),
                                       _scrubbed(d.get("notes"))) if x),
                _url("rule_control_dashboard"))
    if k == "rule_restored":
        by = d.get("restored_by")
        return ("system", "ok", f"Rule {d.get('rule_name') or '?'} restored",
                f"by {by}" if by else "", _url("rule_control_dashboard"))
    if k.startswith("proposal_"):
        return ("system", "ok" if k == "proposal_approved" else "info",
                f"Proposal {d.get('proposed_name') or '#' + str(d.get('proposal_id') or '?')} "
                f"{k.split('_', 1)[1]}",
                f"by {d['reviewed_by']}" if d.get("reviewed_by") else "",
                _url("audit_dashboard"))
    if k.startswith("hypothesis_"):
        return ("ai", "info",
                f"Hypothesis {'re-graded' if 'corrected' in k else 'resolved'}: "
                f"{str(d.get('outcome') or 'unknown').replace('_', ' ')}",
                " · ".join(x for x in (_clip(d.get("claim_text"), 140),
                                       str(d.get("source_agent") or "")) if x),
                _url("audit_dashboard"))
    if k == "setup_armed":
        return ("system", "ok", f"Setup {d.get('setup') or '?'} armed",
                " · ".join(x for x in (f"stage {d['stage']}" if d.get("stage") else "",
                                       f"by {d['by']}" if d.get("by") else "") if x),
                _url("setups_dashboard"))
    if k == "ops_run":
        ok = bool(d.get("ok"))
        secs = d.get("seconds")
        return ("system", "ok" if ok else "error",
                f"Ops command {d.get('name') or '?'} "
                + (f"ran in {secs}s" if ok else "failed"),
                "", _url("ops_dashboard"))
    if k == "ops_run_refused":
        return ("system", "warn", f"Ops command {d.get('name') or '?'} refused",
                _clip(d.get("reason"), DETAIL_MAX), _url("ops_dashboard"))
    if k == "share_plan":
        return ("system", "info",
                f"Share plan #{d.get('plan_id') or '?'} "
                f"{str(d.get('decision') or 'recorded').replace('_', ' ')}",
                " · ".join(x for x in (f"owner {d['owner']}" if d.get("owner") else "",
                                       f"by {d['by']}" if d.get("by") else "") if x),
                _url("audit_dashboard"))
    if k == "persona_apply":
        return ("bot", "info",
                f"{d.get('config') or 'A bot'} now trades as {d.get('persona') or '?'}",
                " · ".join(x for x in (str(d.get("asset_class") or ""),
                                       str(d.get("mode") or ""),
                                       "forced" if d.get("forced") else "") if x),
                _url("asset_bots_dashboard"))
    # Anything else the chain carries: its kind in words and the few
    # scalar facts that name what it was about — never the dict itself.
    facts = [f"{key.replace('_', ' ')} {d[key]}"
             for key in ("name", "symbol", "rule_name", "setup", "config")
             if isinstance(d.get(key), (str, int)) and str(d.get(key)).strip()]
    return ("system", "info", _words(k), " · ".join(facts[:3]),
            _url("audit_dashboard"))


def _audit(user, since, n, now):
    from bot_program.audit_models import AuditLogEntry
    busy_desk = (Q(kind="desk_plan", data__n_chosen__gt=0)
                 | Q(kind="desk_plan", data__n_displaced__gt=0))
    qs = (AuditLogEntry.objects
          .filter(Q(user=user) | Q(user__isnull=True))
          .filter(~Q(kind__in=AUDIT_SKIP) | busy_desk))
    if since is not None:
        qs = qs.filter(created_at__gt=since)
    out = []
    for row in qs.order_by("-created_at", "-id").values(
            "id", "kind", "data", "created_at")[:n]:
        line = _audit_line(row)
        if line is None:
            continue
        kind, level, title, detail, url = line
        out.append(_event("audit", row["id"], row["created_at"], now,
                          kind=kind, level=level, title=title,
                          detail=detail, url=url))
    return out


def _gates(user, since, n, now):
    from bot_program.notifications import class_words, reject_words
    from bot_program.orchestrator_models import OrchestratorEvent
    qs = OrchestratorEvent.objects.filter(user=user, decision="reject")
    if since is not None:
        qs = qs.filter(created_at__gt=since)
    out = []
    for row in qs.order_by("-created_at", "-id").values(
            "id", "asset_class", "symbol", "side", "reason", "created_at")[:n]:
        sym = str(row["symbol"] or "").upper()
        title = (f"Buying {sym} was blocked" if _is_long(row["side"])
                 else f"Selling {sym} short was blocked")
        words = reject_words(row["reason"])
        why = words["clause"]
        why = (why[:1].upper() + why[1:]) if why else " · ".join(words["lines"])
        detail = " · ".join(x for x in (class_words(row["asset_class"], capital=True),
                                        why) if x)
        out.append(_event(
            "gate", row["id"], row["created_at"], now, kind="gate",
            level="warn", title=title, detail=detail,
            url=_url("eye_gate_events",
                     query=f"decision=reject&symbol={sym}" if re.fullmatch(
                         r"[A-Z0-9.\-]+", sym) else "decision=reject")))
    return out


def _ai(user, since, n, now):
    from ai_agents.models import AgentTask
    qs = AgentTask.objects.all()
    if since is not None:
        qs = qs.filter(created_at__gt=since)
    out = []
    for row in qs.order_by("-created_at", "-id").values(
            "id", "agent", "provider", "model", "success", "error",
            "duration_seconds", "input_tokens", "output_tokens", "cost_usd",
            "created_at")[:n]:
        who = _words(row["agent"] or "an agent")
        tokens = (row["input_tokens"] or 0) + (row["output_tokens"] or 0)
        facts = [x for x in (row["provider"], row["model"]) if x]
        if tokens:
            facts.append(f"{tokens:,} tokens")
        if row["cost_usd"]:
            facts.append(f"${float(row['cost_usd']):.4f}")
        if row["success"]:
            secs = row["duration_seconds"] or 0
            title = f"{who} answered" + (f" in {secs:.1f} s" if secs else "")
            level, detail = "ok", " · ".join(facts)
        else:
            from bot_program.telegram_eye import plain_detail
            title = f"{who} failed"
            level = "error"
            detail = " · ".join(x for x in (plain_detail(_first_line(row["error"]), 160),
                                            " · ".join(facts)) if x)
        out.append(_event("ai", row["id"], row["created_at"], now, kind="ai",
                          level=level, title=title, detail=detail,
                          url=_url("ai_tasks_list")))
    return out


PIPELINE_WORDS = {
    "success": ("ok", "ran"),
    "warning": ("warn", "ran with a warning"),
    "error": ("error", "failed"),
    "skipped": ("info", "skipped its run"),
}


def _pipelines(user, since, n, now):
    from core.platform_control import PlatformComponent
    qs = PlatformComponent.objects.filter(last_run_at__gte=now - PIPELINE_WINDOW)
    if since is not None:
        qs = qs.filter(last_run_at__gt=since)
    out = []
    for row in qs.order_by("-last_run_at", "-id").values(
            "key", "name", "is_enabled", "last_run_at", "last_status",
            "last_message")[:n]:
        level, verb = PIPELINE_WORDS.get(row["last_status"] or "", ("info", "ran"))
        name = row["name"] or _words(row["key"])
        detail = _scrubbed(row["last_message"])
        if not row["is_enabled"]:
            detail = " · ".join(x for x in ("switched off", detail) if x)
        stamp = int(row["last_run_at"].timestamp())
        out.append(_event("pipeline", f"{row['key']}:{stamp}", row["last_run_at"],
                          now, kind="pipeline", level=level,
                          title=f"{name} {verb}", detail=detail,
                          url=_url("system_map")))
    return out


def _tick_line(name, status, note, age_s):
    """(level, title, detail) for one bot's last tick."""
    status = str(status or "").upper()
    note = " ".join(str(note or "").split())
    if status == "RUNNING":
        if age_s is not None and age_s > TICK_STALE_S:
            return ("error", f"{name} did not finish its last tick",
                    "the heartbeat still says RUNNING")
        return ("info", f"{name} is ticking", "")
    if status and status != "OK":
        return ("error", f"{name} tick ended {status.lower()}", note)
    low = note.lower()
    if low in ("", "ok"):
        return ("ok", f"{name} ticked · open to new entries", "")
    if low.startswith("ok (unchecked"):
        return ("warn", f"{name} ticked · some gates could not be checked", note)
    if low.startswith(("circuit breaker", "daily loss")):
        return ("warn", f"{name} ticked · entries halted", note)
    return ("info", f"{name} ticked · no new entries", note)


def _bots(user, since, n, now):
    from bot_program.asset_models import AssetBotConfig
    from core.secret_scrub import scrub
    rows = (AssetBotConfig.objects.filter(user=user, enabled=True)
            .order_by("id").values("id", "name", "asset_class", "mode",
                                   "extras")[:MAX_BOTS])
    out = []
    for row in rows:
        extras = row["extras"] if isinstance(row["extras"], dict) else {}
        raw = extras.get("last_tick_at")
        at = _aware(raw) if raw else None
        if at is None or (since is not None and at <= since):
            continue
        age = max(0.0, (now - at).total_seconds())
        name = row["name"] or f"Bot #{row['id']}"
        level, title, note = _tick_line(name, extras.get("last_tick_status"),
                                        extras.get("last_tick_note"), age)
        detail = " · ".join(x for x in (
            str(row["asset_class"] or ""), str(row["mode"] or ""),
            _clip(scrub(note), DETAIL_MAX)) if x)
        out.append(_event("bot", f"{row['id']}:{int(at.timestamp())}", at, now,
                          kind="bot", level=level, title=title, detail=detail,
                          url=_url("asset_bots_dashboard")))
    out.sort(key=lambda e: e["at"], reverse=True)
    return out[:n]


def _alert_marks():
    """{mark: meaning} from the notifier's own table, so a renamed mark
    moves here too. 'mirror' = the bell's copy of a fact another source
    already prints; a level otherwise."""
    from bot_program.notifications import CLOSE_MARKS, NOTIFY_MARKS, OPEN_MARKS
    marks = {
        NOTIFY_MARKS.get("drawdown_warning"): "warn",
        NOTIFY_MARKS.get("broker_unreachable"): "warn",
        NOTIFY_MARKS.get("manual_close_refused"): "warn",
        NOTIFY_MARKS.get("unclaimed_position"): "warn",
        NOTIFY_MARKS.get("track_record_decay"): "warn",
        NOTIFY_MARKS.get("evidence_chain_cold"): "warn",
        # Shared by protection_vanished (a live position with no stop) and
        # the staff warning (a leg that may still be live): the loud one.
        NOTIFY_MARKS.get("protection_vanished"): "error",
    }
    fills = set(OPEN_MARKS.values()) | set(CLOSE_MARKS.values())
    return marks, fills, NOTIFY_MARKS.get("orchestrator_reject"), \
        NOTIFY_MARKS.get("manual_fill_open")


def _alerts(user, since, n, now):
    from alerts.models import Notification
    marks, fills, gate_mark, hand_mark = _alert_marks()
    qs = Notification.objects.filter(user=user)
    if since is not None:
        qs = qs.filter(created_at__gt=since)
    out = []
    # Twice the slice: the mirrors dropped below would otherwise eat it.
    for row in qs.order_by("-created_at", "-id").values(
            "id", "notification_type", "title", "body", "url", "data",
            "created_at")[:n * 2]:
        data = row["data"] if isinstance(row["data"], dict) else {}
        mark = data.get("mark")
        if mark and (mark == gate_mark or mark == hand_mark
                     or (mark in fills and row["notification_type"] == "bot")):
            continue  # the gate line or the trade line already says it
        out.append(_event(
            "alert", row["id"], row["created_at"], now, kind="alert",
            level=marks.get(mark, "info") if mark else "info",
            title=row["title"] or _words(row["notification_type"]),
            detail=_first_line(row["body"]),
            url=safe_link(row["url"]) or _url("notifications_inbox")))
        if len(out) >= n:
            break
    return out


#: (name, builder) in the order they are read. The name is the fence's.
SOURCES = (
    ("audit", _audit),
    ("gates", _gates),
    ("ai", _ai),
    ("pipelines", _pipelines),
    ("bots", _bots),
    ("alerts", _alerts),
)


def activity_events(user, *, since=None, limit=DEFAULT_LIMIT) -> list[dict]:
    """The newest `limit` events across every source, newest first.

    `since` (an aware datetime, or an ISO-8601 string) keeps only events
    strictly newer than it. Each event is {"id", "at", "ago", "kind",
    "level", "title", "detail", "url"} — see the module docstring."""
    if isinstance(since, str):
        since = parse_since(since)
    try:
        limit = max(1, min(MAX_LIMIT, int(limit)))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    now = timezone.now()
    events = []
    for name, build in SOURCES:
        try:
            events.extend(build(user, since, limit, now))
        except Exception as e:  # noqa: BLE001 — one source, one fence
            logger.warning("activity feed: %s unavailable: %s", name, e)
    events.sort(key=lambda e: (e["at"], e["id"]), reverse=True)
    return events[:limit]
