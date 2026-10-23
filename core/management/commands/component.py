"""Turn platform components on and off from the shell.

The health page has a toggle per component; this is the same write,
reachable without the page. It names the state before and after, refuses
a key it does not know (and suggests the nearest), and registers a
component that exists in the code but not yet in the database before
setting it — so "run seed_components first" is never the answer.

    python manage.py component list
    python manage.py component list --category agent
    python manage.py component on generator_auto_research
    python manage.py component off actuator_mode_live scraper_etoro

Turning `platform_master` off stops every automated task; the command
says so when it does it.

A live-money switch (core.platform_control.LIVE_MONEY_SWITCHES) is
never turned ON from here (2026-10-23, core/switch_pin.py): turning one
on takes the trading PIN, and this command neither prompts for one nor
accepts one on its command line, where it would sit in the shell
history. It refuses before any write, even when other keys in the same
list could be set, and names /ops/, where the toggle takes the PIN.
Turning one OFF stays free here, as everywhere.
"""
import difflib

from django.core.management.base import BaseCommand, CommandError

MASTER = "platform_master"


class Command(BaseCommand):
    help = "List, enable or disable platform components (same write as /health/)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "on", "off"])
        parser.add_argument("keys", nargs="*", help="Component keys for on/off.")
        parser.add_argument("--category", default="",
                            help="list: only this category.")

    def handle(self, *args, **opts):
        action = opts["action"]
        if action == "list":
            return self._list(opts["category"])
        keys = opts["keys"]
        if not keys:
            raise CommandError(f"component {action}: give at least one key "
                               f"(see `component list`).")
        self._set(keys, enabled=(action == "on"))

    # ── list ────────────────────────────────────────────────────────────
    def _list(self, category):
        from core.platform_control import PlatformComponent
        rows = PlatformComponent.objects.all().order_by("category", "key")
        if category:
            rows = rows.filter(category=category)
        rows = list(rows)
        if not rows:
            self.stdout.write("no components registered — run seed_components")
            return
        current = None
        for c in rows:
            if c.category != current:
                current = c.category
                self.stdout.write(f"\n[{current}]")
            state = "ON " if c.is_enabled else "OFF"
            self.stdout.write(f"  {state}  {c.key:<34} {c.name}")
        n_on = sum(1 for c in rows if c.is_enabled)
        self.stdout.write(f"\n{n_on} on, {len(rows) - n_on} off, {len(rows)} total")

    # ── on / off ────────────────────────────────────────────────────────
    def _set(self, keys, *, enabled):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           PlatformComponent,
                                           is_component_enabled,
                                           seed_components)
        from core.switch_pin import (VIA_SHELL, needs_pin, refusal_sentence,
                                     refuse_here, set_switch)
        # A live-money switch is not turned ON from the shell: checked for
        # every key before any write, and before the registering below, so
        # a refused list changes nothing at all.
        blocked = [k for k in dict.fromkeys(keys)
                   if needs_pin(k, was_on=is_component_enabled(k),
                                want_on=enabled)]
        if blocked:
            for key in blocked:
                refuse_here(key, via=VIA_SHELL)
            raise CommandError(refusal_sentence(blocked, via=VIA_SHELL))
        known = {c["key"] for c in DEFAULT_COMPONENTS}
        registered = set(PlatformComponent.objects.values_list("key", flat=True))
        # A key the code knows but the database does not: register first.
        missing = [k for k in keys if k in known and k not in registered]
        if missing:
            n = seed_components()
            self.stdout.write(f"registered {n} new component(s) first "
                              f"(seed_components)")
        for key in keys:
            row = PlatformComponent.objects.filter(key=key).first()
            if row is None:
                pool = sorted(known | registered)
                near = difflib.get_close_matches(key, pool, n=3, cutoff=0.5)
                hint = f" — did you mean: {', '.join(near)}?" if near else ""
                raise CommandError(f"unknown component {key!r}{hint}")
            # THE WRITE (core.switch_pin.set_switch), with its updated_at
            # stamp: the instant of the flip, which the alarm bot reads
            # off platform_master to tell a pause from a stop.
            result = set_switch(key, enabled, via=VIA_SHELL)
            if not result.ok:
                raise CommandError(result.message)
            before = "ON" if result.before else "OFF"
            after = "ON" if result.after else "OFF"
            self.stdout.write(f"{key}: {before} → {after}"
                              + ("" if before != after else " (unchanged)"))
            if key == MASTER and not enabled:
                self.stdout.write(self.style.WARNING(
                    "platform_master is OFF: every automated task is stopped."))
