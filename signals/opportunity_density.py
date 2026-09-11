"""How much of each asset class is showing a setup right now.

One input to the share allocator: a class where a quarter of the active
universe carries an open OpportunityFlag or a fresh, scoring Signal is a
class with something to trade, and a class with nothing flagged is one
where a bigger pool would sit idle. The reader counts DISTINCT
instruments — ten flags on one symbol are one opportunity — over the
active universe of that class, and says `measured: False` rather than
`share: 0.0` when the answer is an absence of measurement: an empty
universe, or a scanner that is switched off with no signals to speak for
it. The allocator turns `share` into a factor; this module never does,
so the number here means one thing on every page that prints it
(2026-09-12).

Pure DB reads, no broker I/O, and it never raises into a caller — a
reader that raises turns a missing scanner into a missing plan.
"""
from datetime import timedelta

from django.utils import timezone

# A flag stays "open" until the scanner resolves it; 48h covers two
# daily scans so a weekend does not read as an empty market.
DEFAULT_HOURS_FLAGS = 48
DEFAULT_HOURS_SIGNALS = 24
DEFAULT_MIN_SIGNAL_SCORE = 0.6
SCANNER_COMPONENT = "pipeline_opportunity_scanner"


def opportunity_density(*, hours_flags=DEFAULT_HOURS_FLAGS,
                        hours_signals=DEFAULT_HOURS_SIGNALS,
                        min_signal_score=DEFAULT_MIN_SIGNAL_SCORE,
                        now=None) -> dict:
    """{asset_class: {n_flags, n_flag_instruments, n_signals,
                      n_signal_instruments, universe, share, measured,
                      reason}} for every class in the active universe
    (plus any class a flag or signal names).

    `share` is distinct instruments carrying a flag or a signal over the
    class's active universe, 0..1. Signals the scanner itself raised
    (sub_scores["opportunity_setup"]) are excluded so a flag is not
    counted twice through its linked Signal.
    """
    from django.db.models import Count

    from core.platform_control import is_component_enabled
    from instruments.models import Instrument
    from signals.models import Signal
    from signals.models_opportunity import OpportunityFlag

    now = now or timezone.now()
    out: dict = {}

    def _slot(ac):
        return out.setdefault(ac, {
            "n_flags": 0, "n_flag_instruments": 0, "n_signals": 0,
            "n_signal_instruments": 0, "universe": 0, "share": 0.0,
            "measured": False, "reason": ""})

    for row in (Instrument.objects.filter(is_active=True)
                .values("asset_class").annotate(n=Count("id"))):
        _slot(row["asset_class"])["universe"] = int(row["n"] or 0)

    flagged: dict = {}
    flags = (OpportunityFlag.objects
             .filter(scanned_at__gte=now - timedelta(hours=hours_flags),
                     outcome="")
             .values_list("instrument_id", "instrument__asset_class"))
    for inst_id, ac in flags:
        _slot(ac)["n_flags"] += 1
        flagged.setdefault(ac, set()).add(inst_id)

    signalled: dict = {}
    signals = (Signal.objects
               .filter(is_active=True,
                       created_at__gte=now - timedelta(hours=hours_signals),
                       score__gte=min_signal_score)
               .exclude(sub_scores__has_key="opportunity_setup")
               .values_list("instrument_id", "instrument__asset_class"))
    for inst_id, ac in signals:
        _slot(ac)["n_signals"] += 1
        signalled.setdefault(ac, set()).add(inst_id)

    try:
        scanner_on = bool(is_component_enabled(SCANNER_COMPONENT))
    except Exception:  # noqa: BLE001 — an unreadable switch reads as off
        scanner_on = False

    for ac, slot in out.items():
        f, s = flagged.get(ac, set()), signalled.get(ac, set())
        slot["n_flag_instruments"] = len(f)
        slot["n_signal_instruments"] = len(s)
        carrying = len(f | s)
        if slot["universe"] <= 0:
            slot["reason"] = "no active instruments in this class"
            continue
        if not scanner_on and not s:
            slot["reason"] = (f"scanner off ({SCANNER_COMPONENT}) and no "
                              f"signals in {hours_signals}h — unmeasured")
            continue
        slot["share"] = min(1.0, carrying / slot["universe"])
        slot["measured"] = True
        slot["reason"] = (f"{carrying}/{slot['universe']} instruments "
                          f"carry a flag ({hours_flags}h) or a signal "
                          f"({hours_signals}h, score ≥ {min_signal_score:g})")
    return out
