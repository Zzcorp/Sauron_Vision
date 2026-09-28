"""Prove each promise of the Saxo adapter against the real SIM, read-only.

The documentation left four things only SIM can settle — which body
fields an order truly requires, whether the audit log is where a fill
appears, the stop-type spelling per instrument, and how a closed position
surfaces under the account's netting profile. This command does NOT place
orders; it exercises every read the adapter makes and reports each in
three states, so an operator can tell "Saxo refused" from "the adapter is
wrong" from "the session is gone" before a single order exists.

Run with:

    python manage.py saxo_smoke --user mathe
    python manage.py saxo_smoke --user mathe --symbol AAPL

Deliberately NOT runnable from the ops page: it presents the operator's
Saxo session to an external service and prints the account's balance.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()

OK, REFUSED, UNKNOWN = "ok", "refused", "unknown"


def _verdict(fn):
    """Three states, never two: (state, detail). A Saxo ErrorCode is
    'refused' — Saxo answered and said no. Anything else that raised is
    'unknown' — the adapter, the network or the session is at fault, and
    the operator must not read it as Saxo's refusal."""
    from bot_program.engine.saxo_client import SaxoApiError, SaxoAuthError
    try:
        return OK, fn()
    except SaxoAuthError as e:
        return UNKNOWN, f"session refused ({e.correlation or 'no correlation'}) — sign in again at /brokers/"
    except SaxoApiError as e:
        return REFUSED, f"{e.code}: {e.message}" + (f" [{e.correlation}]" if e.correlation else "")
    except Exception as e:  # noqa: BLE001 — the point is to name it
        return UNKNOWN, f"{type(e).__name__}: {e}"


class Command(BaseCommand):
    help = ("Exercise every READ of the Saxo adapter against SIM/LIVE for one "
            "user and report each in three states. Places no orders.")

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True,
                            help="username whose SaxoAccount row to use")
        parser.add_argument("--symbol", default="EURUSD",
                            help="instrument to price and chart (default EURUSD — "
                                 "the one thing a demo account always sees)")

    def handle(self, *args, **opts):
        from bot_program.engine.saxo_client import SaxoTrader

        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"no user {opts['user']!r}")
        acct = getattr(user, "saxo_account", None)
        if acct is None or not acct.get_credentials()[0]:
            raise CommandError("no Saxo application registered for this user — "
                               "Register Saxo Application on /brokers/ first")
        if not acct.session_alive():
            raise CommandError("no live Saxo session — press Connect Saxo on "
                               "/brokers/ and sign in once")

        w = self.stdout.write
        env = "SIM" if acct.sim else "LIVE"
        w(f"SAXO SMOKE — {user.username} · {env} · symbol {opts['symbol']}")
        w("=" * 70)
        t = SaxoTrader(acct)
        symbol = opts["symbol"]
        checks = [
            ("ping (sessions/capabilities)", lambda: "authenticated" if t.ping() else "NOT authenticated"),
            ("identity (clients/me, accounts/me)",
             lambda: "{client_key} · account {account_id} · {currency} · netting {netting_profile}/{netting_mode}".format(**t.identity())),
            ("net_liquidation (balances)",
             lambda: (lambda nl: f"{nl[0]:,.2f} {nl[1]}" if nl else "unreadable → None")(t.net_liquidation())),
            (f"resolve {symbol} (ref/v1/instruments)",
             lambda: "Uic {} · {} · stops {}".format(*[
                 t.resolve(symbol)[0], t.resolve(symbol)[1],
                 [x for x in (t.resolve(symbol)[2].get("SupportedOrderTypes") or [])
                  if "Stop" in x or "Trailing" in x]])),
            (f"ticker {symbol} (infoprices)",
             lambda: (lambda tk: f"last {tk['last']} bid {tk['bid']} ask {tk['ask']} · "
                                 f"delayed {tk['delayed_minutes']} min · {tk['price_type'] or '?'} · "
                                 f"{tk['market_state'] or '?'}")(t.ticker(symbol))),
            (f"klines {symbol} 4h (chart/v3)",
             lambda: (lambda rows: f"{len(rows)} bars, newest open {rows[-1][0] if rows else '—'}")(t.klines(symbol, "4h", 50))),
            (f"order_book {symbol} (MarketDepth)",
             lambda: (lambda b: f"{len(b['bids'])} bid / {len(b['asks'])} ask levels"
                                f"{' (synthetic — no depth on this feed)' if b['bids'] and b['bids'][0][1] == '1000000' else ''}")(t.order_book(symbol, 5))),
            (f"size floor {symbol} (LotSize/MinimumTradeSize)",
             lambda: (lambda f: f"{f:g} minimum"
                      if f else "no floor published — UNMEASURED, and an "
                                "under-minimum order would be refused at "
                                "the order")(
                 SaxoTrader._size_floor(t.resolve(symbol)[2] or {}))),
            ("get_positions (port/v1/positions)",
             lambda: f"{len(t.get_positions())} open"),
            ("broker_portfolio",
             lambda: (lambda p: f"{len(p)} rows" if p is not None else "unreadable → None")(t.broker_portfolio())),
            ("closedpositions reachable",
             lambda: f"{len(t._get('port/v1/closedpositions', {'ClientKey': t.identity()['client_key'], 'AccountKey': t.identity()['account_key'], 'FieldGroups': 'ClosedPosition', '$top': 5}).get('Data') or [])} recent"),
        ]
        tally = {OK: 0, REFUSED: 0, UNKNOWN: 0}
        for name, fn in checks:
            state, detail = _verdict(fn)
            tally[state] += 1
            w(f"  {state:<8} {name:<40} {detail}")
        w("=" * 70)
        w(f"{tally[OK]} ok · {tally[REFUSED]} refused by Saxo · {tally[UNKNOWN]} unknown")
        if tally[UNKNOWN]:
            w("  unknown = the adapter, the network or the session — NOT Saxo saying no. "
              "Read the detail before blaming the keys.")
        w("No order was placed. The four facts only an order can settle are "
          "named in engine/saxo_client.py.")
