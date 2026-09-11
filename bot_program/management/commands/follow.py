"""Make a live pool a share of the account, or stop it following — from
the shell, through the same arithmetic as the Follow button.

The asset-bots page has a Follow form per live config: a share (percent)
or blank for automatic, and the trading PIN, because following re-sizes
a live pool on the spot. This is that form without the page. It reads
the last stored broker reading, asks `allocate_shares` whether the share
fits beside every other follower's, prints the whole plan, and writes
only with `--yes`. It never touches the broker.

The PIN gate is the page's; a shell on the server is already behind SSH,
and `--yes` is the deliberate act here. Say so when handing this to an
operator.

    python manage.py follow                      # who follows, at what share
    python manage.py follow 14 --share 20        # plan only
    python manage.py follow 14 --share 20 --yes  # write it
    python manage.py follow 14 --yes             # automatic share
    python manage.py follow 14 --stop --yes      # stop following, pool stays
"""
import math
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Make a live pool a share of the broker account (the Follow button, as a command)."

    def add_arguments(self, parser):
        parser.add_argument("config_id", nargs="?", type=int)
        parser.add_argument("--share", type=float, default=None,
                            help="Percent of the account (0, 100]; omit for automatic.")
        parser.add_argument("--stop", action="store_true",
                            help="Stop following; the pool keeps its last value.")
        parser.add_argument("--yes", action="store_true",
                            help="Write. Without it the command only prints the plan.")
        parser.add_argument("--user", default="",
                            help="Username; defaults to the config's owner.")

    def handle(self, *args, **opts):
        from bot_program.asset_models import AssetBotConfig
        from bot_program.capital_truth import (account_equity, allocate_shares,
                                               followers_of, share_label)

        if opts["config_id"] is None:
            return self._list(opts["user"])

        cfg = AssetBotConfig.objects.filter(pk=opts["config_id"]).first()
        if cfg is None:
            raise CommandError(f"no config with id {opts['config_id']}")
        user = cfg.user
        ex = dict(cfg.extras or {})

        if opts["stop"]:
            if "capital_tracks_broker" not in ex:
                self.stdout.write(f"[{cfg.pk}] {cfg.name} does not follow the account — nothing to stop")
                return
            self.stdout.write(f"[{cfg.pk}] {cfg.name}: stop following; the pool stays at {cfg.capital}")
            if not opts["yes"]:
                self.stdout.write("(plan only — add --yes to write)")
                return
            ex.pop("capital_tracks_broker", None)
            ex.pop("account_share_pct", None)
            cfg.extras = ex
            cfg.save(update_fields=["extras", "updated_at"])
            self.stdout.write(self.style.SUCCESS("written"))
            return

        if cfg.mode == "paper":
            raise CommandError(f"[{cfg.pk}] {cfg.name} is a paper pool — it follows nothing")
        share = opts["share"]
        if share is not None and (not math.isfinite(share) or share <= 0 or share > 100):
            raise CommandError("--share must be a percentage in (0, 100]")
        reading = account_equity(user)
        if reading is None:
            raise CommandError("no broker reading has landed — run the sync first: "
                               "python manage.py shell -c 'from bot_program.tasks import "
                               "sync_broker_account as s; print(s())'")
        followers = followers_of(user, include=cfg)
        alloc = allocate_shares(followers, shares={cfg.pk: share})
        if not alloc["ok"]:
            raise CommandError(f"following would over-allocate the account: {alloc['reason']}")

        value = float(reading["value"])
        cur = reading["currency"] or ""
        self.stdout.write(f"account reading: {value:.2f} {cur}")
        self.stdout.write("plan, every follower after this change:")
        for f in followers:
            frac = float(alloc["plan"][f.pk])
            label = f"{share:g}%" if (f.pk == cfg.pk and share is not None) else (
                "auto" if f.pk == cfg.pk else share_label(f, alloc["plan"]))
            mark = "  <- this one" if f.pk == cfg.pk else ""
            self.stdout.write(f"  [{f.pk}] {f.name:<22} {label:<9} -> {value * frac:.2f} {cur}{mark}")
        if not opts["yes"]:
            self.stdout.write("(plan only — add --yes to write)")
            return

        fraction = float(alloc["plan"][cfg.pk])
        ex["capital_tracks_broker"] = True
        if share is not None:
            ex["account_share_pct"] = share
        else:
            ex.pop("account_share_pct", None)
        cfg.extras = ex
        cfg.capital = Decimal(str(round(value * fraction, 2)))
        cfg.save(update_fields=["extras", "capital", "updated_at"])
        # The other followers' shares changed too (an automatic share is
        # what the explicit ones leave). Re-split them from the same
        # reading NOW — before this, the pools were over-allocated until
        # the next sync came round, and the preflight said so.
        from bot_program.tasks import _follow_the_account
        _follow_the_account(user, value, reading["currency"])
        self.stdout.write(self.style.SUCCESS(
            f"[{cfg.pk}] {cfg.name} follows the account at {fraction * 100:.0f}% — "
            f"pool {cfg.capital} {cur}; every follower re-split from the "
            f"same reading, and the sync keeps them there"))

    def _list(self, username):
        from django.contrib.auth import get_user_model
        from bot_program.asset_models import AssetBotConfig
        from bot_program.capital_truth import (account_equity, allocate_shares,
                                               followers_of, share_label)
        User = get_user_model()
        users = ([User.objects.get(username=username)] if username else
                 list(User.objects.filter(
                     pk__in=AssetBotConfig.objects.values_list("user_id", flat=True)
                 ).distinct()))
        for user in users:
            reading = account_equity(user)
            followers = followers_of(user)
            alloc = allocate_shares(followers)
            head = (f"{float(reading['value']):.2f} {reading['currency'] or ''}"
                    if reading else "no reading")
            self.stdout.write(f"{user.username}: account {head}, {len(followers)} follower(s)")
            for f in followers:
                frac = alloc["plan"].get(f.pk) if alloc["ok"] else None
                self.stdout.write(
                    f"  [{f.pk}] {f.name:<22} {share_label(f, alloc.get('plan')):<9} "
                    f"pool {f.capital}"
                    + (f"  (= {float(reading['value']) * frac:.2f})" if reading and frac is not None else ""))
            if not alloc["ok"]:
                self.stdout.write(self.style.ERROR(f"  OVER-ALLOCATED: {alloc['reason']}"))
            fixed = [c for c in AssetBotConfig.objects.filter(user=user, enabled=True)
                     .exclude(mode="paper") if c not in followers]
            for c in fixed:
                self.stdout.write(f"  [{c.pk}] {c.name:<22} fixed     pool {c.capital}")
