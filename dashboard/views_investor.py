"""The investor panel — one funded account's book, read-only.

Everything here is scoped by the InvestorAccess row and nothing else: no
query in this module takes a symbol, a user id, or a portfolio from the
REQUEST. The row names the owner; the owner names the book; the flags
name how much of it renders. An investor cannot ask this page a question
about anybody else's money because the page accepts no questions.

Standalone template, deliberately (the lock screen's precedent): the app
shell's headband, sidebar and sockets are an operator's cockpit wired to
request.user — rendering it for an investor would show them their own
empty book beside links the gate bounces. The panel ships its own small
world and its own live refresh instead.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from core.investor_gate import investor_access_for

logger = logging.getLogger(__name__)


def _panel_context(access):
    from portfolio.models import PortfolioSnapshot
    from portfolio.services import (get_or_create_default_portfolio,
                                    unified_open_positions)

    owner = access.owner
    portfolio = get_or_create_default_portfolio(user=owner)

    snapshots = list(PortfolioSnapshot.objects.filter(
        portfolio=portfolio).order_by("date"))[-90:]
    curve = [{"date": s.date.isoformat(),
              "pct": float(s.cumulative_pnl_pct)} for s in snapshots]
    latest = snapshots[-1] if snapshots else None

    positions = []
    if access.show_positions:
        for row in unified_open_positions(owner, portfolio):
            inst = getattr(row, "instrument", None)
            positions.append({
                "symbol": getattr(inst, "symbol", "") or "—",
                "asset_class": getattr(inst, "asset_class", "") or "—",
                "direction": (row.direction or "").upper(),
                "pnl_pct": row.unrealized_pnl_pct,
                # Dollar columns obey the same flag as everything else.
                "pnl": (None if access.percents_only
                        else row.unrealized_pnl),
            })

    history = []
    if access.show_history:
        from portfolio.services import unified_closed_positions
        for row in list(unified_closed_positions(owner, portfolio))[:30]:
            inst = getattr(row, "instrument", None)
            history.append({
                "symbol": getattr(inst, "symbol", "") or "—",
                "direction": (row.direction or "").upper(),
                "pnl_pct": row.unrealized_pnl_pct,
                "pnl": (None if access.percents_only
                        else row.unrealized_pnl),
                "closed_at": row.closed_at,
            })

    # The equity curve as a ready SVG polyline — computed here so the
    # page ships zero chart script: an investor surface should carry the
    # least executable machinery this platform knows how to serve.
    curve_points = ""
    if curve:
        vals = [c["pct"] for c in curve]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        n = len(vals)
        curve_points = " ".join(
            "%.1f,%.1f" % ((i / (n - 1) if n > 1 else 0.0) * 600,
                           160 - ((v - lo) / span) * 150 - 5)
            for i, v in enumerate(vals))

    value = None if access.percents_only else float(portfolio.current_value)
    return {
        "curve_points": curve_points,
        "access": access,
        # Neutral fallback — the OWNER'S LOGIN NAME is internal plumbing
        # and must never reach an outsider's screen, title bar included.
        "label": access.label or "Investor account",
        "value": value,
        "currency": portfolio.currency,
        "cumulative_pct": (float(latest.cumulative_pnl_pct)
                           if latest else None),
        "daily_pct": float(latest.daily_pnl_pct) if latest else None,
        "max_drawdown": float(latest.max_drawdown) if latest else None,
        "curve": curve,
        "positions": positions,
        "history": history,
        "n_open": len(positions) if access.show_positions else None,
    }


# ── HQ management ────────────────────────────────────────────────────────
# The HOUSE admin gate, not staff_member_required: every HQ action on
# this platform is superuser-only (views_admin_hq._admin_only), and a
# weaker predicate here would make "who can mint an investor" the one
# question with a different answer than "who can save broker keys".
from dashboard.views_admin_hq import _admin_only  # noqa: E402


@_admin_only
def hq_create_investor(request):
    """POST {owner_username, investor_username, investor_password, label,
    show_positions?, show_history?, show_amounts?} — mint an investor
    login caged to one funded account's book.

    The password is set here and never stored in the clear anywhere; the
    operator hands it over out-of-band. The new user gets no staff bit,
    no PIN, no profile privileges — the gate middleware is its whole
    world from the first request.
    """
    from django.contrib import messages
    from django.contrib.auth.models import User
    from django.http import HttpResponseNotAllowed
    from django.shortcuts import redirect as _redirect

    from portfolio.investor_models import InvestorAccess

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    owner_name = request.POST.get("owner_username", "").strip()
    inv_name = request.POST.get("investor_username", "").strip()
    password = request.POST.get("investor_password", "")

    owner = User.objects.filter(username=owner_name).first()
    if owner is None:
        messages.error(request, f"Investor: owner '{owner_name}' not found.")
        return _redirect("admin_dashboard")
    if owner.is_superuser or owner.is_staff:
        # A window onto the ADMIN's book would hand an outsider the
        # platform's own ledger under a friendly label. Funded accounts
        # are ordinary users by construction.
        messages.error(request, f"Investor: '{owner_name}' is an admin "
                                f"account — investor windows show funded "
                                f"accounts only.")
        return _redirect("admin_dashboard")
    label = request.POST.get("label", "").strip()[:120]
    if not label:
        # Mandatory, because the blank-label fallback used to print the
        # owner's internal username on the investor's screen.
        messages.error(request, "Investor: a display label is required — "
                                "it is the name the investor sees.")
        return _redirect("admin_dashboard")
    if not inv_name:
        messages.error(request, "Investor: a username is required.")
        return _redirect("admin_dashboard")
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    try:
        # The platform's own validators, against the unsaved user so the
        # similarity check can compare — "12345678" must not mint an
        # outsider credential just because it is eight characters long.
        validate_password(password, user=User(username=inv_name))
    except ValidationError as e:
        messages.error(request, "Investor password refused: "
                                + "; ".join(e.messages))
        return _redirect("admin_dashboard")
    if User.objects.filter(username=inv_name).exists():
        messages.error(request, f"Investor: username '{inv_name}' is taken.")
        return _redirect("admin_dashboard")
    if getattr(owner, "investor_access", None) is not None:
        # The OWNER of a book cannot itself be an investor login — the
        # gate would cage the very account the bots trade under.
        messages.error(request, f"Investor: '{owner_name}' is an investor "
                                f"login, not a funded account.")
        return _redirect("admin_dashboard")

    investor = User.objects.create_user(inv_name, password=password)
    access = InvestorAccess.objects.create(
        investor=investor, owner=owner,
        label=label,
        show_positions=request.POST.get("show_positions") == "on",
        show_history=request.POST.get("show_history") == "on",
        percents_only=request.POST.get("show_amounts") != "on",
        created_by=request.user.username[:80],
    )
    messages.success(
        request,
        f"Investor '{inv_name}' created — sees {access.label or owner_name}"
        f"'s book, {'with' if not access.percents_only else 'without'} "
        f"dollar amounts. Hand the password over out-of-band.")
    return _redirect("admin_dashboard")


@_admin_only
def hq_toggle_investor(request):
    """POST {access_id} — revoke or restore. Revoked ends the session at
    the gate on its very next request; there is no half-revoked state."""
    from django.contrib import messages
    from django.http import HttpResponseNotAllowed
    from django.shortcuts import redirect as _redirect

    from portfolio.investor_models import InvestorAccess

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    access = InvestorAccess.objects.filter(
        pk=request.POST.get("access_id")).first()
    if access is None:
        messages.error(request, "Investor: access row not found.")
    else:
        access.is_active = not access.is_active
        access.save(update_fields=["is_active"])
        messages.success(
            request,
            f"Investor '{access.investor.username}' "
            f"{'restored' if access.is_active else 'REVOKED'}.")
    return _redirect("admin_dashboard")


@login_required
def investor_panel(request):
    access = investor_access_for(request.user)
    # getattr, not attribute access: the gate can answer UNREADABLE (a
    # bare sentinel) and this page must treat that exactly like "no".
    if not getattr(access, "is_active", False):
        # Not an investor: this page holds nothing for an operator, and
        # naming its existence to an anonymous probe is already too much.
        return redirect("/")
    return render(request, "investor/panel.html", _panel_context(access))


@login_required
def investor_panel_live(request):
    """The panel's own live regions — same context, bare shell."""
    access = investor_access_for(request.user)
    if not getattr(access, "is_active", False):
        return redirect("/")
    ctx = _panel_context(access)
    ctx["live_only"] = True
    return render(request, "investor/panel.html", ctx)
