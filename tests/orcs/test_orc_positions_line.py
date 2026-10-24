"""THE ORC ON THE POSITIONS PAGE (spec §9.2, O1d): one line under the
symbol of an open row an Orc follows, and the dwell card's section.

Pinned here: the line and its link; the row's data-pos-orc-* attributes
only on a row with an Orc; the history tab unchanged; the dwell card
paints the Orc's lines as text.

Run with:  python manage.py test tests.orcs.test_orc_positions_line
"""
import pathlib
import re
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tests.orcs.helpers import _on, born

POSITIONS = "/positions/"
HISTORY = "/positions/?tab=history"
SCRIPT = "<script>alert(1)</script>"


def _setup(user, symbol="BTCUSD", status="OPEN", reason="trend up"):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "crypto"})
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal("61000"),
                                   "source": "binance_public"})
    cfg = AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name=f"book-{symbol}-{status}",
        enabled=True, mode="paper", symbols=[], capital=Decimal("10000"))
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="crypto", symbol=symbol, side="BUY",
        qty=Decimal("0.5"), entry_price=Decimal("60000"),
        stop_loss=Decimal("59000"), take_profit=Decimal("62000"),
        status=status, paper=True, rule_name="breakout_1h", reason=reason,
        metadata={"value_per_unit": 1.0, "initial_stop_loss": 59000.0},
        closed_at=timezone.now() if status == "CLOSED" else None)


def _rows(html):
    return re.findall(r"<tr data-sv-position-row.*?>", html, flags=re.S)


class ThePositionsLineTests(TestCase):

    def setUp(self):
        _on()
        self.user = get_user_model().objects.create_user("orc_pos",
                                                         password="x")
        self.client.force_login(self.user)
        self.trade = _setup(self.user)
        self.orc = born(self, self.trade)

    def html(self, url=POSITIONS):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return r.content.decode("utf-8", "replace")

    def test_the_line_under_the_symbol(self):
        html = self.html()
        m = re.search(r'<div class="pos-orc-line"><a href="([^"]+)">([^<]+)'
                      r'</a></div>', html)
        self.assertIsNotNone(m, "no Orc line")
        self.assertEqual(m.group(1), f"/orcs/{self.trade.pk}/")
        self.assertTrue(m.group(2).startswith(
            f"Orc #{self.trade.pk} · L0 · Snaga, class · "), m.group(2))
        self.assertIn("no plan yet · risk 1.0R of 2R", m.group(2))
        # the live region re-renders the same line
        live = self.client.get("/positions/live/").content.decode()
        self.assertIn('class="pos-orc-line"', live)

    def test_the_dwell_card_attributes_only_with_an_orc(self):
        plain = _setup(self.user, symbol="ETHUSD")
        rows = _rows(self.html())
        mine = [r for r in rows if f'data-pos-href="/forensics/{self.trade.pk}/'
                in r]
        other = [r for r in rows if f'data-pos-href="/forensics/{plain.pk}/'
                 in r]
        self.assertEqual((len(mine), len(other)), (1, 1))
        self.assertIn(f'data-pos-orc-label="Orc #{self.trade.pk}"', mine[0])
        self.assertIn(f'data-pos-orc-href="/orcs/{self.trade.pk}/"', mine[0])
        self.assertIn('data-pos-orc-plan="No plan yet: Orcs write plans once '
                      'they reason."', mine[0])
        self.assertIn("data-pos-orc-j1=", mine[0])
        self.assertNotIn("data-pos-orc", other[0])
        _on(False)
        self.assertNotIn("data-pos-orc", self.html())
        self.assertNotIn('class="pos-orc-line"', self.html())

    def test_the_history_tab_is_unchanged(self):
        closed = _setup(self.user, symbol="SOLUSD", status="CLOSED")
        from bot_program.models import AssetBotTrade
        meta = dict(closed.metadata)
        meta["orc"] = dict(self.trade.metadata.get("orc") or {"idea": 1})
        AssetBotTrade.objects.filter(pk=closed.pk).update(metadata=meta)
        html = self.html(HISTORY)
        # the closed row's stamp is never read: no line, no attribute
        self.assertNotIn('class="pos-orc-line"', html)
        self.assertNotIn("data-pos-orc", html)
        from dashboard import views
        import inspect
        src = inspect.getsource(views._render_positions)
        self.assertEqual(src.count("orcs=True"), 1)
        self.assertIn("_position_card_details(request.user, closed_positions)",
                      src)

    def test_an_operator_thesis_never_reaches_the_row_as_markup(self):
        from bot_program.orcs import journal
        journal.append(self.orc, "thesis", f"Your thesis: {SCRIPT}",
                       author="operator",
                       body={"thesis": {"source": "operator",
                                        "text": SCRIPT}})
        html = self.html()
        self.assertNotIn(SCRIPT, html)
        # the line and the dwell card's lines are there, escaped
        self.assertIn('class="pos-orc-line"', html)
        self.assertIn("&lt;script&gt;", html)

    def test_an_operator_thesis_that_may_name_money_is_withheld(self):
        """The dwell card's journal lines pass PR68's plain words in
        notes.slot, as the Horde's seat does: his thesis naming an amount
        is withheld whole, his clean one kept as written."""
        from bot_program.orcs import journal, notes
        text = "Long into the print, risking $400"
        journal.append(self.orc, "thesis", "Your thesis: " + text,
                       author="operator",
                       body={"thesis": {"source": "operator", "text": text}})
        html = self.html()
        self.assertNotIn("risking $400", html)
        self.assertIn("Withheld: this line may name an amount of money.",
                      html)
        sl = notes.for_trades([self.trade], user=self.user)[self.trade.pk]
        self.assertEqual(sl["thesis"]["t"],
                         "Withheld: this line may name an amount of money.")
        self.assertIn("operator: Withheld: this line may name an amount of "
                      "money.", notes.line_dict(sl)["j1"])
        journal.append(self.orc, "thesis", "Your thesis: holds 59500.00",
                       author="operator",
                       body={"thesis": {"source": "operator",
                                        "text": "holds 59500.00"}})
        sl = notes.for_trades([self.trade], user=self.user)[self.trade.pk]
        self.assertEqual(sl["thesis"]["t"], "holds 59500.00")
        self.assertIn("operator: Your thesis: holds 59500.00",
                      notes.line_dict(sl)["j1"])

    def test_the_card_reads_no_orc_key_the_row_does_not_write(self):
        """The other half of the dwell card's contract (tests/
        test_position_capital_and_percents.py): on a row an Orc follows,
        every data-pos-orc-* key the card reads is written."""
        js = (pathlib.Path(settings.BASE_DIR) / "static" / "js" /
              "sv-position-card.js").read_text(encoding="utf-8")
        reads = {k for k in re.findall(r'(?:val|num|flag)\(row, "([a-z-]+)"\)',
                                       js) if k.startswith("orc-")}
        reads |= set(re.findall(r'"(orc-j[0-9])"', js))
        self.assertTrue(reads)
        row = [r for r in _rows(self.html())
               if f'data-pos-href="/forensics/{self.trade.pk}/' in r][0]
        writes = set(re.findall(r'data-pos-([a-z0-9-]+)=', row))
        self.assertEqual(reads - writes, set())


class TheDwellScriptTests(TestCase):

    def test_the_dwell_script_paints_the_orc_as_text(self):
        js = (pathlib.Path(settings.BASE_DIR) / "static" / "js" /
              "sv-position-card.js").read_text(encoding="utf-8")
        block = js.split("The Orc that follows the row", 1)[1] \
                  .split("── Actions ──", 1)[0]
        self.assertNotIn("innerHTML", block)
        self.assertIn('val(row, "orc-label")', block)
        self.assertIn('kv(orcBox, "Plan", val(row, "orc-plan"))', block)
        self.assertNotIn("innerHTML", js.split("var orcHref", 1)[1]
                         .split("var rowClose", 1)[0])
        # the Orc's page link stays before the destructive action
        self.assertLess(js.index("JOURNAL ›"), js.index("pos-pop-close"))
