"""Is the live pipe actually live?

The operator opened a trade and saw no banner and no badge — everything
had to be refreshed into view. Every one of those live updates rides one
WebSocket and one channel-layer dispatch, and BOTH failure modes are
silent by design: `push_eye_event` swallows its exception and returns
False that nobody reads, and a browser whose socket never connected
looks exactly like a platform with nothing to say.

So the platform gets to answer the question directly: send a real event
through the real pipe, and report what happened at each end. The server
half is here; the browser half is the socket-state dot in base.html,
which knows whether the message ever arrived.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def channel_layer_report() -> dict:
    """What the channel layer IS, not what settings hoped it would be."""
    out = {"backend": "none", "reachable": False, "detail": ""}
    try:
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer is None:
            out["detail"] = "no channel layer configured"
            return out
        out["backend"] = type(layer).__name__
        # An in-memory layer is per-process: a push from a Celery worker
        # can never reach a browser attached to the web process, so it is
        # worth naming rather than reporting as healthy.
        if "InMemory" in out["backend"]:
            out["reachable"] = True
            out["detail"] = ("in-memory layer — live updates work only when "
                             "the sender is the web process itself")
            return out
        from asgiref.sync import async_to_sync
        async_to_sync(layer.group_add)("sv_livecheck", "sv_livecheck_probe")
        async_to_sync(layer.group_discard)("sv_livecheck", "sv_livecheck_probe")
        out["reachable"] = True
    except Exception as exc:  # noqa: BLE001 — this endpoint reports faults
        out["detail"] = str(exc)[:200]
    return out


@login_required
@require_POST
def live_selftest(request):
    """Push a real banner to the caller and report the server's half.

    `dispatched` answers "did the platform hand this to the channel
    layer". If that is true and no banner appears, the break is in the
    browser's socket, which the page can see for itself — between the two
    the operator always learns which half is broken.
    """
    from dashboard.consumers import push_eye_event

    report = channel_layer_report()
    dispatched = push_eye_event(request.user, "notification", {
        "id": "livecheck",
        "type": "system",
        "title": "Live pipe test",
        "body": "If you can read this as a banner, live updates are working.",
        "url": "",
        "silent": False,
    })
    if not dispatched:
        logger.warning("[livecheck] dispatch failed for %s — layer=%s (%s)",
                       request.user, report["backend"], report["detail"])
    return JsonResponse({
        "dispatched": dispatched,
        "layer": report["backend"],
        "layer_reachable": report["reachable"],
        "detail": report["detail"],
    })
