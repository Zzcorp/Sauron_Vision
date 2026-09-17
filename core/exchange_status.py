"""Stock exchange status with time-until-change calculation."""
from datetime import datetime, time, timedelta
import pytz

EXCHANGES = [
    {"code":"NYSE","name":"New York Stock Exchange","flag":"US","tz":"US/Eastern","open":time(9,30),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"NASDAQ","name":"NASDAQ","flag":"US","tz":"US/Eastern","open":time(9,30),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"LSE","name":"London Stock Exchange","flag":"GB","tz":"Europe/London","open":time(8,0),"close":time(16,30),"weekdays":[0,1,2,3,4]},
    {"code":"EURONEXT","name":"Euronext Paris","flag":"FR","tz":"Europe/Paris","open":time(9,0),"close":time(17,30),"weekdays":[0,1,2,3,4]},
    {"code":"XETRA","name":"Frankfurt Xetra","flag":"DE","tz":"Europe/Berlin","open":time(9,0),"close":time(17,30),"weekdays":[0,1,2,3,4]},
    {"code":"TSE","name":"Tokyo Stock Exchange","flag":"JP","tz":"Asia/Tokyo","open":time(9,0),"close":time(15,0),"weekdays":[0,1,2,3,4]},
    {"code":"HKEX","name":"Hong Kong Exchange","flag":"HK","tz":"Asia/Hong_Kong","open":time(9,30),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"SSE","name":"Shanghai Exchange","flag":"CN","tz":"Asia/Shanghai","open":time(9,30),"close":time(15,0),"weekdays":[0,1,2,3,4]},
    {"code":"ASX","name":"Australian SE","flag":"AU","tz":"Australia/Sydney","open":time(10,0),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"BSE","name":"Bombay SE","flag":"IN","tz":"Asia/Kolkata","open":time(9,15),"close":time(15,30),"weekdays":[0,1,2,3,4]},
    {"code":"TSX","name":"Toronto SE","flag":"CA","tz":"US/Eastern","open":time(9,30),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"SIX","name":"SIX Swiss","flag":"CH","tz":"Europe/Zurich","open":time(9,0),"close":time(17,30),"weekdays":[0,1,2,3,4]},
    {"code":"FOREX","name":"Forex Market","flag":"FX","tz":"UTC","open":time(0,0),"close":time(23,59),"weekdays":[0,1,2,3,4]},
    {"code":"CME","name":"CME Futures","flag":"US","tz":"US/Central","open":time(17,0),"close":time(16,0),"weekdays":[6,0,1,2,3,4]},
]

def _time_until(local_now, target_time, tz):
    """Calculate timedelta until a target time, handling next-day rollover."""
    target_dt = local_now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
    if target_dt <= local_now:
        target_dt += timedelta(days=1)
    # Skip weekends
    while target_dt.weekday() > 4:
        target_dt += timedelta(days=1)
    return target_dt - local_now

def _format_delta(td):
    """Format timedelta as human-readable string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "now"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 24:
        days = hours // 24
        return f"{days}d {hours % 24}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

def _weekday_session(ex, local_now, tz):
    """Open-or-not and the countdown for a plain weekday session (one open,
    one close, listed weekdays). Shared by the EXCHANGES rows that keep
    such hours and by the product sessions below."""
    weekday = local_now.weekday()
    local_time = local_now.time()
    is_open = weekday in ex["weekdays"] and ex["open"] <= local_time < ex["close"]
    if is_open:
        time_until = _format_delta(_time_until(local_now, ex["close"], tz))
    else:
        time_until = _format_delta(_time_until(local_now, ex["open"], tz))
    return is_open, time_until


def get_exchange_status(now_utc=None):
    if now_utc is None:
        now_utc = datetime.now(pytz.UTC)
    results = []
    open_count = 0

    for ex in EXCHANGES:
        tz = pytz.timezone(ex["tz"])
        local_now = now_utc.astimezone(tz)
        weekday = local_now.weekday()
        local_time = local_now.time()

        if ex["code"] == "FOREX":
            utc_weekday = now_utc.weekday()
            utc_hour = now_utc.hour
            is_open = not (utc_weekday == 5 or (utc_weekday == 6 and utc_hour < 21) or (utc_weekday == 4 and utc_hour >= 21))
            if is_open:
                # Time until Friday 21:00 UTC close
                days_until_fri = (4 - utc_weekday) % 7
                close_dt = now_utc.replace(hour=21, minute=0, second=0) + timedelta(days=days_until_fri)
                if close_dt <= now_utc:
                    close_dt += timedelta(days=7)
                time_until = _format_delta(close_dt - now_utc)
            else:
                # Time until Sunday 21:00 UTC open
                days_until_sun = (6 - utc_weekday) % 7
                open_dt = now_utc.replace(hour=21, minute=0, second=0) + timedelta(days=days_until_sun)
                if open_dt <= now_utc:
                    open_dt += timedelta(days=7)
                time_until = _format_delta(open_dt - now_utc)
        elif ex["code"] == "CME":
            # The Globex week the old comment claimed and the old code did
            # not implement: Sunday 17:00 CT through Friday 16:00 CT with a
            # daily 16:00-17:00 CT break. The old branch modelled only the
            # daily break, so this row read OPEN all Sunday daytime and all
            # Friday evening — harmless while nothing consulted it, wrong
            # everywhere once the session aliases routed every futures
            # venue and defaulted commodity through it. And _time_until is
            # unusable here on both sides: its weekend skip would push the
            # Sunday 17:00 reopen to Monday, and a close can land on a
            # Saturday-adjacent boundary it refuses to count to.
            in_break = time(16, 0) <= local_time < time(17, 0)
            is_open = not (
                weekday == 5
                or (weekday == 4 and local_time >= time(16, 0))
                or (weekday == 6 and local_time < time(17, 0))
                or in_break
            )
            if is_open:
                # Close: 16:00 CT — today during the daytime hours, or
                # tomorrow for the evening hours after the 17:00 reopen.
                close_dt = local_now.replace(hour=16, minute=0, second=0,
                                             microsecond=0)
                if local_time >= time(17, 0):
                    close_dt += timedelta(days=1)
                time_until = _format_delta(close_dt - local_now)
            else:
                # Reopen: 17:00 CT — today for the daily break and Sunday
                # pre-open, the coming Sunday for the weekend.
                open_dt = local_now.replace(hour=17, minute=0, second=0,
                                            microsecond=0)
                if weekday == 4:
                    open_dt += timedelta(days=2)
                elif weekday == 5:
                    open_dt += timedelta(days=1)
                time_until = _format_delta(open_dt - local_now)
        else:
            is_open, time_until = _weekday_session(ex, local_now, tz)

        if is_open:
            open_count += 1

        results.append({
            "code": ex["code"], "name": ex["name"], "flag": ex["flag"],
            "is_open": is_open,
            "local_time": local_now.strftime("%H:%M"),
            "opens": ex["open"].strftime("%H:%M"),
            "closes": ex["close"].strftime("%H:%M"),
            "time_until_change": time_until,
            "next_state": "closes" if is_open else "opens",
        })
    return {"open_count": open_count, "total": len(EXCHANGES), "exchanges": results}


# ── Which session clock does an instrument answer to? ───────────────────────
#
# `Instrument.exchange` holds whatever the seed data wrote — "NYMEX",
# "CBOT", "EUREX" — and most of those venues have no row in EXCHANGES.
# Anything that reasons about "is this instrument's market open" (the
# anomaly scan, the instrument page badge) needs one answer per instrument,
# not a lookup that silently misses.
#
# Aliases map a venue to the EXCHANGES row whose clock it genuinely keeps:
# NYMEX/COMEX/CBOT are CME Group and trade the same Globex week; ICE
# futures keep hours within minutes of Globex; Osaka keeps Tokyo's, Madrid
# keeps Paris's, Eurex approximates Frankfurt cash hours. LME maps to LSE —
# wrong about intraday edges (LMEselect runs 01:00–19:00 London), right
# about the part that bites: London weekdays on, weekends off. The weekend
# is what produced a "Rice up 3.77%" alert on a Saturday.
#
# "CRYPTO" is deliberately not an EXCHANGES row: it has no local clock, no
# open, no close. `market_status_for` synthesises it.

SESSION_ALIASES = {
    "NYMEX": "CME", "COMEX": "CME", "CBOT": "CME", "ICE": "CME",
    "LME": "LSE", "EUREX": "XETRA", "OSE": "TSE", "BME": "EURONEXT",
}

# When the exchange string matches nothing at all, the asset class picks
# the clock. Stocks default to NYSE — not because every unknown listing is
# American, but because a wrong-but-stated clock beats no answer, and the
# payload names the session it used so the approximation is visible.
ASSET_CLASS_DEFAULT_SESSION = {
    "crypto": "CRYPTO",
    "forex": "FOREX",
    "commodity": "CME",
    "stock": "NYSE",
    "etf": "NYSE",
    "index": "NYSE",
}

_EXCHANGE_CODES = {ex["code"] for ex in EXCHANGES}

# ── Products whose session is narrower than their venue's clock ───────────
#
# The CME row is the Globex week — right for metals and energy, which
# trade nearly round the clock, and WRONG for every product that keeps a
# daytime session, a gap, or an overnight that starts and stops. Read on
# 2026-09-17: at 05:54 CT the readiness report called lean hogs, live
# cattle and lumber OPEN with an 18.9h bar and blamed the feed. Nothing was
# wrong with the feed; the clock was one row for a whole exchange group.
#
# A product session is a list of SEGMENTS in the product's own zone. A
# segment whose close is EARLIER than its open wraps past midnight: it
# opens on each listed weekday and closes the next day. Hours below were
# read at the source (CME Group contract specifications and FAQ, ICE
# product pages), 2026-09-17, in the venue's local time:
#
#   CME livestock (HE, LE)   Mon–Fri 08:30–13:05 CT
#   CME lumber (LBR)         Mon–Fri 09:00–15:05 CT   (16:05 was the
#                            delisted LBS contract — the feed is LBR=F)
#   CBOT grains (ZC ZW ZS    Sun–Thu 19:00 → next day 07:45 CT, and
#     ZO ZR)                 Mon–Fri 08:30–13:20 CT — a 13:20–19:00 gap
#   ICE coffee (KC)          Mon–Fri 04:15–13:30 ET
#   ICE cocoa (CC)           Mon–Fri 04:45–13:30 ET
#   ICE sugar no. 11 (SB)    Mon–Fri 03:30–13:00 ET
#   ICE orange juice (OJ)    Mon–Fri 08:00–14:00 ET
#   ICE cotton no. 2 (CT)    Sun–Thu 21:00 → next day 14:20 ET
#
# Consulted BY SYMBOL before the exchange string, and deliberately not part
# of EXCHANGES: that list is the world-exchange strip and the topbar's N/14
# count, and "CME Livestock" is not a world exchange. A caller that does
# not know the symbol gets the venue's answer, exactly as before. The
# short forms (ZCUSD, KCUSD…) are the pre-catalogue aliases public_feed
# still accepts.
_CT, _ET = "US/Central", "US/Eastern"


def _seg(open_, close, weekdays=(0, 1, 2, 3, 4)) -> dict:
    return {"open": open_, "close": close, "weekdays": list(weekdays)}


_LIVESTOCK = {"code": "CME_LIVESTOCK", "name": "CME Livestock", "flag": "US",
              "tz": _CT, "segments": [_seg(time(8, 30), time(13, 5))]}
_LUMBER = {"code": "CME_LUMBER", "name": "CME Lumber", "flag": "US",
           "tz": _CT, "segments": [_seg(time(9, 0), time(15, 5))]}
_GRAINS = {"code": "CBOT_GRAINS", "name": "CBOT Grains", "flag": "US",
           "tz": _CT, "segments": [_seg(time(19, 0), time(7, 45), (6, 0, 1, 2, 3)),
                                   _seg(time(8, 30), time(13, 20))]}
_COFFEE = {"code": "ICE_COFFEE", "name": "ICE Coffee", "flag": "US",
           "tz": _ET, "segments": [_seg(time(4, 15), time(13, 30))]}
_COCOA = {"code": "ICE_COCOA", "name": "ICE Cocoa", "flag": "US",
          "tz": _ET, "segments": [_seg(time(4, 45), time(13, 30))]}
_SUGAR = {"code": "ICE_SUGAR", "name": "ICE Sugar", "flag": "US",
          "tz": _ET, "segments": [_seg(time(3, 30), time(13, 0))]}
_OJ = {"code": "ICE_OJ", "name": "ICE Orange Juice", "flag": "US",
       "tz": _ET, "segments": [_seg(time(8, 0), time(14, 0))]}
_COTTON = {"code": "ICE_COTTON", "name": "ICE Cotton", "flag": "US",
           "tz": _ET, "segments": [_seg(time(21, 0), time(14, 20), (6, 0, 1, 2, 3))]}
PRODUCT_SESSIONS = {
    "LEANHOGS": _LIVESTOCK, "LIVECATTLE": _LIVESTOCK,
    "LUMBER": _LUMBER,
    "WHEATUSD": _GRAINS, "CORNUSD": _GRAINS, "SOYUSD": _GRAINS,
    "OATS": _GRAINS, "RICE": _GRAINS,
    "ZWUSD": _GRAINS, "ZCUSD": _GRAINS, "ZSUSD": _GRAINS,
    "COFFEEUSD": _COFFEE, "KCUSD": _COFFEE,
    "COCOAUSD": _COCOA, "CCUSD": _COCOA,
    "SUGARUSD": _SUGAR, "SBUSD": _SUGAR,
    "ORANGEJUICE": _OJ,
    "COTTONUSD": _COTTON, "CTUSD": _COTTON,
}
_PRODUCT_BY_CODE = {p["code"]: p for p in PRODUCT_SESSIONS.values()}

# Symbols whose BARS come from a cash index that prints only during the
# cash market's hours, while the catalogue files them under the futures
# venue: ^GSPC, ^NDX, ^DJI, ^RUT print with New York, ^FTSE with London.
# The clock must be the feed's, or every evening reads as a dead feed.
SYMBOL_VENUE = {
    "SPX500": "NYSE", "NSDQ100": "NYSE", "DJ30": "NYSE", "RUSSELL2000": "NYSE",
    "SPX": "NYSE", "NDX": "NYSE", "DJI": "NYSE", "RUT": "NYSE",
    "FTSE100": "LSE", "FTSE": "LSE",
}


def _segment_window(seg, day, tz):
    """The absolute (start, end) of one segment that OPENS on `day`."""
    start = tz.localize(datetime.combine(day, seg["open"]))
    end_day = day if seg["close"] > seg["open"] else day + timedelta(days=1)
    end = tz.localize(datetime.combine(end_day, seg["close"]))
    return start, end


def _segments_status(ex, local_now, tz):
    """(is_open, time_until, opens, closes) for a multi-segment session.

    A wrapped segment that opened YESTERDAY may still be running, so both
    days are checked. When shut, the countdown points at the nearest next
    open of any segment within the coming week, and `opens`/`closes` name
    that segment — the one the operator is waiting for."""
    today = local_now.date()
    for seg in ex["segments"]:
        for day in (today - timedelta(days=1), today):
            if day.weekday() not in seg["weekdays"]:
                continue
            start, end = _segment_window(seg, day, tz)
            if start <= local_now < end:
                return (True, _format_delta(end - local_now),
                        seg["open"], seg["close"])
    upcoming = []
    for seg in ex["segments"]:
        for offset in range(0, 8):
            day = today + timedelta(days=offset)
            if day.weekday() not in seg["weekdays"]:
                continue
            start, _end = _segment_window(seg, day, tz)
            if start > local_now:
                upcoming.append((start, seg))
                break
    if not upcoming:
        first = ex["segments"][0]
        return False, "", first["open"], first["close"]
    start, seg = min(upcoming, key=lambda pair: pair[0])
    return False, _format_delta(start - local_now), seg["open"], seg["close"]


def _product_status(ex, now_utc=None) -> dict:
    """A product session answered in the same shape as an EXCHANGES row."""
    if now_utc is None:
        now_utc = datetime.now(pytz.UTC)
    tz = pytz.timezone(ex["tz"])
    local_now = now_utc.astimezone(tz)
    is_open, time_until, opens, closes = _segments_status(ex, local_now, tz)
    return {
        "code": ex["code"], "name": ex["name"], "flag": ex["flag"],
        "session": ex["code"], "is_open": is_open,
        "local_time": local_now.strftime("%H:%M"),
        "opens": opens.strftime("%H:%M"),
        "closes": closes.strftime("%H:%M"),
        "time_until_change": time_until,
        "next_state": "closes" if is_open else "opens",
    }


def product_sessions_status(now_utc=None) -> list:
    """Every product session, once each, for the badge poller: the JSON
    endpoint appends these beside the EXCHANGES rows so a livestock badge
    left open across 13:05 CT flips like every other badge on the page —
    without touching the strip's count."""
    return [_product_status(p, now_utc) for p in _PRODUCT_BY_CODE.values()]


def session_code_for(asset_class: str, exchange: str = "",
                     symbol: str = "") -> str:
    """The EXCHANGES code (or "CRYPTO", or a PRODUCT_SESSIONS code) whose
    clock this instrument keeps.

    Crypto wins over any stored exchange string: the seeds write
    exchange="CRYPTO" and no session row will ever exist for it. Then the
    product table, by symbol, for the few contracts whose session is
    narrower than their venue's; then the venue string as before.
    """
    if asset_class == "crypto":
        return "CRYPTO"
    sym = (symbol or "").strip().upper()
    product = PRODUCT_SESSIONS.get(sym)
    if product is not None:
        return product["code"]
    if sym in SYMBOL_VENUE:
        return SYMBOL_VENUE[sym]
    venue = (exchange or "").strip().upper()
    if venue in _EXCHANGE_CODES:
        return venue
    if venue in SESSION_ALIASES:
        return SESSION_ALIASES[venue]
    return ASSET_CLASS_DEFAULT_SESSION.get(asset_class, "NYSE")


def market_status_for(asset_class: str, exchange: str = "", now_utc=None,
                      _status=None, symbol: str = "") -> dict:
    """One instrument's market, answered: which session, open or not, and
    when that changes. Shape matches a get_exchange_status() row plus
    "session" (the code actually consulted, so a defaulted clock is
    visible rather than passed off as the venue's own).

    `_status` lets a caller that already paid for get_exchange_status()
    (the anomaly scan walks every quote) reuse it instead of recomputing
    fourteen timezones per instrument.
    """
    code = session_code_for(asset_class, exchange, symbol)
    product = _PRODUCT_BY_CODE.get(code)
    if product is not None:
        return _product_status(product, now_utc)
    if code == "CRYPTO":
        return {
            "code": "CRYPTO", "name": "Crypto", "flag": "₿",
            "session": "CRYPTO", "is_open": True,
            "local_time": "", "opens": "", "closes": "",
            "time_until_change": "", "next_state": "",
        }
    status = _status or get_exchange_status(now_utc)
    for row in status["exchanges"]:
        if row["code"] == code:
            out = dict(row)
            out["session"] = code
            return out
    # Unreachable while session_code_for only returns EXCHANGES codes, but
    # a renamed row must degrade to "unknown, treat as open" — a wrongly
    # CLOSED badge (or an anomaly scan that silently drops a market) is the
    # worse failure.
    return {"code": code, "name": code, "flag": "", "session": code,
            "is_open": True, "local_time": "", "opens": "", "closes": "",
            "time_until_change": "", "next_state": ""}
