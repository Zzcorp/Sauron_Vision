"""Phase-28 admin audit-log views.

Two endpoints:
  /audit/         — admin-only HTML dashboard with chain integrity status
                     + last 100 entries + verify-now button + export link
  /audit/export/  — admin-only CSV download of all entries (or filtered)
"""
import csv
import json

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import render


def _is_admin(user):
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(_is_admin)
def audit_dashboard(request):
    from bot_program.models import AuditLogEntry
    from bot_program.audit import verify_chain

    total = AuditLogEntry.objects.count()
    # Verify last 500 entries by default — full-chain verify on a million-row
    # log would be expensive. Admin can hit /audit/verify-full/ for total scan.
    sample_limit = 500
    sample_start = max(0, total - sample_limit)
    sample_start_id = None
    if sample_start > 0:
        first_in_window = (AuditLogEntry.objects
                           .order_by("id")
                           .values_list("id", flat=True)[sample_start:sample_start+1])
        sample_start_id = list(first_in_window)[0] if first_in_window else None

    integrity = verify_chain(start_id=sample_start_id) if total else {
        "ok": True, "verified": 0, "breaks": [],
    }

    recent = list(
        AuditLogEntry.objects.order_by("-id")[:100]
    )
    by_kind = {}
    for k, _ in AuditLogEntry.KIND_CHOICES:
        by_kind[k] = AuditLogEntry.objects.filter(kind=k).count()

    context = {
        "page_id": "audit",
        "total": total,
        "by_kind": by_kind,
        "integrity": integrity,
        "sample_window": sample_limit,
        "recent": recent,
    }
    return render(request, "dashboard/audit_log.html", context)


@login_required
@user_passes_test(_is_admin)
def audit_export(request):
    """Stream every audit row as CSV. Optional ?kind=, ?since=YYYY-MM-DD."""
    from bot_program.models import AuditLogEntry
    from datetime import datetime
    from django.utils import timezone

    qs = AuditLogEntry.objects.order_by("id")
    kind = request.GET.get("kind", "").strip()
    if kind:
        qs = qs.filter(kind=kind)
    since = request.GET.get("since", "").strip()
    if since:
        try:
            dt = datetime.fromisoformat(since)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            qs = qs.filter(created_at__gte=dt)
        except ValueError:
            pass

    response = HttpResponse(content_type="text/csv")
    fname = f"sauron-audit-{timezone.now():%Y%m%d-%H%M%S}.csv"
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    writer = csv.writer(response)
    writer.writerow(["id", "created_at", "user_id", "user", "kind",
                     "data_json", "prev_hash", "payload_hash"])
    for e in qs.iterator(chunk_size=500):
        writer.writerow([
            e.id, e.created_at.isoformat(),
            e.user_id or "", (e.user.username if e.user else ""),
            e.kind, json.dumps(e.data, default=str),
            e.prev_hash, e.payload_hash,
        ])
    return response
