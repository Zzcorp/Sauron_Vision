"""eTORO'S CANDLE HEADROOM (spec §5.2a item 3, O1c): before the Orcs' 15m
and 5m candles may run, measure how fast eToro answers candle reads before
its first 429.

The ramp asks 15m and 5m candles of 2 bars each, round the symbols, with a
gap of GAP_START_S that halves every HALVE_EVERY reads down to GAP_MIN_S,
and stops at the first 429 or at the request ceiling. It records the clean
rate (reads a minute before any 429), the rate at the 429, the quota
headers eToro sent, and the tape's budget per bar pass:

    tape_per_pass = floor(TAPE_SHARE x clean_per_min x CANDLE_PASS_MAX_S / 60)

in OrcSetting "etoro_candle_headroom". Its reads are BACKGROUND reads
(EtoroTrader.klines): never noted on the venue's health, never granting a
429 pause. It is refused on a live account without --live, while eToro is
sick, after a trading-lane 429 within YIELD_AFTER_LIVE_429_S, and while a
bar pass holds its lock. The command (manage.py etoro_candle_headroom) is a
dry run unless --yes.
"""
import math
import time

GAP_START_S = 2.0
GAP_MIN_S = 0.25
HALVE_EVERY = 10
DEFAULT_MAX_REQUESTS = 60
BARS_PER_READ = 2
INTERVALS = ("15m", "5m")


def _mono() -> float:
    return time.monotonic()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def ramp(n) -> list:
    """The gap before each of `n` reads (the first's is the start gap)."""
    return [max(GAP_MIN_S, GAP_START_S / (2 ** (i // HALVE_EVERY)))
            for i in range(int(n))]


def client_for(user, symbol, cfg):
    """The eToro client the bar refresh would use for (user, symbol)."""
    from market_data.bot_bars import _client_for
    return _client_for(user, symbol, cfg)


def world_of(client) -> str:
    from market_data.bot_bars import _etoro_world
    return _etoro_world(client)


def refusing(world) -> str:
    """Why the ramp must not run now, or ""."""
    from django.core.cache import cache

    from market_data.bot_bars import _etoro_refusing
    from market_data.tasks import BARS_LOCK_KEY
    why = _etoro_refusing(world)
    if why:
        return why
    if cache.get(BARS_LOCK_KEY):
        return "a bar refresh is running (it holds its lock)"
    return ""


def plan_words(world, symbols, max_requests) -> list:
    gaps = ramp(max_requests)
    return [f"eToro world: {world or 'not eToro'}",
            f"symbols: {', '.join(symbols) or 'none'}",
            f"reads: {' and '.join(INTERVALS)} candles, {BARS_PER_READ} bars "
            f"each, round the symbols",
            f"ramp: a {gaps[0]:g} s gap, halved every {HALVE_EVERY} reads "
            f"down to {GAP_MIN_S:g} s",
            f"ceiling: at most {max_requests} candle reads, stopping at "
            f"eToro's first 429"]


def run(client, symbols, *, max_requests=DEFAULT_MAX_REQUESTS) -> dict:
    """The ramp: {requests, hit_429, clean_per_min, at_429_per_min,
    headers, elapsed_s, last_gap_s}."""
    from market_data.bot_bars import _http_status, _venue_symbol
    symbols = list(symbols)
    gaps = ramp(max_requests)
    ok_times, hit, last_gap = [], False, None
    for i in range(int(max_requests)):
        if i:
            _sleep(gaps[i])
            last_gap = gaps[i]
        sym = symbols[(i // len(INTERVALS)) % len(symbols)]
        interval = INTERVALS[i % len(INTERVALS)]
        at = _mono()
        try:
            client.klines(_venue_symbol(client, sym), interval=interval,
                          limit=BARS_PER_READ)
        except Exception as e:  # noqa: BLE001
            if _http_status(e) == 429:
                hit = True
                break
            raise
        ok_times.append(at)
    # the clean rate: n answered reads span n - 1 gaps, so the rate is
    # (n - 1) over that span (counting n would run the budget high)
    clean = None
    if len(ok_times) >= 2 and ok_times[-1] > ok_times[0]:
        clean = round((len(ok_times) - 1)
                      / ((ok_times[-1] - ok_times[0]) / 60.0), 2)
    at_429 = round(60.0 / last_gap, 2) if hit and last_gap else None
    headers = getattr(client, "last_rate_headers", None)
    return {"requests": len(ok_times), "hit_429": hit,
            "clean_per_min": clean, "at_429_per_min": at_429,
            "headers": dict(headers) if isinstance(headers, dict) else {},
            "elapsed_s": round(ok_times[-1] - ok_times[0], 2)
            if len(ok_times) >= 2 else 0.0}


def tape_per_pass(clean_per_min) -> int:
    from bot_program.orcs.constants import TAPE_SHARE

    from market_data.bot_bars import CANDLE_PASS_MAX_S
    if not clean_per_min:
        return 0
    return int(math.floor(TAPE_SHARE * float(clean_per_min)
                          * CANDLE_PASS_MAX_S / 60.0 + 1e-9))


def record(result, *, world, symbols, now=None) -> dict:
    from django.utils import timezone

    from bot_program.orcs.constants import HEADROOM_KEY
    from bot_program.orcs.models import OrcSetting
    now = now or timezone.now()
    value = {**result, "world": world, "symbols": list(symbols),
             "at": now.isoformat(),
             "tape_per_pass": tape_per_pass(result.get("clean_per_min")),
             "by": "etoro_candle_headroom"}
    OrcSetting.objects.update_or_create(
        key=HEADROOM_KEY, defaults={"value": value,
                                    "updated_by": "etoro_candle_headroom"})
    return value
