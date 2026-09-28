"""WITHDRAWALS — money asked for in advance, held back before it leaves.

The page the operator and Gandalf share (one login, one book, one PIN):
file a request ahead of time, see whether the cash is there and what the
reserve shrinks, and mark it withdrawn at the moment the money is sent at
the broker — or cancel it. The arithmetic and the rules live in
bot_program.withdrawals; this module only reads the form, checks the PIN
and redirects.

Every state change takes the trading PIN, the same check as the HQ forms
(views_admin_hq._pin_ok, form field "pin") and deliberately NOT the
superuser gate those forms also carry: Gandalf acts on this account as
its owner does. A wrong PIN flashes an error and changes nothing.
POST-redirect-GET throughout, so a refresh never files a request twice.
Owner-scoped: another user's request is a 404, not a refusal that
confirms it exists. Nothing here places, closes or cancels an order.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def _pin_ok(request) -> bool:
    from dashboard.views_admin_hq import _pin_ok as hq_pin_ok
    return hq_pin_ok(request)


def _own_request(request, pk):
    from bot_program.models import WithdrawalRequest
    wr = WithdrawalRequest.objects.filter(pk=pk, user=request.user).first()
    if wr is None:
        raise Http404("No such withdrawal request.")
    return wr


def _flash(request, out, success: str) -> None:
    if out.get("error"):
        messages.error(request, out["error"])
        return
    messages.success(request, success)
    for w in out.get("warnings") or []:
        messages.warning(request, w)


def _age_text(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 90 * 60:
        return f"{seconds // 60} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds // 86400}d"


def _dress(ready):
    """Every money cell as '1,234.56 EUR' or an em dash, pre-grouped here
    because the template has no grouping filter — the rule
    capital_truth.account_equity already follows for value_text."""
    from bot_program.withdrawals import money
    if ready is None:
        return None
    ccy = ready["currency"]
    for key in ("value", "reserved", "paid_unread", "held", "deployable",
                "free_cash", "shortfall"):
        ready[f"{key}_text"] = money(ready[key], ccy)
    ready["age_text"] = _age_text(ready["age_seconds"])
    ready["cash_age_text"] = (
        _age_text((timezone.now() - ready["cash_at"]).total_seconds())
        if ready.get("cash_at") else "—")
    for row in ready["following"]:
        for key in ("now", "before", "after"):
            row[f"{key}_text"] = money(row[key], ccy)
    for row in ready["typed_live"] + ready["paper"]:
        row["capital_text"] = money(row["capital"], row["currency"])
    return ready


def _row(wr) -> dict:
    """One request as the tables print it."""
    from bot_program.withdrawals import money, who_label
    return {
        "id": wr.pk, "status": wr.status,
        "status_label": wr.get_status_display(),
        "amount_text": money(wr.amount, wr.currency),
        # The default in the "Mark withdrawn" amount box: plain, no
        # grouping, so the number input accepts it as it stands.
        "amount_plain": f"{wr.amount:.2f}",
        "currency": wr.currency,
        "requested_by": who_label(wr.requested_by),
        "requested_by_code": wr.requested_by,
        "acted_by": who_label(wr.acted_by) or "—",
        "wanted_by": wr.wanted_by, "reason": wr.reason,
        "created_at": wr.created_at,
        "paid_at": wr.paid_at, "cancelled_at": wr.cancelled_at,
        "paid_text": (money(wr.paid_amount, wr.currency)
                      if wr.paid_amount is not None else "—"),
        "closing_note": wr.closing_note,
    }


@login_required
def withdrawals_page(request):
    from bot_program.models import WithdrawalRequest
    from bot_program.withdrawals import FALLBACK_CURRENCY, readiness

    user = request.user
    ready, ready_error = None, ""
    try:
        ready = readiness(user)
    except Exception as e:  # noqa: BLE001 — a money page that 500s says nothing
        logger.error("withdrawals: readiness failed for %s: %s", user, e)
        ready_error = f"{type(e).__name__}: {e}"[:200]

    try:
        ready = _dress(ready)
    except Exception as e:  # noqa: BLE001
        logger.error("withdrawals: readiness unprintable for %s: %s", user, e)
        ready, ready_error = None, f"{type(e).__name__}: {e}"[:200]

    rows = WithdrawalRequest.objects.filter(user=user)
    active = [_row(w) for w in
              rows.filter(status=WithdrawalRequest.STATUS_RESERVED)
              .order_by("wanted_by", "created_at")]
    history = [_row(w) for w in
               rows.exclude(status=WithdrawalRequest.STATUS_RESERVED)
               .order_by("-updated_at")[:50]]
    prof = getattr(user, "trader_profile", None)
    currency = ((ready or {}).get("currency") or "")
    return render(request, "dashboard/withdrawals.html", {
        "page_id": "withdrawals",
        "ready": ready, "ready_error": ready_error,
        "active": active, "history": history,
        "who_choices": WithdrawalRequest.WHO_CHOICES,
        # What a new request will be recorded in: the reading's currency,
        # or the stated fallback when no reading has ever landed.
        "form_currency": currency or FALLBACK_CURRENCY,
        "currency_fallback": not currency,
        "today": timezone.now().date().isoformat(),
        "has_pin": bool(prof and getattr(prof, "access_pin_hash", "")),
    })


@login_required
@require_POST
def withdrawal_create(request):
    from bot_program.withdrawals import create_request
    if not _pin_ok(request):
        messages.error(request, "Wrong or missing trading PIN. Nothing was "
                                "reserved.")
        return redirect("withdrawals")
    out = create_request(
        request.user,
        requested_by=request.POST.get("requested_by", ""),
        amount=request.POST.get("amount", ""),
        wanted_by=request.POST.get("wanted_by", "") or None,
        reason=request.POST.get("reason", ""))
    if out.get("ok"):
        wr = out["request"]
        from bot_program.withdrawals import money
        success = (f"Request #{wr.pk} filed: {money(wr.amount, wr.currency)} "
                   f"is held back from new sizing from now on. Nothing was "
                   f"sold.")
    else:
        success = ""
    _flash(request, out, success)
    return redirect("withdrawals")


@login_required
@require_POST
def withdrawal_mark_paid(request, pk):
    from bot_program.withdrawals import mark_paid, money
    wr = _own_request(request, pk)
    if not _pin_ok(request):
        messages.error(request, "Wrong or missing trading PIN. Nothing "
                                "changed.")
        return redirect("withdrawals")
    out = mark_paid(request.user, wr.pk,
                    acted_by=request.POST.get("acted_by", ""),
                    paid_amount=request.POST.get("paid_amount", "") or None,
                    paid_at=request.POST.get("paid_at", "") or None,
                    note=request.POST.get("note", ""))
    success = ""
    if out.get("ok"):
        done = out["request"]
        success = (f"Request #{done.pk} marked withdrawn: "
                   f"{money(done.paid_amount, done.currency)}. The reserve "
                   f"is released, and the account's history reads it as a "
                   f"withdrawal, not a loss.")
    _flash(request, out, success)
    return redirect("withdrawals")


@login_required
@require_POST
def withdrawal_cancel(request, pk):
    from bot_program.withdrawals import cancel_request, money
    wr = _own_request(request, pk)
    if not _pin_ok(request):
        messages.error(request, "Wrong or missing trading PIN. Nothing "
                                "changed.")
        return redirect("withdrawals")
    out = cancel_request(request.user, wr.pk,
                         acted_by=request.POST.get("acted_by", ""),
                         note=request.POST.get("note", ""))
    success = ""
    if out.get("ok"):
        success = (f"Request #{wr.pk} cancelled: "
                   f"{money(wr.amount, wr.currency)} can be deployed again.")
    _flash(request, out, success)
    return redirect("withdrawals")
