"""Phase-27 tax-lot dashboard + Form 8949–style CSV export.

GET  /tax-lots/        — open lots + YTD realised gain/loss summary
GET  /tax-lots/export/ — CSV of consumptions in date range (default current year)
"""
import csv
from datetime import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone


@login_required
def tax_lots_dashboard(request):
    from bot_program.models import TaxLot, TaxLotConsumption

    mode = (request.GET.get("mode") or "live").strip().lower()
    paper_filter = mode == "paper"
    try:
        year = int(request.GET.get("year", timezone.now().year))
    except (TypeError, ValueError):
        year = timezone.now().year
    year_start = timezone.make_aware(datetime(year, 1, 1))
    year_end = timezone.make_aware(datetime(year + 1, 1, 1))

    open_lots = list(
        TaxLot.objects.filter(
            user=request.user, paper=paper_filter,
            qty_remaining__gt=Decimal("0"),
        ).order_by("symbol", "opened_at")
    )

    cons_qs = TaxLotConsumption.objects.filter(
        lot__user=request.user, lot__paper=paper_filter,
        sold_at__gte=year_start, sold_at__lt=year_end,
    )
    realised_total = cons_qs.aggregate(s=Sum("realized_gain"))["s"] or Decimal("0")
    short_term = (cons_qs.filter(long_term=False)
                  .aggregate(s=Sum("realized_gain"))["s"] or Decimal("0"))
    long_term = (cons_qs.filter(long_term=True)
                  .aggregate(s=Sum("realized_gain"))["s"] or Decimal("0"))
    n_consumptions = cons_qs.count()
    recent = list(cons_qs.select_related("lot", "consuming_trade")
                          .order_by("-sold_at")[:30])

    # Per-symbol open-lot totals.
    sym_summary = {}
    for lot in open_lots:
        agg = sym_summary.setdefault(lot.symbol, {
            "symbol": lot.symbol,
            "asset_class": lot.asset_class,
            "qty": Decimal("0"),
            "cost_basis_total": Decimal("0"),
            "lots": 0,
        })
        agg["qty"] += Decimal(str(lot.qty_remaining))
        agg["cost_basis_total"] += (Decimal(str(lot.qty_remaining))
                                    * Decimal(str(lot.cost_basis_per_unit))
                                    * Decimal(str(lot.multiplier or 1)))
        agg["lots"] += 1
    sym_rows = sorted(sym_summary.values(), key=lambda r: -r["cost_basis_total"])

    # Phase 63 — additional aggregates for the enriched strip + breakdown
    total_cost_basis_open = sum(
        (r["cost_basis_total"] for r in sym_rows), Decimal("0"))
    n_distinct_symbols = len(sym_rows)
    oldest_lot = min((lot.opened_at for lot in open_lots), default=None)
    # ST vs LT donut (over the consumption window)
    abs_st = abs(float(short_term))
    abs_lt = abs(float(long_term))
    abs_total = abs_st + abs_lt
    st_lt_donut = []
    if abs_st > 0:
        st_lt_donut.append({
            "key": "short_term", "n": float(short_term),
            "pct": round(abs_st / max(abs_total, 1) * 100, 1),
        })
    if abs_lt > 0:
        st_lt_donut.append({
            "key": "long_term", "n": float(long_term),
            "pct": round(abs_lt / max(abs_total, 1) * 100, 1),
        })

    context = {
        "page_id": "tax_lots",
        "mode": mode,
        "year": year,
        "available_years": list(range(timezone.now().year, timezone.now().year - 5, -1)),
        "n_open_lots": len(open_lots),
        "open_lots": open_lots,
        "sym_rows": sym_rows,
        "realised_total": realised_total,
        "short_term": short_term,
        "long_term": long_term,
        "n_consumptions": n_consumptions,
        "recent_consumptions": recent,
        "total_cost_basis_open": total_cost_basis_open,
        "n_distinct_symbols": n_distinct_symbols,
        "oldest_lot": oldest_lot,
        "st_lt_donut": st_lt_donut,
    }
    return render(request, "dashboard/tax_lots.html", context)


@login_required
def tax_lots_export(request):
    """Form 8949–style CSV export of consumptions for the user.

    Filters: ?year= (default current), ?mode=live|paper (default live).
    Columns approximate IRS Form 8949 Part I/II:
      description, date_acquired, date_sold, proceeds, cost_basis,
      gain_loss, holding_period (ST/LT)
    """
    from bot_program.models import TaxLotConsumption

    mode = (request.GET.get("mode") or "live").strip().lower()
    paper_filter = mode == "paper"
    try:
        year = int(request.GET.get("year", timezone.now().year))
    except (TypeError, ValueError):
        year = timezone.now().year
    year_start = timezone.make_aware(datetime(year, 1, 1))
    year_end = timezone.make_aware(datetime(year + 1, 1, 1))

    qs = (TaxLotConsumption.objects
          .filter(lot__user=request.user, lot__paper=paper_filter,
                   sold_at__gte=year_start, sold_at__lt=year_end)
          .select_related("lot")
          .order_by("sold_at"))

    response = HttpResponse(content_type="text/csv")
    fname = f"sauron-form8949-{year}-{mode}.csv"
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    writer = csv.writer(response)
    writer.writerow([
        "description", "asset_class", "date_acquired", "date_sold",
        "qty", "proceeds", "cost_basis", "gain_loss", "holding_period",
        "holding_days",
    ])
    for c in qs.iterator(chunk_size=500):
        lot = c.lot
        mult = Decimal(str(lot.multiplier or 1))
        proceeds = Decimal(str(c.qty_consumed)) * Decimal(str(c.sale_price_per_unit)) * mult
        cost_basis = Decimal(str(c.qty_consumed)) * Decimal(str(lot.cost_basis_per_unit)) * mult
        writer.writerow([
            lot.symbol,
            lot.asset_class,
            lot.opened_at.date().isoformat(),
            c.sold_at.date().isoformat(),
            str(c.qty_consumed),
            f"{proceeds:.2f}",
            f"{cost_basis:.2f}",
            f"{c.realized_gain:.2f}",
            "Long-term" if c.long_term else "Short-term",
            c.holding_period_days,
        ])
    return response
