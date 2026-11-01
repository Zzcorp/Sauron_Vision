"""Measure the shape of eToro's BATCHED rates answer, read-only (2026-11-01).

The batched rates read (EtoroTrader.tickers, bot_program/engine/
etoro_rates) sends ONE GET /api/v1/market-data/instruments/rates with
instrumentIds as a comma list, and matches every row to its symbol by the
row's OWN instrumentId, never by its position. That answer has never met a
key. The batch does not wait for it: it is sent from the first pass, and
the first answer the adapter does not trust (a row with no id of its own,
no row at all...) turns it off for a day, every symbol read alone
meanwhile, as before the batch. This is the operator's measurement. It
sends ONE such GET (a 5xx or a transport failure is asked once more, as
every read is), with two instrument ids, on the world chosen (demo by
default), through the request budget at P5, and prints:

  * the HTTP status, the top-level keys, the type and length of `rates`;
  * each row in the order it came back: its own id and the key it rides
    under, and which fields it carries with their kind (number, text,
    null ...), never a value: no price, no account figure;
  * whether the rows came back in the order asked or reordered;
  * whether the adapter's parser trusts the answer, and if not, why — and
    for a 429 or a 5xx, what the adapter's batch does with one (one
    failure noted on that world's health, its symbols not asked again for
    30 s, the batch left on: a failure is no distrust);
  * whether the batch is unproven today, since when and why.

Read-only: that GET and nothing else. Nothing is cached, nothing is marked
unproven, no order exists, and — a BACKGROUND read, as the candles are
(2026-11-01, review) — a 429, a 5xx or a transport failure is noted on no
world's health and starts no 429 pause: the measurement never holds an
entry. The keys are never printed. Not runnable from the ops page: it
presents the operator's eToro keys to an external service.

    python manage.py etoro_rates_shape --user <you>
    python manage.py etoro_rates_shape --user <you> --world live
    python manage.py etoro_rates_shape --user <you> --ids 18,100005
"""
from datetime import datetime, timezone as dt_tz

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

#: Two ids eToro answered by name (engine/etoro_client.VENUE_ID_PINS: gold
#: 18, litecoin 100005): a metal and a crypto, so one of them trades at any
#: hour of the week.
DEFAULT_IDS = (18, 100005)


def _kind(value) -> str:
    """The kind of a field's value, never the value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _ids(raw) -> tuple:
    try:
        ids = tuple(int(x) for x in str(raw or "").split(",") if x.strip())
    except ValueError:
        ids = ()
    if len(ids) != 2 or len(set(ids)) != 2 or min(ids) <= 0:
        raise CommandError("--ids takes two different instrument ids, "
                           "comma separated (e.g. 18,100005)")
    return ids


def _at(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=dt_tz.utc).strftime(
            "%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


class Command(BaseCommand):
    help = ("Send ONE batched eToro rates GET with two instrument ids (demo "
            "by default) and print the shape of the answer: the row keys, "
            "their order, the fields each row carries, and whether the "
            "adapter trusts it. Read-only; no price, no account figure, no "
            "key.")

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True,
                            help="whose stored eToro key pair to use")
        parser.add_argument("--world", choices=("demo", "live"),
                            default="demo",
                            help="the world asked (default demo)")
        parser.add_argument("--ids",
                            default=",".join(str(i) for i in DEFAULT_IDS),
                            help="two instrument ids, comma separated")

    def handle(self, *args, **opts):
        # P5 IN THE eTORO REQUEST BUDGET, as etoro_smoke: a measurement
        # leaves the marks, the proposals and the orders their tokens, and
        # a read the budget did not send says so in the budget's words.
        from bot_program.engine import etoro_budget
        with etoro_budget.at(etoro_budget.P5, "etoro_rates_shape"):
            return self._measure(**opts)

    def _measure(self, **opts):
        from bot_program.engine import etoro_client as ec
        from bot_program.engine import etoro_rates

        ids = _ids(opts.get("ids"))
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=opts["user"])
        except user_model.DoesNotExist:
            raise CommandError(f"no user {opts['user']!r}") from None
        try:
            acct = user.etoro_account
        except Exception:  # noqa: BLE001 — RelatedObjectDoesNotExist
            acct = None
        if acct is None:
            raise CommandError("no eToro row for this user — paste both "
                               "keys on /brokers/ first")
        k, u = acct.get_credentials()
        if not (k and u):
            raise CommandError("the eToro row is not keyed — paste both "
                               "keys on /brokers/ first")
        # NEVER A KEY (etoro_smoke's rule): requests quotes a header value
        # it refuses, and both keys are header values; every line goes
        # through here.
        scrub = [(s, tag) for raw, tag in ((k, "<x-api-key>"),
                                           (u, "<x-user-key>"))
                 for s in (raw, repr(raw)[1:-1]) if s]

        def w(text: str):
            for s, tag in scrub:
                text = text.replace(s, tag)
            self.stdout.write(text)

        world = opts["world"]
        t = ec.EtoroTrader(k, u, env=world)
        path = ec.RATES_URL.replace(ec.BASE, "")
        w(f"eToro BATCHED RATES — the shape of one answer · "
          f"{user.username} · world {world}")
        w(f"  asked    ONE GET {path}?instrumentIds={ids[0]},{ids[1]} — two "
          f"ids, in that order, at P5 in the budget")
        try:
            code, body = t.rates_raw(ids)
        except Exception as e:  # noqa: BLE001 — said, never raised
            if getattr(e, "budget_refused", False):
                w(f"  answer   not asked — {getattr(e, 'why', '') or e}")
            else:
                w(f"  answer   could not ask: {type(e).__name__}: "
                  f"{str(e)[:120]}")
            return
        w(f"  answer   HTTP {code} · {ec._rates_shape(body)}")
        rows = body.get("rates") if isinstance(body, dict) else None
        answered = []
        if isinstance(rows, list):
            for n, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    w(f"  row {n}: a {type(row).__name__}, not an object")
                    continue
                own = [(key, row[key]) for key in ec.RATE_ROW_ID_KEYS
                       if key in row]
                named = (", ".join(f"{key} {val}" for key, val in own)
                         if own else "no instrumentId of its own")
                fields = ", ".join(f"{key} {_kind(row[key])}"
                                   for key in sorted(row, key=str))
                w(f"  row {n}: {named} · {fields}")
                answered.append(ec._row_id(row))
        if answered and None not in answered:
            asked = [i for i in ids if i in answered]
            w("  order    the rows came back in the order asked"
              if answered == asked else
              f"  order    the rows came back REORDERED (asked "
              f"{', '.join(map(str, ids))}; answered "
              f"{', '.join(map(str, answered))}): only the rows' own ids "
              f"can match them")
        elif answered:
            w("  order    a row carries no id of its own: the order of the "
              "rows cannot be told")
        try:
            if int(code) == 429 or int(code) >= 500:
                # what tickers() does with one (2026-11-01, review): a
                # failure, never distrust
                pause = (" (and its shared 429 pause starts)"
                         if int(code) == 429 else "")
                w(f"  parser   not judged: HTTP {code} is a failure, not a "
                  f"shape — the adapter's batch answers BatchFailed: one "
                  f"failure noted on that world's health{pause}, its "
                  f"symbols not asked again for {etoro_rates.FAILED_MEMO_S} "
                  f"s, and the batch stays on. This measurement, a "
                  f"background read, noted nothing")
            else:
                if not 200 <= int(code) < 300:
                    raise ec._Untrusted(f"HTTP {code} to a batched read",
                                        f"HTTP {code}")
                ec._parse_rates_batch(body, ids)
                w("  parser   trusted — each row matched by its own id")
        except ec._Untrusted as e:
            w(f"  parser   NOT trusted: {e.why} — the adapter would mark the "
              f"batch unproven for {etoro_rates.UNPROVEN_TTL_S // 3600} h "
              f"and read every symbol alone")
        held = etoro_rates.unproven()
        if held:
            w(f"  today    the batch is unproven since {_at(held.get('at'))} "
              f"({held.get('why') or '?'}), until {_at(held.get('until'))}: "
              f"every symbol is read alone meanwhile")
        else:
            w("  today    the batch is not marked unproven")
