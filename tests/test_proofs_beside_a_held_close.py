"""THE DEMO SHORT PROOFS DO NOT WAIT ON A CLOSE eTORO ALREADY HOLDS
(2026-11-02).

The demo short proofs (bot_program/short_proofs.py) hold every step while
a real close is pending ("a real position's close is pending: closes go
first", short_proofs.refusing): one key's quota serves both of eToro's
worlds, and it is kept for the closes the retry task still has to SEND. A
close eToro took and queued at a shut market leaves its row CLOSE_PENDING
with close_order_working, and the retry task only READS that row from then
on: eToro cannot withdraw a close order (EtoroTrader.CANCELS_CLOSE_ORDERS),
so no pass reaches the cancel and the resend
(pending_closes.retry_trade_close). It stays so when the queued close is
cancelled in the eToro app. The runner waited on such a row for good.

Pinned here (pending_closes.close_held_at_venue and
pending_closes.blocked_behind_held_close, read by short_proofs):

  * a close eToro already holds no longer holds the runner, on the run and
    on the dry run, in either of eToro's worlds and whatever world the
    account trades now;
  * nor does a row the retry task holds back behind it (2026-11-02,
    review): a second real row on the same symbol whose own close eToro
    does not hold, which the retry task reads every pass and sends nothing
    for while the held close stands (on its side the sibling block; on the
    other side, in the same world, the other-side block), once a pass of
    the retry task has sent nothing for it. It is waited on again the
    moment the held close is booked, and from its first resend;
  * a close the retry task may still send holds every step, as before: no
    close held, a working close on a venue that can withdraw it (cancel,
    then resend), one with no carrier recorded, one marked off, or the day
    eToro declares it can withdraw a close; an unreadable one holds too;
  * the predicates are the retry task's own: over the real router, adapter
    and retry task, a row they let go gets no order, close, cancel or move,
    pass after pass, and a held close one lookup read a pass while eToro
    answers; a row they keep is sent at the next pass, and a row held back
    once the held close is booked or, on the other side, at the pass that
    sees the held position gone;
  * the dry run and /short-proofs/ name each row not waited on, and why.

The runner's client is the real demo adapter over a fake wire
(tests.test_short_proofs); the retry task runs over a fake eToro
(tests.test_closes_never_abandoned), where no socket may open.
Illustrative numbers only.

Run with:  python manage.py test tests.test_proofs_beside_a_held_close
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from tests.test_closes_never_abandoned import BEAT_S, REFUSE
from tests.test_closes_never_abandoned import _Base as _RetryTaskBase
from tests.test_short_proofs import ROW_BTC, SUNDAY, _Wire, _demo, \
    _round_trip, _run
from tests.test_short_proofs import _Base as _ProofsBase

User = get_user_model()

CLOSES_FIRST = "a real position's close is pending: closes go first"
#: The marks a close eToro took and queued leaves on its row (a shut
#: market, AssetBot.venue_stamps and resolve_exit_fill): the carrier, its
#: world, the working close and the close order's id.
HELD = {"broker": "etoro", "broker_env": "live",
        "close_order_working": True, "close_working_order_id": "770000001"}
#: A row whose close the retry task still sends: eToro holds no close.
RETRIED = {"broker": "etoro", "broker_env": "live"}
WORDS = ("a close eToro already holds is not waited on: EURUSD (BUY); the "
         "retry task only reads it and sends nothing more for it")
LINE = WORDS[0].upper() + WORDS[1:] + "."
#: The marks a pass of the retry task that sent nothing leaves on its row
#: (pending_closes._note_close_blocked), here the sibling block's. The
#: words are not read; the stamp is.
BLOCKED = {"close_blocked_since": "2026-11-01T11:00:00+00:00",
           "close_blocked_at": "2026-11-01T11:55:00+00:00",
           "close_blocked_passes": 12,
           "close_blocked_why": "another live row of this user claims EURUSD "
                                "on the same side, so the 2000 in the book "
                                "cannot be attributed to this row"}
#: A row the retry task holds back behind a close eToro holds on its
#: symbol: eToro holds no close for it, and its last pass sent nothing.
BEHIND = dict(RETRIED, **BLOCKED)
#: A resend after that pass, refused (pending_closes._record_attempt).
RESENT = {"close_retry_attempts": 1,
          "close_retry_last_at": "2026-11-01T11:58:00+00:00",
          "close_retry_last_error": "CONSTRUCTED: refused"}
BOTH = WORDS + (". A close the retry task holds back behind one eToro "
                "holds on the same symbol is not waited on either: EURUSD "
                "(BUY); nothing is sent for it until that one is gone")
BOTH_LINE = BOTH[0].upper() + BOTH[1:] + "."
GOLD_HELD = ("a close eToro already holds is not waited on: XAUUSD (BUY); "
             "the retry task only reads it and sends nothing more for it")
GOLD_BEHIND = (". A close the retry task holds back behind one eToro holds "
               "on the same symbol is not waited on either: XAUUSD ({}); "
               "nothing is sent for it until that one is gone")


class _Proofs(_ProofsBase):
    """The runner's world (tests.test_short_proofs) beside a real lane's
    row, built with the marks the lanes and the retry task write."""

    def _row(self, *, symbol="EURUSD", side="BUY", status="CLOSE_PENDING",
             paper=False, asset_class="forex", user=None, **meta):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=user or self.user, asset_class=asset_class,
            name="held_close_live",
            defaults={"mode": "live", "symbols": [symbol],
                      "capital": Decimal("1000")})
        return AssetBotTrade.objects.create(
            config=cfg, asset_class=asset_class, symbol=symbol, side=side,
            qty=Decimal("1000"), entry_price=Decimal("1.1"), status=status,
            paper=paper, rule_name="r", metadata=dict(meta))

    def _clear(self):
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.all().delete()

    def _wire(self):
        return _Wire(rows=[ROW_BTC], lookups={7001: _round_trip()})

    def _dry(self):
        from bot_program import short_proofs
        return short_proofs.run_once(now=SUNDAY, dry_run=True)

    def _orders(self, wire):
        return [u for u in wire.urls("POST") if u.endswith("/orders")]


# ── the run and the dry run ──────────────────────────────────────────────

class ACloseEtoroHoldsDoesNotHoldTheRunnerTests(_Proofs):

    def test_on_the_run(self):
        row = self._row(**HELD)
        before = dict(row.metadata)
        wire = self._wire()
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "success", out)
        self.assertEqual(len(self._orders(wire)), 1)
        [proof] = self._rows()
        self.assertEqual((proof.asset_class, proof.proof_state,
                          proof.demo_proven), ("crypto", "proven", True))
        for url in wire.urls():
            if "/trading/" in url:
                self.assertIn("/demo/", url)
        # the real row stays the retry task's: the runner books nothing
        row.refresh_from_db()
        self.assertEqual((row.status, row.metadata),
                         ("CLOSE_PENDING", before))

    def test_on_the_dry_run(self):
        self._row(**HELD)
        out = self._dry()
        self.assertEqual(out.get("refusing"), "")
        self.assertEqual(out.get("not_waited_on"), WORDS)
        self.assertEqual(self._rows(), [])

    def test_in_either_world_and_whatever_world_the_account_trades(self):
        """A row of the other world: filled in eToro's demo world
        (broker_env "paper") while the account trades the real one, or a
        real one while the account now trades the demo world. eToro holds
        its close all the same, and the retry task sends nothing for it: in
        the account's own world it only reads it, in the other one
        broker_router.client_for_row hands it the simulator and the pass is
        noted blocked."""
        from bot_program.models import EtoroAccount
        # no subTest: the parallel runner cannot send back a failing one
        # from a case holding mocks
        for what, meta, demo in (
                ("filled in the demo world", dict(HELD, broker_env="paper"),
                 False),
                ("the account now trades the demo world", HELD, True),
                ("both", dict(HELD, broker_env="paper"), True)):
            self._clear()
            EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=demo)
            self._row(**meta)
            out = self._dry()
            self.assertEqual((out.get("refusing"), out.get("not_waited_on")),
                             ("", WORDS), what)


class ACloseStillToSendHoldsTheRunnerTests(_Proofs):

    def test_a_close_the_retry_task_may_still_send_holds_every_step(self):
        no_carrier = {k: v for k, v in HELD.items()
                      if k not in ("broker", "broker_env")}
        for what, meta in (
                ("no close held at eToro", RETRIED),
                ("a working close on a venue that can withdraw it",
                 dict(HELD, broker="saxo")),
                ("a working close with no carrier recorded", no_carrier),
                ("a working close marked off",
                 dict(HELD, close_order_working=False))):
            self._clear()
            self._row(**meta)
            wire = self._wire()
            out = _run(_demo(wire), SUNDAY)
            self.assertEqual((out["status"], out["reason"]),
                             ("skipped", CLOSES_FIRST), what)
            self.assertEqual(wire.calls, [], what)
            dry = self._dry()
            self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                             (CLOSES_FIRST, ""), what)

    def test_a_row_of_the_other_world_still_retried_holds_it_too(self):
        """No close held, in the demo world or while the account trades the
        other one: nothing is sent for it now, and it is sent the day the
        account trades its world again. Waited on, as before."""
        from bot_program.models import EtoroAccount
        for what, meta, demo in (
                ("filled in the demo world",
                 dict(RETRIED, broker_env="paper"), False),
                ("the account now trades the demo world", RETRIED, True)):
            self._clear()
            EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=demo)
            self._row(**meta)
            dry = self._dry()
            self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                             (CLOSES_FIRST, ""), what)

    def test_a_held_close_beside_one_still_retried_waits_on_that_one(self):
        self._row(**HELD)
        self._row(symbol="GBPUSD", side="SELL", **RETRIED)
        wire = self._wire()
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual((out["status"], out["reason"]),
                         ("skipped", CLOSES_FIRST))
        self.assertEqual(wire.calls, [])
        dry = self._dry()
        self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                         (CLOSES_FIRST, WORDS))

    def test_the_day_etoro_can_withdraw_a_close_its_rows_are_waited_on(self):
        """Declared by the venue, never tested by class: the retry task
        would then cancel and resend, so the runner waits again."""
        from bot_program.engine.etoro_client import EtoroTrader
        self._row(**HELD)
        with mock.patch.object(EtoroTrader, "CANCELS_CLOSE_ORDERS", True):
            dry = self._dry()
        self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                         (CLOSES_FIRST, ""))

    def test_an_unreadable_pending_close_holds_every_step(self):
        self._row(**HELD)
        with mock.patch("bot_program.pending_closes.close_held_at_venue",
                        side_effect=RuntimeError("unreadable")):
            dry = self._dry()
        self.assertEqual(dry.get("refusing"),
                         "the pending closes are unread (RuntimeError)")
        self.assertEqual(dry.get("not_waited_on"), "")

    def test_a_paper_row_is_neither_waited_on_nor_named(self):
        self._row(paper=True, **HELD)
        dry = self._dry()
        self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                         ("", ""))


# ── a row held back behind a held close (2026-11-02, review) ─────────────

class ARowHeldBackBehindAHeldCloseDoesNotHoldTheRunnerTests(_Proofs):
    """A second real row on the symbol of a close eToro holds, eToro
    holding no close for it: the retry task reads it every pass and sends
    nothing while the held close stands (broker_exposure: the sibling block
    on its side, the other-side block on the other)."""

    def test_on_the_run(self):
        from bot_program.pending_closes import blocked_behind_held_close
        held = self._row(**HELD)
        row = self._row(**BEHIND)
        self.assertTrue(blocked_behind_held_close(row))
        before = {r.pk: dict(r.metadata) for r in (held, row)}
        wire = self._wire()
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual(out["status"], "success", out)
        self.assertEqual(len(self._orders(wire)), 1)
        for url in wire.urls():
            if "/trading/" in url:
                self.assertIn("/demo/", url)
        # both real rows stay the retry task's: the runner books nothing
        for r in (held, row):
            r.refresh_from_db()
            self.assertEqual((r.status, r.metadata),
                             ("CLOSE_PENDING", before[r.pk]))

    def test_on_the_dry_run(self):
        self._row(**HELD)
        self._row(**BEHIND)
        out = self._dry()
        self.assertEqual((out.get("refusing"), out.get("not_waited_on")),
                         ("", BOTH))
        self.assertEqual(self._rows(), [])

    def test_on_its_side_in_either_world(self):
        """The sibling block reads Sauron's rows, not a book: a held close
        filled in eToro's demo world holds a real-world row back all the
        same; a row the account no longer trades the world of is handed
        the simulator, whose pass is blocked too, and is held back again
        by the sibling block once the account trades its world."""
        from bot_program.models import EtoroAccount
        from bot_program.pending_closes import blocked_behind_held_close
        for what, held, behind, demo in (
                ("the held close filled in the demo world",
                 dict(HELD, broker_env="paper"), BEHIND, False),
                ("the row filled in the demo world", HELD,
                 dict(BEHIND, broker_env="paper"), False),
                ("the account now trades the demo world", HELD, BEHIND,
                 True)):
            self._clear()
            EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=demo)
            self._row(**held)
            row = self._row(**behind)
            self.assertTrue(blocked_behind_held_close(row), what)
            out = self._dry()
            self.assertEqual((out.get("refusing"), out.get("not_waited_on")),
                             ("", BOTH), what)

    def test_on_the_other_side_in_the_same_world(self):
        """The other-side block: eToro lists the held position against it,
        in the world both rows were filled in."""
        from bot_program.pending_closes import blocked_behind_held_close
        for world in ("live", "paper"):
            self._clear()
            self._row(**dict(HELD, broker_env=world))
            row = self._row(side="SELL", **dict(BEHIND, broker_env=world))
            self.assertTrue(blocked_behind_held_close(row), world)
            out = self._dry()
            self.assertEqual(
                (out.get("refusing"), out.get("not_waited_on")),
                ("", BOTH.replace("EURUSD (BUY); nothing",
                                  "EURUSD (SELL); nothing")), world)

    def test_waited_on_again_the_moment_the_held_close_is_booked(self):
        """Read on every call: once the retry task books the held close,
        the row it held back is waited on again, before the pass that
        sends it."""
        from bot_program.models import AssetBotTrade
        from bot_program.pending_closes import blocked_behind_held_close
        held = self._row(**HELD)
        row = self._row(**BEHIND)
        self.assertEqual(self._dry().get("refusing"), "")
        AssetBotTrade.objects.filter(pk=held.pk).update(status="CLOSED")
        self.assertFalse(blocked_behind_held_close(row))
        dry = self._dry()
        self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                         (CLOSES_FIRST, ""))
        wire = self._wire()
        out = _run(_demo(wire), SUNDAY)
        self.assertEqual((out["status"], out["reason"]),
                         ("skipped", CLOSES_FIRST))
        self.assertEqual(wire.calls, [])

    def test_several_are_named_in_one_sentence(self):
        self._row(**HELD)
        self._row(**BEHIND)
        self._row(side="SELL", **BEHIND)
        self._row(symbol="GBPUSD", side="SELL", **HELD)
        self._row(symbol="GBPUSD", side="SELL", **BEHIND)
        self.assertEqual(
            self._dry().get("not_waited_on"),
            "a close eToro already holds is not waited on: EURUSD (BUY), "
            "GBPUSD (SELL); the retry task only reads them and sends "
            "nothing more for them. Closes the retry task holds back "
            "behind one eToro holds on the same symbol are not waited on "
            "either: EURUSD (BUY), EURUSD (SELL), GBPUSD (SELL); nothing is "
            "sent for them until that one is gone")


class ARowStillToSendBesideAHeldCloseHoldsTheRunnerTests(_Proofs):
    """Beside a close eToro holds, a row the retry task may still send for
    is waited on, as before."""

    def _waited(self, row, what, named=WORDS):
        from bot_program.pending_closes import blocked_behind_held_close
        self.assertFalse(blocked_behind_held_close(row), what)
        dry = self._dry()
        self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                         (CLOSES_FIRST, named), what)

    def test_before_the_retry_task_has_read_it_beside_the_held_close(self):
        """Its last pass must be one that sent nothing: a row whose close
        was just refused, beside a held close, is waited on until the
        retry task's first pass over it."""
        self._row(**HELD)
        self._waited(self._row(**RETRIED), "no pass yet")

    def test_from_its_first_resend_after_its_last_blocked_pass(self):
        """On the other side, the pass that sees the held position gone
        sends its close, even before the held row is booked: from that
        resend on it is waited on, whatever still stands beside it. An
        unreadable stamp is waited on too."""
        from bot_program.pending_closes import blocked_behind_held_close
        for what, meta, side in (
                ("a resend after the block", dict(BEHIND, **RESENT), "BUY"),
                ("on the other side", dict(BEHIND, **RESENT), "SELL"),
                ("an unreadable blocked stamp",
                 dict(BEHIND, close_blocked_at="not a time"), "BUY"),
                ("a blocked stamp with no zone",
                 dict(BEHIND, close_blocked_at="2026-11-01T11:55:00"),
                 "BUY"),
                ("an unreadable resend stamp",
                 dict(BEHIND, close_retry_last_at="not a time"), "BUY")):
            self._clear()
            self._row(**HELD)
            self._waited(self._row(side=side, **meta), what)
        # blocked again after that resend: held back again
        self._clear()
        self._row(**HELD)
        row = self._row(**dict(BEHIND, **RESENT,
                               close_blocked_at="2026-11-01T12:03:00+00:00"))
        self.assertTrue(blocked_behind_held_close(row))

    def test_on_the_other_side_in_the_other_world(self):
        """The other book does not list the held position: nothing holds
        it back there, and its close is sent once the account trades that
        world. A row that names no world is read in whichever the account
        trades."""
        no_world = {k: v for k, v in BEHIND.items() if k != "broker_env"}
        for what, held, behind in (
                ("the held close filled in the demo world",
                 dict(HELD, broker_env="paper"), BEHIND),
                ("the row filled in the demo world", HELD,
                 dict(BEHIND, broker_env="paper")),
                ("the row names no world", HELD, no_world)):
            self._clear()
            self._row(**held)
            self._waited(self._row(side="SELL", **behind), what)

    def test_when_nothing_beside_it_is_a_close_etoro_holds_for_its_book(self):
        """Held back only behind a close the retry task reads as its own
        sibling (the same user, symbol and asset class) and eToro holds,
        for a row eToro carries and the book nets."""
        other = User.objects.create_user("held_close_other", password="x")
        no_carrier = {k: v for k, v in BEHIND.items()
                      if k not in ("broker", "broker_env")}
        gbp = WORDS.replace("EURUSD", "GBPUSD")
        for what, held, behind, named in (
                ("another user's held close", dict(user=other, **HELD),
                 BEHIND, WORDS),
                ("a held close on another symbol",
                 dict(symbol="GBPUSD", **HELD), BEHIND, gbp),
                ("a held close in another asset class",
                 dict(asset_class="cfd", **HELD), BEHIND, WORDS),
                ("a held close whose entry still works",
                 dict(HELD, entry_working=True), BEHIND, WORDS),
                ("a paper row's close", dict(paper=True, **HELD), BEHIND,
                 ""),
                ("two rows blocking each other, no close held", BEHIND,
                 BEHIND, ""),
                ("a row with no carrier recorded", HELD, no_carrier, WORDS),
                ("a row of another carrier", HELD,
                 dict(BEHIND, broker="saxo"), WORDS),
                ("an options row", dict(asset_class="options", **HELD),
                 dict(asset_class="options", **BEHIND), WORDS)):
            self._clear()
            self._row(**held)
            self._waited(self._row(**behind), what, named)

    def test_the_day_etoro_can_withdraw_a_close_neither_is_let_go(self):
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.pending_closes import blocked_behind_held_close
        self._row(**HELD)
        row = self._row(**BEHIND)
        with mock.patch.object(EtoroTrader, "CANCELS_CLOSE_ORDERS", True):
            self.assertFalse(blocked_behind_held_close(row))
            dry = self._dry()
        self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                         (CLOSES_FIRST, ""))

    def test_an_unreadable_one_holds_every_step(self):
        self._row(**HELD)
        self._row(**BEHIND)
        wire = self._wire()
        with mock.patch("bot_program.pending_closes.blocked_behind_held_close",
                        side_effect=RuntimeError("unreadable")):
            dry = self._dry()
            out = _run(_demo(wire), SUNDAY)
        self.assertEqual(dry.get("refusing"),
                         "the pending closes are unread (RuntimeError)")
        self.assertEqual(dry.get("not_waited_on"), "")
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(wire.calls, [])

    def test_a_paper_row_beside_it_is_neither_waited_on_nor_named(self):
        from bot_program.pending_closes import blocked_behind_held_close
        self._row(**HELD)
        self.assertFalse(blocked_behind_held_close(
            self._row(paper=True, **BEHIND)))
        dry = self._dry()
        self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                         ("", WORDS))


# ── the words ────────────────────────────────────────────────────────────

class TheWordsTests(_Proofs):

    def test_the_dry_run_command_names_what_it_does_not_wait_on_and_why(self):
        self._row(**HELD)
        out = StringIO()
        with mock.patch("bot_program.short_proofs.demo_client") as build:
            call_command("short_proofs_demo", "--dry-run", stdout=out)
        build.assert_not_called()
        text = out.getvalue()
        self.assertIn(LINE, text)
        self.assertNotIn("Waiting on the live lane", text)
        self.assertEqual(self._rows(), [])
        # beside a close still retried it says both, the wait first
        self._row(symbol="GBPUSD", side="SELL", **RETRIED)
        out = StringIO()
        call_command("short_proofs_demo", "--dry-run", stdout=out)
        text = out.getvalue()
        wait = f"Waiting on the live lane: {CLOSES_FIRST}."
        self.assertIn(wait, text)
        self.assertIn(LINE, text)
        self.assertLess(text.index(wait), text.index(LINE))

    def test_the_dry_run_command_names_a_row_held_back_and_why(self):
        self._row(**HELD)
        self._row(**BEHIND)
        out = StringIO()
        with mock.patch("bot_program.short_proofs.demo_client") as build:
            call_command("short_proofs_demo", "--dry-run", stdout=out)
        build.assert_not_called()
        text = out.getvalue()
        self.assertIn(BOTH_LINE, text)
        self.assertNotIn("Waiting on the live lane", text)
        self.assertEqual(self._rows(), [])

    def test_several_held_closes_are_named_in_one_sentence(self):
        self._row(**HELD)
        self._row(symbol="GBPUSD", side="SELL", **HELD)
        self.assertEqual(
            self._dry().get("not_waited_on"),
            "a close eToro already holds is not waited on: EURUSD (BUY), "
            "GBPUSD (SELL); the retry task only reads them and sends "
            "nothing more for them")

    def test_the_page_names_it_too(self):
        admin = User.objects.create_superuser(
            "held_close_admin", "held_close_admin@example.test", "pw-test")
        self.client.force_login(admin)
        self._row(**HELD)
        body = self.client.get("/short-proofs/").content.decode()
        self.assertIn(LINE, body)
        self.assertNotIn("closes go first", body)
        self.assertIn("or while a real close the retry task may still send "
                      "is pending (a close eToro already holds is not "
                      "waited on, nor one the retry task holds back behind "
                      "it)", body)
        # and the wait, beside a close still retried
        self._row(symbol="GBPUSD", side="SELL", **RETRIED)
        body = self.client.get("/short-proofs/").content.decode()
        self.assertIn("closes go first", body)
        self.assertIn(LINE, body)

    def test_the_page_names_a_row_held_back_too(self):
        admin = User.objects.create_superuser(
            "held_back_admin", "held_back_admin@example.test", "pw-test")
        self.client.force_login(admin)
        self._row(**HELD)
        self._row(**BEHIND)
        body = self.client.get("/short-proofs/").content.decode()
        self.assertIn(BOTH_LINE, body)
        self.assertNotIn("closes go first", body)
        # and the wait, beside a close still retried
        self._row(symbol="GBPUSD", side="SELL", **RETRIED)
        body = self.client.get("/short-proofs/").content.decode()
        self.assertIn("closes go first", body)
        self.assertIn(BOTH_LINE, body)


# ── the predicate is the retry task's ────────────────────────────────────

class TheRetryTaskSendsNothingForWhatItLetsGoTests(_RetryTaskBase):
    """Over the real router, adapter and retry task on a fake eToro
    (tests.test_closes_never_abandoned): every pass of the retry task over
    a row the predicate lets go sends nothing; a row it keeps is sent."""

    username = "held_close_op"

    def _queued(self):
        cfg, row = self._gold_row()
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSE_PENDING")
        return cfg, row

    def _writes(self, since):
        return [c for c in self.wire.calls[since:] if c[0] != "GET"]

    def test_a_close_etoro_holds_is_only_read_one_lookup_a_pass(self):
        from bot_program.pending_closes import close_held_at_venue
        _cfg, row = self._queued()
        self.assertTrue(close_held_at_venue(row))
        n0 = len(self.wire.calls)
        self._passes(row, 24)                       # two hours of beats
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertEqual(self._writes(n0), [], "the retry task sent")
        reads = self.wire.calls[n0:]
        self.assertEqual(len(reads), 24, reads[:6])
        self.assertTrue(all("orders:lookup" in c[1] for c in reads))
        self.assertTrue(close_held_at_venue(row))

    def test_nor_when_its_order_read_does_not_answer(self):
        from bot_program.pending_closes import close_held_at_venue
        _cfg, row = self._queued()
        self.wire.fail_lookup = True
        n0 = len(self.wire.calls)
        self._passes(row, 12)
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertEqual(self._writes(n0), [])
        self.assertFalse(row.metadata.get("close_retry_attempts"))
        self.assertTrue(close_held_at_venue(row))

    def test_nor_on_a_lane_stood_down_or_an_account_of_the_other_world(self):
        from bot_program.models import EtoroAccount
        from bot_program.pending_closes import close_held_at_venue
        cfg, row = self._queued()
        n0 = len(self.wire.calls)
        self._stand_down(cfg)
        self._passes(row, 6)
        EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=True)
        self._passes(row, 6, start=timezone.now() + timedelta(hours=1))
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertEqual(self._writes(n0), [])
        self.assertTrue(close_held_at_venue(row))

    def test_a_close_it_keeps_is_sent_at_the_next_pass(self):
        """The control: eToro refused the close, so it holds none; the
        predicate keeps the row, and the retry task sends its close."""
        from bot_program.pending_closes import close_held_at_venue
        _cfg, row = self._gold_row()
        self.wire.close_plans = [REFUSE, "close"]
        self._close_now(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertFalse(close_held_at_venue(row))
        n0 = len(self._close_posts())
        self._passes(row, 3)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(len(self._close_posts()), n0 + 1)


class TheRetryTaskHoldsBackWhatTheRunnerLetsGoTests(_RetryTaskBase):
    """Over the real router, adapter and retry task on a fake eToro: a
    second gold row beside a close eToro holds, eToro refusing its own
    close once, gets no write pass after pass while the held close stands
    (2026-11-02, review); the runner lets it go from the retry task's first
    pass over it and waits on it again before its close is sent."""

    username = "held_back_op"

    def _queued(self, name="gold bot"):
        _cfg, row = self._gold_row(name=name)
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSE_PENDING")
        return row

    def _refused(self, name="gold bot two", *, sell=False):
        """The bot's own close of a second gold row, refused once: the row
        is CLOSE_PENDING and eToro holds no close for it. `sell` turns the
        row and its listed position to the other side first (eToro lists
        each position with its own side), built by hand."""
        from bot_program.models import AssetBotTrade
        _cfg, row = self._gold_row(name=name)
        if sell:
            pid = self._pid_of(row)
            AssetBotTrade.objects.filter(pk=row.pk).update(side="SELL")
            for p in self.wire.portfolio:
                if str(p.get("positionID")) == str(pid):
                    p["isBuy"] = False
            for o in self.wire.orders:
                if str(o["pid"]) == str(pid):
                    o["lookup"]["transaction"] = "sell"
                    o["lookup"]["asset"]["side"] = "short"
            row.refresh_from_db()
        self.wire.close_plans = [REFUSE]
        self._close_now(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertFalse((row.metadata or {}).get("close_order_working"))
        return row

    def _pid_of(self, row):
        return next(o["pid"] for o in self.wire.orders
                    if str(o["oid"]) == str(row.broker_order_id))

    def _writes(self, since):
        return [c for c in self.wire.calls[since:] if c[0] != "GET"]

    def _beats(self, row, n, t0):
        """`n` passes of the retry task: no write in any, and the row held
        back after each."""
        from bot_program.pending_closes import blocked_behind_held_close
        n0 = len(self.wire.calls)
        for i in range(n):
            self._drain_at(t0 + timedelta(seconds=BEAT_S * (i + 1)))
            row.refresh_from_db()
            self.assertEqual(self._writes(n0), [], f"pass {i + 1}")
            self.assertEqual(row.status, "CLOSE_PENDING", f"pass {i + 1}")
            self.assertTrue(blocked_behind_held_close(row), f"pass {i + 1}")

    def test_on_its_side_it_gets_no_write_while_the_held_close_stands(self):
        from bot_program import short_proofs
        from bot_program.pending_closes import (MAX_RETRY_ATTEMPTS,
                                                blocked_behind_held_close,
                                                close_held_at_venue)
        held = self._queued()
        row = self._refused()
        self.assertTrue(close_held_at_venue(held))
        self.assertFalse(close_held_at_venue(row))
        self.assertNotEqual(held.config_id, row.config_id)
        # not yet read beside it: waited on
        self.assertFalse(blocked_behind_held_close(row))
        self.assertEqual(short_proofs.refusing(), CLOSES_FIRST)
        self.wire.close_plans = ["close"]       # eToro would close it if asked
        self._beats(row, 3 * MAX_RETRY_ATTEMPTS, timezone.now())  # 3 hours
        held.refresh_from_db()
        self.assertEqual(held.status, "CLOSE_PENDING")
        self.assertFalse(row.metadata.get("close_retry_attempts"))
        self.assertIn("another live row of this user claims XAUUSD on the "
                      "same side", row.metadata.get("close_blocked_why"))
        self.assertEqual(short_proofs.refusing(), "")
        self.assertEqual(short_proofs.not_waited_on(),
                         GOLD_HELD + GOLD_BEHIND.format("BUY"))
        dry = short_proofs.run_once(dry_run=True)
        self.assertEqual((dry.get("refusing"), dry.get("not_waited_on")),
                         ("", GOLD_HELD + GOLD_BEHIND.format("BUY")))

    def test_waited_on_again_once_the_held_close_is_booked_then_sent(self):
        """eToro closes the held position (the operator, in the app). The
        retry task reads the newest row first (AssetBotTrade's ordering):
        this one, still held back by the sibling block, then the held one,
        booked. From then on the runner waits on it, and the next pass
        sends its close."""
        from bot_program import short_proofs
        from bot_program.pending_closes import blocked_behind_held_close
        held = self._queued()
        row = self._refused()
        self.assertGreater(row.opened_at, held.opened_at)
        self.wire.close_plans = ["close"]
        t0 = timezone.now()
        self._beats(row, 3, t0)
        posts0 = len(self._close_posts())
        self.wire.close_at_once(self._pid_of(held))
        self._drain_at(t0 + timedelta(hours=1))
        held.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual((held.status, row.status),
                         ("CLOSED", "CLOSE_PENDING"))
        self.assertEqual(len(self._close_posts()), posts0)
        self.assertFalse(blocked_behind_held_close(row))
        self.assertEqual(short_proofs.refusing(), CLOSES_FIRST)
        self.assertEqual(short_proofs.not_waited_on(), "")
        self._drain_at(t0 + timedelta(hours=1, seconds=BEAT_S))
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(len(self._close_posts()), posts0 + 1)
        self.assertEqual(short_proofs.refusing(), "")

    def test_a_row_older_than_the_held_close_goes_at_the_pass_that_books_it(
            self):
        """The other order: the held row is read first and booked, then
        this one, with nothing beside it any more, and its close goes in
        that same pass. The runner let it go until that pass began: a demo
        step under way then shares the key's quota with this one close, as
        with any real close that becomes pending while a step runs."""
        from bot_program.pending_closes import blocked_behind_held_close
        row = self._refused(name="gold bot")
        held = self._queued(name="gold bot two")
        self.assertGreater(held.opened_at, row.opened_at)
        self.wire.close_plans = ["close"]
        t0 = timezone.now()
        self._beats(row, 3, t0)
        posts0 = len(self._close_posts())
        self.wire.close_at_once(self._pid_of(held))
        self._drain_at(t0 + timedelta(hours=1))
        held.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual((held.status, row.status), ("CLOSED", "CLOSED"))
        self.assertEqual(len(self._close_posts()), posts0 + 1)
        self.assertFalse(blocked_behind_held_close(row))

    def test_on_the_other_side_it_gets_no_write_while_the_position_stands(
            self):
        from bot_program import short_proofs
        from bot_program.pending_closes import blocked_behind_held_close
        held = self._queued()
        row = self._refused(sell=True)
        self.assertEqual(row.side, "SELL")
        self.assertFalse(blocked_behind_held_close(row))
        self.wire.close_plans = ["close"]
        self._beats(row, 12, timezone.now())
        held.refresh_from_db()
        self.assertEqual(held.status, "CLOSE_PENDING")
        self.assertIn("on the OTHER side",
                      row.metadata.get("close_blocked_why"))
        self.assertEqual(short_proofs.refusing(), "")
        self.assertEqual(short_proofs.not_waited_on(),
                         GOLD_HELD + GOLD_BEHIND.format("SELL"))

    def test_on_the_other_side_the_pass_that_sees_it_gone_sends_and_waits(
            self):
        """The other-side block lasts while eToro lists the held position.
        Once eToro lets it go, the pass that sees it gone sends this row's
        close, here before the held row is booked (its order read does not
        answer, and this row's position now stands against it on the other
        side). That resend is this row's last pass: waited on again."""
        from bot_program import short_proofs
        from bot_program.pending_closes import (blocked_behind_held_close,
                                                close_held_at_venue)
        held = self._queued()
        row = self._refused(sell=True)
        t0 = timezone.now()
        self.wire.close_plans = ["close"]
        self._beats(row, 3, t0)
        self.wire.fail_lookup = True
        self.wire.close_plans = [REFUSE]
        self.wire.close_at_once(self._pid_of(held))
        posts0 = len(self._close_posts())
        self._drain_at(t0 + timedelta(hours=1))
        held.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(len(self._close_posts()), posts0 + 1)
        self.assertEqual((held.status, row.status),
                         ("CLOSE_PENDING", "CLOSE_PENDING"))
        self.assertEqual(row.metadata.get("close_retry_attempts"), 1)
        self.assertTrue(close_held_at_venue(held))
        self.assertFalse(blocked_behind_held_close(row))
        self.assertEqual(short_proofs.not_waited_on(), GOLD_HELD)
        self.assertEqual(short_proofs.refusing(), CLOSES_FIRST)
        waited, held_rows, behind = short_proofs._real_closes_pending()
        self.assertEqual(([r.pk for r in waited], [r.pk for r in held_rows],
                          behind), ([row.pk], [held.pk], []))

    def test_nor_on_a_lane_stood_down_or_an_account_of_the_other_world(self):
        from bot_program.models import EtoroAccount
        held = self._queued()
        row = self._refused()
        t0 = timezone.now()
        self.wire.close_plans = ["close"]
        self._stand_down(row.config)
        self._beats(row, 6, t0)
        EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=True)
        self._beats(row, 6, t0 + timedelta(hours=1))
        held.refresh_from_db()
        self.assertEqual(held.status, "CLOSE_PENDING")
        self.assertIn("PaperTrader fallback",
                      row.metadata.get("close_blocked_why"))
        self.assertFalse(row.metadata.get("close_retry_attempts"))
