"""Stop SmcSignal storing the same bar's setup eighteen times, record the
sample size behind the hit rate it prints, and scrub the priors already stored.

Three changes, in the order they have to happen:

  1. `rule_hit_rate_n` — how many closed cards `rule_hit_rate_30d` was
     measured on. NULL means nobody measured; 0 means nobody has closed.

  2. Clear the published priors sitting in `rule_hit_rate_30d`. Removing the
     table from `scan_symbol` only stops NEW rows carrying it; every row a
     deployed database already holds still has the strategy author's PDF
     number in that column, and `_signal_cards.html` now renders it under a
     "Measured on N closed cards" tooltip. See `clear_published_priors`.

  3. A unique constraint on (symbol, timeframe, setup, direction, trigger_ts).
     Every detector evaluates the LAST bar, so the 900s SignalEngine pass and
     the 1800s universe scan re-detected each live setup on every pass and
     `persist_cards` stored every one of them — roughly 18 identical rows per
     4h bar per symbol. Existing databases are therefore full of duplicates
     that would make AddConstraint fail, so the collapse runs first: the
     OLDEST row of each group survives, because that one is the moment the
     setup actually fired.
"""
from django.db import migrations, models


def clear_published_priors(apps, schema_editor):
    """NULL every hit rate that no sample size stands behind.

    Until this slice, the ONLY writer of `rule_hit_rate_30d` was a literal
    dict in `scan_symbol` copied out of the strategy author's PDF —
    RP_BREAKER 0.76, RANGE_MSB_SD 0.61, and so on — so every value a deployed
    database holds today is a book number, not this platform's record. The
    scanner no longer writes them, but the feed still reads them, and the card
    template labels what it reads "Measured on N closed cards in the last 30
    days". Leaving them in place would keep publishing the marketing claim
    under a measurement label, which is the whole defect this slice exists to
    end.

    `rule_hit_rate_n` is the discriminator, and it is exact rather than
    approximate: the column was created empty by the AddField immediately
    above, so at this instant a NULL sample means the row predates the change.
    Anything the new code writes carries a sample (0 for "nothing has closed",
    a count for a real measurement) alongside a rate it actually measured, so
    a later re-run of this function — a squashed migration, a restored dump —
    cannot touch an honest row.
    """
    SmcSignal = apps.get_model("signals", "SmcSignal")
    cleared = (
        SmcSignal.objects
        .filter(rule_hit_rate_n__isnull=True, rule_hit_rate_30d__isnull=False)
        .update(rule_hit_rate_30d=None)
    )
    if cleared:
        print("  cleared %d published-prior hit rate(s)" % cleared)


def collapse_duplicate_cards(apps, schema_editor):
    """Keep the earliest row of each (symbol, timeframe, setup, direction, bar)."""
    from django.db.models import Count, Min

    SmcSignal = apps.get_model("signals", "SmcSignal")
    keys = ["symbol", "timeframe", "setup", "direction", "trigger_ts"]

    groups = (
        SmcSignal.objects
        .exclude(trigger_ts__isnull=True)
        # order_by() clears SmcSignal's -created_at Meta ordering. Without it
        # the GROUP BY picks up created_at and every row becomes its own
        # group, so the migration would find no duplicates and AddConstraint
        # would then fail on the real ones.
        .order_by()
        .values(*keys)
        .annotate(n=Count("id"), keep=Min("id"))
        .filter(n__gt=1)
    )

    removed = 0
    for group in groups:
        doomed = SmcSignal.objects.filter(
            **{k: group[k] for k in keys}
        ).exclude(id=group["keep"])
        removed += doomed.count()
        doomed.delete()
    if removed:
        print("  collapsed %d duplicate SmcSignal row(s)" % removed)


def noop(apps, schema_editor):
    """Nothing to undo. Deleted duplicates are not recoverable, and a reverse
    that put the PDF priors back would be re-publishing the very numbers this
    migration exists to remove — so unapplying it simply drops the constraint
    and the column."""


class Migration(migrations.Migration):

    dependencies = [
        ('signals', '0015_opportunitysetup_sizing_help_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='smcsignal',
            name='rule_hit_rate_n',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.RunPython(clear_published_priors, noop),
        migrations.RunPython(collapse_duplicate_cards, noop),
        migrations.AddConstraint(
            model_name='smcsignal',
            constraint=models.UniqueConstraint(
                fields=('symbol', 'timeframe', 'setup', 'direction', 'trigger_ts'),
                name='uniq_smcsignal_per_bar',
            ),
        ),
    ]
