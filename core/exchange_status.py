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
            # CME: Sun 17:00 CT to Fri 16:00 CT with daily 16:00-17:00 break
            is_open = weekday in ex["weekdays"] and not (local_time >= time(16,0) and local_time < time(17,0))
            if weekday == 5:
                is_open = False
            if is_open:
                close_t = time(16, 0)
                time_until = _format_delta(_time_until(local_now, close_t, tz))
            else:
                open_t = time(17, 0)
                time_until = _format_delta(_time_until(local_now, open_t, tz))
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
