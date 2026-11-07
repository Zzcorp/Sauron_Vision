"""THE FEED'S STORES OF eTORO'S QUOTES (the eToro feed spec, F1, §5.2-§5.3;
2026-11-07).

One record per channel and instrument, never mixed (I2):

  vq:ws:{iid}     the stream's record, written by the feed only;
  vq:rest:{iid}   the feed's REST record, written by its watchdog and the
                  Celery fallback only;
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
  W3 same            the same Date and sides, or the same rate id: a
                     confirmation only (a REST answer at its arrival less
                     C_rest, the REST cache bound, §5.4).
  W4 conflict        the same Date with other sides: the stored sides are
                     kept and the conflict counted.
  W5 older           never replaces; an older snapshot confirms nothing.
  W6 price-less      a frame with no price is liveness only.
  W7 untimed REST    kept beside the record for display, never the record.
  "0"                eToro's no-price answer never replaces a priced
                     record; the absence is noted beside it and never
                     refreshes the confirmation.
  W1 (refused)       never reaches a store: the frame is classified before
                     (`frame`), and the refusal is counted by reason.

Nothing writes these stores in F1: the feed that will (F6) does not exist
yet, and the pins (tests/feed/test_feed_pins.py) hold that only the feed's
modules ever name a vq:* key.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal, InvalidOperation
from typing import NamedTuple, Optional

from market_data.venue_quotes import (C_REST_UNMEASURED_S, ENGINE, REST,
                                      RECORD_KEEP_S, WS, InvalidQuote,
                                      VenueQuote)

#: Every key the feed writes starts here (and nothing else writes one).
VQ_PREFIX = "vq:"
#: The engine's rates cache, read-only to the feed before F9
#: (bot_program.engine.etoro_rates._key).
ENGINE_RATES_PREFIX = "etoro_rates:r:"

#: M2 proves eToro's Dates compare across the two channels (the same
#: PriceRateID carries the same Date on both); until then the read-time
#: choice never compares them (§5.2).
CROSS_CHANNEL_DATES_PROVEN = False
#: M2 proves PriceRateID only increases and is shared by both channels.
RATE_ID_PROVEN = False

# frame kinds
PUSH, SNAPSHOT, REST_ANSWER = "push", "snapshot", "rest"
KINDS = (PUSH, SNAPSHOT, REST_ANSWER)
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
#: the last frame seen, the last absence and their count, and the last
#: untimed answer (ub, ua, uarr), kept for display.
FIELDS = ("bid", "ask", "vt", "rid", "arr", "conf", "seen", "absent",
          "absent_n", "ub", "ua", "uarr")


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
    return int(round(when.timestamp() * 1000))


def _at(ms) -> Optional[datetime]:
    if ms in (None, ""):
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=dt_tz.utc)


def _norm(value) -> str:
    """A side as both implementations compare it: Decimal's own text."""
    return str(Decimal(str(value).strip()))


def _is_zero_or_absent(value) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    try:
        return Decimal(str(value).strip()) == 0
    except (InvalidOperation, ValueError, TypeError):
        return False


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

    def args(self) -> list:
        """The Lua script's ARGV."""
        return [self.kind, self.klass, self.bid, self.ask, self.vt_ms,
                self.rid, self.arr_ms, self.conf_ms,
                str(RECORD_KEEP_S * 1000)]

    def as_dict(self) -> dict:
        return {"k": self.kind, "c": self.klass, "bid": self.bid,
                "ask": self.ask, "vt": self.vt_ms, "rid": self.rid,
                "arr": self.arr_ms, "conf": self.conf_ms}


def frame(*, kind, bid, ask, vt, arrival, rate_id="",
          c_rest_s=C_REST_UNMEASURED_S) -> Frame:
    """Classify one answer of eToro's.

    A stream frame (PUSH, SNAPSHOT) with no price at all is W6 liveness;
    a REST answer whose every side is "0" or absent is eToro's no-price
    answer; a REST answer without eToro's Date is W7 (display only). Any
    other frame must make a whole VenueQuote (W1), or it is refused with
    its reason. A REST answer's confirmation is dated its arrival less
    C_rest (§5.4); a stream frame's, its arrival."""
    if kind not in KINDS:
        raise ValueError(f"not a frame kind: {kind!r}")
    rid = str(rate_id or "")
    arr = _ms(arrival)
    conf = arr - int(c_rest_s * 1000) if kind == REST_ANSWER else arr
    blank = dict(bid="", ask="", vt_ms="", rid=rid, arr_ms=str(arr),
                 conf_ms=str(conf), reason="")

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
    sides = dict(bid=_norm(q.bid), ask=_norm(q.ask))
    if q.vt is None:
        if kind == REST_ANSWER:
            return _out(UNTIMED_C, UNTIMED, **sides)
        return _out("", REFUSED, reason="untimed_push")
    return _out(PRICED, None, vt_ms=str(_ms(q.vt)), **sides)


def decide(cur: dict, fr: dict) -> tuple:
    """THE RULE (the in-memory twin; CAS_LUA mirrors it): the stored record
    `cur` (FIELDS, strings; {} when none) after the frame `fr`
    (Frame.as_dict), and the outcome."""
    out = {f: str(cur.get(f, "") or "") for f in FIELDS}
    if out["absent_n"] == "":
        out["absent_n"] = "0"
    arr = int(fr["arr"])
    out["seen"] = str(max(int(out["seen"] or 0), arr))
    c = fr["c"]
    if c == PRICELESS_C:
        return out, PRICELESS
    if c == ZERO_C:
        out["absent"] = str(arr)
        out["absent_n"] = str(int(out["absent_n"]) + 1)
        return out, ZERO
    if c == UNTIMED_C:
        out["ub"], out["ua"], out["uarr"] = fr["bid"], fr["ask"], str(arr)
        return out, UNTIMED
    record = {"bid": fr["bid"], "ask": fr["ask"], "vt": fr["vt"],
              "rid": fr["rid"], "arr": fr["arr"], "conf": fr["conf"]}
    if out["vt"] == "":
        out.update(record)
        out["absent"] = ""
        return out, NEW
    if fr["rid"] != "" and fr["rid"] == out["rid"]:
        out["conf"] = str(max(int(out["conf"]), int(fr["conf"])))
        return out, SAME
    cv, fv = int(out["vt"]), int(fr["vt"])
    if fv > cv:
        out.update(record)
        out["absent"] = ""
        return out, NEW
    if fv == cv:
        if fr["bid"] == out["bid"] and fr["ask"] == out["ask"]:
            out["conf"] = str(max(int(out["conf"]), int(fr["conf"])))
            return out, SAME
        return out, CONFLICT
    if fr["k"] == SNAPSHOT:
        return out, SNAPSHOT_OLDER
    return out, OLDER


#: THE SAME RULE IN REDIS, one atomic step. KEYS[1] must be a vq:* key;
#: ARGV = Frame.args(). Returns the outcome.
CAS_LUA = r"""
local key = KEYS[1]
if string.sub(key, 1, 3) ~= 'vq:' then
  return redis.error_reply('venue_store: not a vq: key')
end
local k, c, bid, ask, vt, rid, arr, conf, ttl =
  ARGV[1], ARGV[2], ARGV[3], ARGV[4], ARGV[5], ARGV[6], ARGV[7], ARGV[8],
  ARGV[9]
local names = {'bid', 'ask', 'vt', 'rid', 'arr', 'conf', 'seen', 'absent',
               'absent_n', 'ub', 'ua', 'uarr'}
local got = redis.call('HMGET', key, unpack(names))
local out = {}
for i, n in ipairs(names) do
  if got[i] then out[n] = got[i] else out[n] = '' end
end
if out['absent_n'] == '' then out['absent_n'] = '0' end
local arrn = tonumber(arr)
local seen = tonumber(out['seen']) or 0
if arrn > seen then seen = arrn end
out['seen'] = string.format('%d', seen)
local outcome
local function maxs(a, b)
  local x, y = tonumber(a), tonumber(b)
  if y > x then x = y end
  return string.format('%d', x)
end
if c == 'priceless' then
  outcome = 'priceless'
elseif c == 'zero' then
  out['absent'] = arr
  out['absent_n'] = string.format('%d', tonumber(out['absent_n']) + 1)
  outcome = 'zero'
elseif c == 'untimed' then
  out['ub'], out['ua'], out['uarr'] = bid, ask, arr
  outcome = 'untimed'
else
  local function take()
    out['bid'], out['ask'], out['vt'], out['rid'] = bid, ask, vt, rid
    out['arr'], out['conf'], out['absent'] = arr, conf, ''
  end
  if out['vt'] == '' then
    take()
    outcome = 'new'
  elseif rid ~= '' and rid == out['rid'] then
    out['conf'] = maxs(out['conf'], conf)
    outcome = 'same'
  else
    local cv, fv = tonumber(out['vt']), tonumber(vt)
    if fv > cv then
      take()
      outcome = 'new'
    elseif fv == cv then
      if bid == out['bid'] and ask == out['ask'] then
        out['conf'] = maxs(out['conf'], conf)
        outcome = 'same'
      else
        outcome = 'same_ts_conflict'
      end
    elseif k == 'snapshot' then
      outcome = 'snapshot_older'
    else
      outcome = 'older'
    end
  end
end
local flat = {}
for _, n in ipairs(names) do
  flat[#flat + 1] = n
  flat[#flat + 1] = out[n]
end
redis.call('HSET', key, unpack(flat))
redis.call('PEXPIRE', key, tonumber(ttl))
return outcome
"""


def _quote_of(iid, channel, raw) -> Optional[VenueQuote]:
    if not raw or not raw.get("vt"):
        return None
    try:
        return VenueQuote(iid=int(iid), bid=raw["bid"],
                          ask=raw["ask"], vt=_at(raw["vt"]), channel=channel,
                          arrival=_at(raw["arr"]), rate_id=raw.get("rid", ""),
                          confirmed_at=_at(raw["conf"]))
    except (InvalidQuote, KeyError, ValueError, TypeError):
        return None


class _Store:
    """What both implementations share: the frame's refusal count, the
    record as a VenueQuote, and the read-time choice."""

    def __init__(self):
        self.counts = Counter()

    def write(self, iid, channel, fr: Frame) -> str:
        record_key(channel, iid)                     # a feed channel only
        if fr.outcome_hint == REFUSED:
            self.counts[REFUSED] += 1
            self.counts[f"{REFUSED}:{fr.reason}"] += 1
            return REFUSED
        outcome = self._apply(record_key(channel, iid), fr)
        self.counts[outcome] += 1
        return outcome

    def record(self, iid, channel) -> Optional[VenueQuote]:
        return _quote_of(iid, channel, self.raw(iid, channel))

    def current(self, iid, *, ws_candidate=True, cross_channel_proven=None,
                engine=None) -> Optional[VenueQuote]:
        """The record money and the screen read: until M2 proves eToro's
        Dates compare across channels, the stream's record while it is a
        candidate (§5.6 trust), else the REST record (the feed's, else the
        engine's); never a comparison of Dates. Once proven, the newest by
        (Date, then PriceRateID once proven), the stream's on a tie."""
        proven = (CROSS_CHANNEL_DATES_PROVEN if cross_channel_proven is None
                  else cross_channel_proven)
        ws = self.record(iid, WS) if ws_candidate else None
        rest = self.record(iid, REST) or engine
        if not proven:
            return ws or rest
        rank = {WS: 1, REST: 0, ENGINE: 0}

        def key(q):
            rid = 0
            if RATE_ID_PROVEN:
                try:
                    rid = int(q.rate_id)
                except (TypeError, ValueError):
                    rid = 0
            return (q.vt, rid, rank.get(q.channel, 0))
        found = [q for q in (ws, rest) if q is not None]
        return max(found, key=key) if found else None


class MemoryVenueStore(_Store):
    """The in-memory twin: the same rules as the Lua script, for tests and
    the decision replay."""

    def __init__(self):
        super().__init__()
        self._data = {}

    def _apply(self, key, fr):
        new, outcome = decide(self._data.get(key, {}), fr.as_dict())
        self._data[key] = new
        return outcome

    def raw(self, iid, channel) -> dict:
        return dict(self._data.get(record_key(channel, iid), {}))


class RedisVenueStore(_Store):
    """The production store: CAS_LUA over a redis client the caller hands
    in (the feed's own connection, F6). Opens nothing itself."""

    def __init__(self, client):
        super().__init__()
        self._client = client
        self._script = client.register_script(CAS_LUA)

    def _apply(self, key, fr):
        out = self._script(keys=[key], args=fr.args())
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


def engine_record(world, iid, *, cache=None,
                  c_rest_s=C_REST_UNMEASURED_S) -> Optional[VenueQuote]:
    """THE ENGINE'S RATES CACHE, READ ONLY (§5.2; written by the client's
    rates reads exactly as today, never by the feed before F9): the answer
    kept for (world, iid) as a VenueQuote on the ENGINE channel, confirmed
    at its arrival less C_rest — or None when there is none, it is
    unreadable, it carries no whole quote or no eToro Date (an untimed
    answer is display only, W7). Never writes; never raises."""
    try:
        if cache is None:
            from django.core.cache import cache as _cache
            cache = _cache
        held = cache.get(engine_key(world, iid))
        if not isinstance(held, dict):
            return None
        vt = _parse_date(held.get("date"))
        if vt is None:
            return None
        arrival = datetime.fromtimestamp(float(held["at"]), tz=dt_tz.utc)
        return VenueQuote(iid=int(iid), bid=held.get("bid"),
                          ask=held.get("ask"), vt=vt, channel=ENGINE,
                          arrival=arrival,
                          rate_id=str(held.get("priceRateID") or ""),
                          confirmed_at=arrival - timedelta(seconds=c_rest_s))
    except Exception:  # noqa: BLE001 — an unreadable cache is no record
        return None
