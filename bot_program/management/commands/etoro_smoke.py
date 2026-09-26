"""Prove each READ of the eToro adapter with the stored key pair, read-only.

The WRITE path — the v2 order POST, the orders:lookup poll, the market-close
POST and the PATCH stop mover — met eToro on 2026-09-23 on the DEMO segment
only (deploy/ETORO_DEPARTURE.md §4 D2 / D2b-ii, pinned in
tests/test_etoro_client.py::TheMeasuredWireTests); on the LIVE segment it has
never been sent a byte. Of the reads, five have, on 2026-09-22, with a
live real key: aggregate-portfolio 200, portfolio 200, real/pnl 200, a GET
of the market-close path 405, and /market-data/search 200 — the adapter's
path table and tests/test_etoro_client.py record the first four. Two have
NOT: /instruments/rates and /history/candles are measured for the first
time BY this command. It is how the operator repeats the measurement before
a single order exists. Each read is reported in four states, so "eToro
refused the keys" can be told from "eToro knows no such spelling" from "the
adapter is wrong" from "the network is gone".

What it prints, in order:

  * the row — label, demo flag, which classes it carries, keyed yes/no.
    Never a key: "keyed" is the whole of what is said about them. A row
    with no class ticked is not the book and is routed to by nothing, but
    it is still read by sync_etoro_accounts every cycle and still counted
    by reconcile_asset.keyed_venue_count as a keyed venue.
  * the row's world: ping (aggregate-portfolio, top-level key NAMES only,
    plus the account currency read from that same payload), the adapter's
    own two-state ping(), and net_liquidation from the nested accountTotals
    block.
  * every symbol of every LIVE config of the user, enabled or not, with
    its route (broker_router.broker_name_for_symbol, read from the
    database: route=etoro, binance, alpaca …; "[no Instrument row →
    routes as crypto, no bars]"; "[index in a stock config]" where the
    row's class is not the config's): the instrument id beside eToro's OWN
    spelling of it — "(BTC ← BTCUSD)" where the adapter's VENUE_SPELLING
    rewrites the platform spelling (measured 2026-09-23); a lone /search
    result spelled differently is refused by the adapter and printed
    'unknown', never 'ok' — or NO SUCH SPELLING with eToro's own answer,
    or could-not-ask;
    then the ticker, printed as "no rate" whenever lastPrice is not > 0,
    which is the rule asset_engine/base.py applies (NO_PRICE), never as a
    price of 0; then klines on the config's timeframe, 5 bars, because
    market_data/bot_bars.py falls back to the public feed in silence when
    a venue answers no bars. order_book is composed from the same rates
    read and sends nothing of its own.
  * the book (get_positions, broker_portfolio), read AFTER the symbols so
    the reverse map is warm and the book can be named; an id this client
    never resolved is printed as ETORO:<id> [unnamed here], never guessed.
    Then how many of the user's live platform rows are OPEN without an
    etoro stamp — rows this book says nothing about.
  * with --other-world only: a ping of the OTHER world with the SAME pair.
    MEASURED 2026-09-23 (--user Sauron --other-world): the pair saved with
    Demo ticked answered 200 on the live world too — one eToro pair opens
    both worlds, and the Demo tick on /brokers/ alone picks the URL
    segment. Off by default so the ordinary run touches one world; kept so
    the operator can re-measure it.
  * the write URLs by name — composed, never called — each with what the
    tree records about it: on the DEMO segment all five answered on
    2026-09-23 (the measured facts are printed beside each); on the real
    segment the close path was attested by a GET answering 405 and the v2
    paths carry no measurement at all.
  * the floors, named and never read here: the MONEY floor
    (minPositionExposure) and the fractional reading (unitsQuantityType)
    are MEASURED 2026-09-23 on the eligibility row, which the engine reads
    before an entry; this command makes GET calls only — the adapter's
    eligibility read is run by hand (deploy/ETORO_DEPARTURE.md §4 D2c-0).

Run with:

    python manage.py etoro_smoke --user Sauron
    python manage.py etoro_smoke --user Sauron --symbol GLDM
    python manage.py etoro_smoke --user Sauron --other-world

Deliberately NOT runnable from the ops page: it presents the operator's
eToro keys to an external service and prints the account's balance.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()

OK, REFUSED, NOSUCH, UNKNOWN = "ok", "refused", "no-such", "unknown"

#: The classes an EtoroAccount row can claim, in is_primary_for()'s own
#: vocabulary — the same four save_etoro_credentials reads back.
CARRIED_CLASSES = ("stock", "forex", "commodity", "crypto")

#: Timeframe for a --symbol spelling that belongs to no config:
#: AssetBotConfig.timeframe's own default.
DEFAULT_TIMEFRAME = "1h"


class _NoSuch(Exception):
    """eToro answered 200 and knows no such spelling — its own no, and not
    a verdict on the keys."""


class _Unknown(Exception):
    """A read that answered, whose answer this command must not print as
    'ok' — said in its own words, without a type name in front."""


def _verdict(fn):
    """Four states, never two: (state, detail).

    401 is 'refused' — eToro saw the keys and said no; it is the one
    refusal the tree has measured (dashboard/views_brokers.etoro_probe).
    A 403 has never been measured and is 'unknown' here, with its body
    printed — the probe on /brokers/ would call it refused; this command
    will not until one has been seen. Any other HTTP status is 'unknown':
    a 404 is a path this adapter composed, a 5xx is eToro's day, and
    neither is a verdict on the keys. _NoSuch is eToro's own no to a
    spelling. Everything else is 'unknown' and named by type — including a
    LookupError from the adapter's path table, whose message names the
    tail itself.
    """
    import requests
    try:
        return OK, fn()
    except _NoSuch as e:
        return NOSUCH, str(e)
    except _Unknown as e:
        return UNKNOWN, str(e)
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        code = getattr(resp, "status_code", None)
        body = str(getattr(resp, "text", "") or "")[:120]
        if code == 401:
            return REFUSED, (f"HTTP 401 — eToro saw the keys and said no "
                             f"(the measured refusal) · body: {body!r}")
        if code == 403:
            return UNKNOWN, (f"HTTP 403 — refused at the door; 401 is "
                             f"eToro's measured refusal and a 403 has not "
                             f"been measured, so read the body: {body!r}")
        return UNKNOWN, f"HTTP {code or '?'} — not a verdict on the keys ({e})"
    except Exception as e:  # noqa: BLE001 — the point is to name it
        return UNKNOWN, f"{type(e).__name__}: {e}"


def _price_line(t, symbol: str) -> str:
    """instrument id, eToro's own spelling, and the ticker, for one spelling.

    The adapter asks /search for VENUE_SPELLING's rewrite of the platform
    spelling (measured 2026-09-23); a mapped one prints as "(BTC ← BTCUSD)"
    — eToro's spelling, then the platform's. A LookupError of exactly that
    type from instrument_id is eToro's own answer — /search returned 200
    and nothing matched — and becomes _NoSuch; the same type raised for a
    LONE result spelled differently (it carries `lone_id`: the adapter
    refuses it since 2026-09-26) is 'unknown', because a different
    instrument is possible and nothing here can tell. A KeyError or
    IndexError is also a LookupError and is NOT eToro's answer: it
    propagates and is named by type. The ticker is 'no rate' whenever
    lastPrice is not > 0 — the rule base.py applies for the mark (None) and
    for the entry (NO_PRICE) — never a price of 0, whichever shape the
    sentinel took.
    """
    from bot_program.engine.etoro_client import VENUE_SPELLING
    key = str(symbol).upper()
    wire = VENUE_SPELLING.get(key, key)
    try:
        iid = t.instrument_id(symbol)
    except LookupError as e:
        if type(e) is not LookupError:
            raise
        if getattr(e, "lone_id", None) is not None:
            raise _Unknown(
                f"instrument {e.lone_id} — eToro's lone /search result is "
                f"spelled {getattr(e, 'lone_spelling', '')!r}, not "
                f"{wire!r}: the adapter refuses it "
                f"(etoro_client.instrument_id) and a different instrument "
                f"is possible; map it in VENUE_SPELLING only once the "
                f"eligibility row's symbol confirms the name") from None
        raise _NoSuch(f"NO SUCH SPELLING AT ETORO: {e}") from None
    venue = str(t._venue_spelling.get(iid) or "")
    if venue != wire:
        raise _Unknown(
            f"instrument {iid} — eToro's own spelling reads {venue!r}, not "
            f"{wire!r} (etoro_client._venue_spelling); verify by hand "
            f"before this spelling trades")
    name = venue + (f" ← {key}" if wire != key else "")
    tk = t.ticker(symbol)
    try:
        last = float(tk.get("lastPrice") or 0)
    except (TypeError, ValueError):
        last = 0.0
    if last <= 0:
        return (f"instrument {iid} ({name}) · no rate (lastPrice "
                f"{tk.get('lastPrice')!r}, bid {tk.get('bid')!r}, ask "
                f"{tk.get('ask')!r} — the engine skips this as NO_PRICE; "
                f"not a price of 0)")
    return (f"instrument {iid} ({name}) · last {tk['lastPrice']} "
            f"bid {tk.get('bid')} ask {tk.get('ask')}")


def _route_note(user, symbol: str, cfg) -> str:
    """Where the router sends `symbol` for this config, read from the
    database — nothing is asked of any broker. The name is
    broker_router.broker_name_for_symbol, which answers the default
    client_for_symbol routes on (since 2026-09-26 a symbol with no
    Instrument row is crypto there too); beside it, a missing Instrument
    row, an Instrument class that is not the config's (an index or an ETF
    in a stock config rides the stocks box), and eToro's spelling where
    the adapter maps it."""
    from bot_program.engine.broker_router import broker_name_for_symbol
    from bot_program.engine.etoro_client import VENUE_SPELLING
    from instruments.models import Instrument
    try:
        route = broker_name_for_symbol(user, symbol, cfg)
    except Exception as e:  # noqa: BLE001 — the point is to name it
        route = f"? ({type(e).__name__}: {e})"
    parts = [f"route={route}"]
    inst = Instrument.objects.filter(symbol=symbol).first()
    if inst is None:
        parts.append("[no Instrument row → routes as crypto, no bars]")
    elif str(inst.asset_class) != str(cfg.asset_class):
        parts.append(f"[{inst.asset_class} in a {cfg.asset_class} config]")
    key = str(symbol).upper()
    if key in VENUE_SPELLING:
        parts.append(f"eToro spells it {VENUE_SPELLING[key]}")
    return " · ".join(parts)


def _bars_line(t, symbol: str, timeframe: str) -> str:
    """klines on the timeframe the config would trade, 5 bars. 0 bars is an
    answer — and the one market_data/bot_bars.py papers over by writing the
    public feed's bars instead, in silence."""
    rows = t.klines(symbol, timeframe, 5)
    if not rows:
        return (f"0 bars on {timeframe} — the venue is mute here; "
                f"bot_bars.py would fall back to the public feed and the "
                f"bot would trade on bars eToro never served")
    return f"{len(rows)} bars on {timeframe} · newest close {rows[-1][4]}"


def _two_state_ping(t) -> str:
    """ping() is two-state by contract: an exception is swallowed to False
    (etoro_client.ping), so a False here is 'unknown', never 'refused' —
    the aggregate-portfolio line above it is the one that can tell."""
    if t.ping():
        return "True"
    raise _Unknown("False — refused and could-not-ask both read False here "
                   "(etoro_client.ping swallows the exception); the "
                   "aggregate-portfolio line above is the one that can tell")


def _book_line(rows: list) -> str:
    if not rows:
        return "0 open — an empty list is an answer"
    parts = []
    for r in rows:
        name = r["symbol"] + (" [unnamed here]" if r.get("symbol_unresolved")
                              else "")
        parts.append(f"{r['side']} {r['qty']:g} {name}")
    return f"{len(rows)} open · " + " · ".join(parts)


def _unstamped_open_rows(user) -> int:
    """Live platform rows OPEN or CLOSE_PENDING whose metadata does not
    stamp broker == "etoro" — counted in Python, deliberately: the ORM's
    exclude(metadata__broker="etoro") compiles to NOT (json_extract(...) =
    'etoro') with no IS NOT NULL guard (metadata is null=False), so a row
    whose metadata never had the key compares NULL and is DROPPED — the
    unstamped rows are exactly the ones it would not count. The reading is
    reconcile_asset.unattributable's own."""
    from bot_program.models import AssetBotTrade
    n = 0
    for tr in AssetBotTrade.objects.filter(
            config__user=user, paper=False,
            status__in=("OPEN", "CLOSE_PENDING")).only("metadata"):
        carried = str((tr.metadata or {}).get("broker") or "")
        if carried != "etoro":
            n += 1
    return n


class Command(BaseCommand):
    help = ("Exercise the READS of the eToro adapter with one user's stored "
            "key pair — the row, its world, every live config's symbols "
            "(id, eToro's spelling, rate, bars), the book — and report each "
            "as ok / refused / no-such / unknown. Names the write URLs it "
            "never calls. Places no order.")

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True,
                            help="username whose EtoroAccount row to use")
        parser.add_argument("--symbol", action="append", default=[],
                            help="one more spelling to resolve, price and "
                                 "chart, beside every live config's symbols")
        parser.add_argument("--other-world", action="store_true",
                            default=False,
                            help="also ping the OTHER world (demo for a live "
                                 "row, live for a demo row) with the SAME "
                                 "pair — measured 2026-09-23: one pair opens "
                                 "both worlds; off by default so the ordinary "
                                 "run touches one world; pass it to "
                                 "re-measure")

    def handle(self, *args, **opts):
        from bot_program.engine import capabilities as cap
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.models import AssetBotConfig

        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"no user {opts['user']!r}")
        acct = getattr(user, "etoro_account", None)
        if acct is None:
            raise CommandError("no eToro row for this user — paste both keys "
                               "on /brokers/ first")
        k, u = acct.get_credentials()
        if not (k and u):
            raise CommandError("the eToro row is not keyed — paste both keys "
                               "on /brokers/ first")

        # NEVER A KEY. requests quotes the header VALUE when it refuses one
        # ("... in header value: '<key>'"), and both keys are header values;
        # the repr form is scrubbed too, because a key holding a line break
        # is quoted escaped. Every line of output goes through here.
        scrub = [(s, tag) for raw, tag in ((k, "<x-api-key>"),
                                           (u, "<x-user-key>"))
                 for s in (raw, repr(raw)[1:-1]) if s]

        def w(text: str):
            for s, tag in scrub:
                text = text.replace(s, tag)
            self.stdout.write(text)

        env = "demo" if acct.demo else "live"
        other = "live" if acct.demo else "demo"
        carried = [c for c in CARRIED_CLASSES if acct.is_primary_for(c)]
        carries = (", ".join(carried) if carried else
                   "NOTHING (no class ticked — not the book and routed to by "
                   "nothing; still read by sync_etoro_accounts every cycle "
                   "and still counted by reconcile_asset.keyed_venue_count "
                   "as a keyed venue)")
        w(f"ETORO SMOKE — {user.username} · {acct.env_label}")
        w("=" * 70)
        w(f"  row      label {acct.label!r} · demo {acct.demo} · carries "
          f"{carries} · keyed yes · connected {acct.connected} · last_sync "
          f"{acct.last_sync or '—'}")
        if acct.last_equity is not None:
            w(f"  row      cached equity {acct.last_equity} "
              f"{acct.last_equity_currency} at {acct.last_equity_at} — the "
              f"sync's cell, not a live read")
        else:
            w("  row      cached equity — (never synced, or dropped on an "
              "environment flip)")

        t = EtoroTrader(k, u, env=env)
        tally = {OK: 0, REFUSED: 0, NOSUCH: 0, UNKNOWN: 0}

        def line(name, fn):
            state, detail = _verdict(fn)
            tally[state] += 1
            w(f"  {state:<8} {name:<44} {detail}")
            return state

        account_ccy = None

        def _ping():
            nonlocal account_ccy
            info = t.account()
            account_ccy = str(info.get("accountCurrency") or "") or None
            return ("200 · top-level keys: " + ", ".join(sorted(info.keys()))
                    + f" · accountCurrency {account_ccy or 'ABSENT'}")
        world = line(f"{env} ping (aggregate-portfolio)", _ping)
        line(f"{env} ping() (the engine's two-state read)",
             lambda: _two_state_ping(t))

        def _nl():
            nl = t.net_liquidation()
            if nl:
                return f"{nl[0]:,.2f} {nl[1]}"
            if world != OK:
                raise _Unknown("None — the adapter swallowed the failure "
                               "(etoro_client.net_liquidation); the "
                               "aggregate-portfolio line says why")
            return ("None — a zero or a missing accountTotals block "
                    "(etoro_client.net_liquidation); NOT an empty account, "
                    "and the sync would store nothing")
        line(f"{env} net_liquidation (accountTotals)", _nl)

        def _mc():
            mc = t.margin_cells()
            if mc is None:
                raise _Unknown("None — the adapter swallowed the failure "
                               "(etoro_client.margin_cells); the sync would "
                               "leave the margin cells as they are")
            cash, used = mc.get("available_cash"), mc.get("used_margin")
            cash_s = "ABSENT" if cash is None else f"{cash:,.2f}"
            used_s = "ABSENT" if used is None else f"{used:,.2f}"
            return (f"available cash {cash_s} · used margin {used_s} "
                    f"{mc.get('currency') or ''} — the cells "
                    f"_leverage_headroom reads; ABSENT is a key the payload "
                    f"lacks, never a 0")
        line(f"{env} margin_cells (accountTotals)", _mc)

        w("-" * 70)
        configs = list(AssetBotConfig.objects.filter(user=user, mode="live")
                       .order_by("id"))
        w(f"  live configs: {len(configs)} — enabled or not; a disabled "
          f"config's symbols are the ones it would trade")
        wanted = []
        for cfg in configs:
            base = str(cfg.base_currency or "")
            if account_ccy is None:
                note = (" · account currency unmeasured (no accountCurrency "
                        "read from aggregate-portfolio) — the platform "
                        "converts nothing")
            elif base != account_ccy:
                note = (f" · base {base} ≠ account {account_ccy} — the "
                        f"platform converts nothing")
            else:
                note = f" · base {base} = account {account_ccy}"
            syms = list(cfg.symbols or [])
            w(f"  config   [{cfg.id}] {cfg.name} {cfg.asset_class} "
              f"enabled={cfg.enabled} · {len(syms)} symbols{note}")
            if not syms:
                w("           (no symbols — nothing to resolve)")
            for sym in syms:
                wanted.append((f"[{cfg.id}]", str(sym), str(cfg.timeframe)))
                w(f"           {str(sym):<12} "
                  f"{_route_note(user, str(sym), cfg)}")
        for sym in opts["symbol"]:
            wanted.append(("--symbol", str(sym), DEFAULT_TIMEFRAME))
        for owner, sym, tf in wanted:
            state = line(f"{owner} {sym}", lambda s=sym: _price_line(t, s))
            if state == OK:
                line(f"{owner} {sym} klines {tf}",
                     lambda s=sym, f=tf: _bars_line(t, s, f))

        w("-" * 70)
        line(f"{env} book (get_positions)", lambda: _book_line(t.get_positions()))

        def _bp():
            p = t.broker_portfolio()
            if p is None:
                raise _Unknown("None — the adapter swallowed the failure "
                               "(etoro_client.broker_portfolio); the sync "
                               "would count this account unreachable")
            return f"{len(p)} rows"
        line(f"{env} broker_portfolio", _bp)
        n = _unstamped_open_rows(user)
        w(f"  rows     {n} platform row(s) OPEN or CLOSE_PENDING, live, not "
          f"stamped broker=etoro — this book says nothing about them "
          f"(reconcile_asset.unattributable)")

        if opts["other_world"]:
            t2 = EtoroTrader(k, u, env=other)
            line(f"{other} ping with the SAME pair (measurement)",
                 lambda: f"200 — this pair opens the {other} world too · keys: "
                         + ", ".join(sorted(t2.account().keys())))
        else:
            w(f"  skipped  {other} ping with the SAME pair — measured "
              f"2026-09-23: one pair opens both worlds (the Demo tick on "
              f"/brokers/ alone picks the world); pass --other-world to "
              f"re-measure")

        w("-" * 70)
        w("  write path — composed and named here, NEVER called:")
        close_key = "market-close-orders"
        close_attested = close_key in EtoroTrader._V1_EXEC_REAL_SEG
        if t.demo:
            close_url = t._v1_exec(f"{close_key}/positions/<positionId>")
            close_note = ("measured 2026-09-23 on the demo segment: POST 2xx, "
                          "body orderForClose{positionID, instrumentID, "
                          "orderID (orderType 19, statusID 1)}; that orderID "
                          "is findable on no read path — the proof of the "
                          "close is the OPEN order's positionExecutions[0]"
                          ".state turning 'closed', reached after ~8 s with "
                          "three transient 500s on the way (the 2x close); "
                          "no executedQty, no closing price; a body carrying "
                          "UnitsToDeduct is accepted and never executes - "
                          "InstrumentID alone closes (measured 17:43-17:58 UTC)")
        elif close_attested:
            close_url = t._v1_exec(f"{close_key}/positions/<positionId>")
            close_note = ("real path attested by GET → 405 on 2026-09-22 "
                          "(_V1_EXEC_REAL_SEG); the POST itself has never "
                          "been sent on the real segment (demo: measured "
                          "2026-09-23)")
        else:
            close_url = "(real path not in _V1_EXEC_REAL_SEG — _seg raises)"
            close_note = "NOT attested"
        try:
            delete_url = t._v3_exec_order("<orderId>")
        except LookupError:
            delete_url = ("(real v3 spelling not attested — _seg raises; demo "
                          "measured 2026-09-23)")
        delete_note = (("measured 2026-09-23 20:29 UTC on the demo segment: 202 "
                        "{orderId, referenceId ''} on a WaitingForMarket order "
                        "(status 11, positionExecutions [], legs not shown, used "
                        "margin 42.5 AND accountFrozenCash 42.5 pledged); the "
                        "lookup then read status {id 7, Canceled} and both cells "
                        "returned to 0.0; never sent on a CLOSE order id")
                       if t.demo else
                       "real segment never sent; measured 2026-09-23 on the demo "
                       "segment")
        segment_note = ("measured 2026-09-23 on the demo segment"
                        if t.demo else
                        "real segment never sent; measured 2026-09-23 on "
                        "the demo segment")
        for name, url, note in (
            ("order POST", t._v2_exec_orders(),
             f"{segment_note}: 2xx, body {{token, orderId (int), "
             f"referenceId}}; filled in 200 ms in NYSE hours; a 2x order "
             f"locked notional / 2 as margin, units untouched"),
            ("orders:lookup GET", t._v2_lookup(),
             f"{segment_note}: 200 by ?orderId=<int>, 404 by ?referenceId= "
             f"(eToro keeps no client reference), 400 by ?token=; status is "
             f"an object {{id, name, errorCode}} — 3/Filled, 11/WaitingForMarket, "
             f"7/Canceled and 4/Rejected (errorCode 720) seen; the "
             f"fill facts ride positionExecutions[0]"),
            ("market-close POST", close_url, close_note),
            ("order DELETE v3", delete_url, delete_note),
            ("stop mover PATCH", t._v2("positions/<positionId>"),
             f"{segment_note}: ok on {{stopLossRate}} (tighter only), the "
             f"new stop echoed on the next lookup; 200 vs 202 not recorded; "
             f"a widening PATCH never sent"),
        ):
            w(f"  {'url':<8} {name:<44} {url}")
            w(f"           {note}")

        # THE FLOORS (2026-09-26): named as measured, never read here — the
        # read is an eligibility POST and this run is GET-only
        # (tests/test_etoro_smoke.py pins it).
        if cap.has_capability(t, "size_floor"):
            w("  size floor: min_tradable now exists on EtoroTrader — this "
              "line and capabilities.py disagree; update both")
        elif cap.has_capability(t, "money_floor"):
            w("  size floor: none in units — the floor is MONEY, MEASURED "
              "2026-09-23: minPositionExposure on the eligibility row (10 "
              "USD stocks, ETFs and crypto; 1,000 USD forex, indices and "
              "commodities), read by the engine before an entry (the "
              "money_floor tier, EtoroTrader.min_notional). This command "
              "does not POST that read: run the adapter's eligibility "
              "read by hand (deploy/ETORO_DEPARTURE.md §4 D2c-0).")
        else:
            w("  size floor: none declared (capabilities.py) — this adapter "
              "answers no floor before an order")
        if cap.has_capability(t, "fractional_units"):
            w("  fractional units: MEASURED 2026-09-23 — unitsQuantityType "
              "'fractional' on every eligibility row read (stocks, ETFs, "
              "forex, crypto, indices, commodities); "
              "takes_fractional_units reads the row (True / False / None "
              "unread), and fractions are sent only while the "
              "fractional_units_live switch is ON. This command does not "
              "call the eligibility endpoint.")

        w("=" * 70)
        w(f"{tally[OK]} ok · {tally[REFUSED]} refused by eToro · "
          f"{tally[NOSUCH]} spelling(s) eToro does not know · "
          f"{tally[UNKNOWN]} unknown")
        if tally[UNKNOWN]:
            w("  unknown = the adapter, the network, a 403 nobody measured, "
              "a spelling eToro reads differently, or a path nobody attested "
              "— NOT eToro saying no. Read the detail before blaming the "
              "keys.")
        w("No order was placed. The DEMO write path met eToro on 2026-09-23 "
          "(deploy/ETORO_DEPARTURE.md §4); the LIVE write path never has, "
          "and this command cannot change either.")
