"""List, then on request delete, the public feed's 4h bars left on an old
grid beside the bars of the fixed UTC grid (2026-10-31), or beside the
bars of another old grid (2026-11-01).

    python manage.py prune_offgrid_4h                  # a dry run: the list, nothing deleted
    python manage.py prune_offgrid_4h --symbol XAUUSD  # one symbol
    python manage.py prune_offgrid_4h --yes            # delete what the dry run listed

Yahoo has no 4h bar; the public feed builds it from 1h. It used to anchor
the 4h grid at the first midnight of its ~200-day window in the exchange's
zone, so the grid moved by an hour in UTC whenever that window started
across a daylight-saving change, and the bars of both grids stayed in the
table (the timestamp is part of the key): pairs of near-identical 4h
candles an hour apart, read by the chart and by every rule on the symbol.
The feed now writes one grid, 00, 04, 08... UTC (public_feed.YFinanceFeed).

Only the PUBLIC FEED's rows are listed (their source ends in "_public"):
a venue's own bars are never listed, on any grid, and the delete reads
the source again. Two rules list a row.

1. Beside the UTC grid: a public row off the UTC 4h grid that overlaps a
   4h row of the same instrument that is on it. Until the bar refresh has
   written the new grid for a symbol, this rule lists nothing of it. It
   clears London (its winter grid is the UTC grid), New York (its summer
   grid is) and Tokyo (one grid) wherever the new grid's window reaches.

2. An old grid beside another old grid (2026-11-01). Where neither of a
   zone's two clocks puts midnight on the UTC grid, both old grids are
   off it: the CET zone's (DAX40, CAC40, IBEX35, STOXX50, any Berlin,
   Paris or Madrid series) were anchored at CET's midnight, 23:00 UTC
   (bars at 03, 07, 11... UTC), or at CEST's, 22:00 UTC (02, 06, 10...),
   and Sydney's, Helsinki's and Chicago's clocks miss it too. Where both
   old grids were stored before the new grid's window, rule 1 saw
   nothing, the command said there was nothing, and the bots, which read
   300 to 500 4h bars, read both. Among the public off-grid rows rule 1
   leaves, a row that overlaps a public off-grid row on another grid is
   contested; a run of contested rows is an overlapping stretch, and the
   stretch prefers ONE grid:
   - continuity: the grid of the bar just before the stretch and of the
     bar just after it (any source, once rule 1's rows are gone), when
     one of them is on one of the stretch's grids, or both on the same;
   - else (they are on two different grids of the stretch, or neither is
     on one of its grids) the later anchor: the grid whose bars open an
     hour after the other's (CET's 23:00 UTC over CEST's 22:00 UTC;
     _later_anchor).

   No hour loses its bar (2026-11-01, on review of the first cut, which
   deleted a row whenever its twin of the same 4h period stayed). A row
   goes only when every hour of its 4h span is in a whole bar that stays,
   or in an EMPTY 4h period of another grid: one with no bar although
   that grid was written on both sides of it (the old feed wrote every
   period of its window that held a trade, so that one held none), at the
   edge of a session (inside a session, between bars, a missing bar is
   likelier a row lost than a pause in trading), and beside no bar of the
   UTC grid (there the first rule deletes the old grids' bars, on this run
   or an earlier one). Sydney's 05:00 UTC bar holds 05:00 alone, inside
   the 02:00 bar, the 06:00 period being empty; Chicago's 10:00 bar holds
   13:00 alone, inside the 13:00 bar, the 09:00 period being empty. A
   stretch's two edges are where this bites:
   - where a grid STARTS, its first pass wrote its 200 bars from wherever
     the 200th fell, often inside a session (a Xetra session has 3 bars,
     and 200 = 66 x 3 + 2): the hours before its first bar are in the
     other grid's bars alone;
   - where a grid STOPS (no bar of it between the stretch and the next
     lone bar), its last pass wrote its newest bar while that period may
     still have been trading: that bar may be short of hours, so it is
     not whole. A stretch whose grids all end where the UTC grid's bars
     begin ran into the UTC grid (the first rule cut them there): they
     went on.
   So each SESSION of a stretch (a run of bars with no hour between them
   that no bar spans: a trading day for an index, a week for a market
   that trades round the clock) keeps one grid whole, and the series
   changes grid between two sessions, never inside one: the preferred
   grid when its bars hold every hour of the other grid's there; else the
   other grid when its bars hold every hour of the preferred grid's; else
   (both grids stop inside it) the session is left as it is, and the
   command says so: "No off-grid 4h duplicates of the public feed." still
   means that nothing overlapping is left. London, New York and Tokyo
   have at most one old grid off the UTC grid, so this rule never lists
   one of theirs.

   This reads each grid of a stretch as ONE run of the old feed. The old
   feed's runs on a grid lasted five to seven months, and the next run on
   that grid looked back its 200 bars either not that far (two to five
   months: the CET zone, Sydney) or weeks past the earlier run's end,
   rewriting its last bars (Chicago's livestock): never to within days of
   that end, where two runs of one grid would meet unseen inside a
   stretch and the earlier one's short last bar would pass for whole.

Off-grid history with nothing overlapping it stays (deleting it would cut
the history short).

The deletion is destructive and changes the bars the bots read (once,
toward one bar per period): it runs only with --yes, after the operator
has read the dry run. --yes lists again, deletes that list and counts it.
"""
import bisect

from django.core.management.base import BaseCommand

FOUR_H = 4 * 3600
INF = float("inf")

#: A stretch whose grids have no bar after it, followed within this by a
#: bar on the UTC grid, ran into the UTC grid (2026-11-01): the first rule
#: deletes the old grids' bars beside the UTC grid's, on this run or on an
#: earlier one, so they went on there rather than stopped. Ten days covers
#: a weekend and a holiday break, not a series that stopped for months.
RAN_INTO_UTC_S = 10 * 86400

#: Why a run of sessions kept its grid, as the command prints it; "whole"
#: names the grid its stretch prefers.
KEPT_BECAUSE = {
    "both": "the grid of the bars before and after the stretch",
    "before": "the grid of the bar before the stretch",
    "after": "the grid of the bar after the stretch",
    "split": ("the later anchor (the bars before and after the stretch "
              "are on different grids)"),
    "none": ("the later anchor (no bar beside the stretch is on one of "
             "its grids)"),
    "whole": ("which holds every hour of the session(s) there; the {} grid "
              "does not"),
}

#: Rule 2, as the command prints it under the rows it lists.
PAIR_RULE = ("Where two old grids overlap, each stretch keeps one grid: the "
             "grid of the bars just before and after it (continuity), else "
             "the later anchor (the grid whose bars open an hour after the "
             "other's). A session (a run of bars with no hour between them) "
             "keeps one grid whole, so the grid changes between sessions, "
             "never inside one: a session the kept grid does not hold every "
             "hour of (such as one where a grid starts or stops) keeps the "
             "other grid. "
             "A row goes only when every hour of its span is in a whole bar "
             "that stays (a grid's last bar before it stopped may be short) "
             "or in a 4h period another grid shows empty (no bar at a "
             "session's edge, that grid written on both sides): one bar per "
             "period, and no hour loses its bar.")


def offgrid_duplicates(symbol=""):
    """{instrument symbol: [(pk, timestamp, source), ...]} of every row the
    command deletes, by both rules, oldest first (2026-11-01: the old-grid
    pairs too, never a row it leaves as it is)."""
    out = {}
    for sym, groups in offgrid_groups(symbol).items():
        rows = [row for g in groups if g["rule"] != "left"
                for row in g["rows"]]
        if rows:
            out[sym] = sorted(rows, key=lambda row: row[1])
    return out


def offgrid_groups(symbol=""):
    """{instrument symbol: [group, ...]}: what the command lists, by rule
    (2026-11-01). A group is a dict: "rule" ("utc": beside the UTC grid,
    "pair": an old grid beside another, "left": overlapping rows the
    second rule leaves as they are, said and never deleted) and "rows"
    [(pk, timestamp, source), ...], oldest first. A "pair" group also has
    "grids" (the listed rows' grids, each as its offset from the UTC grid
    in seconds), "kept" (the grid its sessions keep), "why" (a
    KEPT_BECAUSE key) and "preferred" (the grid its stretch prefers); a
    "left" group has "grids". The UTC grid's group comes first, then the
    stretches' groups, oldest first: one per run of sessions that keep one
    grid, or that are left."""
    from market_data.models import PriceData

    qs = PriceData.objects.filter(timeframe="4h")
    if symbol:
        qs = qs.filter(instrument__symbol=symbol)
    rows = (qs.order_by("instrument_id", "timestamp")
            .values_list("pk", "instrument__symbol", "timestamp", "source"))
    by_inst = {}
    for pk, sym, ts, source in rows:
        by_inst.setdefault(sym, []).append(
            (pk, ts, source, int(ts.timestamp())))
    out = {}
    for sym, items in by_inst.items():
        items.sort(key=lambda row: row[3])
        groups = _groups(items)
        if groups:
            out[sym] = groups
    return out


def _public(source) -> bool:
    """The public feed's row: its source ends in "_public"."""
    return str(source or "").endswith("_public")


def _groups(items):
    """One instrument's groups (2026-11-01). `items`: every 4h row of it,
    any source, as (pk, timestamp, source, epoch second), oldest first."""
    on_grid = [t for *_row, t in items if t % FOUR_H == 0]
    beside = [row for row in items
              if on_grid and row[3] % FOUR_H and _public(row[2])
              and any(abs(g - row[3]) < FOUR_H
                      for g in _near(on_grid, row[3]))]
    groups = []
    if beside:
        groups.append({"rule": "utc", "rows": [row[:3] for row in beside]})
    gone = {row[0] for row in beside}
    groups.extend(_old_grid_pairs(items, gone))
    return groups


def _old_grid_pairs(items, gone):
    """Rule 2 on one instrument (2026-11-01): its groups, oldest first.
    `items`: every 4h row of it, any source, oldest first; `gone`: the
    pks rule 1 lists."""
    left = [row for row in items if row[0] not in gone]
    rows = [row for row in left if row[3] % FOUR_H and _public(row[2])]
    n = len(rows)
    contested = [False] * n
    for i in range(n):
        j = i + 1
        # Two rows of one grid are 4h apart at least: a row opening less
        # than 4h after this one is on another grid, and overlaps it.
        while j < n and rows[j][3] - rows[i][3] < FOUR_H:
            contested[i] = contested[j] = True
            j += 1
    if not any(contested):
        return []
    table = _Table(items, left)
    groups = []
    i = 0
    while i < n:
        if not contested[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and contested[j + 1]:
            j += 1
        groups.extend(_stretch_groups(
            rows[i:j + 1], rows[i - 1] if i else None,
            rows[j + 1] if j + 1 < n else None, table))
        i = j + 1
    return groups


class _Table:
    """What rule 2 reads off one instrument's 4h rows (2026-11-01): the
    rows rule 1 leaves, cut into sessions; which 4h periods hold a row;
    where each old grid was written."""

    def __init__(self, items, left):
        self.left = left
        self.stamps = [row[3] for row in left]
        # Every row's open, any source, rule 1's too: a period holding one
        # of them is not empty.
        self.taken = {row[3] for row in items}
        # Each old grid's public opens, rule 1's too: where it was written.
        self.written_at = {}
        for row in items:
            if row[3] % FOUR_H and _public(row[2]):
                self.written_at.setdefault(row[3] % FOUR_H, []).append(row[3])
        # The UTC grid's opens, any source: beside them the first rule
        # deletes the old grids' bars.
        self.utc_opens = [row[3] for row in items if row[3] % FOUR_H == 0]
        # Sessions: a new one opens where an hour lies between a row and
        # every row before it, an hour no bar spans. `bounds`: each
        # session's first open and last close.
        self.session_of, self.sessions, self.bounds = {}, [], []
        for row in left:
            if not self.bounds or row[3] > self.bounds[-1][1]:
                self.sessions.append([])
                self.bounds.append([row[3], row[3] + FOUR_H])
            self.sessions[-1].append(row)
            self.session_of[row[3]] = len(self.sessions) - 1
            self.bounds[-1][1] = max(self.bounds[-1][1], row[3] + FOUR_H)

    def written(self, grid, lo, hi):
        """A public row of `grid` opens in [lo, hi) (2026-11-01)."""
        opens = self.written_at.get(grid, [])
        k = bisect.bisect_left(opens, lo)
        return k < len(opens) and opens[k] < hi

    def ran_into_utc(self, last, after):
        """The row rule 1 leaves right after `last` (an open) is on the UTC
        grid, within RAN_INTO_UTC_S, and before `after` (the next lone
        public off-grid row, or None) (2026-11-01)."""
        k = bisect.bisect_right(self.stamps, last)
        if k == len(self.left):
            return False
        t = self.left[k][3]
        return (t % FOUR_H == 0 and t - last <= RAN_INTO_UTC_S
                and (after is None or t < after[3]))

    def beside_utc(self, t):
        """A 4h period opening at `t` overlaps a bar on the UTC grid
        (2026-11-01)."""
        return any(abs(u - t) < FOUR_H for u in _near(self.utc_opens, t))


def _stretch_groups(stretch, before, after, table):
    """One overlapping stretch's groups (2026-11-01): the grid it prefers,
    then, session by session, the grid each session keeps and the rows
    that go. `before` and `after`: the public off-grid rows just outside
    the stretch, or None."""
    grids = {row[3] % FOUR_H for row in stretch}
    preferred, why = _preferred(stretch, grids, table)
    first, last = stretch[0][3], stretch[-1][3]
    # Did each grid run before the stretch, and on after it? On after it:
    # a public row of it before the next lone row (rule 1's count: a grid
    # that runs on beside the UTC grid went on). Where none did and the
    # stretch runs straight into the UTC grid, the first rule cut them all
    # there, on this run or an earlier one: they went on.
    went = {g: [table.written(g, before[3] if before else -INF, first),
                table.written(g, last + 1, after[3] + 1 if after else INF)]
            for g in grids}
    if not any(on for _b, on in went.values()) and \
            table.ran_into_utc(last, after):
        for flags in went.values():
            flags[1] = True
    # Each grid's written span, and its last bar where it stopped.
    span, short = {}, set()
    for g in grids:
        own = [row for row in stretch if row[3] % FOUR_H == g]
        ran_before, went_on = went[g]
        span[g] = (-INF if ran_before else own[0][3],
                   INF if went_on else own[-1][3])
        if not went_on:
            short.add(own[-1][0])
    order = _by_preference(grids, preferred)
    by_session = {}
    for row in stretch:
        by_session.setdefault(table.session_of[row[3]], []).append(row)
    runs = []    # [(the grid kept, or None for "left"), group]
    for s in sorted(by_session):
        cands = by_session[s]
        here = {row[0] for row in cands}
        fixed = [row for row in table.sessions[s] if row[0] not in here]
        kept = next((g for g in order
                     if _holds(g, cands, fixed, span, short, table,
                               table.bounds[s])),
                    None)
        listed = cands if kept is None else \
            [row for row in cands if row[3] % FOUR_H != kept]
        if runs and runs[-1][0] == kept:
            group = runs[-1][1]
            group["rows"].extend(row[:3] for row in listed)
            group["grids"] = sorted(set(group["grids"])
                                    | {row[3] % FOUR_H for row in listed})
            continue
        group = {"rule": "left" if kept is None else "pair",
                 "rows": [row[:3] for row in listed],
                 "grids": sorted({row[3] % FOUR_H for row in listed})}
        if kept is not None:
            group.update(kept=kept, preferred=preferred,
                         why=why if kept == preferred else "whole")
        runs.append((kept, group))
    return [group for _kept, group in runs]


def _preferred(stretch, grids, table):
    """The grid a stretch prefers, and why (a KEPT_BECAUSE key): the grid
    of the bar just before it and of the bar just after it (any source),
    when one of them is on one of its grids, or both on the same; else
    the later anchor (2026-11-01)."""
    lo = bisect.bisect_left(table.stamps, stretch[0][3])
    hi = bisect.bisect_right(table.stamps, stretch[-1][3])
    beside = (("before", table.left[lo - 1] if lo > 0 else None),
              ("after", table.left[hi] if hi < len(table.left) else None))
    votes = {side: row[3] % FOUR_H for side, row in beside
             if row is not None and row[3] % FOUR_H in grids}
    if len(set(votes.values())) == 1:
        kept = next(iter(votes.values()))
        return kept, "both" if len(votes) == 2 else next(iter(votes))
    return _later_anchor(grids), "split" if votes else "none"


def _by_preference(grids, preferred):
    """The grids a session tries, in turn (2026-11-01): the stretch's
    preferred grid, then the later anchor of the others, and so on."""
    order, rest = [preferred], set(grids) - {preferred}
    while rest:
        order.append(_later_anchor(rest))
        rest.discard(order[-1])
    return order


def _holds(grid, cands, fixed, span, short, table, bounds):
    """`grid` holds a session (2026-11-01): every hour of each of the
    session's contested rows on another grid is in a whole bar that stays
    (a row of `grid` that is not its last bar before it stopped, `short`,
    or a row of the session outside the stretch, `fixed`) or in an EMPTY
    4h period of one of the stretch's grids:
    - no row of any source opens it;
    - it lies inside that grid's written `span`;
    - it reaches past the session's `bounds` (first open, last close),
      where trading starts or ends: inside a session, between bars, a
      missing bar is likelier a row lost than a pause in trading;
    - no bar on the UTC grid overlaps it (the first rule deletes the old
      grids' bars there, on this run or an earlier one)."""
    cover = [(row[3], row[3] + FOUR_H) for row in cands
             if row[3] % FOUR_H == grid and row[0] not in short]
    cover += [(row[3], row[3] + FOUR_H) for row in fixed]
    opens, closes = bounds
    for row in cands:
        t = row[3]
        if t % FOUR_H == grid:
            continue
        spans = list(cover)
        for g, (lo, hi) in span.items():
            start = t - (t - g) % FOUR_H    # g's period holding t
            for x in (start, start + FOUR_H):
                if (x < t + FOUR_H and x not in table.taken and lo < x < hi
                        and (x < opens or x + FOUR_H > closes)
                        and not table.beside_utc(x)):
                    spans.append((x, x + FOUR_H))
        if not _covered(t, t + FOUR_H, spans):
            return False
    return True


def _covered(start, end, spans):
    """[start, end) lies inside the union of `spans`, (from, to) pairs
    (2026-11-01)."""
    pos = start
    for a, b in sorted(spans):
        if a > pos:
            break
        pos = max(pos, b)
        if pos >= end:
            return True
    return pos >= end


def _later_anchor(grids):
    """Of a stretch's grids (offsets from the UTC grid, in seconds), the
    later anchor (2026-11-01): the grid whose bars open last, an hour after
    the other's for two grids an hour apart (CET's midnight, 23:00 UTC,
    over CEST's, 22:00 UTC; Sydney's AEST midnight, 14:00 UTC, over AEDT's,
    13:00 UTC). In general, the grid that the widest gap round the 4h
    circle follows; the larger offset breaks a tie."""
    ps = sorted(grids)
    return max(((ps[(k + 1) % len(ps)] - p) % FOUR_H or FOUR_H, p)
               for k, p in enumerate(ps))[1]


def _near(sorted_stamps, t):
    """The stamps that could overlap `t` (the two around it)."""
    i = bisect.bisect_left(sorted_stamps, t)
    return sorted_stamps[max(0, i - 1):i + 1]


def _grid(offset):
    """A grid in words, its bars' first opening times: "02:00, 06:00,
    10:00... UTC" (2026-11-01)."""
    def hm(s):
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}"
    return ", ".join(hm(offset + k * FOUR_H) for k in range(3)) + "... UTC"


def _line(sym, group):
    """One group as the command lists it (2026-11-01): the symbol, the
    count, the source, the rule and the first and last row. Rule 1's line
    is word for word what the command printed before rule 2."""
    rows = group["rows"]
    sources = ", ".join(sorted({s for _pk, _ts, s in rows}))
    span = (f"{rows[0][1]:%Y-%m-%d %H:%M} to {rows[-1][1]:%Y-%m-%d %H:%M} "
            f"UTC")
    if group["rule"] == "utc":
        return (f"  {sym}: {len(rows)} off-grid 4h row(s) of {sources} "
                f"beside the UTC grid's, {span}")
    on = " and ".join(_grid(g) for g in group["grids"])
    if group["rule"] == "left":
        return (f"  {sym}: {len(rows)} off-grid 4h row(s) of {sources} on the "
                f"{on} grids overlap, {span}; left as they are: no grid "
                f"holds every hour of the session(s) there")
    kept = _grid(group["kept"])
    why = KEPT_BECAUSE[group["why"]].format(_grid(group["preferred"]))
    return (f"  {sym}: {len(rows)} off-grid 4h row(s) of {sources} on the "
            f"{on} grid beside the {kept} grid's, {span}; kept: the {kept} "
            f"grid, {why}")


def _left_words(rows, symbols):
    """The overlapping rows rule 2 leaves as they are, in one line
    (2026-11-01)."""
    return (f"{rows} overlapping off-grid 4h row(s) in {symbols} symbol(s) "
            f"are left as they are: no grid holds every hour of their "
            f"session, so deleting either could leave an hour without a "
            f"bar.")


class Command(BaseCommand):
    help = ("List the public feed's off-grid 4h bars that sit beside the UTC "
            "grid's or beside another old grid's (dry run by default); "
            "--yes deletes them.")

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true",
                            help="delete the listed rows")
        parser.add_argument("--symbol", default="",
                            help="one instrument symbol")

    def handle(self, *args, **opts):
        from market_data.models import PriceData

        symbol = (opts.get("symbol") or "").strip().upper()
        found = offgrid_groups(symbol)
        # Said only when nothing overlapping is left (2026-11-01): no row to
        # delete, and none left as it is.
        if not found:
            self.stdout.write("No off-grid 4h duplicates of the public feed"
                              + (f" for {symbol}" if symbol else "") + ".")
            return
        for sym in sorted(found):
            for group in found[sym]:
                self.stdout.write(_line(sym, group))
        going = [g for sym in sorted(found) for g in found[sym]
                 if g["rule"] != "left"]
        total = sum(len(g["rows"]) for g in going)
        symbols = sum(1 for sym in found
                      if any(g["rule"] != "left" for g in found[sym]))
        held = [g for sym in sorted(found) for g in found[sym]
                if g["rule"] == "left"]
        left = _left_words(
            sum(len(g["rows"]) for g in held),
            sum(1 for sym in found
                if any(g["rule"] == "left" for g in found[sym]))
        ) if held else ""
        if any(g["rule"] == "pair" for g in going):
            self.stdout.write(PAIR_RULE)
        if not total:
            self.stdout.write("Nothing to delete. " + left)
            return
        if not opts.get("yes"):
            self.stdout.write(
                f"Dry run: {total} row(s) in {symbols} symbol(s) would be "
                f"deleted, nothing was. Run again with --yes to delete them.")
            if left:
                self.stdout.write(left)
            return
        pks = [pk for g in going for pk, _ts, _s in g["rows"]]
        # The source is read again at the delete (2026-11-01): a venue's bar
        # written over a listed row since the list (the bar pass writes in
        # another process) is the venue's now, and stays.
        deleted, _ = (PriceData.objects
                      .filter(pk__in=pks, timeframe="4h",
                              source__endswith="_public")
                      .delete())
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {deleted} off-grid 4h row(s) in {symbols} "
            f"symbol(s)."))
        if deleted < total:
            self.stdout.write(
                f"{total - deleted} listed row(s) were no longer the public "
                f"feed's when the delete ran (a venue's bar written over "
                f"them, or gone already): left as they are.")
        if left:
            self.stdout.write(left)
