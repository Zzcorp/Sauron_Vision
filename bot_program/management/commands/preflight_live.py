"""Answer, in one pass, whether it is safe to arm REAL MONEY right now.

`why_no_trade` answers "why is nothing trading". `check_feeds` answers "are
quotes arriving". Neither answers the question an operator actually asks with
their finger over the arming button, and that question has about a dozen parts
spread across six modules — several of which fail SILENTLY in the expensive
direction:

  * the declared pool is a number typed into a form. `capital` is the
    denominator of the whole per-config risk stack (sizing divides by it, the
    daily-loss floor is a percentage of it, the drawdown curve starts at it)
    and arming live checks only the PIN. A pool declared LARGER than the
    account loosens every limit the operator set: 2% of a declared 100,000
    against a real 20,000 is a 10% daily loss.
  * `base_currency` on the config defaults to "USD". A UK ISA is GBP, the
    book defaults to EUR, and this codebase has no FX conversion anywhere by
    design — so three currencies can meet in one risk calculation with
    nothing to make them disagree out loud.
  * `broker_account_sync` is a PlatformComponent created DISABLED, while
    `tracking_freeze_reason` refuses every entry on an account-following pool
    until an equity reading lands. A live bot can therefore be armed, enabled,
    and frozen for hours with no order and no complaint.
  * the port decides paper/live. A port IBKR does not ship makes `env` None,
    which is not paper and not safe.

EVERYTHING HERE IS READ-ONLY. It writes nothing, places no order, and makes
no broker round trip: every number comes from a cached column, because a
broker call in front of an arming decision is a network dependency at exactly
the wrong moment. Age is reported beside every reading so a stale one cannot
pass for a fresh one.

    python manage.py preflight_live
    python manage.py preflight_live --user mathe
"""
from django.core.management.base import BaseCommand


# How old the newest broker equity reading may be before a LIVE account is
# considered unreachable. `broker_account_sync` runs every 15 minutes, so two
# hours is eight missed passes — long enough to ride out a restart or a 2FA
# re-login, short enough that a Gateway which died at the open is named before
# the session is over.
BROKER_READING_STALE_HOURS = 2.0


def _age(dt, now):
    """Human age of a timestamp, or "never"."""
    if dt is None:
        return "never"
    h = (now - dt).total_seconds() / 3600.0
    if h < 1:
        return f"{h * 60:.0f}m ago"
    if h < 48:
        return f"{h:.1f}h ago"
    return f"{h / 24:.1f}d ago"


class Command(BaseCommand):
    help = "Check whether it is safe to arm live trading. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--user", default="",
                            help="Only this username (default: every user "
                                 "that has an IBKR account).")
        parser.add_argument("--symbols", type=int, default=4,
                            help="How many symbols per live config to detail.")

    def handle(self, *args, **opts):
        from django.conf import settings
        from django.contrib.auth.models import User
        from django.utils import timezone

        from bot_program.capital_truth import account_equity
        from bot_program.models import AssetBotConfig, IBKRAccount
        from core.platform_control import PlatformComponent, is_component_enabled
        from market_data.models import PriceData

        w = self.stdout.write
        now = timezone.now()
        per = max(1, int(opts["symbols"]))
        blockers, warnings = [], []
        book_ccy = (settings.PORTFOLIO_CONFIG or {}).get("base_currency", "")

        w("=" * 70)
        w("PREFLIGHT — IS IT SAFE TO ARM REAL MONEY")
        w("=" * 70)

        # ── 1. the switches every live order passes through ─────────────
        w("\n1. PLATFORM SWITCHES")
        for key in ("platform_master", "pipeline_asset_bots",
                    "pipeline_signals", "broker_account_sync"):
            row = PlatformComponent.objects.filter(key=key).first()
            if row is None:
                w(f"   {key:<22} NO ROW  — the gated task no-ops forever")
                blockers.append(f"{key} has no PlatformComponent row "
                                f"(run: manage.py seed_components)")
                continue
            try:
                on = is_component_enabled(key)
            except Exception as exc:            # noqa: BLE001
                on = f"ERR {exc}"
            w(f"   {key:<22} {str(on):<6} last_run={_age(row.last_run_at, now)}")
            if on is False:
                # broker_account_sync is called out by name because its
                # failure mode is the quiet one: it does not stop the bot, it
                # stops the bot from ever getting an equity reading, and
                # tracking_freeze_reason then refuses every entry.
                extra = ("" if key != "broker_account_sync" else
                         " — an account-following live pool will refuse EVERY "
                         "entry until a reading lands")
                blockers.append(f"{key} is OFF{extra}")

        users = (User.objects.filter(username=opts["user"])
                 if opts["user"] else
                 User.objects.filter(ibkr_account__isnull=False))
        if opts["user"] and not users.exists():
            w(f"\n   no user named {opts['user']!r}")
            return
        if not users.exists():
            w("\n   NO IBKR ACCOUNT ON ANY USER — nothing to arm.")
            blockers.append("no IBKRAccount row exists")

        for user in users.order_by("username"):
            acct = IBKRAccount.objects.filter(user=user).first()

            # ── 2. the connection, and which account it points at ───────
            w(f"\n2. IBKR CONNECTION — {user.username}")
            if acct is None:
                w("   NONE — set one up on /admin-dashboard/")
                blockers.append(f"{user.username} has no IBKRAccount")
                continue
            w(f"   label        {acct.label}")
            w(f"   env          {acct.env_label}")
            w(f"   socket       {acct.host}:{acct.port}  "
              f"(slot {acct.gateway_slot} -> {acct.gateway_host})")
            w(f"   client_id    {acct.client_id}")
            w(f"   login stored {acct.has_login}")
            # Labelled for what it is. Left bare it reads as live status, and
            # it is not: nothing but the TEST IBKR button and a form save ever
            # writes it. Section 3 answers reachability.
            w(f"   last manual probe: {acct.connected}  at="
              f"{_age(acct.last_sync, now)}  (not live status — see THE MONEY)")

            if not acct.env_is_certain:
                # None is NOT paper. Everything that renders this must show
                # the unknown as an unknown and refuse to call it safe.
                blockers.append(
                    f"{user.username}: port {acct.port} is not a port IBKR "
                    f"ships — the platform cannot tell paper from live")
            if acct.paper_flag_disagrees:
                warnings.append(
                    f"{user.username}: the stored paper flag says "
                    f"{acct.paper} and the port says {acct.env} — somebody "
                    f"believes something false about which account this is")
            if not acct.has_login:
                blockers.append(f"{user.username}: no Gateway login stored — "
                                f"the container cannot sign in")
            if acct.host in ("127.0.0.1", "localhost") and acct.gateway_host:
                warnings.append(
                    f"{user.username}: host is {acct.host}, but in the compose "
                    f"stack the Gateway is reachable as "
                    f"{acct.gateway_host!r} — 127.0.0.1 inside a worker "
                    f"container is the worker itself")

            # ── 3. the money, with its currency ─────────────────────────
            w(f"\n3. THE MONEY — {user.username}")
            reading = account_equity(user)
            if reading is None:
                w("   broker equity   NEVER MEASURED")
                warnings.append(
                    f"{user.username}: no equity reading has ever landed, so "
                    f"nothing can compare a declared pool against the account")
            else:
                w(f"   broker equity   {reading['value_text']} "
                  f"{reading['currency'] or '(currency UNLABELLED)'}  "
                  f"({reading['age_seconds'] / 3600.0:.1f}h old)")
                if not reading["currency"]:
                    warnings.append(
                        f"{user.username}: the equity reading carries no "
                        f"currency, and this platform converts nothing")
            w(f"   book currency   {book_ccy or '(unset)'}")

            # REACHABILITY IS THE AGE OF THIS READING, NEVER THE `connected`
            # FLAG. The flag is written only when somebody presses TEST IBKR
            # or saves the credentials form, so it means "a socket answered
            # once" and has no expiry — capital_truth.broker_backed says
            # exactly that and refuses to use it, in both directions: it goes
            # on reading True forever after a gateway dies, and it sits at
            # False forever on a gateway nobody has pressed the button for.
            #
            # The first version of this command made a stale False into
            # blocker #1 on a Gateway that IBC had just logged into live, that
            # `docker ps` called healthy, and whose equity reading — printed
            # two lines above the blocker — was four minutes old. The command
            # contradicted itself on its own page. A reading that arrived is
            # proof the socket answered; nothing else here is.
            age_h = (None if reading is None
                     else reading["age_seconds"] / 3600.0)
            if acct.is_live and (age_h is None
                                 or age_h > BROKER_READING_STALE_HOURS):
                blockers.append(
                    f"{user.username}: pointed at a LIVE port and no equity "
                    f"reading has landed "
                    + ("at all" if age_h is None else f"for {age_h:.1f}h")
                    + f" (limit {BROKER_READING_STALE_HOURS:.0f}h) — the "
                    f"broker is not answering, whatever the connected flag "
                    f"says. Is the Gateway logged in?")

            # ── 4. the live configs ─────────────────────────────────────
            live = list(AssetBotConfig.objects.filter(
                user=user, mode="live").order_by("asset_class", "name"))
            w(f"\n4. LIVE CONFIGS — {user.username}")
            if not live:
                w("   none — every config is in paper mode. Nothing is armed.")
            primary = {
                "stock": acct.is_primary_for_stocks,
                "forex": acct.is_primary_for_forex,
                "option": acct.is_primary_for_options,
                "options": acct.is_primary_for_options,
                "commodity": acct.is_primary_for_commodity,
            }
            for cfg in live:
                w(f"   [{cfg.id}] {cfg.name[:20]:<20} {cfg.asset_class:<9} "
                  f"enabled={str(cfg.enabled):<5} "
                  f"pool={cfg.capital} {cfg.base_currency}")
                routed = primary.get(cfg.asset_class)
                if routed is False:
                    w(f"        ^ IBKR is NOT primary for {cfg.asset_class} — "
                      f"this config routes elsewhere, and to PaperTrader if "
                      f"that broker has no account row")
                    warnings.append(
                        f"config {cfg.id} ({cfg.name}) is LIVE but IBKR is not "
                        f"primary for {cfg.asset_class}")

                # THE POOL AGAINST THE ACCOUNT. The direction matters: a pool
                # larger than the account loosens every limit derived from it.
                if reading is not None:
                    same_ccy = (reading["currency"] and cfg.base_currency
                                and reading["currency"].upper()
                                == cfg.base_currency.upper())
                    if not same_ccy and reading["currency"]:
                        w(f"        ^ CURRENCY MISMATCH: pool declared in "
                          f"{cfg.base_currency}, account reads in "
                          f"{reading['currency']}")
                        blockers.append(
                            f"config {cfg.id} ({cfg.name}) declares its pool "
                            f"in {cfg.base_currency} while the account is in "
                            f"{reading['currency']} — every limit derived from "
                            f"`capital` is wrong by the FX rate, and nothing "
                            f"here converts")
                    try:
                        pool = float(cfg.capital)
                    except (TypeError, ValueError):
                        pool = None
                    if pool and pool > reading["value"]:
                        over = pool / reading["value"]
                        w(f"        ^ POOL EXCEEDS THE ACCOUNT by {over:.1f}x")
                        blockers.append(
                            f"config {cfg.id} ({cfg.name}) declares a pool of "
                            f"{pool:,.0f} against an account holding "
                            f"{reading['value']:,.0f} — every risk limit is "
                            f"{over:.1f}x looser than it reads")

                if cfg.enabled and not list(cfg.symbols or []):
                    from bot_program.manual_trade import MANUAL_CONFIG_NAME
                    if cfg.name != MANUAL_CONFIG_NAME:
                        blockers.append(f"config {cfg.id} ({cfg.name}) is LIVE "
                                        f"and enabled with no symbols")

            # ── 5. fuel for the armed ones ──────────────────────────────
            armed = [c for c in live if c.enabled]
            if armed:
                w(f"\n5. FUEL FOR ARMED LIVE CONFIGS — {user.username}")
                for cfg in armed:
                    for sym in list(cfg.symbols or [])[:per]:
                        newest = (PriceData.objects
                                  .filter(instrument__symbol=sym,
                                          timeframe="4h")
                                  .order_by("-timestamp")
                                  .values_list("timestamp", flat=True)
                                  .first())
                        w(f"   {sym:<12} newest 4h bar {_age(newest, now)}")
                        if newest is None:
                            blockers.append(f"{sym} has no 4h bars — an armed "
                                            f"live bot cannot form a decision")

            # ── 6. the PIN ──────────────────────────────────────────────
            prof = getattr(user, "trader_profile", None)
            has_pin = bool(prof and prof.access_pin_hash)
            w(f"\n6. TRADING PIN — {user.username}: "
              f"{'set' if has_pin else 'NOT SET'}")
            if not has_pin:
                blockers.append(
                    f"{user.username} has no trading PIN — configuring or "
                    f"arming a live bot is unreachable without one, by design")

        # ── the verdict ─────────────────────────────────────────────────
        w("\n" + "=" * 70)
        if blockers:
            w("BLOCKERS — do not arm until these are answered:")
            for i, b in enumerate(blockers, 1):
                w(f"  {i}. {b}")
        else:
            w("NO BLOCKERS FOUND.")
            w("Which is not the same as safe. This command reads cached")
            w("columns; it cannot tell you the Gateway is logged in RIGHT")
            w("NOW, and it has never seen your broker answer an order.")
        if warnings:
            w("\nWORTH READING:")
            for i, m in enumerate(warnings, 1):
                w(f"  {i}. {m}")
        w("=" * 70)
