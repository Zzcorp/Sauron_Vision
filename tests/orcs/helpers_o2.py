"""THE O2 HARNESS (spec N7, §1.1.7; 2026-11-05). Every O2 test runs the
REAL provider on a fake client, reaches no network, and proves AFTER the
code has run what the Orc code would have swallowed (every Orc step is
fenced by `except Exception`: observe.py, wake.py's render pass).

- `FakeClient`: the client every ClaudeProvider() is given. It answers
  from a script (an answer, an error before the stream, or an error event
  in the middle of it) on both stream paths (client.messages and
  client.beta.messages), records every messages request with its
  traceback.extract_stack() in a list the test owns, and every
  count_tokens request in a second list.
- `fake_answer()`: one scripted answer.
- `MindTestMixin`, through `MindTestCase(TestCase)` or
  `MindTransactionTestCase(TransactionTestCase)`: the no-network guard
  (socket.connect, requests, the anthropic client's constructor), the
  behavioural guard (no binding Orc column, no OrcSeat level, status or
  pinned, no trade-row column and no metadata key but "orc" changed by the
  Orcs' code) and the stack proof (every request was sent from inside
  mind_gateway.call, after a can_spend(line="orcs", total_only=False) that
  answered allowed in the same call).
- `minds_on()`: the four gates of A.2 ON and the Orcs line set.
- The K-B10 fixture figures, and the walk that finds none of them in any
  text block of any recorded request.

A zero-call claim is a pair inside one test method (P37):
`assert_one_call` first, on the fixture with every gate ON, then only the
gate under test flipped and `assert_no_call`. `assert_no_call` refuses to
run before its positive control; tests/orcs/test_orc_o2a_meta.py (T16)
proves the same of the source.
"""
import copy
import itertools
import json
import os
import re
import socket
import sys
import traceback
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase

# ── the K-B10 figures (spec N6) ───────────────────────────────────────────
#: The fixture's distinctive FAKE account figures: a balance, an Orc's
#: r_money and a quantity. No request may carry any of them, in any
#: format (raw, grouped or rounded), matched by value.
KB10_BALANCE = Decimal("123456.78")
KB10_R_MONEY = Decimal("987.65")
KB10_QTY = Decimal("4321")
KB10_FIGURES = (KB10_BALANCE, KB10_R_MONEY, KB10_QTY)

#: What minds_on() sets: the Orcs line of O2a's first week and the total
#: raised with it (spec §4 Q3), written whole, never this process's env.
MINDS_LINE_USD = 6.0
MINDS_TOTAL_USD = 24.0
#: The rows minds_on() turns ON beside the line (A.2's four gates).
MIND_GATES = ("platform_master", "orcs", "orcs_minds")

#: The one function every Orc request leaves through (A.22).
GATEWAY_PATH = "bot_program/orcs/mind_gateway.py"
GATEWAY_FUNC = "call"
#: The Orcs' own code: a write is theirs when one of its frames is here.
ORCS_CODE = ("/bot_program/orcs/", "/bot_program/management/commands/orcs.py")

#: N1.5's binding columns, which no Orc code ever changes.
ORC_BINDING = ("stop_level", "stop_why", "stop_at", "trail_owner",
               "lock_waiver", "be_swap_floor", "captain_may_cut",
               "commission", "stood_down", "hand_hold_until",
               "last_step_tick")
SEAT_BINDING = ("level", "status", "pinned")
#: The one trade-row metadata key the Orcs write (O1a's stamp).
STAMP_KEY = "orc"

#: One sequence for the requests and the spend checks, so "before the
#: send" is an order, not a guess.
_SEQ = itertools.count(1)


def _posix(path):
    return str(path or "").replace(os.sep, "/")


def is_gateway_frame(filename, name) -> bool:
    return _posix(filename).endswith(GATEWAY_PATH) and name == GATEWAY_FUNC


def _gateway_frame():
    """The live frame of the mind_gateway.call that is running, or None."""
    f = sys._getframe(1)
    while f is not None:
        if is_gateway_frame(f.f_code.co_filename, f.f_code.co_name):
            return f
        f = f.f_back
    return None


def by_the_orcs(stack=None) -> str:
    """The first frame of the Orcs' own code in `stack` (now when None),
    as "file:line in function"; "" when no frame is theirs."""
    for fr in stack if stack is not None else traceback.extract_stack():
        name = _posix(fr.filename)
        if any(part in name for part in ORCS_CODE):
            where = name.split("/bot_program/", 1)[-1]
            return f"{where}:{fr.lineno} in {fr.name}"
    return ""


# ── the scripted answers ──────────────────────────────────────────────────

def fake_usage(input_tokens=1200, output_tokens=300, *, cache_read=0,
               cache_write_1h=0, cache_write_5m=0):
    """A usage as the SDK reports it: an absent cache field is None."""
    writes = cache_write_1h + cache_write_5m
    return SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_input_tokens=cache_read or None,
        cache_creation_input_tokens=writes or None,
        cache_creation=SimpleNamespace(
            ephemeral_5m_input_tokens=cache_write_5m,
            ephemeral_1h_input_tokens=cache_write_1h) if writes else None)


def fake_answer(answer=None, *, text=None, usage=None, stop_reason="end_turn",
                model=None):
    """One scripted answer. A dict `answer` is sent as its JSON text (the
    answer an Orc's schema asks for); `text` as it is; neither: an empty
    hold. The usage is fake_usage() unless given."""
    if text is None:
        text = json.dumps(answer if answer is not None
                          else {"action": "hold"}, sort_keys=True)
    content = [SimpleNamespace(type="text", text=text)] if text else []
    return SimpleNamespace(content=content, stop_reason=stop_reason,
                           stop_details=None, usage=usage or fake_usage(),
                           model=model or "fake-model", id="msg_fake")


class PreStream:
    """A scripted error raised when the request is sent, before anything
    streams (a connection error, a 4xx, a timeout)."""

    def __init__(self, exc):
        self.exc = exc


class MidStream:
    """A scripted error EVENT in the middle of a stream: raised while the
    final message is read, after the request was sent."""

    def __init__(self, exc):
        self.exc = exc


def mid_stream_error(kind="overloaded_error", message="Overloaded"):
    """The SDK's own error for an error event mid-stream: an
    APIStatusError whose text is the event's payload, which is what the
    provider reads (claude_provider.py's _TRANSIENT_MARKERS). Built on a
    fake response: nothing is sent."""
    import anthropic
    payload = {"type": "error", "error": {"details": None, "type": kind,
                                          "message": message}}
    response = SimpleNamespace(status_code=200, headers={}, request=None)
    return MidStream(anthropic.APIStatusError(str(payload), response=response,
                                              body=payload))


class Sent:
    """One recorded messages request: its path ("plain" or "beta"), its
    keywords as sent, its stack, its place in the sequence, and the live
    mind_gateway.call frame it was sent from (None: not from the
    gateway)."""

    def __init__(self, path, kwargs, stack, seq, gateway):
        self.path, self.kwargs, self.stack = path, kwargs, stack
        self.seq, self.gateway = seq, gateway

    def texts(self):
        return list(_texts(self.kwargs))


def _texts(kwargs):
    """Every text the request carries: the system prompt or blocks, and
    every message's content, string or blocks."""
    system = kwargs.get("system")
    if isinstance(system, str):
        yield system
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                yield block["text"]
    for msg in kwargs.get("messages") or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            yield content
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                yield block["text"]


class _Stream:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        if self.error is not None:
            raise self.error
        return self.response


class _Messages:
    def __init__(self, client, path):
        self._client, self._path = client, path

    def stream(self, **kwargs):
        return self._client._send(self._path, kwargs)

    def count_tokens(self, **kwargs):
        return self._client._count(kwargs)


class FakeClient:
    """The fake client: scripted outcomes, recorded requests. `requests`
    and `count_requests` are lists the test owns (the mixin passes its
    own). A script of one item answers every request; an empty one
    answers fake_answer()."""

    def __init__(self, *script, requests=None, count_requests=None,
                 count_answer=2000):
        self.script = list(script)
        self.requests = [] if requests is None else requests
        self.count_requests = [] if count_requests is None else count_requests
        self.count_answer = count_answer
        #: the requests already accounted for by a positive control
        self.mark = 0
        self.messages = _Messages(self, "plain")
        self.beta = SimpleNamespace(messages=_Messages(self, "beta"))

    def answer(self, *items):
        """Append outcomes to the script."""
        self.script.extend(items)
        return self

    def _next(self):
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0] if self.script else fake_answer()

    def _send(self, path, kwargs):
        self.requests.append(Sent(path, copy.deepcopy(kwargs),
                                  traceback.extract_stack()[:-2], next(_SEQ),
                                  _gateway_frame()))
        item = self._next()
        if isinstance(item, PreStream):
            raise item.exc
        if isinstance(item, MidStream):
            return _Stream(error=item.exc)
        return _Stream(response=item)

    def _count(self, kwargs):
        self.count_requests.append(Sent("count", copy.deepcopy(kwargs),
                                        traceback.extract_stack()[:-2],
                                        next(_SEQ), _gateway_frame()))
        return SimpleNamespace(input_tokens=self.count_answer)


# ── the spend spy and the stack proof ────────────────────────────────────

class SpendCall:
    def __init__(self, seq, kwargs, result, gateway):
        self.seq, self.kwargs, self.result = seq, kwargs, result
        self.gateway = gateway

    @property
    def orcs_allowed(self) -> bool:
        return (self.kwargs.get("line") == "orcs"
                and self.kwargs.get("total_only", False) is False
                and isinstance(self.result, tuple) and bool(self.result)
                and self.result[0] is True)


def stack_proof_errors(requests, spend_calls) -> list:
    """N7's stack proof, one line per request that fails it: the request
    was not sent from inside mind_gateway.call, or no
    can_spend(line="orcs", total_only=False) answered allowed inside that
    same call before the send."""
    errors = []
    for n, req in enumerate(requests, 1):
        if not any(is_gateway_frame(f.filename, f.name) for f in req.stack) \
                or req.gateway is None:
            errors.append(f"request {n} was not sent through "
                          f"mind_gateway.call ({req.path} path)")
            continue
        asked = [c for c in spend_calls
                 if c.seq < req.seq and c.gateway is req.gateway]
        if not any(c.orcs_allowed for c in asked):
            errors.append(f"request {n}: no can_spend(line='orcs', "
                          f"total_only=False) answered allowed inside the "
                          f"same mind_gateway.call before the send "
                          f"({len(asked)} asked)")
    return errors


# ── the behavioural guard ────────────────────────────────────────────────

_MISSING = object()


def _unstamped(meta):
    """A trade row's metadata less the Orcs' own stamp."""
    if not isinstance(meta, dict):
        return meta
    return {k: v for k, v in meta.items() if k != STAMP_KEY}


class WriteGuard:
    """What the Orcs' code changed on an Orc, an OrcSeat or a trade row
    (N1.5, N7). A write counts when one frame of its stack is the Orcs'
    own code: the test's fixtures and the care's own writes are not the
    Orcs'. Saves are compared with the values the instance was loaded or
    last saved with (no query of its own, so a test's query counts do not
    move); QuerySet.update and bulk_update by their fields."""

    def __init__(self):
        import threading
        self.violations = []
        self._uid = f"o2guard-{id(self)}"
        self._patches = []
        #: inside bulk_update: its own update() is not counted twice
        self._local = threading.local()

    # which fields are guarded on which model
    @staticmethod
    def _models():
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc, OrcSeat
        return Orc, OrcSeat, AssetBotTrade

    def _guarded(self, model):
        Orc, OrcSeat, AssetBotTrade = self._models()
        if isinstance(model, type) and issubclass(model, Orc):
            return ORC_BINDING
        if model is OrcSeat:
            return SEAT_BINDING
        if model is AssetBotTrade:
            return tuple(f.name for f in AssetBotTrade._meta.concrete_fields
                         if not f.primary_key)
        return ()

    def _attname(self, model, name):
        try:
            return model._meta.get_field(name).attname
        except Exception:  # noqa: BLE001
            return name

    def _snapshot(self, instance):
        model = type(instance)
        snap = {}
        for name in self._guarded(model):
            att = self._attname(model, name)
            if att in instance.__dict__:
                snap[att] = copy.deepcopy(instance.__dict__[att])
        instance.__dict__["_o2_guard"] = snap

    @staticmethod
    def _same(field, a, b) -> bool:
        if field is not None and field.get_internal_type() == "JSONField":
            return json.dumps(a, sort_keys=True, default=str) == \
                json.dumps(b, sort_keys=True, default=str)
        try:
            if field is not None:
                return field.to_python(a) == field.to_python(b)
        except Exception:  # noqa: BLE001 — fall back to plain equality
            pass
        return a == b

    def _changes(self, instance, fields=None):
        """The guarded fields `instance` would change, by name."""
        model = type(instance)
        before = instance.__dict__.get("_o2_guard")
        if not isinstance(before, dict):
            return []
        out = []
        for name in self._guarded(model):
            if fields is not None and name not in fields and \
                    self._attname(model, name) not in fields:
                continue
            att = self._attname(model, name)
            old = before.get(att, _MISSING)
            new = instance.__dict__.get(att, _MISSING)
            if old is _MISSING or new is _MISSING:
                continue
            field = model._meta.get_field(name)
            if name == "metadata":
                old, new = _unstamped(old), _unstamped(new)
            if not self._same(field, old, new):
                out.append(name)
        return out

    def _record(self, model, pk, names, how):
        who = by_the_orcs()
        if not who or not names:
            return
        for name in names:
            what = ("a metadata key other than \"orc\"" if name == "metadata"
                    else name)
            self.violations.append(f"{model.__name__} #{pk}: {what} changed "
                                   f"by the Orcs ({how}, {who})")

    # signal receivers
    def _post_init(self, sender, instance, **kwargs):
        self._snapshot(instance)

    def _pre_save(self, sender, instance, raw=False, update_fields=None,
                  **kwargs):
        if raw or instance._state.adding:
            return
        fields = set(update_fields) if update_fields is not None else None
        self._record(sender, instance.pk, self._changes(instance, fields),
                     "save")

    def _post_save(self, sender, instance, raw=False, **kwargs):
        self._snapshot(instance)

    def install(self):
        from django.db.models import Model
        from django.db.models.query import QuerySet
        from django.db.models.signals import post_init, post_save, pre_save
        guard = self
        for model in self._models():
            post_init.connect(self._post_init, sender=model, weak=False,
                              dispatch_uid=(self._uid, model, "init"))
            pre_save.connect(self._pre_save, sender=model, weak=False,
                             dispatch_uid=(self._uid, model, "pre"))
            post_save.connect(self._post_save, sender=model, weak=False,
                              dispatch_uid=(self._uid, model, "post"))
        real_update = QuerySet.update
        real_bulk = QuerySet.bulk_update
        real_refresh = Model.refresh_from_db

        def update(qs, **kwargs):
            names = guard._guarded(qs.model)
            hit = [k for k in kwargs if k in names
                   or any(guard._attname(qs.model, n) == k for n in names)]
            if hit and not getattr(guard._local, "bulk", 0):
                guard._record(qs.model, "(queryset)", hit, "update()")
            return real_update(qs, **kwargs)

        def bulk_update(qs, objs, fields, *args, **kwargs):
            objs = list(objs)
            if guard._guarded(qs.model):
                for obj in objs:
                    guard._record(qs.model, obj.pk,
                                  guard._changes(obj, set(fields)),
                                  "bulk_update()")
            guard._local.bulk = getattr(guard._local, "bulk", 0) + 1
            try:
                out = real_bulk(qs, objs, fields, *args, **kwargs)
            finally:
                guard._local.bulk -= 1
            for obj in objs:
                if guard._guarded(type(obj)):
                    guard._snapshot(obj)
            return out

        def refresh_from_db(obj, *args, **kwargs):
            out = real_refresh(obj, *args, **kwargs)
            if guard._guarded(type(obj)):
                guard._snapshot(obj)
            return out

        self._patches = [patch.object(QuerySet, "update", update),
                         patch.object(QuerySet, "bulk_update", bulk_update),
                         patch.object(Model, "refresh_from_db",
                                      refresh_from_db)]
        for p in self._patches:
            p.start()

    def uninstall(self):
        from django.db.models.signals import post_init, post_save, pre_save
        for p in reversed(self._patches):
            p.stop()
        self._patches = []
        for model in self._models():
            post_init.disconnect(sender=model,
                                 dispatch_uid=(self._uid, model, "init"))
            pre_save.disconnect(sender=model,
                                dispatch_uid=(self._uid, model, "pre"))
            post_save.disconnect(sender=model,
                                 dispatch_uid=(self._uid, model, "post"))


# ── the gates ─────────────────────────────────────────────────────────────

def minds_on(test=None, *, line_usd=MINDS_LINE_USD, total_usd=MINDS_TOTAL_USD):
    """The four gates of A.2 ON: the platform master, `orcs` and
    `orcs_minds` rows ON, and the Orcs line set through
    AI_CONFIG["orc_daily_budget_usd"] with the total written whole beside
    it (the pattern of tests/test_claude_provider_keywords.py's _budget).
    Returns the settings override; with `test`, it is entered for the rest
    of that test."""
    from django.conf import settings
    from django.test import override_settings

    from tests.test_aragorn import _switch
    for key in MIND_GATES:
        _switch(key, True)
    override = override_settings(AI_CONFIG={
        **settings.AI_CONFIG, "daily_budget_usd": total_usd,
        "orc_daily_budget_usd": line_usd})
    if test is not None:
        test.enterContext(override)
    return override


def kb10_marks():
    from dashboard.plain_words import money_marks
    return money_marks([float(x) for x in KB10_FIGURES])


#: A dossier bar row's own clock label, "MMDD HHMM", "MMDD" or "HHMM" at the
#: head of a row of signed deltas (bot_program/orcs/dossier_instrument.py
#: _rows and the tape): strftime's, never an amount. A label such as
#: "1000" (10:00) or "1001" (1 October) sits within money_marks' 3% of the
#: fixture's 987.65, so the walk reads every row with its label blanked
#: (2026-11-05, O2a's first dossier sent: tests/orcs/test_orc_o2a_call.py).
BAR_LABEL = re.compile(r'(?<=")\d{4}(?: \d{4})?(?= [-+]\d)')


def _unlabelled(text) -> str:
    return BAR_LABEL.sub(lambda m: "#" * len(m.group(0)), str(text or ""))


def kb10_hits(requests) -> list:
    """(request number, text excerpt) for every text block that carries a
    K-B10 figure, matched by value (plain_words.money_marks), a bar row's
    clock label aside (BAR_LABEL)."""
    marks = kb10_marks()
    out = []
    for n, req in enumerate(requests, 1):
        for text in req.texts():
            text = _unlabelled(text)
            m = marks.search(text)
            if m:
                lo = max(0, m.start() - 20)
                out.append((n, text[lo:m.end() + 20]))
    return out


# ── the mixin ─────────────────────────────────────────────────────────────

class MindTestMixin:
    """N7 for every O2 test class, installed around the class's own setUp
    and tearDown (unittest's _callSetUp and _callTearDown), so a setUp
    that never calls super() still runs under it:

    - no network: socket.connect and connect_ex, requests.Session.request,
      requests.get and requests.post, and the anthropic client's
      constructor raise;
    - the fake: every ClaudeProvider() is given `self.fake`, which records
      into `self.requests` and `self.count_requests`; `self.spend_calls`
      records every spend.can_spend;
    - after the test's own tearDown: the behavioural guard and the stack
      proof (`mind_problems`). The patches and the guard come off in the
      cleanups, whatever happened.
    """

    def _callSetUp(self):
        self.requests, self.count_requests, self.spend_calls = [], [], []
        self.fake = FakeClient(requests=self.requests,
                               count_requests=self.count_requests)
        self._one_call_proven = False
        self.mind_guard = WriteGuard()
        self._mind_patches = []
        self.addCleanup(self._mind_stop)
        self._start_mind_patches()
        self.mind_guard.install()
        super()._callSetUp()

    def _callTearDown(self):
        super()._callTearDown()
        problems = self.mind_problems()
        if problems:
            self.fail("N7: " + "; ".join(problems))

    def mind_problems(self) -> list:
        """What the behavioural guard and the stack proof found so far."""
        return (list(self.mind_guard.violations)
                + stack_proof_errors(self.requests, self.spend_calls))

    def _mind_stop(self):
        try:
            self.mind_guard.uninstall()
        finally:
            self._stop_mind_patches()
            for item in (list(self.requests) + list(self.count_requests)
                         + list(self.spend_calls)):
                item.gateway = None

    def use_fake(self, *script):
        """A fresh script on the test's fake (its lists stay the test's)."""
        self.fake.script = list(script)
        return self.fake

    def _start_mind_patches(self):
        import anthropic
        import requests

        from ai_agents import spend
        from ai_agents.providers.claude_provider import ClaudeProvider
        test = self

        def refuse(*args, **kwargs):
            raise AssertionError("N7: an O2 test reached the network")

        real_init = ClaudeProvider.__init__

        def provider_init(provider, *args, **kwargs):
            real_init(provider, *args, **kwargs)
            provider.client = test.fake

        real_can_spend = spend.can_spend

        def can_spend_spy(*args, **kwargs):
            gateway = _gateway_frame()
            result = real_can_spend(*args, **kwargs)
            test.spend_calls.append(SpendCall(next(_SEQ), dict(kwargs),
                                              result, gateway))
            return result

        patches = [
            patch.object(socket.socket, "connect", refuse),
            patch.object(socket.socket, "connect_ex", refuse),
            patch.object(requests.Session, "request", refuse),
            patch("requests.get", refuse),
            patch("requests.post", refuse),
            patch.object(anthropic.Anthropic, "__init__", refuse),
            patch.object(ClaudeProvider, "__init__", provider_init),
            patch.object(spend, "can_spend", can_spend_spy),
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
        ]
        for p in patches:
            p.start()
            self._mind_patches.append(p)

    def _stop_mind_patches(self):
        for p in reversed(getattr(self, "_mind_patches", [])):
            p.stop()
        self._mind_patches = []

    # the pair (P37)
    def assert_one_call(self, fake=None):
        """The positive control: exactly one messages request since the
        last control. Marks the list, so the zero-call half that follows
        counts from here."""
        fake = fake or self.fake
        self.assertEqual(len(fake.requests) - fake.mark, 1,
                         "the positive control records exactly one request")
        fake.mark = len(fake.requests)
        self._one_call_proven = True

    def assert_no_call(self, fake=None, *, code=None, got=None):
        """The zero-call half: no messages request since the positive
        control, and the gate's own code when one is named."""
        fake = fake or self.fake
        if not self._one_call_proven:
            self.fail("a zero-call claim needs its positive control first, "
                      "in the same test (N7, P37)")
        self.assertEqual(len(fake.requests) - fake.mark, 0,
                         "no request may be sent with the gate closed")
        if code is not None:
            self.assertEqual(got, code, "the gate's own code")

    def assert_no_account_figure(self, requests=None):
        """K-B10 (N6): no text block of any recorded request, messages or
        count, carries a fixture figure in any format."""
        reqs = (list(self.requests) + list(self.count_requests)
                if requests is None else list(requests))
        self.assertEqual(kb10_hits(reqs), [],
                         "an account figure reached a request")


class MindTestCase(MindTestMixin, TestCase):
    """An O2 test class on Django's TestCase (N7)."""


class MindTransactionTestCase(MindTestMixin, TransactionTestCase):
    """An O2 test class on Django's TransactionTestCase (N7): the lock and
    concurrency proofs, PostgreSQL only."""
