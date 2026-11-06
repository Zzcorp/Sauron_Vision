"""Measure the shape of eToro's BATCHED rates answer, read-only (2026-11-01).

The batched rates read (EtoroTrader.tickers, bot_program/engine/
etoro_rates) sends ONE GET /api/v1/market-data/instruments/rates with
instrumentIds as a comma list, and matches every row to its symbol by the
row's OWN instrumentId, never by its position. That answer has never met a
key, and the batch WAITS FOR THIS MEASUREMENT (2026-11-02, the plan's
order): nothing is sent in batch until it has read an answer the parser
trusts, every symbol read alone meanwhile, as before the batch; the first
answer the adapter does not trust afterwards (a row with no id of its
own, no row at all...) still turns it off for a day. This is the
operator's measurement. It
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
  * whether the batch is unproven today, since when and why, and whether
    it is proven (this measurement or an earlier one).

That GET and one record: when the parser trusts the answer, the proof the
batch waits for (etoro_rates.prove: the instant, the world and the shape's
words, never a price, an id or a key). Nothing else is cached, nothing is
marked unproven, no order exists, and — a BACKGROUND read, as the candles are
(2026-11-01, review) — a 429, a 5xx or a transport failure is noted on no
world's health and starts no 429 pause: the measurement never holds an
entry. The keys are never printed. Not runnable from the ops page: it
presents the operator's eToro keys to an external service.

WHAT THE FEED'S DESIGN WAITS ON (2026-11-06, the feed spec's P-a.2, its
measurement M1):

  * LITERAL COMMAS. The ids ride ?instrumentIds=18,100005 as written
    (etoro_client.rates_url), eToro's own rule for a list; until today
    requests sent them as 18%2C100005, the form that rule rejects, so this
    measured the wrong form and could have "proved" that batching fails.
  * --ids takes two to a hundred ids (eToro's own cap on one v1 list). The
    adapter's batch still carries twenty (etoro_rates.BATCH_MAX_IDS) until
    a measurement says more.
  * --repeat N --gap S: N reads of the same ids S seconds apart (N up to
    20, S from 1 to 60, 3 by default), each read a line, then for each id
    whether its date and its priceRateID advanced, stayed, went back or
    were absent between two reads: how stale eToro's REST answer may be
    (the first trusted answer is the proof, as one read's is).
  * --v2: ONE GET of the v2 rates (etoro_client.RATES_V2_URL): its status
    (200 every id found, 206 some, 404 none), its rows' fields and kinds,
    and the quoteType words (realtime, delayed). Never the batch's proof.
  * --encoded-commas: ONE GET in the old form (%2C), to record what eToro
    answers to it; said as that form's answer, judged by the parser for the
    record and never the batch's proof, whatever it answers.
  * Every answer: the names and values of its RateLimit-* and
    X-RateLimit-* headers (and Retry-After) — quota counters, never an
    account figure; the spelling of the rows' id key; the date's format,
    its digits masked. Still kinds only: no price, no date, no
    priceRateID, no key.

One of --repeat, --v2 and --encoded-commas a run.

    python manage.py etoro_rates_shape --user <you>
    python manage.py etoro_rates_shape --user <you> --world live
    python manage.py etoro_rates_shape --user <you> --ids 18,100005
    python manage.py etoro_rates_shape --user <you> --ids <20 to 100 ids>
    python manage.py etoro_rates_shape --user <you> --repeat 20 --gap 3
    python manage.py etoro_rates_shape --user <you> --v2
    python manage.py etoro_rates_shape --user <you> --encoded-commas
"""
import re
import time
from datetime import datetime, timezone as dt_tz

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

#: Two ids eToro answered by name (engine/etoro_client.VENUE_ID_PINS: gold
#: 18, litecoin 100005): a metal and a crypto, so one of them trades at any
#: hour of the week.
DEFAULT_IDS = (18, 100005)
#: The most ids one run asks: eToro's own cap on one v1 list (the spec
#: copies' maxItems 100; a longer list is a 400).
MAX_IDS = 100
#: The most reads --repeat sends: the feed spec's whole measurement M1 is
#: at most 25 market GETs at P5.
MAX_REPEAT = 20
#: --gap's bounds and default, in seconds.
GAP_MIN_S = 1.0
GAP_MAX_S = 60.0
DEFAULT_GAP_S = 3.0
#: The headers printed by name and value: eToro's quota counters (its
#: spec copies say RateLimit-*, a builders page X-RateLimit-*) and a
#: 429's Retry-After. Never another header.
QUOTA_PREFIXES = ("ratelimit-", "x-ratelimit-")
QUOTA_NAMES = ("retry-after",)
#: The spellings a row's own id may ride under, v1's and v2's.
ID_KEYS = ("instrumentId", "instrumentID")


def _pause(seconds: float) -> None:
    """The gap between two repeated reads (a seam: tests skip it)."""
    time.sleep(seconds)


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
    if (not 2 <= len(ids) <= MAX_IDS or len(set(ids)) != len(ids)
            or min(ids) <= 0):
        raise CommandError(f"--ids takes two to {MAX_IDS} different "
                           f"instrument ids, comma separated (e.g. "
                           f"18,100005)")
    return ids


def _listed(ids, sep=",") -> str:
    """The ids as the query carries them, cut in the middle past ten."""
    if len(ids) <= 10:
        return sep.join(map(str, ids))
    return (sep.join(map(str, ids[:5])) + f"{sep}…{sep}"
            + sep.join(map(str, ids[-2:])))


def _at(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=dt_tz.utc).strftime(
            "%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _rows(body, key):
    rows = body.get(key) if isinstance(body, dict) else None
    return rows if isinstance(rows, list) else None


def _shape_of(body, key) -> str:
    """The SHAPE of an answer whose rows ride under `key` (v2's
    "results"), as etoro_client._rates_shape says v1's: keys and kinds
    only. Never raises."""
    try:
        if not isinstance(body, dict):
            return f"a {type(body).__name__}, not an object"
        top = sorted(str(k) for k in body)
        rows = body.get(key)
        if not isinstance(rows, list):
            return f"keys {top}; {key} is {type(rows).__name__}"
        seen = sorted({tuple(sorted(str(k) for k in r))
                       if isinstance(r, dict) else (f"<{type(r).__name__}>",)
                       for r in rows})
        return (f"keys {top}; {key}: a list of {len(rows)}; row keys "
                f"{[list(r) for r in seen]}")
    except Exception:  # noqa: BLE001
        return "unreadable"


def _quota(headers) -> list:
    """[(name, value)] of the answer's quota headers (QUOTA_PREFIXES,
    QUOTA_NAMES), by name. The values are quota counters and a policy,
    never an account figure. Never raises."""
    try:
        out = [(str(k), str(v)[:60]) for k, v in (headers or {}).items()
               if str(k).lower().startswith(QUOTA_PREFIXES)
               or str(k).lower() in QUOTA_NAMES]
    except Exception:  # noqa: BLE001
        return []
    return sorted(out, key=lambda kv: kv[0].lower())


def _masked(text) -> str:
    """A date's format, its digits masked: never the instant."""
    return re.sub(r"\d", "d", str(text))[:48]


def _instant(value):
    """A date's instant (aware), or None: eToro may write seven fractional
    digits, Python reads six."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt_tz.utc)


def _whole(value):
    """A priceRateID as a whole number (v1 writes one, the stream its
    digits), or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _step(before, after, key) -> str:
    """How `key` moved from one read's row to the next's: "advanced", "the
    same", "went back" or "absent" (a row or a value missing on either)."""
    a = (before or {}).get(key) if isinstance(before, dict) else None
    b = (after or {}).get(key) if isinstance(after, dict) else None
    if key == "date":
        ta, tb = _instant(a), _instant(b)
        if ta is None or tb is None:
            if not (isinstance(a, str) and a and isinstance(b, str) and b):
                return "absent"
            ta, tb = a, b
    else:
        ta, tb = _whole(a), _whole(b)
        if ta is None or tb is None:
            return "absent"
    if tb > ta:
        return "advanced"
    return "the same" if tb == ta else "went back"


class Command(BaseCommand):
    help = ("Send ONE batched eToro rates GET (demo by default; two to a "
            "hundred ids, literal commas) and print the shape of the "
            "answer: the row keys, their order, the fields each row "
            "carries, the quota headers, and whether the adapter trusts "
            "it. --repeat N --gap S reads N times; --v2 and "
            "--encoded-commas ask once in another form. Read-only; no "
            "price, no account figure, no key.")

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True,
                            help="whose stored eToro key pair to use")
        parser.add_argument("--world", choices=("demo", "live"),
                            default="demo",
                            help="the world asked (default demo)")
        parser.add_argument("--ids",
                            default=",".join(str(i) for i in DEFAULT_IDS),
                            help=f"two to {MAX_IDS} instrument ids, comma "
                                 f"separated")
        parser.add_argument("--repeat", type=int, default=1,
                            help=f"how many reads (1 to {MAX_REPEAT}), "
                                 f"--gap seconds apart: do date and "
                                 f"priceRateID advance between them?")
        parser.add_argument("--gap", type=float, default=None,
                            help=f"seconds between two repeated reads "
                                 f"({GAP_MIN_S:g} to {GAP_MAX_S:g}, default "
                                 f"{DEFAULT_GAP_S:g})")
        parser.add_argument("--v2", action="store_true",
                            help="ONE GET of the v2 rates instead (never "
                                 "the batch's proof)")
        parser.add_argument("--encoded-commas", action="store_true",
                            help="ONE GET in the old form, the commas "
                                 "encoded as %%2C, to record eToro's answer "
                                 "to it (never the batch's proof)")

    def handle(self, *args, **opts):
        mode, repeat, gap = self._mode(opts)
        # P5 IN THE eTORO REQUEST BUDGET, as etoro_smoke: a measurement
        # leaves the marks, the proposals and the orders their tokens, and
        # a read the budget did not send says so in the budget's words.
        from bot_program.engine import etoro_budget
        with etoro_budget.at_priority(etoro_budget.P5, "etoro_rates_shape"):
            return self._measure(mode, repeat, gap, opts)

    @staticmethod
    def _mode(opts) -> tuple:
        """("one" | "repeat" | "v2" | "encoded", reads, gap) or a
        CommandError before anything is asked."""
        repeat = opts.get("repeat")
        repeat = 1 if repeat is None else int(repeat)
        gap = opts.get("gap")
        if not 1 <= repeat <= MAX_REPEAT:
            raise CommandError(f"--repeat takes 1 to {MAX_REPEAT} reads")
        if gap is not None and repeat < 2:
            raise CommandError("--gap goes with --repeat (two reads or "
                               "more)")
        gap = DEFAULT_GAP_S if gap is None else float(gap)
        if not GAP_MIN_S <= gap <= GAP_MAX_S:
            raise CommandError(f"--gap takes {GAP_MIN_S:g} to "
                               f"{GAP_MAX_S:g} seconds")
        modes = [m for m, on in (("repeat", repeat > 1),
                                 ("v2", opts.get("v2")),
                                 ("encoded", opts.get("encoded_commas")))
                 if on]
        if len(modes) > 1:
            raise CommandError("one of --repeat, --v2 and --encoded-commas "
                               "a run")
        return (modes[0] if modes else "one"), repeat, gap

    def _measure(self, mode, repeat, gap, opts):
        from bot_program.engine import etoro_client as ec

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
        if mode == "v2":
            return self._v2(t, ids, w, user, world)
        v1 = ec.RATES_URL.replace(ec.BASE, "")
        if mode == "encoded":
            w(f"eToro BATCHED RATES in the OLD form — one answer · "
              f"{user.username} · world {world}")
            w(f"  asked    ONE GET {v1}?instrumentIds="
              f"{_listed(ids, '%2C')} — the OLD form, the commas encoded "
              f"as requests encodes params=, {len(ids)} ids, at P5 in the "
              f"budget: to record eToro's answer to it, never the batch's "
              f"proof")
        else:
            w(f"eToro BATCHED RATES — the shape of one answer · "
              f"{user.username} · world {world}")
            many = (f"{repeat} GETs, {gap:g} s apart," if repeat > 1
                    else "ONE GET")
            w(f"  asked    {many} {v1}?instrumentIds={_listed(ids)} — "
              f"{len(ids)} ids, in that order, literal commas (eToro's rule "
              f"for a list), at P5 in the budget")
        try:
            code, body = t.rates_raw(ids, encoded_commas=mode == "encoded")
        except Exception as e:  # noqa: BLE001 — said, never raised
            self._not_asked(w, "answer  ", e)
            return
        self._answer(w, ec, t, code, body, ids, "rates")
        self._judge(w, ec, code, body, ids, world,
                    may_prove=mode != "encoded")
        if mode == "repeat":
            self._repeat(w, ec, t, ids, body, repeat, gap)
        self._today(w)

    @staticmethod
    def _not_asked(w, label, e) -> None:
        if getattr(e, "budget_refused", False):
            w(f"  {label} not asked — {getattr(e, 'why', '') or e}")
        else:
            w(f"  {label} could not ask: {type(e).__name__}: "
              f"{str(e)[:120]}")

    def _answer(self, w, ec, t, code, body, ids, key) -> None:
        """The answer's shape, its rows' ids and kinds, their order, the id
        key's spelling, the date's format and the quota headers."""
        shape = (ec._rates_shape(body) if key == "rates"
                 else _shape_of(body, key))
        w(f"  answer   HTTP {code} · {shape}")
        rows = _rows(body, key)
        answered = []
        if rows is not None:
            for n, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    w(f"  row {n}: a {type(row).__name__}, not an object")
                    continue
                own = [(k, row[k]) for k in ID_KEYS if k in row]
                named = (", ".join(f"{k} {v}" for k, v in own)
                         if own else "no instrumentId of its own")
                fields = ", ".join(f"{k} {_kind(row[k])}"
                                   for k in sorted(row, key=str))
                w(f"  row {n}: {named} · {fields}")
                answered.append(ec._row_id(row))
        if answered and None not in answered:
            asked = [i for i in ids if i in answered]
            w("  order    the rows came back in the order asked"
              if answered == asked else
              f"  order    the rows came back REORDERED (asked "
              f"{_listed(ids, ', ')}; answered {_listed(answered, ', ')}): "
              f"only the rows' own ids can match them")
        elif answered:
            w("  order    a row carries no id of its own: the order of the "
              "rows cannot be told")
        if rows:
            self._id_key(w, rows)
            self._date(w, rows)
        self._quota(w, t)

    @staticmethod
    def _id_key(w, rows) -> None:
        """The spelling the rows' own id rides under."""
        counts = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            spelt = [k for k in ID_KEYS if k in row]
            name = " and ".join(spelt) if spelt else "none"
            counts[name] = counts.get(name, 0) + 1
        if len(counts) == 1 and "none" not in counts:
            w(f"  id key   {next(iter(counts))}, on every row")
        elif counts:
            w("  id key   " + ", ".join(
                f"{name} on {n} row{'s' if n != 1 else ''}"
                for name, n in sorted(counts.items())))

    @staticmethod
    def _date(w, rows) -> None:
        """The date's kind and format, its digits masked: never the
        instant (C_rest needs its format; a value is a reading)."""
        dated = [r.get("date") for r in rows
                 if isinstance(r, dict) and "date" in r]
        text = next((d for d in dated if isinstance(d, str) and d), None)
        if text is not None:
            w(f"  date     text, {_masked(text)} (digits masked)")
        elif dated:
            w(f"  date     {_kind(dated[0])} on every row that carries one")
        else:
            w("  date     no row carries one")

    @staticmethod
    def _quota(w, t) -> None:
        named = _quota(getattr(t, "last_rate_headers", None))
        if named:
            w("  quota    " + " · ".join(f"{k} {v}" for k, v in named)
              + " (quota counters, no account figure)")
        else:
            w("  quota    no RateLimit-* or X-RateLimit-* header on this "
              "answer")

    def _judge(self, w, ec, code, body, ids, world, *, may_prove) -> None:
        """The parser's verdict, and the proof when it trusts a v1 answer
        in the batch's own form (`may_prove`)."""
        from bot_program.engine import etoro_rates
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
                if not may_prove:
                    w("  parser   trusted — an answer to the OLD form, "
                      "recorded here as that form's answer: never the "
                      "batch's proof")
                    return
                w("  parser   trusted — each row matched by its own id")
                # THE PROOF THE BATCH WAITS FOR (2026-11-02)
                if etoro_rates.prove(world, ec._rates_shape(body)):
                    w("  proof    written: the batch may be sent from now on "
                      "(an answer it does not trust still turns it off for "
                      "a day)")
                else:
                    w("  proof    NOT written (the cache refused it): the "
                      "batch keeps waiting")
        except ec._Untrusted as e:
            old = (" (an answer to the OLD form, never the batch's proof)"
                   if not may_prove else "")
            w(f"  parser   NOT trusted{old}: {e.why} — the adapter would mark "
              f"the batch unproven for {etoro_rates.UNPROVEN_TTL_S // 3600} "
              f"h and read every symbol alone")

    def _repeat(self, w, ec, t, ids, first, repeat, gap) -> None:
        """Reads 2 to `repeat`, `gap` seconds apart, a line each, then for
        each id how its date and priceRateID moved between two reads."""
        reads = [first]
        for n in range(2, repeat + 1):
            _pause(gap)
            try:
                code, body = t.rates_raw(ids)
            except Exception as e:  # noqa: BLE001 — said, and the run ends
                self._not_asked(w, f"read {n}/{repeat}:", e)
                break
            rows = _rows(body, "rates")
            said = (f"{len(rows)} row{'s' if len(rows) != 1 else ''}"
                    if rows is not None else ec._rates_shape(body))
            quota = "".join(f" · {k} {v}" for k, v in
                            _quota(getattr(t, "last_rate_headers", None)))
            w(f"  read {n}/{repeat}: HTTP {code} · {said}{quota}")
            reads.append(body)
        pairs = len(reads) - 1
        if pairs < 1:
            return
        series = {i: [] for i in ids}
        for body in reads:
            by_id = {}
            for row in _rows(body, "rates") or []:
                if isinstance(row, dict):
                    iid = ec._row_id(row)
                    if iid in series and iid not in by_id:
                        by_id[iid] = row
            for i in ids:
                series[i].append(by_id.get(i))
        for i in ids:
            moved = []
            for key in ("date", "priceRateID"):
                n = {"advanced": 0, "the same": 0, "went back": 0,
                     "absent": 0}
                for a, b in zip(series[i], series[i][1:]):
                    n[_step(a, b, key)] += 1
                moved.append(f"{key} " + " · ".join(
                    f"{word} {count}" for word, count in n.items()))
            w(f"  id {i}: {'; '.join(moved)} (of {pairs} pairs {gap:g} s "
              f"apart)")
        w(f"  note     an id whose date and priceRateID advance between "
          f"reads {gap:g} s apart was answered no staler than that; one "
          f"that does not is a quiet market or an answer eToro kept")

    def _v2(self, t, ids, w, user, world) -> None:
        """ONE GET of the v2 rates: never parsed by the adapter, never the
        batch's proof."""
        from bot_program.engine import etoro_client as ec
        path = ec.RATES_V2_URL.replace(ec.BASE, "")
        w(f"eToro RATES v2 — the shape of one answer · {user.username} · "
          f"world {world}")
        w(f"  asked    ONE GET {path}?instrumentIds={_listed(ids)} — "
          f"{len(ids)} ids, literal commas, at P5 in the budget: never the "
          f"batch's proof")
        try:
            code, body = t.rates_v2_raw(ids)
        except Exception as e:  # noqa: BLE001 — said, never raised
            self._not_asked(w, "answer  ", e)
            return
        self._answer(w, ec, t, code, body, ids, "results")
        rows = _rows(body, "results") or []
        words = {}
        for row in rows:
            if not isinstance(row, dict) or "quoteType" not in row:
                continue
            q = row.get("quoteType")
            word = (q if isinstance(q, str)
                    and re.fullmatch(r"[A-Za-z_]{1,20}", q)
                    else f"<{_kind(q)}>")
            words[word] = words.get(word, 0) + 1
        if words:
            w("  quoteType " + ", ".join(f"{word} {n}" for word, n
                                         in sorted(words.items())))
        else:
            w("  quoteType no row carries one")
        status = {200: "every id found", 206: "some ids found",
                  404: "no id found"}.get(int(code or 0), "")
        w(f"  status   HTTP {code}" + (f": {status}" if status else "")
          + " — v2 is measured here, never read by the engine")
        self._today(w)

    @staticmethod
    def _today(w) -> None:
        from bot_program.engine import etoro_rates
        held = etoro_rates.unproven()
        if held:
            w(f"  today    the batch is unproven since {_at(held.get('at'))} "
              f"({held.get('why') or '?'}), until {_at(held.get('until'))}: "
              f"every symbol is read alone meanwhile")
        else:
            w("  today    the batch is not marked unproven")
        proof = etoro_rates.proven()
        if proof:
            w(f"  proven   since {_at(proof.get('at'))} on the "
              f"{proof.get('world') or '?'} world")
        elif etoro_rates.MEASURED_FIRST:
            w("  proven   not yet: the batch waits for a trusted answer, "
              "every symbol read alone")
