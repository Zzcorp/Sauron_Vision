"""Re-book forex tax-lot consumptions in account currency.

`close_lots_for` computed `realized_gain` as (sale - cost) x qty x multiplier
and stopped there. On a forex row those prices are in the QUOTE currency, so
a USDJPY consumption was filed in yen into a column every tax report reads as
dollars — a 33-dollar gain recorded as 5,000. The rate is now applied at
write time; the rows written before that are still in yen, and no report can
tell them apart from the correct ones by looking.

Deliberately a command and not a data migration. This rewrites financial
records: the operator should choose the moment, read the dry run first, and
have the option not to. Migrations do none of those things.

    manage.py backfill_taxlot_currency              # dry run, changes nothing
    manage.py backfill_taxlot_currency --apply

Only rows whose consuming trade is forex AND carries its entry-time rate in
metadata["value_per_unit"] are touched. A row without that rate is REPORTED
AND SKIPPED rather than converted at today's price — a made-up rate on a tax
record is the same class of error this command exists to remove.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

#: Written onto the consuming trade once its consumptions have been
#: converted, so a second run is a no-op rather than a second
#: conversion.
MARK = 'taxlot_ccy_backfilled'


class Command(BaseCommand):
    help = "Convert forex TaxLotConsumption.realized_gain to account currency"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="write the corrections (without this, nothing is saved)")

    def handle(self, *args, **opts):
        from bot_program.tax_lot_models import TaxLotConsumption

        apply = bool(opts.get("apply"))
        rows = (TaxLotConsumption.objects
                .select_related("consuming_trade")
                .filter(consuming_trade__asset_class="forex")
                .order_by("sold_at"))

        fixed = skipped = already = 0
        total_before = Decimal("0")
        total_after = Decimal("0")

        for cons in rows:
            trade = cons.consuming_trade
            rate = (getattr(trade, "metadata", None) or {}).get("value_per_unit")
            if not rate:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"  SKIP #{cons.pk} {cons.lot.symbol} — the trade never "
                    f"recorded its entry-time rate; converting at any other "
                    f"rate would be a guess on a tax record"))
                continue
            try:
                fx = Decimal(str(rate))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            if fx <= 0 or fx == 1:
                already += 1
                continue
            # Rows this command has already converted must never be
            # converted again. The only 'already done' test was `fx == 1`,
            # which catches USD-quoted pairs and nothing else — so a second
            # run (a re-deploy, a second operator, a cautious repeat) would
            # multiply every JPY row by 0.0067 a second time and file a
            # 33-dollar gain as 22 cents.
            #
            # The marker rides on the CONSUMING TRADE, whose `metadata` is a
            # JSON column that already exists. Neither TaxLot nor
            # TaxLotConsumption has one, and a migration to add a field
            # whose only purpose is bookkeeping for a one-off command is a
            # schema change this does not need. Every consumption of a given
            # trade is converted in the same pass, so one flag per trade is
            # exactly the right grain.
            if (getattr(trade, "metadata", None) or {}).get(MARK):
                already += 1
                continue

            before = Decimal(str(cons.realized_gain or 0))
            after = (before * fx).quantize(Decimal("0.0001"))
            total_before += before
            total_after += after
            fixed += 1
            self.stdout.write(
                f"  #{cons.pk} {cons.lot.symbol} {cons.sold_at:%Y-%m-%d} "
                f"{before:+.4f} -> {after:+.4f}  (x{fx})")
            if apply:
                with transaction.atomic():
                    TaxLotConsumption.objects.filter(pk=cons.pk).update(
                        realized_gain=after)
                    meta = dict(getattr(trade, "metadata", None) or {})
                    meta[MARK] = timezone.now().isoformat()
                    type(trade).objects.filter(pk=trade.pk).update(
                        metadata=meta)
                    trade.metadata = meta

        self.stdout.write("")
        self.stdout.write(f"forex consumptions examined : {rows.count()}")
        self.stdout.write(f"already in account currency : {already}")
        self.stdout.write(f"no entry rate on file       : {skipped}")
        self.stdout.write(f"convertible                 : {fixed}")
        self.stdout.write(f"  filed total  {total_before:+.2f}")
        self.stdout.write(f"  correct total{total_after:+.2f}")
        if apply:
            self.stdout.write(self.style.SUCCESS("written."))
        else:
            self.stdout.write(self.style.WARNING(
                "dry run — nothing was saved. Re-run with --apply."))
