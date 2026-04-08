"""Streamer health endpoint — reports freshness per data source."""
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache


@never_cache
@login_required
def live_health(request):
    """Returns freshness for each `source` value seen in LiveQuote.
    Status: green (<60s old), yellow (<10min), red (older or missing)."""
    from market_data.models import LiveQuote
    try:
        from django.db.models import Max
        now = timezone.now()
        # Group by source, take freshest updated_at
        by_src = (LiveQuote.objects.values("source")
                  .annotate(latest=Max("updated_at")))
        sources = []
        for row in by_src:
            src = (row["source"] or "unknown").strip()
            if not src or src == "unknown":
                continue
            latest = row["latest"]
            if not latest:
                state = "red"; age_s = None
            else:
                age_s = (now - latest).total_seconds()
                if age_s < 60: state = "green"
                elif age_s < 600: state = "yellow"
                else: state = "red"
            sources.append({
                "source": src, "state": state, "age_seconds": age_s,
                "latest": latest.isoformat() if latest else None,
            })
        sources.sort(key=lambda s: s["source"])

        # Recent liquidations + funding as bonus health signals
        from market_data.models import LiquidationEvent, FundingRate
        try:
            last_liq = LiquidationEvent.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()
            last_fund = FundingRate.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()
        except Exception:
            last_liq = last_fund = None
        return JsonResponse({
            "sources": sources,
            "last_liquidation_age": (now - last_liq).total_seconds() if last_liq else None,
            "last_funding_age":     (now - last_fund).total_seconds() if last_fund else None,
        })
    except Exception as e:
        return JsonResponse({"error": str(e), "sources": []}, status=200)
