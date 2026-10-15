"""The Big Money Board on the shell (spec §2.11, the command).

    python manage.py big_money show [--row R]
    python manage.py big_money compute [--date YYYY-MM-DD] [--run morning|evening]
    python manage.py big_money replay --from D --to D --yes
    python manage.py big_money fred-history --yes
    python manage.py big_money record
    python manage.py big_money symbols

`compute` stores one read as `manual`, made with the morning's rules or,
with --run evening, the evening's (a US session close not stored yet is
said, never yesterday's read as today's). With --date earlier than today's
as-of it is read point in time (publication lags, like a replay) and stored
with the replayed rows: a past day read with today's data in hand is not a
live record. `replay` writes replayed rows, never pooled with the live.
Nothing here places an order or writes a Signal.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "The Big Money Board: show, compute, replay, fred-history, record, symbols."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["show", "compute", "replay",
                                               "fred-history", "record",
                                               "symbols"])
        parser.add_argument("--row", default="")
        parser.add_argument("--date", default="")
        parser.add_argument("--run", default="morning",
                            choices=["morning", "evening"])
        parser.add_argument("--from", dest="date_from", default="")
        parser.add_argument("--to", dest="date_to", default="")
        parser.add_argument("--yes", action="store_true")

    def handle(self, *args, **opts):
        getattr(self, "_" + opts["action"].replace("-", "_"))(opts)

    # ── show ─────────────────────────────────────────────────────────
    def _show(self, opts):
        from bigmoney.read import newest
        from bigmoney.rows import GLOBAL, INSTRUMENTS, ROW_ORDER, ROWS
        head = newest(max_age_h=None)
        if not head.get("reads"):
            self.stdout.write("No read yet.")
            return
        self.stdout.write(f"Read of the market day {head['as_of']} "
                          f"({head['run']}, {head['computed_at']:%Y-%m-%d %H:%M} UTC)"
                          + ("" if head.get("ok") or head.get("age_h") is None
                             else f", {int(head['age_h'])} hours old"))
        keys = [opts["row"]] if opts["row"] else list(ROW_ORDER) + [GLOBAL, INSTRUMENTS]
        for key in keys:
            r = head["reads"].get(key)
            if r is None:
                self.stdout.write(f"\n{key}: no read")
                continue
            title = ROWS.get(key, {}).get("title", key)
            self.stdout.write(f"\n{title}: {r.lean_label or ''}"
                              + (f" ({', '.join(r.lean_from)})" if r.lean_from else ""))
            cells = r.cells or {}
            if key == INSTRUMENTS:
                for sym, entry in sorted(cells.items()):
                    lean = (entry or {}).get("_lean") or {}
                    self.stdout.write(f"  {sym}: {lean.get('label', '')}")
                continue
            for name, c in cells.items():
                if name.startswith("_") or not isinstance(c, dict):
                    continue
                if c.get("state") == "read":
                    self.stdout.write(f"  {name}: {c.get('words', '')}")
                elif c.get("state") == "unread":
                    self.stdout.write(f"  {name}: - ({c.get('why', '')})")
            for f in r.risk or []:
                self.stdout.write(f"  risk: {f}")

    # ── compute ──────────────────────────────────────────────────────
    def _compute(self, opts):
        from bigmoney.calendar import BusinessCalendar, as_of_for
        from bigmoney.read import read_board
        from bigmoney.score import score_due, store_board
        from django.utils import timezone
        cal = BusinessCalendar.from_db()
        live_as_of = as_of_for(timezone.now(), cal)
        as_of = date.fromisoformat(opts["date"]) if opts["date"] else None
        if as_of is not None and as_of > live_as_of:
            # A live row dated in the future would be the newest read on
            # the page, the brief and the ticket until that day passed.
            raise CommandError(f"--date {as_of} is after the live as-of day "
                               f"{live_as_of}: nothing read.")
        replayed = as_of is not None and as_of < live_as_of
        # Read with the morning's or the evening's rules (the evening says
        # "no close yet" for a close not stored), stored as manual.
        board = read_board(as_of, replayed=replayed, run=opts["run"], cal=cal)
        if board.get("failed"):
            self.stdout.write(
                f"The read of {board['as_of']} failed: nothing stored "
                f"({'; '.join(board.get('reasons') or [])}).")
            return
        stored = store_board(board, run="manual")
        score_due()
        self.stdout.write(
            f"Read of {board['as_of']} ({opts['run']} rules) stored as manual"
            + (" (point in time, with the replayed rows)" if replayed else "")
            + f": {stored} rows, {board['unread_count']} of "
              f"{board['footprints']} footprints unread.")
        for reason in board.get("reasons", [])[:10]:
            self.stdout.write(f"  unread: {reason}")

    # ── replay ───────────────────────────────────────────────────────
    def _replay(self, opts):
        from bigmoney.calendar import BusinessCalendar
        from bigmoney.inputs import Store
        from bigmoney.read import read_board
        from bigmoney.score import score_due, store_board
        if not (opts["date_from"] and opts["date_to"]):
            raise CommandError("replay needs --from and --to (YYYY-MM-DD).")
        start = date.fromisoformat(opts["date_from"])
        end = date.fromisoformat(opts["date_to"])
        cal = BusinessCalendar.from_db()
        days, d = [], start
        while d <= end:
            if cal.is_business_day(d):
                days.append(d)
            d += timedelta(days=1)
        if not opts["yes"]:
            self.stdout.write(f"Would replay {len(days)} business days "
                              f"({start} to {end}) with publication lags, "
                              f"stored as replayed rows. --yes runs it.")
            return
        store = Store(upto=end + timedelta(days=40))
        n, failed = 0, []
        for d in days:
            # One store for the whole replay; read_board slices it point in
            # time (closes <= as_of, COT and FRED by publication).
            board = read_board(d, replayed=True, run="replay", cal=cal,
                               store=store)
            if board.get("failed"):
                failed.append(d.isoformat())
                continue
            store_board(board, store=store)
            n += 1
        scored = score_due(cal=cal, store=Store(), replayed=True)
        self.stdout.write(f"Replayed {n} days; {scored} claims scored.")
        if failed:
            self.stdout.write(f"  failed, nothing stored: {', '.join(failed[:10])}"
                              + (f" and {len(failed) - 10} more"
                                 if len(failed) > 10 else ""))

    # ── fred-history ─────────────────────────────────────────────────
    def _fred_history(self, opts):
        from bigmoney.inputs import BOARD_FRED_SERIES
        if not opts["yes"]:
            self.stdout.write("Would fetch 2000 observations of each of "
                              + ", ".join(BOARD_FRED_SERIES)
                              + " from FRED. --yes runs it.")
            return
        from market_data.adapters.fred_adapter import _api_key
        if not _api_key():
            raise CommandError("FRED_API_KEY is not set: nothing fetched.")
        for series in BOARD_FRED_SERIES:
            got = fetch_history(series)
            self.stdout.write(f"{series}: {got.get('parsed', 0)} observations "
                              f"({got.get('created', 0)} new, "
                              f"{got.get('revised', 0)} revised)")

    # ── record ───────────────────────────────────────────────────────
    def _record(self, opts):
        from bigmoney.score import record
        for flag, name in ((False, "Live"), (True, "Replayed")):
            rows = record(replayed=flag)
            self.stdout.write(f"\n{name} record ({len(rows)} footprint-markets)")
            for r in rows:
                self.stdout.write(f"  {r['footprint']:<20} {r['market']:<12} "
                                  f"{r['verdict']}"
                                  + (f" | {r['cost']}" if r.get("cost") else ""))

    # ── symbols ──────────────────────────────────────────────────────
    def _symbols(self, opts):
        from bigmoney.rows import BOND_LEG, FX_FIX_PAIRS, ROWS
        syms = []
        for s in (["SPX500", *BOND_LEG] + [r["graded_on"] for r in ROWS.values()]
                  + [r["etf"] for r in ROWS.values()]
                  + list(FX_FIX_PAIRS.values()) + list(FX_FIX_PAIRS)
                  + _cot_commodities()):
            if s not in syms:
                syms.append(s)
        self.stdout.write("python manage.py backfill_bars --symbols "
                          + ",".join(syms) + " --intervals 1d --bars 1600")


def _cot_commodities() -> list:
    try:
        from scraping.models import COTReport
        return sorted(set(COTReport.objects.filter(
            instrument__asset_class="commodity")
            .values_list("instrument__symbol", flat=True)))
    except Exception:  # noqa: BLE001
        return []


def fetch_history(series_id, limit=2000) -> dict:
    """fetch_series(series_id, limit=2000), upserted through the adapter's
    own get_or_create / revise path (fred_adapter.save_series_to_db)."""
    from market_data.adapters.fred_adapter import save_series_to_db
    return save_series_to_db(series_id, limit=limit)
