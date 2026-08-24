"""Copy the brain's historical LLM costs into the AgentTask ledger.

The AgentTask ledger is what spent_today(), the daily budget and the
/ai-models/ readout believe; the seven brain modules called the provider
directly and wrote their costs into six domain tables instead. The write
side is fixed (the provider itself now records every call) — this repairs
the HISTORY, so "what has intelligence cost us" stops having two answers
that disagree by half.

Three ways a naive copy would lie, each closed here:

  * FAN-OUT — the strategy generator stamps ONE call's full cost onto
    every proposal it persists (up to three). Rows are grouped: siblings
    sharing the same usage numbers within a short window are one call and
    emit one ledger row, marked by the group's first pk.

  * ROWS OLDER THAN THEIR CALL — a research ask's pending row and a
    position review's layer-one row are written BEFORE the model call
    that pays for them, so a timestamp cut cannot tell them from history.
    The provider stamps `source_ref` into its live ledger rows; any
    domain row a live row already references is skipped.

  * LIVE OVERLAP — everything at or after the first live ledger row per
    agent is already recorded by the provider and never copied.

Idempotent: each backfilled row carries a `ledger-backfill:<table>:<pk>`
marker in response_summary and is skipped on re-run. `created_at` is
rewritten to the source row's own timestamp inside the same transaction
(auto_now_add stamps the insert time), so daily aggregations land on the
day the money actually left. The critic stored its cost nowhere at all;
that slice of history is honestly unrecoverable and is not estimated.

Run with:  python manage.py backfill_llm_ledger
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

# Two sibling proposals from one generator call are written in one loop —
# seconds apart at most. Two genuinely separate calls with IDENTICAL token
# counts and cost inside this window is the collision this trades away;
# on hourly/daily cadences it does not occur.
GROUP_WINDOW_SECONDS = 120


class Command(BaseCommand):
    help = "Backfill AgentTask ledger rows from the brain's own cost columns."

    def handle(self, *args, **options):
        from ai_agents.models import AgentTask

        # Names MATCH the live attribution (each module passes its own
        # agent.agent_name), so one name aggregates one agent's whole
        # history. Every table here was written by a direct-provider
        # BYPASS site — never a BaseAgent path, whose costs were always
        # in the ledger and would double if copied.
        SOURCES = [
            ("sauron_mind", "brain.models", "BrainReport",
             "tokens_in", "tokens_out"),
            ("strategist", "brain.briefing_models", None, None, None),
            ("earnings_reviewer", "brain.earnings_models", None, None, None),
            ("strategy_generator", "brain.generator_models", None, None, None),
            ("position_reviewer", "brain.position_review_models",
             None, None, None),
            ("research", "brain.research_models", None, None, None),
        ]

        # One pass over the ledger up front instead of one query per source
        # row: the markers we must not re-emit, and the domain rows live
        # ledger rows already reference.
        markers = set()
        referenced = set()
        for summary, structured in (AgentTask.objects
                                    .values_list("response_summary",
                                                 "structured_output")):
            if summary.startswith("ledger-backfill:"):
                markers.add(summary)
            if isinstance(structured, dict) and structured.get("source_ref"):
                referenced.add(structured["source_ref"])

        total_rows, total_usd = 0, 0.0
        for agent_name, module_path, model_name, tin, tout in SOURCES:
            import importlib
            module = importlib.import_module(module_path)
            model_cls = (getattr(module, model_name) if model_name
                         else self._cost_model(module))
            if model_cls is None:
                self.stdout.write(f"  {module_path}: no cost-bearing model "
                                  f"found — skipped")
                continue
            tin = tin or self._field(model_cls, ("tokens_in", "input_tokens"))
            tout = tout or self._field(model_cls,
                                       ("tokens_out", "output_tokens"))

            live_start = (AgentTask.objects
                          .filter(agent=agent_name)
                          .exclude(response_summary__startswith=
                                   "ledger-backfill:")
                          .order_by("created_at")
                          .values_list("created_at", flat=True).first())
            qs = model_cls.objects.exclude(cost_usd=0).order_by("created_at")
            if live_start:
                qs = qs.filter(created_at__lt=live_start)

            emitted, usd, skipped_ref = 0, 0.0, 0
            group = []  # sibling rows of one call

            def usage_of(row):
                return (float(row.cost_usd),
                        int(getattr(row, tin, 0) or 0) if tin else 0,
                        int(getattr(row, tout, 0) or 0) if tout else 0,
                        getattr(row, "model_used", "")
                        or getattr(row, "model", "") or "")

            def flush():
                nonlocal emitted, usd
                if not group:
                    return
                head = group[0]
                marker = (f"ledger-backfill:{model_cls.__name__}:{head.pk}")
                if marker in markers:
                    group.clear()
                    return
                cost, itok, otok, used_model = usage_of(head)
                covers = (f" (one call, {len(group)} persisted rows)"
                          if len(group) > 1 else "")
                # create + created_at rewrite as ONE unit: an interrupted
                # run must roll the create back, or the historical dollar
                # books itself on the backfill day forever.
                with transaction.atomic():
                    task = AgentTask.objects.create(
                        agent=agent_name[:30],
                        provider="claude",
                        model=(used_model or "unknown")[:50],
                        prompt_summary=(f"backfilled from "
                                        f"{model_cls.__name__} "
                                        f"#{head.pk}{covers}"),
                        input_tokens=itok,
                        output_tokens=otok,
                        cost_usd=head.cost_usd,
                        response_summary=marker,
                        success=True,
                    )
                    AgentTask.objects.filter(pk=task.pk).update(
                        created_at=head.created_at)
                markers.add(marker)
                emitted += 1
                usd += cost
                group.clear()

            for row in qs.iterator():
                ref = f"{model_cls.__name__}:{row.pk}"
                if ref in referenced:
                    skipped_ref += 1
                    continue
                if group:
                    same_call = (
                        usage_of(row) == usage_of(group[0])
                        and (row.created_at - group[0].created_at)
                        <= timedelta(seconds=GROUP_WINDOW_SECONDS))
                    if not same_call:
                        flush()
                group.append(row)
            flush()

            note = (f", {skipped_ref} already ledgered live"
                    if skipped_ref else "")
            self.stdout.write(
                f"  {model_cls.__name__:24s} -> {emitted} call(s), "
                f"${usd:.4f}{note}")
            total_rows += emitted
            total_usd += usd

        self.stdout.write(self.style.SUCCESS(
            f"Backfilled {total_rows} ledger row(s), ${total_usd:.4f} of "
            f"previously invisible spend. Re-running is safe: rows are "
            f"marked and skipped."))

    @staticmethod
    def _cost_model(module):
        """The module's one Django model carrying a cost_usd column."""
        from django.db import models as djm
        for name in dir(module):
            obj = getattr(module, name)
            if (isinstance(obj, type) and issubclass(obj, djm.Model)
                    and not obj._meta.abstract
                    and obj.__module__ == module.__name__
                    and any(f.name == "cost_usd"
                            for f in obj._meta.get_fields()
                            if hasattr(f, "name"))):
                return obj
        return None

    @staticmethod
    def _field(model_cls, candidates):
        names = {f.name for f in model_cls._meta.get_fields()
                 if hasattr(f, "name")}
        for c in candidates:
            if c in names:
                return c
        return None
