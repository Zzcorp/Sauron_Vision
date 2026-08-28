"""Two readings of one dataset are not two confirmations.

An operator who raises `min_signals_for_entry` to 2 is buying INDEPENDENT
confirmation. They were not getting it: `weighted_consensus` counts
`len(rules)` — distinct rule NAMES — and two rules that both read the
funding-rate table satisfy that quorum between them. Worse, the reason
string written onto the trade reports the headcount as though it were
evidence count, so the row itself asserts a confirmation that never
happened.

The platform already MEASURES which rules are the same thing.
`brain.correlation_audit.detect_realized_return_correlation` runs Pearson
on daily realized-R and finds "rules that LOOK different but TRADE the same
factor in practice" — and that measurement is routed only to an LLM
narrator. It has never reached the moment the money moves.

This module turns those pairs into clusters, so the quorum can count
sources instead of names.

WHAT IT DELIBERATELY DOES NOT DO
It does not change position sizing, and it does not veto an entry on its
own. Sizing off a correlation reading would compound two estimates; the
quorum is a count, and a count is exactly the thing a cluster map can make
honest. An unavailable measurement returns `stale=True` and every rule in
its own cluster — the pre-existing behaviour — because a correlation this
platform could not measure must not silently tighten a gate the operator
set.
"""
import logging

logger = logging.getLogger(__name__)

# The audit's own default. Named here so a reader can see what "the same
# factor" means without opening another module.
CLUSTER_THRESHOLD = 0.80

# Recomputing Pearson over every active pair on every scan would put an
# O(N²) job inside the tick loop. The pairs move on the scale of weeks.
CACHE_SECONDS = 86400

_CACHE = {"at": None, "map": {}, "stale": True}


def cluster_map(*, threshold: float = CLUSTER_THRESHOLD, force: bool = False):
    """{rule_name: cluster_id}, plus whether the reading is usable.

    Returns (mapping, stale). `stale` True means the correlation audit
    could not be read, and every rule is therefore its own cluster — the
    behaviour the platform had before this existed. Failing that way round
    matters: an unmeasured correlation must not become a stricter gate
    than the operator asked for.
    """
    from django.utils import timezone

    now = timezone.now()
    if (not force and _CACHE["at"]
            and (now - _CACHE["at"]).total_seconds() < CACHE_SECONDS):
        return dict(_CACHE["map"]), _CACHE["stale"]

    try:
        from brain.correlation_audit import detect_realized_return_correlation
        pairs = detect_realized_return_correlation(threshold=threshold) or []
    except Exception as e:  # noqa: BLE001 — an unknown must not raise here
        logger.warning("rule_clusters: correlation audit unreadable (%s) — "
                       "every rule counts as its own source", e)
        _CACHE.update({"at": now, "map": {}, "stale": True})
        return {}, True

    # Union-find over the correlated pairs. Two rules land in one cluster
    # when the audit says their realized returns move together, whatever
    # their evaluators look like.
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for pair in pairs:
        a = pair.get("rule_a") or pair.get("a") or pair.get("rule_1")
        b = pair.get("rule_b") or pair.get("b") or pair.get("rule_2")
        if a and b:
            union(str(a), str(b))

    mapping = {rule: find(rule) for rule in list(parent)}
    _CACHE.update({"at": now, "map": mapping, "stale": False})
    return dict(mapping), False


def independent_sources(rule_names, *, mapping=None, stale=None) -> int:
    """How many genuinely distinct sources are in this set of rules?

    `len(set(rule_names))` was the old answer and it counts names. This
    counts clusters, so two readings of one dataset contribute one.

    A rule absent from the mapping is its own source — the audit only
    reports rules it found a partner for, and an unpaired rule is
    independent by definition rather than by omission.
    """
    names = {str(r) for r in rule_names if r}
    if not names:
        return 0
    if mapping is None:
        mapping, stale = cluster_map()
    if stale:
        return len(names)
    return len({mapping.get(name, name) for name in names})
