"""The positioning map (bot_program/positioning.py): who is already placed
on a symbol, where their stops sit, where the market is pulled — and what
that means for one side.

Read-only: it writes nothing and touches no broker.

    python manage.py positioning EURUSD              # the map
    python manage.py positioning EURUSD --side SELL  # and what it means for a sell
    python manage.py positioning BTCUSD --json       # the whole dict
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Who is placed, where their stops sit, the hunt and the draw, "
            "and the proving ground's word on pool sweeps.")

    def add_arguments(self, parser):
        parser.add_argument("symbol")
        parser.add_argument("--side", choices=["BUY", "SELL"], default=None)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **opts):
        from bot_program.positioning import positioning_map
        from instruments.models import Instrument
        symbol = opts["symbol"].upper()
        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            self.stdout.write(f"no instrument {symbol}")
            return
        pmap = positioning_map(symbol, asset_class=inst.asset_class or "",
                               direction=opts["side"])
        if opts["json"]:
            self.stdout.write(json.dumps(pmap, indent=1, default=str))
            return
        if not pmap["ok"]:
            self.stdout.write(f"{symbol}: {pmap['words']}")
            return
        crowd = pmap["crowd"]
        self.stdout.write(f"{symbol} at {pmap['mark']:g} (ATR {pmap['atr']:g})")
        self.stdout.write(f"  crowd: {crowd['label']}"
                          + (f" (score {crowd['score']:+.2f})"
                             if crowd["score"] is not None else ""))
        for name, c in crowd["components"].items():
            score = ("—" if c.get("score") is None
                     else f"{c['score']:+.2f} x{c.get('weight', 0):g}")
            self.stdout.write(f"    {name:<16} {score:<14} {c.get('words', '')}")
        for side in ("below", "above"):
            s = pmap["stops"][side]
            self.stdout.write(
                f"  pool {side:<5} "
                + (f"{s['price']:g}  {s['kind']}"
                   + (f"  {s['atr_away']:g} ATR" if s.get("atr_away") is not None
                      else "") if s else "none within reach"))
        self.stdout.write(f"  bias: {pmap['bias'] or 'none'}"
                          + (f" ({pmap['bias_confidence']:.2f})"
                             if pmap.get("bias_confidence") is not None else ""))
        po3 = pmap.get("po3") or {}
        self.stdout.write(f"  day: {po3.get('phase', 'unread')}"
                          + (f" pointing {po3['direction']}" if po3.get("direction")
                             else "")
                          + f" ({po3.get('session', '—')} session"
                          + (f", {po3['timeframe']} bars" if po3.get("timeframe")
                             else "") + ")")
        for leg in pmap["path"]:
            self.stdout.write(
                f"  {leg['leg']:<5} {leg.get('side', '—'):<6}"
                + (f"{leg['price']:g}  {leg.get('kind', '')}" if leg.get("price")
                   else "no pool") + f"  — {leg.get('why', '')}")
        od = pmap["odds"]
        self.stdout.write(f"  pool sweeps on {inst.asset_class}: "
                          f"{od.get('verdict', 'unjudged').upper()}"
                          + (f" — {od['why']}" if od.get("why") else ""))
        self.stdout.write("  " + pmap["words"])
        if pmap.get("side"):
            self.stdout.write("  " + pmap["side"]["words"])
