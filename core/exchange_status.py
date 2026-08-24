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
            is_open = weekday in ex["weekdays"] and ex["open"] <= local_time < ex["close"]
            if is_open:
                time_until = _format_delta(_time_until(local_now, ex["close"], tz))
            else:
                time_until = _format_delta(_time_until(local_now, ex["open"], tz))

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


def session_code_for(asset_class: str, exchange: str = "") -> str:
    """The EXCHANGES code (or "CRYPTO") whose clock this instrument keeps.

    Crypto wins over any stored exchange string: the seeds write
    exchange="CRYPTO" and no session row will ever exist for it.
    """
    if asset_class == "crypto":
        return "CRYPTO"
    venue = (exchange or "").strip().upper()
    if venue in _EXCHANGE_CODES:
        return venue
    if venue in SESSION_ALIASES:
        return SESSION_ALIASES[venue]
    return ASSET_CLASS_DEFAULT_SESSION.get(asset_class, "NYSE")


def market_status_for(asset_class: str, exchange: str = "", now_utc=None,
                      _status=None) -> dict:
    """One instrument's market, answered: which session, open or not, and
    when that changes. Shape matches a get_exchange_status() row plus
    "session" (the code actually consulted, so a defaulted clock is
    visible rather than passed off as the venue's own).

    `_status` lets a caller that already paid for get_exchange_status()
    (the anomaly scan walks every quote) reuse it instead of recomputing
    fourteen timezones per instrument.
    """
    code = session_code_for(asset_class, exchange)
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
