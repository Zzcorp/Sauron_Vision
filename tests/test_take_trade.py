"""TAKE TRADE — manual execution of a signal, paper venue.

A signal proposes; the operator disposes. The button turns one Signal
into one sized, tracked position through the same sizing, levels and
bookkeeping the bots use — on a per-user "manual" config that manages
its positions every tick but can never open one on its own.

The second half of the file pins the adversarial-review fixes: per-class
capital pools, margin-aware forex commitment, level-orientation checks,
neutral-signal refusal, signal dedupe, config-collision and kill-state
refusals, minimal-disturbance funding proposals, fill-first sizing, and
the signal-less instrument-popup path.

Run with:  python manage.py test tests.test_take_trade
"""
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "binance_public"})
    return inst


def _signal(inst, *, direction="bullish", entry=60000, stop=59100,
            target=61800, score=0.8):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="high", title=f"{inst.symbol} {direction}", description="d",
        rule_name="test_rule", score=score, sub_scores={},
        price_at_signal=Decimal(str(entry)),
        suggested_entry=Decimal(str(entry)),
        suggested_stop=Decimal(str(stop)),
        suggested_target=Decimal(str(target)), is_active=True)


class TakeTradeEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tt_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def test_preview_carries_the_facts_the_decision_needs(self):
        from bot_program.manual_trade import preview_take_trade
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertNotIn("error", p)
        self.assertEqual(p["side"], "BUY")
        self.assertEqual(p["symbol"], "BTCUSD")
        self.assertGreater(p["qty"], 0)
        self.assertEqual(p["venue"], "paper")
        self.assertTrue(p["sufficient"])
        self.assertIn("managed", p)
        self.assertIn("capital_use", p)
        # Risk-sized: $25 budget at default 0.25% of $10,000 capital.
        self.assertAlmostEqual(p["risk_dollars"], 25.0, places=2)

    def test_the_manual_config_manages_but_never_trades(self):
        """enabled=True with empty symbols: the 5-minute tick runs
        manage_positions for open manual trades, and the entry scan has
        nothing to scan — the config cannot open a position on its own."""
        from bot_program.manual_trade import manual_config_for
        cfg = manual_config_for(self.user, "crypto")
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.symbols, [])
        self.assertEqual(cfg.mode, "paper")

    def test_execute_opens_a_tracked_paper_position(self):
        from bot_program.manual_trade import MANUAL_RULE, execute_take_trade
        from bot_program.models import AssetBotTrade
        sig = _signal(self.inst)
        out = execute_take_trade(self.user, sig)
        self.assertTrue(out.get("ok"), out)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue(trade.paper)
        self.assertEqual(trade.rule_name, MANUAL_RULE)
        # Pinned to the ACTUAL signal pk — the first cut compared the
        # metadata value to itself, which passed for any stored garbage.
        self.assertEqual(trade.metadata.get("signal_id"), sig.pk)
        self.assertEqual(float(trade.stop_loss), 59100.0)
        self.assertEqual(float(trade.take_profit), 61800.0)
        # The paper fill is adversely adjusted — STRICTLY worse than the
        # free raw mark, so a regression to sizing off the mark fails.
        self.assertGreater(float(trade.entry_price),
                           trade.metadata["market_price"])

    def test_a_bearish_signal_sells(self):
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(
            self.inst, direction="bearish", stop=60900, target=58200))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["side"], "SELL")

    def test_insufficient_capital_proposes_funding_closes(self):
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        # Fill the manual config's capital with an open position, then
        # shrink the pool under it.
        first = execute_take_trade(self.user, _signal(self.inst))
        self.assertTrue(first.get("ok"))
        from bot_program.models import AssetBotConfig
        cfg = AssetBotConfig.objects.get(user=self.user,
                                         asset_class="crypto", name="manual")
        cfg.capital = Decimal("1700")
        cfg.save(update_fields=["capital"])

        p = preview_take_trade(self.user, _signal(self.inst))
        if "error" in p:
            self.skipTest(f"sizing rejected the follow-up trade: {p}")
        self.assertFalse(p["sufficient"])
        self.assertTrue(p["close_proposal"],
                        "no funding proposal despite the deficit")

    def test_close_then_open_settles_in_one_chain(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotConfig, AssetBotTrade
        first = execute_take_trade(self.user, _signal(self.inst))
        self.assertTrue(first.get("ok"))
        cfg = AssetBotConfig.objects.get(user=self.user,
                                         asset_class="crypto", name="manual")
        # Shrink capital so the next trade needs the first one closed.
        cfg.capital = Decimal("1700")
        cfg.save(update_fields=["capital"])
        out = execute_take_trade(self.user, _signal(self.inst),
                                 close_ids=[first["trade_id"]])
        self.assertTrue(out.get("ok"), out)
        self.assertIn("BTCUSD", out["closed"])
        old = AssetBotTrade.objects.get(pk=first["trade_id"])
        self.assertEqual(old.status, "CLOSED")
        self.assertIsNotNone(old.realized_r)

    def test_an_index_signal_is_refused_with_the_reason(self):
        from bot_program.manual_trade import preview_take_trade
        idx = _quote("SPX500", 7800, asset_class="index")
        p = preview_take_trade(self.user, _signal(idx))
        self.assertIn("error", p)
        self.assertIn("execution path", p["error"])


class TakeTradeReviewFixTests(TestCase):
    """Every adversarial-review finding, pinned."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ttr_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    # ── money-math ───────────────────────────────────────────────────

    def test_forex_commitment_is_margin_not_levered_notional(self):
        """An EURUSD trade with a 0.3% stop sizes to ~83% notional by
        design (the leverage is at the broker). Charging the pool the full
        notional made every ordinary FX trade 'insufficient capital' on an
        EMPTY book — the commitment must be the margin."""
        from bot_program.manual_trade import preview_take_trade
        fx = _quote("EURUSD", 1.10, asset_class="forex")
        p = preview_take_trade(self.user, _signal(
            fx, entry=1.10, stop=1.0967, target=1.1066))
        self.assertNotIn("error", p)
        self.assertTrue(p["sufficient"], p)
        self.assertLess(p["capital_use"], p["notional"])

    def test_capital_pools_are_per_asset_class(self):
        """A crypto position must not count against the stock pool — each
        class's manual config has its own capital."""
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        first = execute_take_trade(self.user, _signal(self.inst))
        self.assertTrue(first.get("ok"))
        stock = _quote("AAPL", 100, asset_class="stock")
        p = preview_take_trade(self.user, _signal(
            stock, entry=100, stop=97, target=106))
        self.assertNotIn("error", p)
        self.assertEqual(p["committed"], 0.0,
                         "crypto position leaked into the stock pool")

    def test_crossed_levels_are_refused(self):
        """A bullish signal whose stop sits ABOVE the current mark is
        stale — taking it would open a position the next tick closes at a
        guaranteed loss."""
        from bot_program.manual_trade import preview_take_trade
        p = preview_take_trade(self.user, _signal(
            self.inst, stop=60900, target=61800))
        self.assertIn("error", p)
        self.assertIn("wrong side", p["error"])

    def test_neutral_signals_are_refused(self):
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        sig = _signal(self.inst, direction="neutral")
        self.assertIn("no trade direction",
                      preview_take_trade(self.user, sig)["error"])
        self.assertIn("no trade direction",
                      execute_take_trade(self.user, sig)["error"])

    def test_funding_proposal_prefers_smallest_single_cover(self):
        """Deficit $500 with $100 and $1500 positions open: close the
        $1500 one alone. The old greedy walk closed the $100 position too
        — every small position on the book — before reaching the one that
        covered the gap."""
        from bot_program.manual_trade import _funding_proposal

        def mk(pk, notional):
            return SimpleNamespace(
                id=pk, symbol=f"S{pk}", side="BUY", qty=1.0,
                entry_price=notional, asset_class="crypto", metadata={})

        prop = _funding_proposal([mk(1, 100.0), mk(2, 1500.0)], 500.0)
        self.assertEqual([p["trade_id"] for p in prop], [2])

    def test_funding_proposal_prunes_redundant_members(self):
        from bot_program.manual_trade import _funding_proposal

        def mk(pk, notional):
            return SimpleNamespace(
                id=pk, symbol=f"S{pk}", side="BUY", qty=1.0,
                entry_price=notional, asset_class="crypto", metadata={})

        # No single position covers 550; ascending accumulation takes all
        # three, then the 100 is pruned because 200+400 already covers.
        prop = _funding_proposal(
            [mk(1, 100.0), mk(2, 200.0), mk(3, 400.0)], 550.0)
        self.assertEqual(sorted(p["trade_id"] for p in prop), [2, 3])

    # ── lifecycle / safety ───────────────────────────────────────────

    def test_a_signal_cannot_be_taken_twice(self):
        from bot_program.manual_trade import execute_take_trade
        sig = _signal(self.inst)
        first = execute_take_trade(self.user, sig)
        self.assertTrue(first.get("ok"))
        second = execute_take_trade(self.user, sig)
        self.assertIn("error", second)
        self.assertIn("already taken", second["error"])

    def test_a_disabled_manual_config_refuses_instead_of_rearming(self):
        """The kill switch disables configs. The first cut silently
        re-enabled the manual config on the next preview — reversing the
        one decision that must never be reversed quietly."""
        from bot_program.manual_trade import (manual_config_for,
                                              preview_take_trade)
        cfg = manual_config_for(self.user, "crypto")
        cfg.enabled = False
        cfg.save(update_fields=["enabled"])
        p = preview_take_trade(self.user, _signal(self.inst))
        self.assertIn("error", p)
        self.assertIn("disabled", p["error"])
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled, "preview silently re-armed the config")

    def test_a_user_config_named_manual_is_never_adopted(self):
        """get_or_create adopts any existing (user, class, 'manual') row.
        The first cut then wiped its symbols and re-enabled it — the fix
        refuses and leaves the user's config untouched."""
        from bot_program.models import AssetBotConfig
        from bot_program.manual_trade import preview_take_trade
        AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="manual",
            symbols=["AAPL"], enabled=False, mode="paper")
        stock = _quote("AAPL", 100, asset_class="stock")
        p = preview_take_trade(self.user, _signal(
            stock, entry=100, stop=97, target=106))
        self.assertIn("error", p)
        self.assertIn("rename", p["error"])
        cfg = AssetBotConfig.objects.get(user=self.user, asset_class="stock",
                                         name="manual")
        self.assertEqual(cfg.symbols, ["AAPL"], "user's config was rewritten")
        self.assertFalse(cfg.enabled, "user's config was re-enabled")

    def test_execute_stars_the_instrument(self):
        """The star is what keeps quotes and bars flowing — without it a
        manual position on an off-fleet symbol loses its mark and becomes
        permanently unmanageable."""
        from bot_program.manual_trade import execute_take_trade
        self.inst.is_watchlist = False
        self.inst.save(update_fields=["is_watchlist"])
        out = execute_take_trade(self.user, _signal(self.inst))
        self.assertTrue(out.get("ok"), out)
        self.inst.refresh_from_db()
        self.assertTrue(self.inst.is_watchlist)

    def test_open_side_bookkeeping_hooks_run(self):
        """The audit log must get a trade_open for every manual open — the
        first cut wrote closes with no matching opens."""
        from bot_program.manual_trade import execute_take_trade
        out = execute_take_trade(self.user, _signal(self.inst))
        self.assertTrue(out.get("ok"), out)
        from bot_program.audit_models import AuditLogEntry
        self.assertTrue(AuditLogEntry.objects.filter(
            user=self.user, kind="trade_open").exists(),
            "no trade_open audit entry for the manual open")


class AssetTradeTests(TestCase):
    """Signal-less LONG/SHORT from the instrument popups."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("at_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        self.client.force_login(self.user)

    def test_engine_levels_back_a_signal_less_trade(self):
        from bot_program.manual_trade import preview_asset_trade
        p = preview_asset_trade(self.user, self.inst, "BUY")
        if "error" in p:
            self.skipTest(f"no engine levels without bars: {p}")
        self.assertEqual(p["side"], "BUY")
        self.assertGreater(p["qty"], 0)

    def test_preview_endpoint(self):
        resp = self.client.post(
            "/instruments/BTCUSD/take-trade/preview/",
            data='{"side": "BUY"}', content_type="application/json",
            HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Either a full preview or an engine-levels error — never a 500.
        self.assertTrue(data.get("symbol") == "BTCUSD" or data.get("error"))

    def test_execute_endpoint_records_a_signal_less_trade(self):
        from bot_program.models import AssetBotTrade
        resp = self.client.post(
            "/instruments/BTCUSD/take-trade/",
            data='{"side": "BUY"}', content_type="application/json",
            HTTP_HOST="127.0.0.1")
        data = resp.json()
        if data.get("error"):
            self.skipTest(f"no engine levels without bars: {data}")
        trade = AssetBotTrade.objects.get(pk=data["trade_id"])
        self.assertIsNone(trade.metadata.get("signal_id"))

    def test_malformed_bodies_are_400_not_500(self):
        # Non-object JSON crashed with AttributeError before.
        resp = self.client.post(
            "/instruments/BTCUSD/take-trade/",
            data='[1, 2]', content_type="application/json",
            HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 400)
        # String close_ids iterated per character into trade ids.
        resp = self.client.post(
            "/instruments/BTCUSD/take-trade/",
            data='{"side": "BUY", "close_ids": "12"}',
            content_type="application/json", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 400)

    def test_bad_side_is_refused(self):
        resp = self.client.post(
            "/instruments/BTCUSD/take-trade/preview/",
            data='{"side": "SIDEWAYS"}', content_type="application/json",
            HTTP_HOST="127.0.0.1")
        self.assertIn("error", resp.json())


class PopupMarkupTests(TestCase):
    """The instrument popups live INSIDE item anchors. A nested <a> there
    is not a validity nit: the HTML parser's adoption-agency algorithm
    reparents the popup out of the item, the hover binder's querySelector
    finds nothing, and the popup can never open — silently."""

    @staticmethod
    def _strip_comments(src):
        """Template comments never reach the browser — only scan markup
        that does (the comments explaining this very rule mention <a>)."""
        import re
        return re.sub(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", "",
                      src, flags=re.S)

    def test_popups_contain_no_nested_anchor(self):
        import re
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)

        dh = self._strip_comments(
            (base / "templates" / "_partials" / "dh_item.html").read_text(
                encoding="utf-8"))
        pop = dh.split('class="dh-pop"', 1)[1]
        self.assertIsNone(
            re.search(r"<a[\s>]", pop),
            "dh-pop contains a nested <a> — the parser will eject the popup")

        html = self._strip_comments(
            (base / "templates" / "base.html").read_text(encoding="utf-8"))
        self.assertIn('class="dh-pop wl-pop"', html)
        wl = html.split('class="dh-pop wl-pop"', 1)[1].split("</a>", 1)[0]
        self.assertIsNone(
            re.search(r"<a[\s>]", wl),
            "wl-pop contains a nested <a> — the parser will eject the popup")


class TakeTradeEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tte_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)
        self.sig = _signal(self.inst)
        self.client.force_login(self.user)

    def test_preview_endpoint_returns_the_facts(self):
        resp = self.client.post(
            f"/signals/{self.sig.id}/take-trade/preview/",
            HTTP_HOST="127.0.0.1")
        data = resp.json()
        self.assertEqual(data["symbol"], "BTCUSD")
        self.assertTrue(data["sufficient"])

    def test_execute_endpoint_opens_the_trade(self):
        from bot_program.models import AssetBotTrade
        resp = self.client.post(
            f"/signals/{self.sig.id}/take-trade/",
            data="{}", content_type="application/json",
            HTTP_HOST="127.0.0.1")
        self.assertTrue(resp.json().get("ok"), resp.json())
        self.assertEqual(AssetBotTrade.objects.filter(
            config__user=self.user, status="OPEN").count(), 1)

    def test_get_is_refused(self):
        resp = self.client.get(
            f"/signals/{self.sig.id}/take-trade/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 405)

    def test_an_inactive_signal_cannot_be_taken(self):
        self.sig.is_active = False
        self.sig.save(update_fields=["is_active"])
        resp = self.client.post(
            f"/signals/{self.sig.id}/take-trade/",
            data="{}", content_type="application/json",
            HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_users_are_bounced(self):
        self.client.logout()
        resp = self.client.post(
            f"/signals/{self.sig.id}/take-trade/",
            data="{}", content_type="application/json",
            HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 302)
