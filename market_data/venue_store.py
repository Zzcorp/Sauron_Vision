"""THE FEED'S STORES OF eTORO'S QUOTES (the eToro feed spec, F1, §5.2-§5.3;
2026-11-07).

One record per channel and instrument, never mixed (I2):

  vq:ws:{iid}     the stream's record, written by the feed only;
  vq:rest:{iid}   the feed's REST record, written by its watchdog and the
                  Celery fallback only — with eToro's Date, the rate id
                  and the conversion of the answer (§4.5.6);
  vq:ring:{iid}   (F6) the last 120 s of prints, for calibration and the
                  price at a close.

The engine's own rates cache (etoro_rates:r:{world}:{iid}, written by the
client's rates reads exactly as today) is a third record the feed READS
and never writes before F9 (`venue_marks_live`): the engine's marks and
the time stop's booking read it, so a feed write there would change money
inputs in an observe-only phase. engine_record() is that read.

EVERY WRITE IS A COMPARE-AND-SET BY eTORO'S OWN DATE (W2-W7): a Redis Lua
script in production (CAS_LUA, RedisVenueStore over a client the caller
hands in — this module opens no connection) and an in-memory twin with the
same rules (MemoryVenueStore, for tests and the replay). `decide` is the
twin's whole rule; the script mirrors it line for line, and the tests run
the same frames through both and compare the stores field for field.

  W2 newer Date      replaces; confirmed at its arrival.
  W3 same            the same Date and the same sides: a confirmation
                     only (a REST answer at its arrival less C_rest, the
                     REST cache bound, §5.4).
  W4 conflict        the same Date with other sides: the stored sides are
                     kept and the conflict counted — whatever the rate ids
                     say: a rate id never confirms other sides.
  W5 older           never replaces; an older snapshot confirms nothing.
  W6 price-less      a frame with no price is liveness only.
  W7 untimed REST    kept beside the record for display, never the record.
  "0"                eToro's no-price answer never replaces a priced
                     record; the absence is noted beside it and never
                     refreshes the confirmation.
  W1 (refused)       never reaches a store: the frame is classified before
                     (`frame`), and the refusal is counted by reason —
                     a Date more than FUTURE_DATE_TOLERANCE_S ahead of the
                     frame's arrival included (`future_date`).

ORDER BY DATE ONLY UNTIL PROVEN (§8 U3; 2026-11-07, review): the rate id
plays no part in a write until M2 proves PriceRateID only increases
(RATE_ID_PROVEN). Once proven, it orders two prints of the SAME Date —
the higher id replaces, the lower is older — and never overrides a Date or
confirms other sides.

A record's expiry (RECORD_KEEP_S) is set when it is created, replaced or
confirmed — never by an older, refused-in-effect or price-less frame — so
a record nothing confirms expires on time.

Nothing writes these stores in F1: the feed that will (F6) does not exist
yet, and the pins (tests/feed/test_feed_pins.py) hold that only the feed's
writers ever name a vq:* key or the store's write door.
"""
from __future__ import annotations

import threading
from collections import Counter
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal, InvalidOperation
from typing import NamedTuple, Optional

from market_data.venue_quotes import (C_REST_UNMEASURED_S, ENGINE,
                                      FUTURE_DATE_TOLERANCE_S, REST,
                                      RECORD_KEEP_S, WS, InvalidQuote,
                                      VenueQuote, _parse)

#: Every key the feed writes starts here (and nothing else writes one).
VQ_PREFIX = "vq:"
#: The engine's rates cache, read-only to the feed before F9
#: (bot_program.engine.etoro_rates._key).
ENGINE_RATES_PREFIX = "etoro_rates:r:"
#: Market data carries no world (§5.2): the REST reader takes the newest of
#: the world keys.
WORLDS = ("live", "demo")
#: How far ahead of the reader's clock the engine's arrival stamp may lie
#: (etoro_rates.get takes the same 5 s).
ENGINE_AHEAD_S = 5.0

#: M2 proves eToro's Dates compare across the two channels (the same
#: PriceRateID carries the same Date on both); until then the read-time
#: choice never compares a stream Date with a REST one (§5.2). Two REST
#: records (the feed's and the engine's) are both REST v1 answers: their
#: Dates compare.
CROSS_CHANNEL_DATES_PROVEN = False
#: M2 proves PriceRateID only increases and is shared by both channels.
RATE_ID_PROVEN = False

# frame kinds, and the channel each one belongs to
PUSH, SNAPSHOT, REST_ANSWER = "push", "snapshot", "rest"
KINDS = (PUSH, SNAPSHOT, REST_ANSWER)
CHANNEL_OF = {PUSH: WS, SNAPSHOT: WS, REST_ANSWER: REST}
# frame classes
PRICED, PRICELESS_C, ZERO_C, UNTIMED_C = "priced", "priceless", "zero", \
    "untimed"

# outcomes
NEW = "new"
SAME = "same"
CONFLICT = "same_ts_conflict"
OLDER = "older"
SNAPSHOT_OLDER = "snapshot_older"
PRICELESS = "priceless"
ZERO = "zero"
UNTIMED = "untimed"
REFUSED = "refused"

#: Every field of a stored record, as strings ("" when empty): the record
#: itself (bid, ask, vt, rid, arr, conf: milliseconds since the epoch),
#: the last frame seen, the last absence and their count, the last untimed
#: answer (ub, ua, uarr, uconf), kept for display, and the conversion of
#: the newest REST answer that was not older than the record (cb, ca and
#: cat, its confirmation).
FIELDS = ("bid", "ask", "vt", "rid", "arr", "conf", "seen", "absent",
          "absent_n", "ub", "ua", "uarr", "uconf", "cb", "ca", "cat")

_EPOCH = datetime(1970, 1, 1, tzinfo=dt_tz.utc)
_ONE_MS = timedelta(milliseconds=1)


def ws_key(iid) -> str:
    return f"{VQ_PREFIX}ws:{int(iid)}"


def rest_key(iid) -> str:
    return f"{VQ_PREFIX}rest:{int(iid)}"


def ring_key(iid) -> str:
    return f"{VQ_PREFIX}ring:{int(iid)}"


def record_key(channel, iid) -> str:
    if channel == WS:
        return ws_key(iid)
    if channel == REST:
        return rest_key(iid)
    raise ValueError(f"the feed keeps no {channel!r} record")


def engine_key(world, iid) -> str:
    return f"{ENGINE_RATES_PREFIX}{world}:{int(iid)}"


def _ms(when) -> int:
    """Whole milliseconds since the epoch, truncated (never rounded): the
    one precision every record's Date is compared at."""
    return (when - _EPOCH) // _ONE_MS


def _to_ms(when) -> datetime:
    """`when` truncated to the millisecond, as a store keeps it."""
    return _EPOCH + _ms(when) * _ONE_MS


def _at(ms) -> Optional[datetime]:
    if ms in (None, ""):
        return None
    return _EPOCH + int(ms) * _ONE_MS


def _norm(value) -> str:
    """A side as both implementations compare and keep it: its canonical
    text — no trailing zero, no exponent ("1.10" and "1.1" are one side)."""
    return format(Decimal(str(value).strip()).normalize(), "f")


def _is_zero_or_absent(value) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    try:
        return Decimal(str(value).strip()) == 0
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return False


def _conversion_side(value) -> str:
    """A conversion side's canonical text, or "" when it does not read."""
    if value is None or value == "":
        return ""
    try:
        return _norm(_parse(value))
    except (InvalidQuote, ArithmeticError, ValueError, TypeError):
        return ""


def _rid_cmp(a, b) -> Optional[int]:
    """-1, 0 or 1 for two rate ids made of digits only, exactly (as text:
    length first, so no float rounds them); None when either is not."""
    if not (a.isdigit() and b.isdigit() and a.isascii() and b.isascii()):
        return None
    a, b = a.lstrip("0") or "0", b.lstrip("0") or "0"
    if len(a) != len(b):
        return -1 if len(a) < len(b) else 1
    return (a > b) - (a < b)


class Frame(NamedTuple):
    """One incoming answer, classified before any store sees it."""
    kind: str
    klass: str                   # priced | priceless | zero | untimed | ""
    bid: str
    ask: str
    vt_ms: str
    rid: str
    arr_ms: str
    conf_ms: str
    outcome_hint: Optional[str]  # REFUSED, PRICELESS, ZERO, UNTIMED or None
    reason: str                  # the W1 reason of a refused frame
    cb: str = ""                 # the answer's conversion (REST only)
    ca: str = ""

    def args(self) -> list:
        """The frame's part of the Lua script's ARGV."""
        return [self.kind, self.klass, self.bid, self.ask, self.vt_ms,
                self.rid, self.arr_ms, self.conf_ms, self.cb, self.ca]

    def as_dict(self) -> dict:
        return {"k": self.kind, "c": self.klass, "bid": self.bid,
                "ask": self.ask, "vt": self.vt_ms, "rid": self.rid,
                "arr": self.arr_ms, "conf": self.conf_ms, "cb": self.cb,
                "ca": self.ca}


def frame(*, kind, bid, ask, vt, arrival, rate_id="",
          c_rest_s=C_REST_UNMEASURED_S, conversion_bid=None,
          conversion_ask=None) -> Frame:
    """Classify one answer of eToro's.

    A stream frame (PUSH, SNAPSHOT) with no price at all is W6 liveness;
    a REST answer whose every side is "0" or absent is eToro's no-price
    answer; a REST answer without eToro's Date is W7 (display only). Any
    other frame must make a whole VenueQuote (W1), dated no more than
    FUTURE_DATE_TOLERANCE_S ahead of its own arrival, or it is refused with
    its reason. A REST answer's confirmation is dated its arrival less
    C_rest (§5.4); a stream frame's, its arrival. A REST answer carries its
    conversion (conversionRateBid/Ask), kept when both sides read."""
    if kind not in KINDS:
        raise ValueError(f"not a frame kind: {kind!r}")
    rid = str(rate_id or "")
    arr = _ms(arrival)
    conf = arr - int(c_rest_s * 1000) if kind == REST_ANSWER else arr
    cb = ca = ""
    if kind == REST_ANSWER:
        cb, ca = _conversion_side(conversion_bid), \
            _conversion_side(conversion_ask)
        if not (cb and ca):
            cb = ca = ""
    blank = dict(bid="", ask="", vt_ms="", rid=rid, arr_ms=str(arr),
                 conf_ms=str(conf), reason="", cb=cb, ca=ca)

    def _out(klass, hint, **kw):
        values = dict(blank, **kw)
        return Frame(kind, klass, outcome_hint=hint, **values)

    if kind != REST_ANSWER and bid is None and ask is None:
        return _out(PRICELESS_C, PRICELESS)
    if kind == REST_ANSWER and _is_zero_or_absent(bid) \
            and _is_zero_or_absent(ask):
        return _out(ZERO_C, ZERO)
    try:
        q = VenueQuote(iid=0, bid=bid, ask=ask, vt=vt,
                       channel=REST if kind == REST_ANSWER else WS,
                       arrival=arrival, rate_id=rid)
    except InvalidQuote as e:
        return _out("", REFUSED, reason=e.reason)
    except (ArithmeticError, ValueError, TypeError):
        return _out("", REFUSED, reason="unparsed")
    sides = dict(bid=_norm(q.bid), ask=_norm(q.ask))
    if q.vt is None:
        if kind == REST_ANSWER:
            return _out(UNTIMED_C, UNTIMED, **sides)
        return _out("", REFUSED, reason="untimed_push")
    if (q.vt - q.arrival).total_seconds() > FUTURE_DATE_TOLERANCE_S:
        return _out("", REFUSED, reason="future_date")
    return _out(PRICED, None, vt_ms=str(_ms(q.vt)), **sides)


def decide(cur: dict, fr: dict, *, rate_id_proven=False) -> tuple:
    """THE RULE (the in-memory twin; CAS_LUA mirrors it): the stored record
    `cur` (FIELDS, strings; {} when none) after the frame `fr`
    (Frame.as_dict), its outcome, and whether the record's expiry is set
    anew (a record created, replaced or confirmed)."""
    existed = any(str(cur.get(f, "") or "") != "" for f in FIELDS)
    out = {f: str(cur.get(f, "") or "") for f in FIELDS}
    if out["absent_n"] == "":
        out["absent_n"] = "0"
    arr = int(fr["arr"])
    out["seen"] = str(max(int(out["seen"] or 0), arr))
    c = fr["c"]
    if c == PRICELESS_C:
        return out, PRICELESS, not existed
    if c == ZERO_C:
        out["absent"] = str(arr)
        out["absent_n"] = str(int(out["absent_n"]) + 1)
        return out, ZERO, not existed
    if c == UNTIMED_C:
        out["ub"], out["ua"] = fr["bid"], fr["ask"]
        out["uarr"], out["uconf"] = str(arr), fr["conf"]
        return out, UNTIMED, not existed

    def take():
        out.update({"bid": fr["bid"], "ask": fr["ask"], "vt": fr["vt"],
                    "rid": fr["rid"], "arr": fr["arr"], "conf": fr["conf"],
                    "absent": ""})
        convert()

    def convert():
        if fr["cb"] != "" and fr["ca"] != "":
            out["cb"], out["ca"], out["cat"] = fr["cb"], fr["ca"], fr["conf"]

    if out["vt"] == "":
        take()
        return out, NEW, True
    cv, fv = int(out["vt"]), int(fr["vt"])
    if fv > cv:
        take()
        return out, NEW, True
    older = SNAPSHOT_OLDER if fr["k"] == SNAPSHOT else OLDER
    if fv < cv:
        return out, older, False
    # the same Date: once proven, the rate id orders two prints of it
    if rate_id_proven and fr["rid"] != out["rid"]:
        order = _rid_cmp(fr["rid"], out["rid"])
        if order == 1:
            take()
            return out, NEW, True
        if order == -1:
            return out, older, False
    if fr["bid"] == out["bid"] and fr["ask"] == out["ask"]:
        out["conf"] = str(max(int(out["conf"]), int(fr["conf"])))
        convert()
        return out, SAME, True
    return out, CONFLICT, False


#: THE SAME RULE IN REDIS, one atomic step. KEYS[1] must be a vq:* key;
#: ARGV = Frame.args() + [the expiry in ms, "1" once rate ids are proven].
#: Returns the outcome.
CAS_LUA = r"""
local key = KEYS[1]
if string.sub(key, 1, 3) ~= 'vq:' then
  return redis.error_reply('venue_store: not a vq: key')
end
local k, c, bid, ask, vt, rid, arr, conf, cb, ca, keep, proven =
  ARGV[1], ARGV[2], ARGV[3], ARGV[4], ARGV[5], ARGV[6], ARGV[7], ARGV[8],
  ARGV[9], ARGV[10], ARGV[11], ARGV[12]
local names = {'bid', 'ask', 'vt', 'rid', 'arr', 'conf', 'seen', 'absent',
               'absent_n', 'ub', 'ua', 'uarr', 'uconf', 'cb', 'ca', 'cat'}
local got = redis.call('HMGET', key, unpack(names))
local out = {}
local existed = false
for i, n in ipairs(names) do
  if got[i] and got[i] ~= '' then existed = true end
  if got[i] then out[n] = got[i] else out[n] = '' end
end
if out['absent_n'] == '' then out['absent_n'] = '0' end
local arrn = tonumber(arr)
local seen = tonumber(out['seen']) or 0
if arrn > seen then seen = arrn end
out['seen'] = string.format('%d', seen)
local function maxs(a, b)
  local x, y = tonumber(a), tonumber(b)
  if y > x then x = y end
  return string.format('%d', x)
end
local function digits(s)
  return string.match(s, '^%d+$') ~= nil
end
local function rid_cmp(a, b)
  if not (digits(a) and digits(b)) then return nil end
  a = string.gsub(a, '^0+', '')
  b = string.gsub(b, '^0+', '')
  if a == '' then a = '0' end
  if b == '' then b = '0' end
  if #a ~= #b then
    if #a < #b then return -1 else return 1 end
  end
  if a < b then return -1 elseif a > b then return 1 else return 0 end
end
local function convert()
  if cb ~= '' and ca ~= '' then
    out['cb'], out['ca'], out['cat'] = cb, ca, conf
  end
end
local function take()
  out['bid'], out['ask'], out['vt'], out['rid'] = bid, ask, vt, rid
  out['arr'], out['conf'], out['absent'] = arr, conf, ''
  convert()
end
local outcome
local renew = not existed
if c == 'priceless' then
  outcome = 'priceless'
elseif c == 'zero' then
  out['absent'] = arr
  out['absent_n'] = string.format('%d', tonumber(out['absent_n']) + 1)
  outcome = 'zero'
elseif c == 'untimed' then
  out['ub'], out['ua'], out['uarr'], out['uconf'] = bid, ask, arr, conf
  outcome = 'untimed'
elseif out['vt'] == '' then
  take()
  outcome, renew = 'new', true
else
  local cv, fv = tonumber(out['vt']), tonumber(vt)
  local older = 'older'
  if k == 'snapshot' then older = 'snapshot_older' end
  if fv > cv then
    take()
    outcome, renew = 'new', true
  elseif fv < cv then
    outcome, renew = older, false
  else
    local order = nil
    if proven == '1' and rid ~= out['rid'] then
      order = rid_cmp(rid, out['rid'])
    end
    if order == 1 then
      take()
      outcome, renew = 'new', true
    elseif order == -1 then
      outcome, renew = older, false
    elseif bid == out['bid'] and ask == out['ask'] then
      out['conf'] = maxs(out['conf'], conf)
      convert()
      outcome, renew = 'same', true
    else
      outcome, renew = 'same_ts_conflict', false
    end
  end
end
local flat = {}
for _, n in ipairs(names) do
  flat[#flat + 1] = n
  flat[#flat + 1] = out[n]
end
redis.call('HSET', key, unpack(flat))
if renew then
  redis.call('PEXPIRE', key, tonumber(keep))
end
return outcome
"""


class Conversion(NamedTuple):
    """eToro's conversion of the instrument's currency (REST's
    conversionRateBid/Ask), with the confirmation of the answer that
    carried it: its own age, never the record's."""
    bid: Decimal
    ask: Decimal
    confirmed_at: datetime


def _quote_of(iid, channel, raw) -> Optional[VenueQuote]:
    if not raw or not raw.get("vt"):
        return None
    try:
        return VenueQuote(iid=int(iid), bid=raw["bid"],
                          ask=raw["ask"], vt=_at(raw["vt"]), channel=channel,
                          arrival=_at(raw["arr"]), rate_id=raw.get("rid", ""),
                          confirmed_at=_at(raw["conf"]))
    except (InvalidQuote, KeyError, ValueError, TypeError, ArithmeticError):
        return None


def _newer_rest(feed, engine) -> Optional[VenueQuote]:
    """The newer of two REST v1 records by eToro's Date at the millisecond
    (both are answers of the same channel, so their Dates compare); the
    feed's own on a tie."""
    if engine is not None and engine.vt is None:
        engine = None                  # an untimed answer is display only
    if feed is None or engine is None:
        return feed or engine
    return engine if _ms(engine.vt) > _ms(feed.vt) else feed


class _Store:
    """What both implementations share: the frame's refusal count, the
    record as a VenueQuote, and the read-time choice."""

    def __init__(self, *, rate_id_proven=None, keep_s=RECORD_KEEP_S):
        self.counts = Counter()
        self.rate_id_proven = (RATE_ID_PROVEN if rate_id_proven is None
                               else bool(rate_id_proven))
        self.keep_ms = int(keep_s * 1000)

    def write(self, iid, channel, fr: Frame) -> str:
        """Write `fr` to `channel`'s record of `iid`. Each channel writes
        only its own frames (I2): a stream frame to "ws", a REST answer to
        "rest" — anything else raises before the store is touched."""
        key = record_key(channel, iid)                # a feed channel only
        if CHANNEL_OF.get(fr.kind) != channel:
            raise ValueError(f"a {fr.kind!r} frame is not the {channel!r} "
                             f"channel's (I2)")
        if fr.outcome_hint == REFUSED:
            self.counts[REFUSED] += 1
            self.counts[f"{REFUSED}:{fr.reason}"] += 1
            return REFUSED
        outcome = self._apply(key, fr)
        self.counts[outcome] += 1
        return outcome

    def record(self, iid, channel) -> Optional[VenueQuote]:
        return _quote_of(iid, channel, self.raw(iid, channel))

    def untimed(self, iid) -> Optional[VenueQuote]:
        """The last untimed REST answer (W7), DISPLAY ONLY: a VenueQuote
        with no Date, which grade() never makes LIVE (flag `untimed`)."""
        raw = self.raw(iid, REST)
        if not raw or not raw.get("ub"):
            return None
        try:
            return VenueQuote(iid=int(iid), bid=raw["ub"], ask=raw["ua"],
                              vt=None, channel=REST,
                              arrival=_at(raw["uarr"]),
                              confirmed_at=_at(raw.get("uconf")
                                               or raw["uarr"]))
        except (InvalidQuote, KeyError, ValueError, TypeError,
                ArithmeticError):
            return None

    def conversion(self, iid) -> Optional[Conversion]:
        """The conversion the feed's REST record keeps, or None."""
        raw = self.raw(iid, REST)
        if not raw or not raw.get("cb") or not raw.get("ca"):
            return None
        try:
            return Conversion(Decimal(raw["cb"]), Decimal(raw["ca"]),
                              _at(raw["cat"]))
        except (InvalidOperation, KeyError, ValueError, TypeError):
            return None

    def current(self, iid, *, ws_candidate, cross_channel_proven=None,
                engine=None) -> Optional[VenueQuote]:
        """The record money and the screen read. `ws_candidate` (required:
        §5.6 trust, the caller's to say) admits the stream's record; the
        REST record is the newer of the feed's and the engine's (`engine`,
        engine_record()'s answer) by eToro's Date — both REST v1 answers.
        Until M2 proves Dates compare across channels, the stream's record
        while it is a candidate, else that REST record: a stream Date is
        never compared with a REST one. Once proven, the newest by (Date,
        then PriceRateID once proven), the stream's on a tie."""
        proven = (CROSS_CHANNEL_DATES_PROVEN if cross_channel_proven is None
                  else cross_channel_proven)
        ws = self.record(iid, WS) if ws_candidate else None
        rest = _newer_rest(self.record(iid, REST), engine)
        if not proven:
            return ws or rest
        rank = {WS: 1, REST: 0, ENGINE: 0}
        rid_proven = self.rate_id_proven

        def key(q):
            rid = 0
            if rid_proven and str(q.rate_id).isdigit():
                rid = int(q.rate_id)
            return (_ms(q.vt), rid, rank.get(q.channel, 0))
        found = [q for q in (ws, rest) if q is not None]
        return max(found, key=key) if found else None


class MemoryVenueStore(_Store):
    """The in-memory twin: the same rules as the Lua script, for tests and
    the decision replay — one write at a time (a lock: the script is one
    atomic step), and a record expires RECORD_KEEP_S after it was last
    set, on the frames' own clock (their arrival), as Redis expires it on
    the wall clock the frames arrive by."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._data = {}
        self._expires = {}
        self._lock = threading.Lock()

    def _apply(self, key, fr):
        arr = int(fr.arr_ms)
        with self._lock:
            if key in self._data and self._expires.get(key, arr + 1) <= arr:
                del self._data[key]               # expired before this frame
                self._expires.pop(key, None)
            new, outcome, renew = decide(self._data.get(key, {}),
                                         fr.as_dict(),
                                         rate_id_proven=self.rate_id_proven)
            self._data[key] = new
            if renew:
                self._expires[key] = arr + self.keep_ms
            return outcome

    def raw(self, iid, channel) -> dict:
        with self._lock:
            return dict(self._data.get(record_key(channel, iid), {}))

    def expires_ms(self, iid, channel) -> Optional[int]:
        """When the record expires, in ms on the frames' clock (tests)."""
        return self._expires.get(record_key(channel, iid))


class RedisVenueStore(_Store):
    """The production store: CAS_LUA over a redis client the caller hands
    in (the feed's own connection, F6). Opens nothing itself."""

    def __init__(self, client, **kw):
        super().__init__(**kw)
        self._client = client
        self._script = client.register_script(CAS_LUA)

    def _apply(self, key, fr):
        out = self._script(keys=[key], args=fr.args() + [
            str(self.keep_ms), "1" if self.rate_id_proven else "0"])
        return out.decode() if isinstance(out, bytes) else str(out)

    def raw(self, iid, channel) -> dict:
        got = self._client.hgetall(record_key(channel, iid)) or {}
        return {(k.decode() if isinstance(k, bytes) else k):
                (v.decode() if isinstance(v, bytes) else v)
                for k, v in got.items()}


def _parse_date(value) -> Optional[datetime]:
    """eToro's `date` as kept by the client's rate parser (etoro_client.
    _rate_extras), its format unmeasured until M2: ISO 8601, with or
    without a zone (a naive one is UTC). None when unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=dt_tz.utc)


def _engine_one(world, iid, cache, now_s, c_rest_s, untimed):
    held = cache.get(engine_key(world, iid))
    if not isinstance(held, dict):
        return None
    at_s = float(held["at"])
    if at_s - now_s > ENGINE_AHEAD_S:
        return None                    # stamped ahead of this clock
    arrival = datetime.fromtimestamp(at_s, tz=dt_tz.utc)
    vt = _parse_date(held.get("date"))
    if vt is None and not untimed:
        return None
    if vt is not None:
        vt = _to_ms(vt)
        if (vt - arrival).total_seconds() > FUTURE_DATE_TOLERANCE_S:
            return None                # a Date no real print reaches
    return VenueQuote(iid=int(iid), bid=held.get("bid"),
                      ask=held.get("ask"), vt=vt, channel=ENGINE,
                      arrival=arrival,
                      rate_id=str(held.get("priceRateID") or ""),
                      confirmed_at=arrival - timedelta(seconds=c_rest_s))


def engine_record(iid, *, worlds=WORLDS, cache=None, now=None,
                  c_rest_s=C_REST_UNMEASURED_S,
                  untimed=False) -> Optional[VenueQuote]:
    """THE ENGINE'S RATES CACHE, READ ONLY (§5.2; written by the client's
    rates reads exactly as today, never by the feed before F9): the newest
    answer any of `worlds` keeps for `iid` (market data carries no world),
    by eToro's Date at the millisecond, as a VenueQuote on the ENGINE
    channel confirmed at its arrival less C_rest — or None when there is
    none, it is unreadable or carries no whole quote. An answer stamped
    more than ENGINE_AHEAD_S ahead of `now` (a datetime; the wall clock by
    default), or dated more than FUTURE_DATE_TOLERANCE_S ahead of its own
    arrival, is not taken (as etoro_rates.get). An answer without eToro's
    Date is display only (W7): returned only when `untimed` is asked and
    no dated answer is. Never writes; never raises."""
    try:
        if cache is None:
            from django.core.cache import cache as _cache
            cache = _cache
        if now is None:
            now = datetime.now(tz=dt_tz.utc)
        now_s = now.timestamp()
        dated, undated = [], []
        for world in worlds:
            try:
                q = _engine_one(world, iid, cache, now_s, c_rest_s, untimed)
            except Exception:  # noqa: BLE001 — one unreadable world
                q = None
            if q is not None:
                (dated if q.vt is not None else undated).append(q)
        if dated:
            return max(dated, key=lambda q: (_ms(q.vt), q.arrival))
        if untimed and undated:
            return max(undated, key=lambda q: q.arrival)
        return None
    except Exception:  # noqa: BLE001 — an unreadable cache is no record
        return None
