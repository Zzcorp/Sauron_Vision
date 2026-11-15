"""tests/old_design_budget.json: per file and per page, today's count of
each old marker; the ratchet that only goes down, its frozen ceiling, and
STRICT."""
import collections
import json
import os

from tests.old_design.owners import owner
from tests.old_design.rules import ROOT, census, counts

BUDGET = ROOT / "tests" / "old_design_budget.json"

# ══════════════════════════════════════════════════════════════════════════
# The budget: today's counts, a ratchet that only goes down
# ══════════════════════════════════════════════════════════════════════════

def load_budget():
    return json.loads(BUDGET.read_text(encoding="utf-8"))


def write_budget(budget):
    BUDGET.write_text(json.dumps(budget, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def compare_source(now, budget, hits):
    """(over, under): one message per file and marker above its budget
    (with every line of that marker in that file), and one per budget the
    count has gone under (the ratchet must follow it down)."""
    over, under = [], []
    by_key = collections.defaultdict(list)
    for h in hits:
        by_key[(h.file, h.marker)].append(h)
    for f in sorted(set(now) | set(budget)):
        for marker in sorted(set(now.get(f, {})) | set(budget.get(f, {}))):
            got, allowed = now.get(f, {}).get(marker, 0), budget.get(f, {}).get(marker, 0)
            if got > allowed:
                head = ("%s: %s %d, budget %d (%s)" %
                        (f, marker, got, allowed,
                         "a file absent from the budget must be at zero" if f not in budget
                         else "old design added"))
                lines = ["    %s:%d %s [%s]  %s" % (h.file, h.line, h.marker, owner(h.file, h.line, h.marker) or "no batch",
                                                   h.text[:150])
                         for h in sorted(by_key[(f, marker)], key=lambda x: x.line)]
                over.append("\n".join([head] + lines))
            elif got < allowed:
                under.append("%s: %s %d, budget %d: lower the budget to %d (the ratchet follows the count down;"
                             " tests.old_design.budget.lower_budgets() writes it)" % (f, marker, got, allowed, got))
    return over, under


def lower_budgets(write=True):
    """Every source budget lowered to today's count where the count went
    down: never raised. Returns the changes. A batch that removes old
    markers runs it and commits the file with its change."""
    budget = load_budget()
    now = counts(census())
    changes = []
    src = budget.setdefault("source", {})
    for f in sorted(src):
        for marker in sorted(src[f]):
            got = now.get(f, {}).get(marker, 0)
            if got < src[f][marker]:
                changes.append("%s %s %d -> %d" % (f, marker, src[f][marker], got))
                if got:
                    src[f][marker] = got
                else:
                    del src[f][marker]
        if not src[f]:
            del src[f]
    if write and changes:
        write_budget(budget)
    return changes


# ── the frozen ceiling (the review of B0) ──────────────────────────────
#
# B0's budgets, frozen: tests/old_design_ceiling.json. No budget may ever be
# above it, nor name a file, a scene or a marker it lacks, nor record a
# scene as unreached that it does not: a budget raised in the JSON with the
# marker it lets in fails here. The ceiling itself is pinned by its hash
# below, so raising it is a visible change to this file, with its reason.
# A batch that lowers its budgets may lower the ceiling with them
# (ceiling_from(load_budget())), never raise it.

CEILING = ROOT / "tests" / "old_design_ceiling.json"
CEILING_SHA256 = "88fa96b64563a972c3a7148ba2da7a15cc0a68d5c857b5f1b67cbc16eabb38ee"


def ceiling_from(budget):
    """The ceiling a budget makes: its source, measured and unreached."""
    return {"source": budget.get("source", {}), "measured": budget.get("measured", {}),
            "unreached": sorted(budget.get("unreached", {}))}


def ceiling_text(ceiling):
    """One line per file or scene, so a change reads in a diff."""
    lines = ["{"]
    for part in ("measured", "source"):
        lines.append(' "%s": {' % part)
        keys = sorted(ceiling[part])
        for k, key in enumerate(keys):
            lines.append("  %s: %s%s" % (json.dumps(key, ensure_ascii=False),
                                         json.dumps(ceiling[part][key], sort_keys=True, ensure_ascii=False),
                                         "," if k + 1 < len(keys) else ""))
        lines.append(" },")
    lines.append(' "unreached": %s' % json.dumps(ceiling["unreached"], ensure_ascii=False))
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_ceiling(budget):
    """Write the ceiling from a budget; returns its hash, for CEILING_SHA256."""
    import hashlib
    text = ceiling_text(ceiling_from(budget))
    CEILING.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def above_ceiling(budget, ceiling):
    """Every budget the ceiling does not allow."""
    out = []
    for part in ("source", "measured"):
        for key, marks in budget.get(part, {}).items():
            cap = ceiling[part].get(key)
            if cap is None:
                out.append("%s %s: not in the ceiling (a file or scene absent from it is at zero)" % (part, key))
                continue
            for marker, n in marks.items():
                if n > cap.get(marker, 0):
                    out.append("%s %s: %s %d, ceiling %d" % (part, key, marker, n, cap.get(marker, 0)))
    for key in budget.get("unreached", {}):
        if key not in ceiling["unreached"]:
            out.append("unreached %s: not unreached in the ceiling (a scene the book reached must stay reached)" % key)
    return out


# ── STRICT, by file, by batch, by scene, by region ──────────────────────
#
# budget["strict"]["source"]: "<file>" (the whole file at zero, no budget),
# "<file>@<batch>" (the lines of that file the batch owns, at zero), or
# "*@<batch>" (every line the batch owns, in every file). Measured:
# "<scene>" (no budget, at zero), "<scene>@<region>" (that shell region of
# that scene at zero), "*@<region>" (that region of every scene). B1 makes
# its regions strict on every page while the pages' own batches are still
# to come.

def strict_source_breaches(strict, hits, now, budget):
    out = []
    for entry in strict:
        path, _at, batch = entry.partition("@")
        if not batch:
            if path in budget:
                out.append("%s is strict and still has a budget" % path)
            out += ["%s:%d %s (strict)" % (h.file, h.line, h.marker) for h in hits if h.file == path]
            continue
        out += ["%s:%d %s (strict for %s)" % (h.file, h.line, h.marker, batch) for h in hits
                if (path == "*" or h.file == path) and owner(h.file, h.line, h.marker) == batch]
    return out


def strict_measured_breaches(strict, results, budget):
    out = []
    for entry in strict:
        scene, _at, region = entry.partition("@")
        for key, r in results.items():
            if why_unread(key, r) or (scene != "*" and key != scene):
                continue
            if not region:
                if key in budget:
                    out.append("%s is strict and still has a budget" % key)
                if r["counts"]:
                    out.append("%s (strict): %s" % (key, r["counts"]))
            elif r.get("regions", {}).get(region):
                out.append("%s, region %s (strict): %s" % (key, region, r["regions"][region]))
    return out


# ── the measured budget ─────────────────────────────────────────────────

GLYPH_MARKERS = ("glyph_face",)
#: The markers that follow the layout: which face drew a glyph, a box's
#: size against its radius, where the first line falls, what overlaps,
#: what is wider than the screen, how big a target is, which box is large
#: enough to be a card. On the CI machine they may read a little under
#: their budget (never over): a count may sit up to its slack below it.
LAYOUT_MARKERS = ("glyph_face", "radius", "first_line_low", "chrome_over_content", "sideways", "target_small",
                  "see_through", "shadow", "gradient")


def slack(n):
    return max(2, n // 10)


def why_unread(key, r):
    """Why a scene was not read as itself: the state was not reached, or the
    page did not answer 200 (an error page's own code is its point). Such a
    scene is recorded in "unreached", and never compared with a budget: a
    page sent elsewhere was read as the page it was sent to."""
    if r.get("error"):
        return r["error"]
    if r.get("status") not in (200, None) and not key.startswith("error:"):
        return "status %s" % r["status"]
    return None


def compare_measured(results, budget, glyphs=True):
    """(over, under). Over: one message per scene and marker above its
    budget, naming the page or state, and for each element group the
    selector, the property and the value (a scene absent from the budget
    must be at zero). Under: a count below its budget (the budget must
    follow it down), or, for a layout marker, below it by more than its
    slack."""
    over, under = [], []
    for key in sorted(results):
        r = results[key]
        if why_unread(key, r):
            continue
        allowed = budget.get(key, {})
        for marker in sorted(set(r["counts"]) | set(allowed)):
            if not glyphs and marker in GLYPH_MARKERS:
                continue
            n, cap = r["counts"].get(marker, 0), allowed.get(marker, 0)
            if n > cap:
                head = "%s: %s %d, budget %d%s" % (key, marker, n, cap,
                                                   "" if key in budget else " (a page absent from the budget is at zero)")
                lines = ["      x%d  %s  %s: %s  %r" % (k, sel, prop, value, text[:40])
                         for k, sel, prop, value, text in r["examples"].get(marker, [])]
                over.append("\n".join([head] + lines))
            elif n < cap and (marker not in LAYOUT_MARKERS or n < cap - slack(cap)):
                under.append("%s: %s %d, budget %d: lower it (SV_OLD_DESIGN_LOWER=1 on a full measured run, or"
                             " tests.old_design.budget.lower_measured_budgets(results))" % (key, marker, n, cap))
    return over, under


def measured_budget_from(results, glyphs=True):
    out = {}
    for key, r in sorted(results.items()):
        if why_unread(key, r):
            continue
        counts = {m: n for m, n in r["counts"].items() if n and (glyphs or m not in GLYPH_MARKERS)}
        if counts:
            out[key] = dict(sorted(counts.items()))
    return out


def lower_measured_budgets(results, write=True, glyphs=True):
    """Every measured budget lowered where the run's count went under it
    (never raised): an exact marker to its count, a layout marker to its
    count and its slack. Each shard lowers its own scenes; the budget file
    is read, changed and written under a lock (fcntl), so shards running
    in parallel never lose one another's lowering. After a batch, run the
    measured half with SV_OLD_DESIGN_LOWER=1."""
    import fcntl
    changes = []
    import tempfile
    with open(os.path.join(tempfile.gettempdir(), "sv_old_design_budget.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            budget = load_budget()
            meas = budget.setdefault("measured", {})
            for key, r in results.items():
                if why_unread(key, r) or key not in meas:
                    continue
                for marker in list(meas[key]):
                    if not glyphs and marker in GLYPH_MARKERS:
                        continue
                    got, cap = r["counts"].get(marker, 0), meas[key][marker]
                    to = got if marker not in LAYOUT_MARKERS else min(cap, got + slack(got))
                    if to < cap:
                        changes.append("%s %s %d -> %d" % (key, marker, cap, to))
                        if to:
                            meas[key][marker] = to
                        else:
                            del meas[key][marker]
                if not meas[key]:
                    del meas[key]
            if write and changes:
                write_budget(budget)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return changes
