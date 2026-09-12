"""The ops cockpit — /ops/.

"Everything, now": every switch with its last run, every decision queue
with its count and the page that decides it, the broker's reading with
its age, the preflight verdict, and the whole command catalogue — on one
screen. Before 2026-09-12 the decisions lived on eight pages, the shell
twins existed but nothing showed them, and no screen said what was
pending across the platform; an operator asked for "a global and
complete vision of everything" and "a perfect sector for the visibility
of commands". This page is that sector.

Every number carries its source and its age, and reads '—' where nothing
has been measured — an unmeasured queue is not an empty one. Every read
is fenced on its own: one broken model blanks one cell with its reason,
never the page, because a 500 here hides the pending plan an operator
came to decide on.

Two writes exist, and both are narrow. The switch toggles post to the
admin dashboard's own views (with `next=ops` to come back). The Run lane
executes a registered READ-ONLY management command with its FIXED argv
from core.ops_commands and nothing else: no argument ever comes from the
browser, a decide/ops command renders its usage only, and every run and
every refusal is an audit row. Mutating commands stay on the server,
where `--yes` or the PIN keeps its meaning.
"""
import logging
import time
from collections import OrderedDict
from io import StringIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils import timezone

logger = logging.getLogger(__name__)

# The Run lane keeps at most this much of a command's output: a diagnostic
# that prints every bar of every symbol must not become a 5 MB session row.
OUTPUT_CAP = 20_000
LAST_TTL = 3600            # the last output survives an hour of refreshes
PREFLIGHT_TTL = 120        # a refresh does not re-run the preflight
PREFLIGHT_SLOW_TTL = 600   # a run past the guard is kept longer, not re-run
PREFLIGHT_GUARD_SECONDS = 20
# What a non-staff login reads in place of the platform-wide zones.
STAFF_ONLY = "staff only — platform-wide, as on /health/"
# A refused name is echoed into the flash and the audit row. It is the
# browser's own bytes: Postgres JSONB rejects \u0000, so a NUL in the name
# would make record_event swallow the row and the refusal would leave no
# trace (2026-09-12). Printable characters only, capped.
REFUSED_NAME_CAP = 80

# The switch panel's grouping. PlatformComponent.category has four
# declared values; anything else (a future 'feature' category, a typo in a
# seed) lands in 'other' rather than vanishing from the panel.
CATEGORY_ORDER = (
    ("system", "System"),
    ("pipeline", "Pipeline"),
    ("agent", "Agents"),
    ("scraper", "Scrapers"),
    ("other", "Feature / other"),
)


def _age_text(dt, now=None) -> str:
    """'3m ago' / '2.4h ago' / '5d ago', or 'never' for None."""
    if dt is None:
        return "never"
    now = now or timezone.now()
    s = int((now - dt).total_seconds())
    if s < 0:
        s = 0
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400 * 2:
        return f"{s / 3600:.1f}h ago"
    return f"{s // 86400}d ago"


def _cache_get(key):
    try:
        return cache.get(key)
    except Exception as e:  # noqa: BLE001 — a dead Redis is not a 500
        logger.warning("[ops] cache get %s failed: %s", key, e)
        return None


def _cache_set(key, value, ttl):
    try:
        cache.set(key, value, ttl)
    except Exception as e:  # noqa: BLE001
        logger.warning("[ops] cache set %s failed: %s", key, e)


# ── (a) the switches ────────────────────────────────────────────────────
def _switches(now) -> dict:
    from core.platform_control import PlatformComponent

    groups = OrderedDict(
        (k, {"key": k, "label": label, "rows": []}) for k, label in CATEGORY_ORDER)
    n_on = n_off = n_err = 0
    for c in PlatformComponent.objects.order_by("category", "name"):
        group = groups.get(c.category) or groups["other"]
        group["rows"].append({"comp": c, "age": _age_text(c.last_run_at, now)})
        if c.is_enabled:
            n_on += 1
        else:
            n_off += 1
        if c.last_status == "error":
            n_err += 1
    return {
        "groups": [g for g in groups.values() if g["rows"]],
        "on": n_on, "off": n_off, "erroring": n_err,
        "total": n_on + n_off,
        "error": "",
    }


# ── (b) the decision queues ─────────────────────────────────────────────
def _queue(label, url_name, counter, *, decide=True, note=""):
    """One queue row. `counter` returns (count, newest_datetime | None);
    fenced so a broken model renders '—' with the reason, not a 500."""
    from django.urls import reverse
    row = {"label": label, "count": None, "newest": None, "newest_age": "—",
           "url": "", "decide": decide, "note": note, "error": ""}
    try:
        row["url"] = reverse(url_name)
    except Exception as e:  # noqa: BLE001
        row["error"] = f"no page: {e}"
    try:
        count, newest = counter()
        row["count"] = count
        row["newest"] = newest
        row["newest_age"] = _age_text(newest) if newest is not None else "—"
    except Exception as e:  # noqa: BLE001
        logger.warning("[ops] queue %s unreadable: %s", label, e)
        row["error"] = f"{type(e).__name__}: {e}"[:160]
    return row


def _queues(user) -> dict:
    def actuator():
        from signals.models_control import RuleAction
        qs = RuleAction.objects.filter(state=RuleAction.STATE_PROPOSED)
        return qs.count(), qs.order_by("-proposed_at").values_list(
            "proposed_at", flat=True).first()

    def generator():
        from brain.generator_models import GeneratedSetupProposal as G
        qs = G.objects.filter(status=G.STATUS_PENDING)
        return qs.count(), qs.order_by("-created_at").values_list(
            "created_at", flat=True).first()

    def shares():
        from bot_program.share_models import SharePlan
        qs = SharePlan.objects.filter(user=user, state=SharePlan.STATE_PROPOSED)
        return qs.count(), qs.order_by("-proposed_at").values_list(
            "proposed_at", flat=True).first()

    def meta():
        from signals.models_control import MetaAllocation
        qs = MetaAllocation.objects.filter(state=MetaAllocation.STATE_SHADOW)
        return qs.count(), qs.order_by("-proposed_at").values_list(
            "proposed_at", flat=True).first()

    def closes():
        from bot_program.asset_models import AssetBotTrade
        qs = AssetBotTrade.objects.filter(status="CLOSE_PENDING")
        return qs.count(), qs.order_by("-opened_at").values_list(
            "opened_at", flat=True).first()

    def open_live():
        from bot_program.asset_models import AssetBotTrade
        qs = AssetBotTrade.objects.filter(
            status__in=("OPEN", "CLOSE_PENDING"), paper=False)
        return qs.count(), qs.order_by("-opened_at").values_list(
            "opened_at", flat=True).first()

    def open_paper():
        from bot_program.asset_models import AssetBotTrade
        qs = AssetBotTrade.objects.filter(
            status__in=("OPEN", "CLOSE_PENDING"), paper=True)
        return qs.count(), qs.order_by("-opened_at").values_list(
            "opened_at", flat=True).first()

    def research():
        from bot_program.asset_models import AssetBotConfig
        # Filtered in Python: a JSON key lookup differs by engine, and a
        # count that works on SQLite and 500s on Postgres is the failure
        # this page exists to avoid.
        rows = AssetBotConfig.objects.filter(enabled=True).values_list(
            "extras", flat=True)
        n = sum(1 for extras in rows
                if isinstance(extras, dict) and extras.get("research_fleet"))
        return n, None

    shares_note = ""
    try:
        from bot_program.share_allocator import (MAX_APPLIES_PER_DAY,
                                                 applies_used_today)
        shares_note = (f"applied today {applies_used_today(user)}"
                       f"/{MAX_APPLIES_PER_DAY}")
    except Exception as e:  # noqa: BLE001
        shares_note = f"applies today unreadable: {e}"[:120]

    rows = [
        _queue("Rule actuator proposals", "rule_control_dashboard", actuator,
               note="RuleAction proposed"),
        _queue("Generator proposals", "generated_dashboard", generator,
               note="GeneratedSetupProposal pending"),
        _queue("Share plans (yours)", "shares_dashboard", shares,
               note=f"SharePlan proposed · {shares_note}"),
        _queue("Meta-allocation shadows", "allocator_dashboard", meta,
               note="MetaAllocation shadow"),
        _queue("Pending closes", "command_center", closes,
               note="AssetBotTrade CLOSE_PENDING"),
        _queue("Open positions — live", "command_center", open_live,
               decide=False, note="AssetBotTrade OPEN + CLOSE_PENDING, paper=False"),
        _queue("Open positions — paper", "command_center", open_paper,
               decide=False, note="AssetBotTrade OPEN + CLOSE_PENDING, paper=True"),
        _queue("Research-fleet configs enabled", "asset_bots_dashboard", research,
               decide=False, note="AssetBotConfig enabled, extras.research_fleet"),
    ]
    # The strip's one number: what is waiting for a decision. Open
    # positions and the fleet are exposure, not a queue.
    pending = sum((r["count"] or 0) for r in rows if r["decide"])
    unmeasured = any(r["count"] is None for r in rows if r["decide"])
    return {"rows": rows, "pending": pending, "unmeasured": unmeasured}


# ── (c) the broker ──────────────────────────────────────────────────────
def _verdict_lines(output: str) -> list:
    """The BLOCKERS block (or the 'NO BLOCKERS FOUND.' line) out of
    preflight_live's output — the verdict, not the six sections."""
    lines = output.splitlines()
    out = []
    for i, line in enumerate(lines):
        if line.startswith("BLOCKERS") or line.startswith("NO BLOCKERS FOUND"):
            out.append(line.rstrip())
            for nxt in lines[i + 1:]:
                s = nxt.rstrip()
                if not s or s.startswith("=") or s.startswith("WORTH READING"):
                    break
                # Only the numbered blocker lines; the NO-BLOCKERS caveat
                # sentences are the command's, and the card says the same.
                if line.startswith("BLOCKERS"):
                    out.append(s)
            break
    return out


def _preflight(user) -> dict:
    """The preflight verdict for this viewer, cached 120 s per user so a
    refresh does not re-run it. DB-only, so no thread: the guard is the
    wall clock — a run past PREFLIGHT_GUARD_SECONDS is kept ten minutes
    and flagged slow rather than re-run on the next refresh."""
    from django.core.management import call_command
    key = f"ops:preflight:{user.pk}"
    cached = _cache_get(key)
    if cached:
        cached["cached"] = True
        return cached
    buf = StringIO()
    t0 = time.monotonic()
    ok, error = True, ""
    try:
        # One argv item, `--user=NAME`: Django's username validator allows
        # a leading '-', and as a separate item argparse read "-dash" as
        # an option and the card said "error" for that user (2026-09-12).
        call_command("preflight_live", f"--user={user.username}",
                     stdout=buf, stderr=buf)
    except Exception as e:  # noqa: BLE001 — the verdict card says so
        ok, error = False, f"{type(e).__name__}: {e}"[:300]
        logger.warning("[ops] preflight_live failed: %s", e)
    seconds = round(time.monotonic() - t0, 2)
    lines = _verdict_lines(buf.getvalue()) if ok else []
    if not lines and ok:
        verdict = "unknown"
    elif not ok:
        verdict = "error"
    elif lines[0].startswith("NO BLOCKERS"):
        verdict = "clear"
    else:
        verdict = "blocked"
    result = {
        "ok": ok, "error": error, "lines": lines, "verdict": verdict,
        "seconds": seconds, "at": timezone.now(),
        "slow": seconds > PREFLIGHT_GUARD_SECONDS, "cached": False,
    }
    _cache_set(key, result,
               PREFLIGHT_SLOW_TTL if result["slow"] else PREFLIGHT_TTL)
    return result


def _broker(user, now) -> dict:
    out = {"reading": None, "reading_stale": False, "reading_error": "",
           "sync": None, "sync_age": "never", "drawdown": None,
           "governor": None, "drawdown_error": "",
           "live_mode": None, "auto_derisk": None, "mode_error": "",
           "plan_mode": "", "plan_mode_reasons": [], "plan_at": None,
           "preflight": None}
    try:
        from bot_program.capital_truth import (TRACKING_FRESH_SECONDS,
                                               account_equity)
        reading = account_equity(user)
        if reading is not None:
            reading["age_text"] = _age_text(reading["at"], now)
            out["reading_stale"] = reading["age_seconds"] > TRACKING_FRESH_SECONDS
        out["reading"] = reading
    except Exception as e:  # noqa: BLE001
        out["reading_error"] = f"{type(e).__name__}: {e}"[:160]
    try:
        from core.platform_control import PlatformComponent
        sync = PlatformComponent.objects.filter(key="broker_account_sync").first()
        out["sync"] = sync
        if sync is not None:
            out["sync_age"] = _age_text(sync.last_run_at, now)
    except Exception as e:  # noqa: BLE001
        out["reading_error"] = out["reading_error"] or f"sync row: {e}"[:160]
    try:
        from bot_program.capital_truth import equity_drawdown
        from bot_program.share_allocator import governor_for
        dd = equity_drawdown(user)
        if dd is not None:
            dd["pct_text"] = f"{float(dd['drawdown_pct']) * 100:.1f}%"
            dd["hwm_text"] = f"{float(dd['hwm']):,.2f}"
            out["governor"] = governor_for(dd["drawdown_pct"])
        out["drawdown"] = dd
    except Exception as e:  # noqa: BLE001
        out["drawdown_error"] = f"{type(e).__name__}: {e}"[:160]
    try:
        from bot_program.share_allocator import (is_auto_derisk_enabled,
                                                 is_live_mode)
        out["live_mode"] = is_live_mode()
        out["auto_derisk"] = is_auto_derisk_enabled()
    except Exception as e:  # noqa: BLE001
        out["mode_error"] = f"{type(e).__name__}: {e}"[:160]
    # The newest plan's market mode (shock / expansion / normal) — only if
    # the responsive build landed; an older SharePlan has no `mode`.
    try:
        from bot_program.share_models import SharePlan
        latest = SharePlan.objects.filter(user=user).order_by("-proposed_at").first()
        if latest is not None and hasattr(latest, "mode"):
            out["plan_mode"] = latest.mode or ""
            out["plan_mode_reasons"] = list(getattr(latest, "mode_reasons", None) or [])
            out["plan_at"] = latest.proposed_at
    except Exception as e:  # noqa: BLE001
        logger.warning("[ops] newest plan unreadable: %s", e)
    try:
        out["preflight"] = _preflight(user)
    except Exception as e:  # noqa: BLE001
        out["preflight"] = {"ok": False, "error": str(e)[:300], "lines": [],
                            "verdict": "error", "seconds": 0, "at": now,
                            "slow": False, "cached": False}
    return out


# ── the page ────────────────────────────────────────────────────────────
def _last_output(request) -> dict | None:
    """The Run lane's last output for this user: the cache first (it
    survives a session rotation), the session second (it survives a cache
    flush). Both are written by ops_run_command."""
    last = _cache_get(f"ops:last:{request.user.pk}")
    if not last:
        last = request.session.get("ops_last")
    return last or None


@login_required
def ops_dashboard(request):
    from core import ops_commands
    from core.wall_facts import TESTS_GREEN

    now = timezone.now()
    user = request.user
    # /health/'s own rule (views_system_health.system_health): the per-user
    # checks are for anyone, the platform-wide ones are staff's — they
    # expose internal task paths and error text. The switches carry every
    # component's last_message and the queues count every user's rows, so
    # both follow that rule; the broker zone (this viewer's account and
    # plans) and the catalogue stay open to any login (2026-09-12).
    is_staff = bool(user.is_staff or user.is_superuser)

    if not is_staff:
        switches = {"groups": [], "on": None, "off": None, "erroring": None,
                    "total": None, "error": STAFF_ONLY, "staff_only": True}
        queues = {"rows": [], "pending": None, "unmeasured": True,
                  "error": STAFF_ONLY, "staff_only": True}
    else:
        try:
            switches = _switches(now)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ops] switches unreadable: %s", e)
            switches = {"groups": [], "on": None, "off": None, "erroring": None,
                        "total": None, "error": f"{type(e).__name__}: {e}"[:160]}
        try:
            queues = _queues(user)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ops] queues unreadable: %s", e)
            queues = {"rows": [], "pending": None, "unmeasured": True,
                      "error": f"{type(e).__name__}: {e}"[:160]}
    try:
        broker = _broker(user, now)
    except Exception as e:  # noqa: BLE001
        logger.warning("[ops] broker unreadable: %s", e)
        broker = {"reading": None, "reading_error": str(e)[:160],
                  "drawdown": None, "preflight": None, "sync": None,
                  "live_mode": None, "plan_mode": ""}

    catalogue = []
    for key, label, rows in ops_commands.by_category():
        catalogue.append({
            "key": key, "label": label,
            "rows": [dict(e, runnable=ops_commands.is_runnable(e),
                          management_command=ops_commands.is_management_command(e))
                     for e in rows],
        })

    context = {
        "page_id": "ops",
        "is_admin": user.is_superuser,
        "is_staff": is_staff,
        "now": now,
        "switches": switches,
        "queues": queues,
        "broker": broker,
        "catalogue": catalogue,
        "last": _last_output(request),
        "tests_green": TESTS_GREEN,
        "output_cap": OUTPUT_CAP,
    }
    return render(request, "dashboard/ops.html", context)


@login_required
def ops_run_command(request):
    """Run one registered READ-ONLY command with its fixed argv.

    Superuser + POST only. The name is the only input, and it must name a
    registry entry that is read_only and runnable; everything else is
    refused with a message and an audit row. Never accepts arguments from
    the browser — see the module docstring."""
    from django.core.management import call_command

    from bot_program.audit import record_event
    from core import ops_commands

    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access required.")
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    name = (request.POST.get("name") or "").strip()
    entry = ops_commands.get(name)
    if entry is None:
        reason = "not in the registry"
    elif not entry.get("read_only"):
        reason = "not read-only — run it on the server"
    elif not ops_commands.is_runnable(entry):
        reason = entry.get("runnable_reason") or "not runnable from the page"
    else:
        reason = ""
    if reason:
        shown = "".join(ch for ch in name if ch.isprintable())[:REFUSED_NAME_CAP]
        messages.error(request, f"Refused: {shown or '(no name)'} — {reason}.")
        # kind ≤ 20 chars: Postgres enforces AuditLogEntry.kind max_length.
        record_event("ops_run_refused",
                     {"name": shown, "reason": reason}, user=request.user)
        return redirect("ops_dashboard")

    buf = StringIO()
    t0 = time.monotonic()
    ok = True
    try:
        call_command(name, *list(entry.get("run_args") or []),
                     stdout=buf, stderr=buf)
    except Exception as e:  # noqa: BLE001 — the output card says so
        ok = False
        buf.write(f"\n[{type(e).__name__}] {e}\n")
        logger.warning("[ops] %s failed: %s", name, e)
    seconds = round(time.monotonic() - t0, 2)
    output = buf.getvalue()
    truncated = len(output) > OUTPUT_CAP
    output = output[:OUTPUT_CAP]

    at = timezone.now()
    last = {"name": name, "at": at.isoformat(), "seconds": seconds,
            "output": output, "ok": ok, "truncated": truncated}
    _cache_set(f"ops:last:{request.user.pk}", last, LAST_TTL)
    try:
        request.session["ops_last"] = last
    except Exception as e:  # noqa: BLE001
        logger.warning("[ops] session write failed: %s", e)
    record_event("ops_run", {"name": name, "seconds": seconds, "ok": ok},
                 user=request.user)
    if ok:
        messages.success(request, f"{name} ran in {seconds}s.")
    else:
        messages.error(request, f"{name} failed after {seconds}s — see the output.")
    return redirect("ops_dashboard")
