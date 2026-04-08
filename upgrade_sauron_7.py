#!/usr/bin/env python3
"""
upgrade_sauron_7.py
===================
Targeted finishing pass — completes the 3 anchors that pass 6 missed
because of indentation mismatches between my dedent strings and the
actual files written by earlier passes. Plus injects the missing
dashboard headband HTML markup that pass 2 silently failed to add.

Drop next to manage.py and run:

    python upgrade_sauron_7.py

Idempotent. No DB migrations.

Fixes:
 1. Inject the dashboard headband HTML markup (the row of SPX/NDX/BTC
    chips with hover popups) — pass 2 added the CSS but the markup
    block never landed because the insertion anchor used CRLF-naive
    matching. This pass uses CRLF-aware insertion AND the rich popup
    body from pass 6.
 2. Enrich `bot_program/views.bot_home` with all the metrics the new
    template expects (24h pnl, 7d pnl, win rate, exposure, equity
    sparkline, best/worst, last event). The template silently rendered
    blank fields without this.
 3. Enrich `core/context_ui.py` band entries with bid/ask/source/
    updated_human so the new headband popups show real data.
"""
from __future__ import annotations
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run from directory containing manage.py"); sys.exit(1)

def _norm(s): return s.replace("\r\n", "\n").replace("\r", "\n")

def patch(rel, old, new, *, marker=None):
    p = ROOT / rel
    if not p.exists(): print(f"  MISSING: {rel}"); return False
    raw = p.read_text(encoding="utf-8")
    use_crlf = "\r\n" in raw
    norm_txt = _norm(raw); norm_old = _norm(old); norm_new = _norm(new)
    if marker is None:
        for line in norm_new.splitlines():
            ln = line.strip()
            if len(ln) >= 15 and ln not in norm_old:
                marker = ln; break
        if marker is None: marker = norm_new.strip()[:60]
    if marker in norm_txt:
        print(f"  already patched: {rel}"); return True
    if norm_old not in norm_txt:
        print(f"  anchor not found: {rel}"); return False
    out = norm_txt.replace(norm_old, norm_new, 1)
    if use_crlf: out = out.replace("\n", "\r\n")
    p.write_text(out, encoding="utf-8")
    print(f"  patched: {rel}"); return True

print("━" * 60)
print(" SAURON VISION — UPGRADE PASS 7 (finish pass 6)")
print("━" * 60)

# =================================================================
# STEP 1 — Inject dashboard headband HTML markup
# =================================================================
print("\n[1/3] Injecting dashboard headband HTML markup …")

p = ROOT / "templates/base.html"
btxt = p.read_text(encoding="utf-8")
use_crlf = "\r\n" in btxt
norm = _norm(btxt)

if "<!-- UPGRADE-2: Dashboard data headband -->" in norm:
    print("  headband markup already present")
else:
    HEADBAND_HTML = '''<!-- UPGRADE-2: Dashboard data headband -->
<div class="data-headband" id="dataHeadband">
  {% for m in ui_headband %}
  <div class="dh-item" data-symbol="{{ m.symbol }}">
    <span class="dh-dot {% if m.change_pct > 0 %}up{% elif m.change_pct < 0 %}down{% else %}flat{% endif %}"></span>
    <span class="dh-sym">{{ m.symbol }}</span>
    <span class="dh-val">{% if m.last %}{{ m.last|floatformat:2 }}{% else %}—{% endif %}</span>
    <span class="dh-chg {% if m.change_pct >= 0 %}up{% else %}down{% endif %}">
      {% if m.change_pct >= 0 %}+{% endif %}{{ m.change_pct|floatformat:2 }}%
    </span>
    <div class="dh-pop">
      <div class="dh-pop-head">
        <div>
          <div class="dh-pop-title">{{ m.symbol }}</div>
          <div class="dh-pop-name">{{ m.name }}</div>
        </div>
        <div class="dh-pop-badge {% if m.change_pct > 0 %}up{% elif m.change_pct < 0 %}down{% else %}flat{% endif %}">
          {% if m.change_pct >= 0 %}▲{% else %}▼{% endif %}
        </div>
      </div>
      <div class="dh-pop-big">
        <span class="dh-pop-price">{% if m.last %}{{ m.last|floatformat:4 }}{% else %}—{% endif %}</span>
        <span class="dh-pop-pct {% if m.change_pct >= 0 %}up{% else %}down{% endif %}" style="color:{% if m.change_pct >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">
          {% if m.change_pct >= 0 %}+{% endif %}{{ m.change_pct|floatformat:2 }}%
        </span>
      </div>
      <div class="dh-pop-row"><span class="k">Asset class</span><span class="v">{{ m.asset_class|default:"—"|upper }}</span></div>
      <div class="dh-pop-row"><span class="k">24h volume</span><span class="v">{% if m.volume %}{{ m.volume|floatformat:0 }}{% else %}—{% endif %}</span></div>
      {% if m.bid %}<div class="dh-pop-row"><span class="k">Bid / Ask</span><span class="v">{{ m.bid|floatformat:4 }} / {{ m.ask|floatformat:4 }}</span></div>{% endif %}
      <div class="dh-pop-row"><span class="k">Source</span><span class="v" style="color:var(--accent);">{{ m.source|default:"—" }}</span></div>
      <div class="dh-pop-row"><span class="k">Updated</span><span class="v">{{ m.updated_human|default:"—" }}</span></div>
      <div class="dh-pop-cta">▸ Click symbol on dashboard for full chart</div>
    </div>
  </div>
  {% empty %}
  <div class="dh-item" style="color:var(--text-muted);">
    <span class="dh-sym">NO LIVE DATA</span>
    <span class="dh-val">—</span>
  </div>
  {% endfor %}
</div>

'''
    # Insertion point: just before <div class="page-content fade-in"
    needle = '<div class="page-content fade-in"'
    if needle in norm:
        new_norm = norm.replace(needle, HEADBAND_HTML + needle, 1)
        out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
        p.write_text(out, encoding="utf-8")
        print("  inserted headband HTML markup")
    else:
        print("  could not find insertion anchor for headband")

# =================================================================
# STEP 2 — Enrich bot_program.views.bot_home (4-space indent fix)
# =================================================================
print("\n[2/3] Enriching bot_home view …")

# Note: file uses 4-space top-level functions, not 8.
patch("bot_program/views.py",
      '''@login_required
def bot_home(request):
    cfg, _ = BotConfig.objects.get_or_create(user=request.user)
    acct = getattr(request.user, "binance_account", None)
    open_trades = BotTrade.objects.filter(config=cfg, status="OPEN")[:20]
    closed_trades = BotTrade.objects.filter(config=cfg, status="CLOSED")[:30]
    scenarios = BotScenario.objects.filter(user=request.user)[:20]
    equity = float(cfg.capital_usdt)
    pnl_total = sum(float(t.pnl_usdt) for t in BotTrade.objects.filter(config=cfg, status="CLOSED"))
    return render(request, "bot_program/home.html", _ctx(request,
        cfg=cfg, acct=acct, open_trades=open_trades,
        closed_trades=closed_trades, scenarios=scenarios,
        equity=equity, pnl_total=pnl_total,
        weights=cfg.normalized_weights()))''',
      '''@login_required
def bot_home(request):
    from datetime import timedelta
    from django.utils import timezone
    from decimal import Decimal
    cfg, _ = BotConfig.objects.get_or_create(user=request.user)
    acct = getattr(request.user, "binance_account", None)

    all_closed = BotTrade.objects.filter(config=cfg, status="CLOSED")
    open_trades = BotTrade.objects.filter(config=cfg, status="OPEN")[:20]
    closed_trades = all_closed[:30]
    scenarios = BotScenario.objects.filter(user=request.user)[:20]

    equity = float(cfg.capital_usdt)
    pnl_total = float(sum((t.pnl_usdt for t in all_closed), Decimal(0)))
    total_trades = all_closed.count()
    wins = all_closed.filter(pnl_usdt__gt=0).count()
    losses = all_closed.filter(pnl_usdt__lt=0).count()
    win_rate = round((wins / total_trades * 100), 1) if total_trades else 0

    day_ago = timezone.now() - timedelta(hours=24)
    day_closed = all_closed.filter(closed_at__gte=day_ago)
    pnl_24h = float(sum((t.pnl_usdt for t in day_closed), Decimal(0)))
    trades_24h = day_closed.count()

    week_ago = timezone.now() - timedelta(days=7)
    week_closed = all_closed.filter(closed_at__gte=week_ago)
    pnl_7d = float(sum((t.pnl_usdt for t in week_closed), Decimal(0)))

    open_exposure = float(sum((t.qty * t.entry_price for t in open_trades), Decimal(0)))

    best = all_closed.order_by("-pnl_usdt").first()
    worst = all_closed.order_by("pnl_usdt").first()

    spark_qs = list(all_closed.order_by("closed_at").values_list("pnl_usdt", flat=True)[:200])
    spark = []
    running = 0
    for v in spark_qs:
        running += float(v)
        spark.append(round(running, 2))

    last_event = (all_closed.order_by("-closed_at").values_list("closed_at", flat=True).first()
                  or BotTrade.objects.filter(config=cfg).order_by("-opened_at")
                     .values_list("opened_at", flat=True).first())

    return render(request, "bot_program/home.html", _ctx(request,
        cfg=cfg, acct=acct, open_trades=open_trades,
        closed_trades=closed_trades, scenarios=scenarios,
        equity=equity, pnl_total=pnl_total, pnl_24h=pnl_24h, pnl_7d=pnl_7d,
        total_trades=total_trades, trades_24h=trades_24h,
        wins=wins, losses=losses, win_rate=win_rate,
        open_exposure=open_exposure, best_trade=best, worst_trade=worst,
        spark_data=spark, last_event=last_event,
        weights=cfg.normalized_weights()))''',
      marker="trades_24h")

# =================================================================
# STEP 3 — Enrich core/context_ui.py band entries (16-space indent)
# =================================================================
print("\n[3/3] Enriching headband band entries …")

patch("core/context_ui.py",
      '''                band.append({
                    "symbol": sym,
                    "last": float(q.last or 0),
                    "change_pct": float(q.change_pct or 0),
                    "name": q.instrument.name or sym,
                    "asset_class": q.instrument.asset_class or "",
                    "volume": int(q.volume or 0),
                    "updated": q.updated_at.isoformat() if q.updated_at else "",
                })''',
      '''                from django.utils.timesince import timesince
                band.append({
                    "symbol": sym,
                    "last": float(q.last or 0),
                    "change_pct": float(q.change_pct or 0),
                    "name": q.instrument.name or sym,
                    "asset_class": q.instrument.asset_class or "",
                    "volume": int(q.volume or 0),
                    "bid": float(q.bid) if q.bid else None,
                    "ask": float(q.ask) if q.ask else None,
                    "source": q.source or "",
                    "updated": q.updated_at.isoformat() if q.updated_at else "",
                    "updated_human": (timesince(q.updated_at) + " ago") if q.updated_at else "—",
                })''',
      marker="updated_human")

print("\n" + "━" * 60)
print(" ✓ UPGRADE PASS 7 COMPLETE")
print("━" * 60)
print("""
Restart the dev server (or just refresh — no migrations needed):

  python manage.py runserver

You should now see:
  • A new 40px row of metric chips below the info panel showing
    SPX/NDX/DXY/VIX/BTC/ETH/Gold/Silver/Oil/US10Y/EURUSD/GBPUSD,
    each with a rich hover popup (price, change, asset class,
    volume, bid/ask, source, freshness, "click for chart" CTA).
  • The Bot Program page now shows real numbers in all 8 metric
    cards: capital, P&L, win rate, 24h activity, 7d P&L, open
    exposure, best trade, worst trade — plus the live equity
    sparkline.
  • The dashboard headband popups show source ("yfinance",
    "binance_ws", etc.) and how many seconds/minutes ago the
    quote was updated, so you can see at a glance whether your
    streamers are alive.
""")
