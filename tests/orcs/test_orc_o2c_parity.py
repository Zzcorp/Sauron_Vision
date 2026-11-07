"""THE O2c PARITY PROOF: TODAY'S WAKES, CALLS, SPEND AND PAGES ARE MAIN'S
(the O2 spec §1.3 under N1-N8; 2026-11-07).

Orc Minds (`orcs_minds`) is ON at the operator's site since 2026-11-07,
the Orcs line at up to $6 a day. O2c must not change what an ON minds
switch does or costs while O2c's own switches are OFF (the spec's §0 N2
table: orcs_temperaments, orcs_captains, orcs_emperor, orcs_skeptic and
orcs_drum_wakes). This module is that proof. It was written first and run
green on main as it stood at 227e03b, before any O2c change, which wrote
its golden (o2c_parity_golden.json beside it): so it pins main's
behaviour, not O2c's description of it.

THE WORLD. T12's (tests/orcs/test_orc_o2a_e2e._E2E on MindFixture's NOW, a
Thursday), with django.utils.timezone.now patched to the run's own clock
for the whole run, so a weekday and a weekend give one answer: the four
gates ON (the platform master, `orcs`, `orcs_minds`; the Orcs line $6, the
total $24); `orcs_drums` ON, as it may already be at the site; the
router's, the probes' and the frontier's switches OFF; every O2c switch
absent or OFF, asserted through core.platform_control.is_component_enabled.

WHAT IT LIVES, once for a real-money bot row and once for a paper row:
the birth; a third Orc on the same symbol closed by its stop (its
stop_hit drum) and a level_break wave, both routed by drum_bus.route; the
tick that records the wake; wake.render_queued; scheduler.claim and
mind.think on the fake model (a tighten to a level of the wake's own
menu), and the settle; the next tick (intents.take: the O arm in would
mode); the beats as the site runs them (orc_day_roll, orc_hourly,
orc_session_close, orc_render_wakes, orc_think, orc_minds_watch,
track_ghosts, grade_closed); the pages; the close (lifecycle's own
on-commit step, as the receiver queues it) and the grade.

THE TRANSCRIPT, normalized, in six sections:
  a  render: every stored dossier block (MK0, the sessions, the MK-E dash
     and its key, IN-slow, PS with its PS9-PS11 dashes, the tail, S) by
     kind, key and text; each wake's components less its timings (the
     facts hash among them);
  b  calls: every recorded request as sent (the system, shared and
     private blocks, the schema, the efforts, max_tokens and the
     timeout), its model named by its rung;
  c  spend: each ledger row (agent, source_ref, tokens, cost);
     spent_today("orcs"); each Orc's four day counters; the holds;
  d  wakes and journal: every OrcWake (status, code, reasons, priority,
     rung...); every OrcJournal entry (kind, author, headline, body, fact
     id, facts hash, its card flag); every OrcIntent, wave_id included;
     every arm's state, the O arm's among them; the drums and their
     reach; each Orc's memory, card and minds' columns; what each beat
     returned;
  e  pages: GET /orcs/<id>/ and /orcs/ as the owner, then as staff (the
     page's own content, from its orc-page block to the end of the main
     element); notes.slot; notes.for_classes; the Horde board's class
     bands (and each seat's Orc box); surfaces.orc_reply for "/orc N";
  f  the grade: every OrcGrade's columns, its tags, fell and sub_label,
     and its journal entry's body.

THE NORMALIZER. Every table's primary keys start, for each test, at a
fixed band of its own (PK_FLOOR + its index x PK_BAND, set in the
database's own sequences), so each pk the fixture made is a nine-digit
number the normalizer replaces, wherever it stands (a column, a JSON
value, a source_ref, a URL, a headline), by an ordinal placeholder
<app.model#n>; and every text that names one has the same length whatever
ran before in the same database. Ticket keys read "t#", a ladder model id
its rung, a stored block's hash its ordinal; csrf tokens, auto_now stamps
and measured latencies are dropped; floats are rounded to 8 places.

THE GOLDEN (o2c_parity_golden.json):
- Never edited by hand.
- Never regenerated, except after a merge of main into an O2c branch, and
  then only on that merged main WITHOUT O2c: a scratch worktree of
  origin/main, where a scratch subclass of the test class replaces
  `compare` with a dump of the transcript (json.dumps(sort_keys=True,
  indent=1, ensure_ascii=True), its two worlds under their names; a few
  characters may be written as \\u escapes, the same text once loaded).
- This module only reads and compares it; it never writes a file.

A DELIBERATE O2c DIFFERENCE is a named WHITELIST entry below, with its
spec id, its path in the transcript and the value O2c leaves there. None
is taken in this commit. The one planned: C.10's class band sentence (the
fourth O2c commit).

N7: the fake model only (MindTestCase), no network; one positive control
(`assert_one_call`) per answered wake before the closing `assert_no_call`;
the K-B10 walk on every request.

Run with:  python manage.py test tests.orcs.test_orc_o2c_parity
"""
import json
import math
import re
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from tests.orcs.helpers import _config, _row, born
from tests.orcs.helpers_o2 import fake_answer
from tests.orcs.test_orc_o2a_call import NOW, answer
from tests.orcs.test_orc_o2a_e2e import _E2E

GOLDEN = Path(__file__).with_name("o2c_parity_golden.json")
WORLDS = ("real", "paper")

#: O2c's switches (the O2 spec §0 N2 table): absent or OFF throughout.
O2C_SWITCHES = ("orcs_temperaments", "orcs_captains", "orcs_emperor",
                "orcs_skeptic", "orcs_drum_wakes")
#: O2b's switches: OFF, as they ship.
O2B_SWITCHES = ("orcs_router", "orcs_probes", "orcs_frontier")
#: O1's drums switch: ON, as it may already be at the site (C.14).
DRUMS_SWITCH = "orcs_drums"

#: A deliberate O2c difference: (world or "*", path in the transcript) ->
#: (its spec id, the value O2c leaves at that path). The golden's value at
#: the path is replaced by it before the comparison; nothing else moves.
#: Planned: C.10's class band sentence (the fourth O2c commit).
WHITELIST = {}

#: The beats, in the order the site's schedule may run them in one pass.
BEATS = ("orc_day_roll", "orc_hourly", "orc_session_close",
         "orc_render_wakes", "orc_think", "orc_minds_watch", "track_ghosts",
         "grade_closed")
#: The 4h bar the level_break wave closes on.
BAR_END = datetime(2026, 10, 22, 12, 0, tzinfo=dt_tz.utc)

#: Each table's primary keys start at PK_FLOOR + its index x PK_BAND.
PK_FLOOR = 900_000_000
PK_BAND = 100_000
PK_RE = re.compile(r"(?<!\d)(9\d{8})(?!\d)")
TICKET_RE = re.compile(r"\bt[0-9a-f]{16}\b")
HASH_RE = re.compile(r"\b[0-9a-f]{64}\b")
CSRF_RE = re.compile(r'<input[^>]*name="csrfmiddlewaretoken"[^>]*>')
#: The keys a run measures with a real clock (mind_gateway's latency).
TIMING_KEYS = frozenset({"latency"})
#: Where a page's own content starts, and where it ends.
PAGE_START = '<div class="orc-page">'
PAGE_END = "</main>"


class _Clock:
    """The run's one clock: django.utils.timezone.now reads it."""

    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


def _tables():
    """Every table with an integer key the database numbers itself, in a
    fixed order: (model, db_table)."""
    from django.apps import apps
    from django.db import models
    autos = (models.AutoField, models.BigAutoField, models.SmallAutoField)
    out = {}
    for m in apps.get_models(include_auto_created=True):
        if m._meta.managed and not m._meta.proxy and isinstance(
                m._meta.pk, autos):
            out.setdefault(m._meta.db_table, m)
    return [(out[t], t) for t in sorted(out)]


def shift_sequences():
    """Every table's next key at its band (PK_FLOOR + index x PK_BAND + 1),
    in the database's own sequences. Returns {band index: model label}."""
    from django.db import connection
    bands = {}
    with connection.cursor() as c:
        for i, (model, table) in enumerate(_tables()):
            base = PK_FLOOR + i * PK_BAND
            bands[i] = model._meta.label_lower
            if connection.vendor == "sqlite":
                c.execute("SELECT 1 FROM sqlite_sequence WHERE name = %s",
                          [table])
                if c.fetchone() is None:
                    c.execute("INSERT INTO sqlite_sequence (name, seq) "
                              "VALUES (%s, %s)", [table, base])
                else:
                    c.execute("UPDATE sqlite_sequence SET seq = %s "
                              "WHERE name = %s", [base, table])
            elif connection.vendor == "postgresql":
                c.execute("SELECT setval(pg_get_serial_sequence(%s, %s), "
                          "%s, false)", [table, model._meta.pk.column,
                                         base + 1])
            else:  # pragma: no cover — the suite runs SQLite or PostgreSQL
                raise NotImplementedError(connection.vendor)
    return bands


def issued() -> dict:
    """{band index: the highest ordinal its table's sequence issued}, read
    from the database's own sequences, so only a key the run made is ever
    replaced (a nine-digit run inside a hash is not one)."""
    from django.db import connection
    out = {}
    with connection.cursor() as c:
        for i, (model, table) in enumerate(_tables()):
            if connection.vendor == "sqlite":
                c.execute("SELECT seq FROM sqlite_sequence WHERE name = %s",
                          [table])
            else:
                c.execute("SELECT pg_sequence_last_value("
                          "pg_get_serial_sequence(%s, %s))",
                          [table, model._meta.pk.column])
            row = c.fetchone()
            last = int(row[0]) if row and row[0] is not None else 0
            out[i] = max(0, last - (PK_FLOOR + i * PK_BAND))
    return out


class Normalizer:
    """The transcript's one normalizer (the module's docstring)."""

    def __init__(self, bands, block_hashes=(), issued=None):
        from ai_agents.catalog import ORC_FALLBACK_V1, ORC_LADDER_V1
        self.bands = dict(bands)
        self.issued = dict(issued or {})
        rungs = {}
        for step in ORC_LADDER_V1:
            rungs.setdefault(step["model"], step["rung"])
        rungs.setdefault(ORC_FALLBACK_V1, "fallback")
        #: longest first, so a model id is never cut by one it starts with
        self.models = sorted(rungs.items(), key=lambda kv: -len(kv[0]))
        self.blocks = {h: n for n, h in enumerate(block_hashes, 1)}

    def pk(self, value):
        """The placeholder of a primary key its band's sequence issued, or
        None."""
        n = int(value) - PK_FLOOR
        if n < 0:
            return None
        band, ordinal = divmod(n, PK_BAND)
        label = self.bands.get(band)
        if label is None or not 0 < ordinal <= self.issued.get(band, 0):
            return None
        return f"<{label}#{ordinal}>"

    def text(self, s):
        s = CSRF_RE.sub("", str(s))
        for model, rung in self.models:
            s = s.replace(model, f"<rung {rung}>")
        s = TICKET_RE.sub("t#", s)
        s = HASH_RE.sub(lambda m: (f"<block#{self.blocks[m.group(0)]}>"
                                   if m.group(0) in self.blocks
                                   else m.group(0)), s)
        return PK_RE.sub(lambda m: self.pk(m.group(1)) or m.group(1), s)

    def __call__(self, value, *, drop=TIMING_KEYS):
        if isinstance(value, dict):
            return {self.text(k): self(v, drop=drop)
                    for k, v in value.items() if k not in drop}
        if isinstance(value, (list, tuple, set, frozenset)):
            items = [self(v, drop=drop) for v in value]
            return sorted(items, key=json.dumps) if isinstance(
                value, (set, frozenset)) else items
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int):
            return self.pk(value) or value
        if isinstance(value, Decimal):
            value = float(value)
        if isinstance(value, float):
            if not math.isfinite(value):
                return str(value)
            return round(value, 8)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return self.text(value)


def _row_of(obj, *, skip=()):
    """Every concrete column of `obj` but its key, the auto_now stamps and
    `skip`, by name (a relation by its id)."""
    out = {}
    for f in obj._meta.concrete_fields:
        if f.primary_key or f.name in skip or getattr(f, "auto_now", False) \
                or getattr(f, "auto_now_add", False):
            continue
        out[f.name] = getattr(obj, f.attname)
    return out


def _page(html):
    """A page's own content: from its orc-page block to the end of the main
    element, the site's chrome around it left out."""
    start = html.find(PAGE_START)
    end = html.find(PAGE_END, start)
    if start < 0 or end < 0:
        return html
    return html[start:end]


def _golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _at(tree, path):
    for key in path:
        tree = tree[key]
    return tree


def _put(tree, path, value):
    _at(tree, path[:-1])[path[-1]] = value


def _whitelisted(want, world):
    """The golden with each WHITELIST entry of `world` applied."""
    for (where, path), (_spec, value) in WHITELIST.items():
        if where in ("*", world):
            _put(want, tuple(path), value)
    return want


def _diff(want, got, path=(), out=None, limit=40):
    """The differing paths, each with what main wrote and what ran, long
    texts as a unified diff of their lines."""
    import difflib
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(want, dict) and isinstance(got, dict):
        for k in sorted(set(want) | set(got), key=str):
            if k not in want or k not in got:
                out.append(f"{'/'.join(map(str, path + (k,)))}: "
                           f"{'only after O2c' if k not in want else 'gone'}"
                           f" ({json.dumps(got.get(k, want.get(k)))[:200]})")
            else:
                _diff(want[k], got[k], path + (k,), out, limit)
        return out
    if isinstance(want, list) and isinstance(got, list):
        if len(want) != len(got):
            out.append(f"{'/'.join(map(str, path))}: {len(want)} items on "
                       f"main, {len(got)} now")
        for i, (a, b) in enumerate(zip(want, got)):
            _diff(a, b, path + (i,), out, limit)
        return out
    if want != got:
        where = "/".join(map(str, path))
        if isinstance(want, str) and isinstance(got, str) and (
                "\n" in want or len(want) > 200):
            lines = list(difflib.unified_diff(
                want.splitlines(), got.splitlines(), "main", "now",
                lineterm="", n=1))
            out.append(f"{where}:\n" + "\n".join(lines[:60]))
        else:
            out.append(f"{where}: main {json.dumps(want)[:300]}, now "
                       f"{json.dumps(got)[:300]}")
    return out


class O2cParityTests(_E2E):
    """The two worlds, each lived whole and compared with main's."""

    def setUp(self):
        from django.core.cache import cache

        from bot_program.orcs import dossier, journal, tasks
        # what an earlier test of this process left behind is not this
        # run's: the cache (the gap memos, the bands) and the token factors
        cache.clear()
        dossier._FACTORS.update({"at": None, "value": {}})
        self.bands = shift_sequences()
        self.clock = _Clock(NOW)
        # each journal entry's card flag, as its writer passed it; each
        # orc_think ticket a render pass sends (a Celery message, never a
        # model call), at the clock's moment
        self.cards, self.tickets = {}, []
        real_append = journal.append

        def append(*args, **kwargs):
            entry = real_append(*args, **kwargs)
            self.cards[entry.pk] = bool(kwargs.get("card", True))
            return entry
        for p in (patch("django.utils.timezone.now", new=self.clock),
                  patch.object(journal, "append", append),
                  patch.object(tasks.orc_think, "delay",
                               side_effect=lambda *a, **k: self.tickets
                               .append(self.clock.at.isoformat()))):
            p.start()
            self.addCleanup(p.stop)
        super().setUp()
        from core.platform_control import is_component_enabled

        from tests.test_aragorn import _switch
        _switch(DRUMS_SWITCH, True)
        for key in O2B_SWITCHES:
            _switch(key, False)
        for key in O2C_SWITCHES:
            self.assertFalse(is_component_enabled(key),
                             f"{key} is absent or OFF in this world")
        for key in ("platform_master", "orcs", "orcs_minds", DRUMS_SWITCH):
            self.assertTrue(is_component_enabled(key), key)

    # ── the worlds ───────────────────────────────────────────────────────

    def test_a_real_money_bot_row(self):
        """The real-money bot row's life, every wake, call, cost and page
        as main recorded them."""
        self.compare("real", self.lived("real"))

    def test_a_paper_row(self):
        """The paper row's life, every wake, call, cost and page as main
        recorded them."""
        self.compare("paper", self.lived("paper"))

    def test_the_golden_is_mains_normalized(self):
        """The golden holds the two worlds, normalized: a model's rung,
        never its id (model ids live in ai_agents/catalog.py alone)."""
        self.assertEqual(set(_golden()), set(WORLDS))
        self.assertNotIn("claude-", GOLDEN.read_text(encoding="utf-8"))

    def compare(self, world, got):
        """`got` against main's golden for `world`, the WHITELIST applied."""
        want = _whitelisted(_golden()[world], world)
        problems = _diff(want, got)
        if problems:
            self.fail(f"the {world} world differs from main's in "
                      f"{len(problems)} place(s) (40 at most listed):\n"
                      + "\n".join(problems))

    # ── one life ─────────────────────────────────────────────────────────

    def lived(self, world):
        """The world lived whole; its transcript, normalized."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import drum_bus, lifecycle, mind, scheduler, wake
        from bot_program.orcs.models import OrcTrack
        run = {"world": world}
        # 1. the birth
        self.clock.at = NOW
        cfg, row, orc = self.world(world, f5=False)
        # 2. a third Orc on the same symbol, closed by its stop, and a
        # level_break wave; both routed within the user's book
        third_cfg = _config(self.user, name="parity_third")
        third_row = _row(third_cfg, symbol=self.symbol)
        born(self, third_row, at=NOW - timedelta(hours=2))
        AssetBotTrade.objects.filter(pk=third_row.pk).update(
            status="CLOSED", outcome="stopped_out", reason="closed:SL",
            exit_price=third_row.stop_loss,
            closed_at=NOW - timedelta(minutes=3))
        lifecycle._closed_quietly(third_row.pk)
        with patch.object(drum_bus, "_level_breaks", return_value={
                (self.user.pk, "crypto", BAR_END): [self.symbol]}), \
                patch.object(drum_bus, "_sweeps", return_value=[]):
            run["published"] = drum_bus.hourly_market(NOW)
        run["delivered"] = drum_bus.route(NOW)
        # 3. the tick that records the wake
        self.tick(cfg, row, NOW)
        # 4. the render pass: merge, render, admit
        out = wake.render_queued()
        run["render"] = [list(out), out.admitted]
        # 5. the claim, the fake model's tighten, the settle
        got = scheduler.claim(now=NOW)
        w = got["wake"]
        self.assertIsNotNone(w, "the birth wake is pending")
        self.use_fake(fake_answer(answer(
            action="tighten", level_id=self.tighten_of(w),
            facts_cited=self.cites(orc),
            note="Tightening under the swing.")))
        settled = mind.think(w, now=NOW)
        self.assert_one_call()
        self.assertEqual(settled["status"], "done")
        run["settled"] = settled
        # 6. the next tick: the queued intent into the O arm only
        self.use_fake(fake_answer(answer()))
        self.clock.at = NOW + timedelta(minutes=5)
        self.tick(cfg, row, self.clock.at)
        # 7. the beats, as the site runs them
        self.clock.at = NOW + timedelta(minutes=10)
        run["beats"] = self.beats(BEATS)
        # 8. the pages, while the idea lives
        pages = self.pages(row)
        # 9. the close (the receiver's own on-commit step) and the grade
        later = NOW + timedelta(hours=1)
        self.clock.at = later
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CLOSED", outcome="hit_target", reason="closed:TP",
            exit_price=Decimal("100.5"), closed_at=later)
        lifecycle._closed_quietly(row.pk)
        for t in OrcTrack.objects.filter(orc=orc):
            OrcTrack.objects.filter(pk=t.pk).update(
                open=False, exit_r=t.exit_r if not t.open else 0.25,
                exit_price=t.exit_price or Decimal("100.5"),
                exit_at=t.exit_at or later, exit_why=t.exit_why or "parity")
        self.clock.at = later + timedelta(minutes=10)
        run["closing_beats"] = self.beats(("track_ghosts", "grade_closed"))
        # 10. the owner's pages once the idea is graded
        pages["graded"] = self.pages(row, ("owner",), surfaces=False)
        self.assert_no_call()
        self.assert_no_account_figure()
        return self.transcript(run, pages)

    def beats(self, names) -> dict:
        """Each beat run once, at the clock's moment; a beat that read a
        wake on the fake model holds its positive control."""
        from bot_program.orcs import tasks
        from bot_program.orcs.constants import MODEL_ANSWERED
        from bot_program.orcs.models import OrcWake
        out = {}
        for name in names:
            before = len(self.requests)
            answered = OrcWake.objects.filter(
                status__in=MODEL_ANSWERED).count()
            out[name] = getattr(tasks, name)()
            more = OrcWake.objects.filter(
                status__in=MODEL_ANSWERED).count() - answered
            self.assertEqual(len(self.requests) - before, more,
                             f"{name}: one request per wake it answered")
            if more:
                self.assertEqual(more, 1, f"{name}: one wake read a beat")
                self.assert_one_call()
        out["tickets"] = list(self.tickets)
        return out

    def pages(self, row, viewers=("owner", "staff"), *, surfaces=True):
        """What the pages show of the idea, GET as each viewer (the owner,
        then the owner as staff, who also sees the AI spend); with
        `surfaces`, the slot, the class band, the Horde board's bands and
        the /orc reply."""
        from django.urls import reverse
        out = {}
        for viewer in viewers:
            type(self.user).objects.filter(pk=self.user.pk).update(
                is_staff=viewer == "staff")
            self.user.refresh_from_db()
            self.client.force_login(self.user)
            for name, url in (
                    ("orc", reverse("orc_detail", args=[row.pk])),
                    ("orcs", reverse("orcs_list"))):
                resp = self.client.get(url)
                out[f"{viewer}:{name}"] = {
                    "status": resp.status_code,
                    "html": _page(resp.content.decode("utf-8"))}
        type(self.user).objects.filter(pk=self.user.pk).update(is_staff=False)
        self.user.refresh_from_db()
        if surfaces:
            out.update(self.surfaces(row))
        return out

    def surfaces(self, row) -> dict:
        from bot_program.orcs import notes, surfaces
        from bot_program.orcs.constants import ARM_CARE, ARM_ORC
        from bot_program.orcs.models import Orc, OrcTrack
        from bot_program.orcs.switches import minds_on
        from dashboard import horde
        out = {}
        orc = Orc.objects.select_related("seat", "root_trade", "grade").get(
            root_trade=row)
        pair = list(OrcTrack.objects.filter(orc=orc,
                                            arm__in=(ARM_CARE, ARM_ORC)))
        now = self.clock.at
        out["slot"] = notes.slot(orc, trade=orc.root_trade, tracks=pair,
                                 now=now, minds=minds_on())
        out["for_classes"] = notes.for_classes(self.user, [orc.asset_class],
                                               now=now)
        board = horde.board(self.user, now=now)
        out["board"] = [
            {**{k: v for k, v in g.items() if k != "seats"},
             "seats": [{"key": s.get("key"), "orc": s.get("orc")}
                       for s in g.get("seats") or ()]}
            for g in board.get("groups") or ()]
        reply = surfaces.orc_reply(self.user, str(row.pk), now=now)
        out["orc_reply"] = {k: getattr(reply, k)
                            for k in ("mark", "title", "lines", "body",
                                      "meta")}
        return out

    # ── the transcript ───────────────────────────────────────────────────

    def transcript(self, run, pages) -> dict:
        from ai_agents import spend
        from ai_agents.models import AgentTask

        from bot_program.orcs import mind_gateway
        from bot_program.orcs.models import (Orc, OrcDossierBlock, OrcDrum,
                                             OrcGrade, OrcIntent, OrcJournal,
                                             OrcTrack, OrcWake)
        blocks = list(OrcDossierBlock.objects.order_by("pk"))
        norm = Normalizer(self.bands, [b.hash for b in blocks], issued())
        orcs = list(Orc.objects.order_by("pk"))
        a = {"blocks": [{"kind": b.kind, "key": b.key, "model": b.model,
                         "tokens_est": b.tokens_est, "text": b.text,
                         "body": b.body, "built_at": b.built_at}
                        for b in blocks],
             "wakes": [{"wake": w.pk, "components": w.components,
                        "block_hashes": w.block_hashes, "score": w.score,
                        "band": w.band, "day_class": w.day_class}
                       for w in OrcWake.objects.order_by("pk")]}
        b = {"requests": [{"path": r.path, "kwargs": r.kwargs}
                          for r in self.requests],
             "count_requests": [{"kwargs": r.kwargs}
                                for r in self.count_requests]}
        c = {"ledger": [_row_of(t, skip=("duration_seconds",))
                        for t in AgentTask.objects.order_by("pk")],
             "spent_today_orcs": spend.spent_today("orcs"),
             "counters": [{"orc": o.pk,
                           "llm_wakes_today": o.llm_wakes_today,
                           "routine_wakes_today": o.routine_wakes_today,
                           "spend_today_usd": o.spend_today_usd,
                           "routine_spend_today_usd":
                               o.routine_spend_today_usd} for o in orcs],
             "holds": mind_gateway.holds(self.clock.at)}
        d = {"wakes": [_row_of(w, skip=("components", "block_hashes"))
                       for w in OrcWake.objects.order_by("pk")],
             "journal": [{**_row_of(e), "card": self.cards.get(e.pk)}
                         for e in OrcJournal.objects.order_by("pk")],
             "intents": [_row_of(i) for i in OrcIntent.objects.order_by("pk")],
             "tracks": [_row_of(t) for t in OrcTrack.objects.order_by("pk")],
             "drums": [_row_of(x) for x in OrcDrum.objects.order_by("pk")],
             "orcs": [{"orc": o.pk, "root_trade": o.root_trade_id,
                       "state": o.state, "seen": o.seen, "card": o.card,
                       "plan": o.plan, "plan_version": o.plan_version,
                       "watches": o.watches, "latest_note": o.latest_note,
                       "latest_note_at": o.latest_note_at,
                       "last_wake_at": o.last_wake_at,
                       "last_good_wake_at": o.last_good_wake_at,
                       "next_wake_due": o.next_wake_due,
                       "last_facts_hash": o.last_facts_hash,
                       "care_owned_reason": o.care_owned_reason,
                       "died_at": o.died_at} for o in orcs],
             "run": run}
        f = {"grades": [_row_of(g) for g in OrcGrade.objects.order_by("pk")],
             "grade_bodies": [e.body for e in OrcJournal.objects.filter(
                 kind="grade").order_by("pk")]}
        out = {"a_render": a, "b_calls": b, "c_spend": c,
               "d_wakes_and_journal": d, "e_pages": pages, "f_grade": f}
        return json.loads(json.dumps(norm(out), sort_keys=True))
