"""Strategy create wizard with instrument leg picker."""
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


@login_required
def strategy_wizard(request):
    """Render the wizard with available instruments for the leg picker."""
    instruments = []
    try:
        from instruments.models import Instrument
        instruments = list(
            Instrument.objects.filter(is_active=True)
            .order_by("symbol")
            .values("id", "symbol", "name")[:200]
        )
    except Exception:
        pass
    return render(request, "dashboard/_strategy_wizard.html", {
        "instruments": instruments,
        "instruments_json": json.dumps(instruments),
    })


@login_required
@require_POST
def strategy_wizard_save(request):
    """Persist Strategy + StrategyLeg rows from wizard form data."""
    try:
        from strategies.models import Strategy, StrategyLeg
        from instruments.models import Instrument
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"strategies module: {e}"})

    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    horizon = request.POST.get("time_horizon", "swing")
    max_alloc = request.POST.get("max_portfolio_allocation_pct", "10")
    max_loss = request.POST.get("max_loss_pct", "2")
    legs_json = request.POST.get("legs_json", "[]")

    if not name:
        return JsonResponse({"ok": False, "error": "Name is required."})

    try:
        legs = json.loads(legs_json)
    except Exception:
        legs = []

    try:
        s = Strategy.objects.create(
            name=name,
            description=description,
            time_horizon=horizon,
            status="proposed",
            max_portfolio_allocation_pct=float(max_alloc or 10),
            max_loss_pct=float(max_loss or 2),
            ai_reasoning="Created via wizard",
        )
        legs_created = 0
        for leg in legs:
            try:
                inst = Instrument.objects.get(id=int(leg.get("instrument_id")))
                StrategyLeg.objects.create(
                    strategy=s,
                    instrument=inst,
                    action=leg.get("action", "long"),
                    weight=float(leg.get("weight", 1.0)),
                )
                legs_created += 1
            except Exception:
                continue
        return JsonResponse({
            "ok": True,
            "id": s.id,
            "legs_created": legs_created,
            "redirect": f"/strategies/{s.id}/",
        })
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})
