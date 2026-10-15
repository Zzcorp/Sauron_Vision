"""The Lore from the shell: import, export, check, show.

    python manage.py lore import [PATH] [--dry-run] [--only a,b] [--force-slug a]
    python manage.py lore export [PATH]
    python manage.py lore check [PATH] [--refs] [--search "q"]
    python manage.py lore show AGENT [--query Q] [--regime R] [--classes a,b]
                                     [--viewer USERNAME] [--full]

The import reads private/lore/ (or LORE_DIR): every row lands as a draft,
a refused row is said with its code, and the exit status is non-zero when
anything was refused. It stays OUT of the migrate chain on purpose: a
refused row needs a person to read why.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import, export, check or show the Lore (Sauron's library)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["import", "export", "check",
                                               "show"])
        parser.add_argument("target", nargs="?", default="",
                            help="import/export/check: a path; show: the agent")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--only", default="", help="slugs, comma separated")
        parser.add_argument("--force-slug", action="append", default=[],
                            help="replace this slug even if edited here")
        parser.add_argument("--refs", action="store_true",
                            help="check: report code-reference drift")
        parser.add_argument("--search", default="",
                            help="check: time one sample search")
        parser.add_argument("--query", default="")
        parser.add_argument("--regime", default="")
        parser.add_argument("--classes", default="")
        parser.add_argument("--viewer", default="",
                            help="show: a username to read as")
        parser.add_argument("--full", action="store_true",
                            help="show: the page form of each entry")

    def handle(self, *args, **opts):
        action = opts["action"]
        return getattr(self, f"_{action}")(opts)

    # ── import ───────────────────────────────────────────────────────────
    def _path(self, target: str) -> Path:
        return Path(target) if target else Path(settings.LORE_DIR)

    def _import(self, opts):
        from lore.importer import import_path
        path = self._path(opts["target"])
        if not path.exists():
            self.stdout.write(f"No catalogue at {path}. Put the files in "
                              f"private/lore/ or set LORE_DIR.")
            return
        only = [s.strip() for s in opts["only"].split(",") if s.strip()]
        report = import_path(path, dry_run=opts["dry_run"], only=only,
                             force_slugs=opts["force_slug"])
        for line in report.lines():
            self.stdout.write(line)
        if report.n_refused:
            raise CommandError(f"{report.n_refused} entries were refused; "
                               f"the others were imported.")

    # ── export ───────────────────────────────────────────────────────────
    def _export(self, opts):
        from lore.importer import export_all
        rows = export_all()
        if opts["target"]:
            path = Path(opts["target"])
        else:
            path = Path(settings.LORE_DIR) / f"export-{date.today():%Y%m%d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=1, ensure_ascii=False),
                        encoding="utf-8")
        self.stdout.write(f"Wrote {len(rows)} entries to {path}.")

    # ── check ────────────────────────────────────────────────────────────
    def _check(self, opts):
        from lore import curate
        from lore.importer import apply_overlay, read_catalogue
        from lore.models import LoreEntry
        from lore.validate import check, code_ref_exists
        if opts["target"]:
            entries, overlay = read_catalogue(self._path(opts["target"]))
            dicts = [apply_overlay(e, overlay) for e in entries]
            mode = "import"
        else:
            dicts = []
            for e in LoreEntry.objects.all().order_by("slug"):
                d = curate.export_dict(e)
                d["origin"] = e.origin
                dicts.append(d)
            mode = "review"
        n_problems = 0
        n_bad = 0
        for d in dicts:
            errors, warnings = check(d, mode=mode)
            rows = list(errors) + list(warnings)
            if opts["refs"]:
                for x in d.get("sauron_code") or []:
                    ref = x.get("ref", "") if isinstance(x, dict) else ""
                    if ref and not code_ref_exists(ref):
                        rows.append(("W02", f"Code reference {ref} does not "
                                            f"exist in this tree."))
            if rows:
                n_bad += 1
                n_problems += len(rows)
                for code, msg in rows:
                    self.stdout.write(f"  {d.get('slug', '?')}: {code} {msg}")
        if n_problems:
            self.stdout.write(f"{n_problems} problems in {n_bad} entries.")
        else:
            self.stdout.write(f"All {len(dicts)} entries pass.")
        if opts["search"]:
            from lore.search import search
            t0 = time.perf_counter()
            result = search(opts["search"], statuses=("draft", "reviewed"))
            ms = (time.perf_counter() - t0) * 1000
            self.stdout.write(f"Search on this database: simple matcher, "
                              f"{ms:.1f} ms ({result.n_matched} matched).")

    # ── show ─────────────────────────────────────────────────────────────
    def _show(self, opts):
        from lore.policy import POLICY
        from lore.read import block_for, payload_for
        from lore.render import render_card
        agent = opts["target"]
        if agent not in POLICY:
            self.stdout.write(f"Agent {agent or '(none)'} is not cleared to "
                              f"read the library.")
            return
        viewer = None
        if opts["viewer"]:
            from django.contrib.auth import get_user_model
            viewer = get_user_model().objects.filter(
                username=opts["viewer"]).first()
        classes = tuple(c.strip() for c in opts["classes"].split(",")
                        if c.strip())
        regimes = (opts["regime"],) if opts["regime"] else ()
        block = block_for(agent, query=opts["query"], classes=classes,
                          regimes=regimes, regime_now=opts["regime"],
                          viewer=viewer, ledger=False)
        if not block.text:
            self.stdout.write(f"Empty block: {block.reason}.")
            return
        self.stdout.write(f"Block: {block.n_shown} entries ({block.n_full} "
                          f"cards, {block.n_shown - block.n_full} short), "
                          f"about {block.tokens_est} tokens of a "
                          f"{block.cap_tokens} cap.")
        if opts["full"]:
            from lore.models import LoreEntry
            for slug in block.slugs:
                e = LoreEntry.objects.filter(slug=slug).first()
                if e is not None:
                    self.stdout.write(render_card(payload_for(e),
                                                  regime_now=opts["regime"]))
        else:
            self.stdout.write(block.text)
