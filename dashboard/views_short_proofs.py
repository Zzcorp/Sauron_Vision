"""THE DEMO SHORT PROOFS PAGE (2026-10-31, bot_program/short_proofs.py).

What the platform proved itself on eToro's DEMO account, what the bots'
gate lets a short through at because of it, the steps still to run, and
the one write: a superuser revokes the recorded proofs of one class at one
multiplier, every standing row of it at once (the gate reads them no
more), or clears the runner's in-doubt stop after checking eToro's demo
account, with the trading PIN. An ACT door (core/trading_pin.py): a proof
opens real-money shorts to the bots. One audit row each
(bot_program.audit SHORT_PROOF_REVOKED / SHORT_PROOF_CLEARED). No shell
twin: nothing revokes a proof without the PIN. Cached rows only: this page
asks eToro nothing.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST


@login_required
def short_proofs_page(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access required.")
    from bot_program import short_proofs as sp
    from core.platform_control import get_component
    comp = get_component(sp.SWITCH_KEY)
    stop = sp.stopped()
    return render(request, "dashboard/short_proofs.html", {
        "page_id": "short_proofs",
        "switch_key": sp.SWITCH_KEY,
        "switch_on": bool(comp and comp.is_enabled),
        "switch_row": comp is not None,
        "stopped_words": sp.stop_words(stop) if stop is not None else "",
        "refusing": sp.refusing(),
        "not_waited_on": sp.not_waited_on(),
        "keyed": sp.keyed_account() is not None,
        "gate": sp.gate_words(),
        "steps": [dict(s, words=sp.step_words(s)) for s in sp.plan()],
        "rows": sp.page_rows(),
        "min_gap": sp.MIN_GAP_S // 60,
    })


def _gate_after_revoke(icls, lev) -> str:
    """What the bots' gate does with a short of `icls` at `lev` now, read
    from the gate itself (base.missing_proofs, demo_short_leverages)."""
    from bot_program import short_proofs as sp
    from bot_program.asset_engine import base
    if not base.missing_proofs(icls, "SELL", leverage=lev):
        why = ("the code pins a short of it" if base.short_pinned(icls)
               else "another proof of it stands")
        return (f"but the bots' gate still lets {sp.a_class(icls)} short "
                f"through at {lev}x: {why}")
    others = sorted(v for v in base.demo_short_leverages(icls) if v != lev)
    return (f"and the bots' gate now refuses a bot short of "
            f"{sp.class_name(icls)} at {lev}x"
            + (f"; it still lets one through at "
               f"{', '.join(f'{v}x' for v in others)}" if others else ""))


@login_required
@require_POST
def short_proof_revoke(request, pk: int):
    """Revoke the demo proofs of ONE (class, multiplier), every standing
    row of it at once (short_proofs.revoke), or clear ONE in-doubt stop,
    with the trading PIN (an ACT door) and one audit row; never the PIN."""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access required.")
    from bot_program import short_proofs as sp
    from bot_program.short_models import EtoroShortObservation
    from core.trading_pin import ACT, gate, refusal_of, sentence
    row = get_object_or_404(EtoroShortObservation, pk=pk, source=sp.SOURCE)
    back = redirect("short_proofs")
    clearing = row.proof_state == sp.IN_DOUBT
    what = (f"the in-doubt stop on {row.symbol}" if clearing else
            f"the demo proofs of {sp.a_class(row.asset_class)} short at "
            f"{row.leverage}x")
    if row.revoked_at is not None or not (clearing or row.demo_proven):
        messages.error(request, f"Nothing to revoke: {what} is not a "
                                f"standing proof or stop.")
        return back
    pin_ok = gate(request, request.POST.get("pin", ""), door=ACT,
                  act=("clear a demo short stop" if clearing
                       else "revoke a demo short proof"))
    if not pin_ok:
        verdict = refusal_of(pin_ok)
        nothing = "the stop stands" if clearing else "the proof stands"
        subject = (f"Clearing {what}" if clearing else f"Revoking {what}")
        messages.error(request, sentence(verdict, subject=subject,
                                         nothing=nothing) if verdict else
                       f"{subject} takes your trading PIN: {nothing}.")
        return back
    reason = (request.POST.get("reason") or "").strip()[:200]
    marked = sp.revoke(row, user=request.user, reason=reason)
    if clearing:
        messages.success(request, (
            f"Cleared {what}: the demo proofs go on at their next step. "
            f"Whatever eToro's demo account still holds there is yours to "
            f"close."))
    else:
        n = len(marked)
        count = (f"all {n} standing proofs of it at once (round trips and "
                 f"overnight hold alike)" if n > 1 else
                 "its one standing proof")
        messages.success(request, (
            f"Revoked {what}: {count}, "
            f"{_gate_after_revoke(row.asset_class, row.leverage)}. The "
            f"runner does not prove it again by itself; `manage.py "
            f"short_proofs_demo --class {row.asset_class} --leverage "
            f"{row.leverage}` does."))
    return back
