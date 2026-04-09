"""Strategy create wizard."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


@login_required
def strategy_wizard(request):
    """Render the strategy create wizard form."""
    return render(request, "dashboard/_strategy_wizard.html", {})


@login_required
@require_POST
def strategy_wizard_save(request):
    """Persist a Strategy from wizard form data. Tolerant to schema variations."""
    try:
        from strategies.models import Strategy
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"strategies module: {e}"})

    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    horizon = request.POST.get("time_horizon", "swing")
    max_alloc = request.POST.get("max_portfolio_allocation_pct", "10")
    max_loss = request.POST.get("max_loss_pct", "2")

    if not name:
        return JsonResponse({"ok": False, "error": "Name is required."})

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
        return JsonResponse({"ok": True, "id": s.id, "redirect": f"/strategies/{s.id}/"})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})
