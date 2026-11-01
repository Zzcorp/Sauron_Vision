"""Where the money is, what each broker holds, and where the platform and
the broker disagree — in one screen.

The shell twin of /treasury/. Both render bot_program/broker_vision.vision(),
so the page and the terminal cannot tell different stories. Reads cached
columns only: it makes NO broker call and writes nothing.

Run with:

    python manage.py treasury
    python manage.py treasury --user <you>
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()
DASH = "—"          # unmeasured. Never a 0.


def _lev(value) -> str:
    """'2x' for a multiplier the row carried — '1x' for a row that SAID 1;
    the em dash when it did not say. Never '1x' for silence: that is a
    claim about margin nobody measured (a row opened before 2026-09-23, or
    one sent at the adapter's own default, carries no key at all)."""
    if value is None or isinstance(value, bool):
        return DASH
    try:
        return f"{int(value)}x"
    except (TypeError, ValueError):
        return DASH


def _age(seconds) -> str:
    if seconds is None:
        return DASH
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds / 3600:.1f}h"


def _own_figures(h) -> str:
    """'  amount 350.00  net +12.50  position 12' for an eToro holdings row
    that carries them (2026-10-31); '' for a row that carries none."""
    out = ""
    if h.get("amount") is not None:
        out += f"  amount {float(h['amount']):,.2f}"
    if h.get("net_profit") is not None:
        out += f"  net {float(h['net_profit']):+,.2f}"
    if h.get("position_id"):
        out += f"  position {h['position_id']}"
    return out


def _divergence_lines(w, d) -> None:
    """The eToro comparison's own headings (2026-10-31): a row newer than
    the snapshot, a closing row the broker no longer lists, a close Sauron
    stopped trying, a pair whose units differ. Never PLATFORM ONLY."""
    for a in d.get("agree") or []:
        if a.get("units_differ"):
            w(f"      UNITS DIFFER   {a['symbol']:<12} the broker holds "
              f"{float(a['broker'].get('qty') or 0):.4f}, the row "
              f"{float(a['platform'].get('qty') or 0):.4f}")
    for p in d.get("newer") or []:
        w(f"      NEWER          {p['symbol']:<12} {p['side']:<5} "
          f"{p['qty']:.4f}  ({p['config']}) — booked after the holdings "
          f"were read; the next sync compares it")
    for p in d.get("closing_gone") or []:
        w(f"      CLOSING        {p['symbol']:<12} {p['side']:<5} "
          f"{p['qty']:.4f}  ({p['config']}) — the broker no longer reports "
          f"it: the close is being booked")
    for s in d.get("stopped") or []:
        p = s["platform"]
        w(f"      STOPPED        {p['symbol']:<12} {p['side']:<5} "
          f"{p['qty']:.4f}  (#{p['id']}) — Sauron stopped closing it; "
          + ("still open at the broker: close it there" if s.get("held")
             else "the broker no longer lists it"))


def _working_lines(w, d) -> None:
    """One line per WORKING entry under its own heading: an order the tick
    is polling, not a position — never PLATFORM ONLY, never a blocker."""
    for p in d.get("working") or []:
        w(f"      WORKING ENTRY  {p['symbol']:<12} {p['side']:<5} "
          f"{p['qty']:.4f}  ({p['config']}) — an order the tick is "
          f"polling, not a position"
          + ("; the broker already reports it — the fill is being booked"
             if p.get("reported") else ""))


class Command(BaseCommand):
    help = ("Every broker, its capital, its positions, and the divergence "
            "between what the broker reports and what the platform believes. "
            "Read-only, no broker call.")

    def add_arguments(self, parser):
        parser.add_argument("--user", default="",
                            help="username (default: every user with a "
                                 "broker row)")

    def handle(self, *args, **opts):
        from bot_program.broker_vision import vision

        if opts["user"]:
            users = list(User.objects.filter(username=opts["user"]))
            if not users:
                raise CommandError(f"no user {opts['user']!r}")
        else:
            users = [u for u in User.objects.all()
                     if any(getattr(u, a, None) is not None for a in
                            ("saxo_account", "etoro_account", "ibkr_account"))]
            if not users:
                raise CommandError("no user has a broker row — add keys on "
                                   "/brokers/ first")
        w = self.stdout.write
        for user in users:
            self._one(w, user, vision(user))

    def _one(self, w, user, v):
        w("=" * 78)
        w(f"TREASURY {DASH} {user.username} {DASH} "
          f"{v['at'].strftime('%Y-%m-%d %H:%M')} UTC")
        w("=" * 78)

        w("\n1. THE BOOK")
        book = v["book"]
        if book is None:
            w(f"   {DASH} no row is the book: capital_truth has nothing to "
              f"read, and the preflight refuses to arm money")
        else:
            eq = book["equity"]
            money = (f"{eq['value_text']} {eq['currency']}" if eq else DASH)
            w(f"   {book['name']:<22} {book['env']:<6} {money:>20}   "
              f"read {_age(eq['age_seconds'] if eq else None)} ago")
            hw, dd = v["high_water"], v["drawdown"]
            hw_text = f"{hw['hwm']:,.2f} {hw['currency']}" if hw else DASH
            # drawdown_pct is a FRACTION of the high-water mark, never
            # negative — capital_truth.equity_drawdown's own contract.
            dd_text = f"{dd['drawdown_pct'] * 100:.2f}%" if dd else DASH
            w(f"   high water {hw_text:<24} drawdown from it {dd_text}")
        # eToro's own figures and the split (2026-10-31): the page's book
        # card says the same, from bot_program.etoro_used.
        e = v.get("etoro")
        if e:
            w(f"   {e['t']}")
            w(f"   {e['split_t']}.")
            if e.get("read") and e.get("frozen"):
                w(f"   eToro holds {e['frozen_t']} as frozen cash for pending "
                  f"orders (inside its used figure).")

        w("\n2. EVERY BROKER")
        w(f"   {'broker':<22} {'env':<6} {'capital':>18}  {'age':>6} "
          f"{'held':>5}  claims")
        for r in v["brokers"]:
            eq = r["equity"]
            money = f"{eq['value_text']} {eq['currency']}" if eq else DASH
            held = DASH if r["held_n"] is None else str(r["held_n"])
            flag = " *book" if r["is_book"] else ""
            w(f"   {r['name'] + flag:<22} {r['env']:<6} {money:>18}  "
              f"{_age(eq['age_seconds'] if eq else None):>6} {held:>5}  "
              f"{', '.join(r['claims']) or DASH}")
            w(f"   {'':<22} {r['session']}")

        w("\n3. WHERE A NEW TRADE WOULD GO")
        for r in v["routing"]:
            how = ("contested: " + ", ".join(r["claimants"])
                   if r["contested"] else
                   "by default" if r["by_default"] else "claimed")
            w(f"   {r['asset_class']:<12} {r['winner']:<10} {how}")

        w("\n4. POSITIONS THE PLATFORM BELIEVES ARE OPEN")
        plat = v["platform"]
        if not plat["live"]:
            w(f"   no live row open   ({plat['paper_n']} paper row(s), "
              f"counted apart {DASH} venue discipline)")
        else:
            w(f"   {'symbol':<12} {'side':<5} {'qty':>14} {'entry':>14} "
              f"{'broker':<8} {'how':<9} {'lev':>4} state")
            for p in plat["live"]:
                state = ("closing" if p.get("closing") else
                         "working" if p["working"] else
                         "protected" if p["protected"] else "unprotected")
                w(f"   {p['symbol']:<12} {p['side']:<5} {p['qty']:>14.4f} "
                  f"{p['entry']:>14.4f} {p['broker']:<8} "
                  f"{p['attribution']:<9} {_lev(p.get('leverage')):>4} "
                  f"{state}"
                  + (f"  unconverted {p['unconverted']}"
                     if p.get("unconverted") else ""))
            w(f"   and {plat['paper_n']} paper row(s), counted apart")

        w("\n5. WHAT EACH BROKER SAYS IT HOLDS")
        for r in v["brokers"]:
            if r["held"] is None:
                w(f"   {r['name']}: {DASH} never read")
                continue
            w(f"   {r['name']} ({_age(r['held']['age_seconds'])} ago):")
            if not r["held"]["rows"]:
                w("      flat — measured, and zero")
            for h in r["held"]["rows"]:
                mark = h.get("market_price") or 0
                w(f"      {str(h.get('symbol')):<12} "
                  f"{str(h.get('side', '')):<5} "
                  f"{float(h.get('qty') or 0):>14.4f} @ "
                  f"{float(h.get('avg_cost') or 0):>12.4f}  "
                  f"mark {float(mark):>12.4f}  "
                  f"{h.get('currency') or ''}  lev {_lev(h.get('leverage'))}"
                  + _own_figures(h))

        # What eToro holds outside Sauron's rows, position by position
        # (2026-10-31): the page's "Outside Sauron at eToro" card.
        out = (v.get("etoro") or {}).get("positions")
        if out is not None:
            w("\n5b. OUTSIDE SAURON AT eTORO, POSITION BY POSITION")
            if not out["known"]:
                w(f"   {DASH} eToro's holdings have never been read")
            elif not out["rows"]:
                w(f"   every position eToro lists is one of Sauron's rows "
                  f"(holdings read {out['age_t']} ago)")
            else:
                for r in out["rows"]:
                    est = " (estimated)" if r["estimated"] else ""
                    pid = (f"position {r['position_id']}" if r["position_id"]
                           else DASH)
                    # a fresh in-doubt note on the symbol (2026-11-01):
                    # words only, as on the page
                    doubt = (f"  {r['in_doubt_t']}" if r.get("in_doubt_t")
                             else "")
                    w(f"   {r['symbol']:<12} {r['side'] or DASH:<5} "
                      f"{(r['qty'] or 0):>14.4f} @ {(r['avg_cost'] or 0):>12.4f}"
                      f"  lev {_lev(r['leverage'])}  margin "
                      f"{r['margin_t']}{est}  net {r['net_profit_t']}  {pid}"
                      f"{doubt}")
                w(f"   {out['n']} position(s), {out['margin_t']} of margin, "
                  f"holdings read {out['age_t']} ago; matched by eToro's "
                  f"position id, else by symbol, side and units")
                # The page's footer, said here too (2026-10-31).
                w("   section 1's outside figure is eToro's used minus "
                  "Sauron's rows and the closes Sauron stopped trying that "
                  "eToro still lists: pending orders, a row eToro no longer "
                  "holds and the time between the two reads set the two "
                  "apart")

        w("\n6. DIVERGENCE — THE BROKER AGAINST THE PLATFORM")
        for d in v["divergence"]:
            _queued = (f", {len(d['working'])} working entr"
                       f"{'y' if len(d['working']) == 1 else 'ies'} "
                       f"(orders, not compared)" if d["working"] else "")
            if not d["known"]:
                w(f"   {d['name']}: {DASH} cannot be compared ({d['reason']}); "
                  f"{d['platform_n']} platform row(s) attributed to it"
                  f"{_queued}")
                _working_lines(w, d)
                continue
            _vs = (f" — against a snapshot {d['age_text']} old, NOT the "
                   f"broker: this is agreement with a memory"
                   if d.get("stale") else "")
            w(f"   {d['name']}: {len(d['agree'])} agree, "
              f"{len(d['only_broker'])} only at the broker, "
              f"{len(d['only_platform'])} only in the platform{_queued}{_vs}")
            for p in d["only_platform"]:
                w(f"      PLATFORM ONLY  {p['symbol']:<12} {p['side']:<5} "
                  f"{p['qty']:.4f}  ({p['config']})")
            for h in d["only_broker"]:
                w(f"      BROKER ONLY    {str(h.get('symbol')):<12} "
                  f"{str(h.get('side', '')):<5} "
                  f"{float(h.get('qty') or 0):.4f}"
                  + (f"  position {h['position_id']}"
                     if h.get("position_id") else ""))
            _divergence_lines(w, d)
            _working_lines(w, d)

        w("\n" + "=" * 78)
        if v["blockers"]:
            w("BLOCKERS — the platform and the money do not agree:")
            for i, m in enumerate(v["blockers"], 1):
                w(f"  {i}. {m}")
        else:
            w("NO BLOCKERS — every broker read agrees with the platform's own "
              "rows.")
        if v["notes"]:
            w("\nWORTH READING:")
            for i, m in enumerate(v["notes"], 1):
                w(f"  {i}. {m}")
        w("=" * 78)
        w("Cached columns only: this command makes no broker call and writes "
          "nothing. An em dash is never a zero.")
