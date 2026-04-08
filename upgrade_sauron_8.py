#!/usr/bin/env python3
"""
upgrade_sauron_8.py
===================
Final polish pass — adds the five remaining items I'd flagged but
not yet shipped.

Drop next to manage.py and run:

    python upgrade_sauron_8.py

Idempotent. No DB migrations.

Adds:
 1. CHANGE PIN form on the profile page (with current-PIN check or
    initial-set if no PIN exists yet).
 2. Bot Configure form rebuilt with the design system — grouped
    sections, .input/.input-group/.input-label styling, no more
    raw {{ form.as_p }}.
 3. Sauron-styled large keypad on the login PIN page for touch
    devices — 0–9 grid + clear/backspace, alongside the existing
    digit boxes for desktop.
 4. Funding rate visualization on the liquidations page — 24h
    funding rate strip per top symbol, with sparklines and the
    flip/extreme/divergence flags from pass 5's funding alerts.
 5. Live status indicator in the topbar — small pill that polls
    /api/live/health/ every 10s and shows green/yellow/red dots
    for each streamer source (binance_ws, binance_futures,
    finnhub, oanda, etc.) based on freshest LiveQuote.source.
"""
from __future__ import annotations
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run from directory containing manage.py"); sys.exit(1)

def _norm(s): return s.replace("\r\n", "\n").replace("\r", "\n")

def write(rel, content, overwrite=True):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not overwrite:
        print(f"  skip: {rel}"); return
    p.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    print(f"  wrote: {rel}")

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
print(" SAURON VISION — UPGRADE PASS 8 (final polish)")
print("━" * 60)

# =================================================================
# STEP 1 — Change PIN view + URL + form on profile page
# =================================================================
print("\n[1/5] Change PIN form on profile page …")

write("dashboard/pin_views.py", '''
    """Change PIN — handled separately from the profile form so it has
    its own POST endpoint with current-PIN verification."""
    from django.contrib import messages
    from django.contrib.auth.decorators import login_required
    from django.contrib.auth.hashers import check_password, make_password
    from django.shortcuts import redirect
    from django.views.decorators.http import require_POST


    @login_required
    @require_POST
    def change_pin(request):
        from portfolio.trader_profile import TraderProfile
        prof, _ = TraderProfile.objects.get_or_create(user=request.user)

        current = request.POST.get("current_pin", "")
        new_pin = request.POST.get("new_pin", "")
        confirm = request.POST.get("confirm_pin", "")

        if not new_pin or len(new_pin) < 4:
            messages.error(request, "New PIN must be at least 4 digits.")
            return redirect("profile")
        if not new_pin.isdigit():
            messages.error(request, "PIN must be digits only.")
            return redirect("profile")
        if new_pin != confirm:
            messages.error(request, "New PIN and confirmation do not match.")
            return redirect("profile")

        # If a PIN exists, require the current one (unless it's the
        # default 0000 — we still verify it though).
        if prof.access_pin_hash:
            if not check_password(current, prof.access_pin_hash):
                messages.error(request, "Current PIN is incorrect.")
                return redirect("profile")

        prof.access_pin_hash = make_password(new_pin)
        prof.save(update_fields=["access_pin_hash"])
        messages.success(request, "PIN updated successfully.")
        return redirect("profile")
''')

patch("dashboard/urls.py",
      'path("profile/", views.profile, name="profile"),',
      '''path("profile/", views.profile, name="profile"),
    path("profile/change-pin/", __import__("dashboard.pin_views", fromlist=["change_pin"]).change_pin, name="change_pin"),''',
      marker="change_pin")

# Inject the PIN form section into profile.html. We add it as a new
# card at the top so it's hard to miss.
PIN_CARD = '''<!-- UPGRADE-8: Change PIN -->
<div class="card" style="margin-bottom:20px;border-left:3px solid var(--accent-gold);">
  <div class="card-header">
    <div class="card-title">🔒 SECURITY — ACCESS PIN</div>
    <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">2nd factor</span>
  </div>
  <p style="font-family:var(--font-mono);font-size:11px;color:var(--text-secondary);margin-bottom:14px;">
    Your PIN is required to complete login after username + password, and to arm the bot in LIVE mode.
    {% if not profile.access_pin_hash %}<br><b style="color:var(--accent-gold);">No PIN is currently set.</b>{% endif %}
  </p>
  <form method="post" action="{% url 'change_pin' %}" style="display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:12px;align-items:end;">
    {% csrf_token %}
    {% if profile.access_pin_hash %}
    <div class="input-group" style="margin-bottom:0;">
      <label class="input-label">CURRENT PIN</label>
      <input type="password" name="current_pin" class="input" inputmode="numeric" maxlength="8" autocomplete="off">
    </div>
    {% else %}<div></div>{% endif %}
    <div class="input-group" style="margin-bottom:0;">
      <label class="input-label">NEW PIN</label>
      <input type="password" name="new_pin" class="input" inputmode="numeric" maxlength="8" autocomplete="new-password" required>
    </div>
    <div class="input-group" style="margin-bottom:0;">
      <label class="input-label">CONFIRM</label>
      <input type="password" name="confirm_pin" class="input" inputmode="numeric" maxlength="8" autocomplete="new-password" required>
    </div>
    <button type="submit" class="btn btn-primary">UPDATE PIN</button>
  </form>
</div>
'''

p = ROOT / "templates/dashboard/profile.html"
if p.exists():
    txt = p.read_text(encoding="utf-8")
    if "UPGRADE-8: Change PIN" in txt:
        print("  PIN card already present in profile.html")
    else:
        # Insert right after the {% block content %} tag
        use_crlf = "\r\n" in txt
        norm = _norm(txt)
        marker = "{% block content %}"
        if marker in norm:
            new_norm = norm.replace(marker, marker + "\n" + PIN_CARD, 1)
            out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
            p.write_text(out, encoding="utf-8")
            print("  inserted PIN card into profile.html")
        else:
            print("  could not find {% block content %} in profile.html")

# =================================================================
# STEP 2 — Polished Bot Configure form
# =================================================================
print("\n[2/5] Polished Bot Configure form …")

write("bot_program/templates/bot_program/configure.html", '''
    {% extends "base.html" %}
    {% block title %}Configure Bot — Sauron Vision{% endblock %}
    {% block page_title %}⚙ BOT CONFIGURATION{% endblock %}
    {% block content %}
    <div class="page-content fade-in" style="max-width:1100px;">

      <a href="{% url 'bot_home' %}" class="btn btn-ghost btn-sm" style="margin-bottom:16px;">← Back to bot</a>

      {% if messages %}{% for m in messages %}
        <div class="card" style="margin-bottom:14px;border-left:3px solid var(--accent);color:var(--accent);">{{ m }}</div>
      {% endfor %}{% endif %}

      <form method="post">
        {% csrf_token %}

        <!-- ── MODE & MARKET ─────────────────────────────────────── -->
        <div class="card" style="margin-bottom:18px;">
          <div class="card-header"><div class="card-title">🎯 MODE &amp; MARKET</div></div>
          <div class="grid grid-2">
            <div class="input-group">
              <label class="input-label">EXECUTION MODE</label>
              <select name="mode" class="input">
                {% for v,l in form.mode.field.choices %}
                  <option value="{{ v }}" {% if form.mode.value == v %}selected{% endif %}>{{ l }}</option>
                {% endfor %}
              </select>
              <div class="input-hint">Paper = simulated · Live = real funds (PIN required to arm)</div>
            </div>
            <div class="input-group">
              <label class="input-label">MARKET TYPE</label>
              <select name="market_type" class="input">
                {% for v,l in form.market_type.field.choices %}
                  <option value="{{ v }}" {% if form.market_type.value == v %}selected{% endif %}>{{ l }}</option>
                {% endfor %}
              </select>
              <div class="input-hint">Spot = no leverage · Futures = leveraged USDT-M</div>
            </div>
          </div>
          <div class="grid grid-2">
            <div class="input-group">
              <label class="input-label">MARGIN MODE (futures only)</label>
              <select name="margin_mode" class="input">
                {% for v,l in form.margin_mode.field.choices %}
                  <option value="{{ v }}" {% if form.margin_mode.value == v %}selected{% endif %}>{{ l }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="input-group">
              <label class="input-label">LEVERAGE</label>
              <input type="number" name="leverage" value="{{ form.leverage.value }}" step="1" min="1" max="125" class="input">
              <div class="input-hint">1 = spot equivalent · max 125× on Binance futures</div>
            </div>
          </div>
        </div>

        <!-- ── UNIVERSE & SIZING ─────────────────────────────────── -->
        <div class="card" style="margin-bottom:18px;">
          <div class="card-header"><div class="card-title">💰 CAPITAL &amp; UNIVERSE</div></div>
          <div class="input-group">
            <label class="input-label">SYMBOLS (JSON array)</label>
            <textarea name="symbols" class="input" rows="2" style="font-family:var(--font-mono);">{{ form.symbols.value }}</textarea>
            <div class="input-hint">Example: ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT"]</div>
          </div>
          <div class="grid grid-3">
            <div class="input-group">
              <label class="input-label">CAPITAL (USDT)</label>
              <input type="number" name="capital_usdt" value="{{ form.capital_usdt.value }}" step="0.01" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">POSITION SIZE %</label>
              <input type="number" name="position_size_pct" value="{{ form.position_size_pct.value }}" step="0.1" class="input">
              <div class="input-hint">% of capital per trade</div>
            </div>
            <div class="input-group">
              <label class="input-label">MAX CONCURRENT</label>
              <input type="number" name="max_concurrent_positions" value="{{ form.max_concurrent_positions.value }}" step="1" class="input">
            </div>
          </div>
          <div class="grid grid-2">
            <div class="input-group">
              <label class="input-label">BASE QUOTE</label>
              <input type="text" name="base_quote" value="{{ form.base_quote.value }}" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">BOT NAME</label>
              <input type="text" name="name" value="{{ form.name.value }}" class="input">
            </div>
          </div>
        </div>

        <!-- ── RISK MANAGEMENT ───────────────────────────────────── -->
        <div class="card" style="margin-bottom:18px;">
          <div class="card-header"><div class="card-title">🛡 RISK MANAGEMENT</div></div>
          <div class="grid grid-4">
            <div class="input-group">
              <label class="input-label">STOP LOSS %</label>
              <input type="number" name="stop_loss_pct" value="{{ form.stop_loss_pct.value }}" step="0.1" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">TAKE PROFIT %</label>
              <input type="number" name="take_profit_pct" value="{{ form.take_profit_pct.value }}" step="0.1" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">TRAILING %</label>
              <input type="number" name="trailing_stop_pct" value="{{ form.trailing_stop_pct.value }}" step="0.1" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">MAX DAILY LOSS %</label>
              <input type="number" name="max_daily_loss_pct" value="{{ form.max_daily_loss_pct.value }}" step="0.1" class="input">
            </div>
          </div>
          <div style="display:flex;gap:24px;margin-top:6px;">
            <label style="display:flex;align-items:center;gap:8px;font-family:var(--font-mono);font-size:11px;color:var(--text-secondary);">
              <input type="checkbox" name="halt_on_high_impact_news" {% if form.halt_on_high_impact_news.value %}checked{% endif %}>
              HALT ON HIGH-IMPACT NEWS
            </label>
            <label style="display:flex;align-items:center;gap:8px;font-family:var(--font-mono);font-size:11px;color:var(--text-secondary);">
              <input type="checkbox" name="halt_on_drawdown" {% if form.halt_on_drawdown.value %}checked{% endif %}>
              HALT ON DRAWDOWN
            </label>
          </div>
        </div>

        <!-- ── STRATEGY WEIGHTS ──────────────────────────────────── -->
        <div class="card" style="margin-bottom:18px;">
          <div class="card-header"><div class="card-title">⚖ STRATEGY WEIGHTS</div></div>
          <p style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);margin-bottom:12px;">
            How much each signal source contributes to the composite decision. Values are normalised at runtime, so absolute scale doesn't matter — only relative ratios.
          </p>
          <div class="grid grid-3">
            <div class="input-group">
              <label class="input-label">TECHNICAL (TA)</label>
              <input type="number" name="w_technical" value="{{ form.w_technical.value }}" step="0.05" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">SAURON SIGNALS</label>
              <input type="number" name="w_sauron_sig" value="{{ form.w_sauron_sig.value }}" step="0.05" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">NEWS SENTIMENT</label>
              <input type="number" name="w_news" value="{{ form.w_news.value }}" step="0.05" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">LIQUIDITY (L2)</label>
              <input type="number" name="w_liquidity" value="{{ form.w_liquidity.value }}" step="0.05" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">MACRO REGIME</label>
              <input type="number" name="w_macro" value="{{ form.w_macro.value }}" step="0.05" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">SOCIAL SENTIMENT</label>
              <input type="number" name="w_sentiment" value="{{ form.w_sentiment.value }}" step="0.05" class="input">
            </div>
          </div>
        </div>

        <!-- ── ENTRY / EXIT THRESHOLDS ───────────────────────────── -->
        <div class="card" style="margin-bottom:18px;">
          <div class="card-header"><div class="card-title">📊 ENTRY &amp; TIMING</div></div>
          <div class="grid grid-4">
            <div class="input-group">
              <label class="input-label">ENTRY MIN SCORE</label>
              <input type="number" name="entry_score_min" value="{{ form.entry_score_min.value }}" step="0.05" class="input">
              <div class="input-hint">0–1 · Open if &gt;= this</div>
            </div>
            <div class="input-group">
              <label class="input-label">EXIT MAX SCORE</label>
              <input type="number" name="exit_score_max" value="{{ form.exit_score_max.value }}" step="0.05" class="input">
            </div>
            <div class="input-group">
              <label class="input-label">TIMEFRAME</label>
              <input type="text" name="timeframe" value="{{ form.timeframe.value }}" class="input">
              <div class="input-hint">1m / 5m / 15m / 1h</div>
            </div>
            <div class="input-group">
              <label class="input-label">TICK INTERVAL (s)</label>
              <input type="number" name="tick_interval_sec" value="{{ form.tick_interval_sec.value }}" step="1" class="input">
            </div>
          </div>
          <div class="grid grid-2">
            <div class="input-group">
              <label class="input-label">COOLDOWN (min)</label>
              <input type="number" name="cool_down_minutes" value="{{ form.cool_down_minutes.value }}" step="1" class="input">
              <div class="input-hint">Wait this long after closing a trade before re-entering same symbol</div>
            </div>
          </div>
        </div>

        <div style="display:flex;gap:12px;justify-content:flex-end;">
          <a href="{% url 'bot_home' %}" class="btn btn-ghost">CANCEL</a>
          <button type="submit" class="btn btn-primary btn-lg">💾 SAVE CONFIGURATION</button>
        </div>
      </form>
    </div>
    {% endblock %}
''')

# =================================================================
# STEP 3 — Touch-friendly keypad on login PIN page
# =================================================================
print("\n[3/5] Sauron-styled keypad on login PIN page …")

p = ROOT / "templates/registration/login_pin.html"
if p.exists():
    txt = p.read_text(encoding="utf-8")
    if "sauron-keypad" in txt:
        print("  keypad already present")
    else:
        # Insert keypad div after the </form> closing the existing form
        marker = '</form>'
        KEYPAD = '''</form>
      <div class="sauron-keypad">
        <button type="button" data-k="1">1</button>
        <button type="button" data-k="2">2</button>
        <button type="button" data-k="3">3</button>
        <button type="button" data-k="4">4</button>
        <button type="button" data-k="5">5</button>
        <button type="button" data-k="6">6</button>
        <button type="button" data-k="7">7</button>
        <button type="button" data-k="8">8</button>
        <button type="button" data-k="9">9</button>
        <button type="button" data-k="clear" class="kp-fn">⨯</button>
        <button type="button" data-k="0">0</button>
        <button type="button" data-k="back" class="kp-fn">⌫</button>
      </div>'''
        if marker in txt:
            txt = txt.replace(marker, KEYPAD, 1)

        # Inject keypad CSS into the existing <style> block
        css_add = '''
      /* UPGRADE-8: touch keypad */
      .sauron-keypad{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:18px}
      .sauron-keypad button{padding:14px 0;background:#060e0a;border:1px solid #133020;border-radius:8px;color:#c8e8d8;font-family:'Orbitron',sans-serif;font-size:18px;font-weight:700;cursor:pointer;transition:all .15s}
      .sauron-keypad button:hover{border-color:#00e868;color:#00e868;box-shadow:0 0 14px rgba(0,232,104,.18)}
      .sauron-keypad button:active{transform:scale(.95);background:#0a1a14}
      .sauron-keypad button.kp-fn{color:#5a8a6a;font-size:14px}
      .sauron-keypad button.kp-fn:hover{color:#e83030;border-color:#581818}
'''
        txt = txt.replace("</style>", css_add + "\n    </style>", 1)

        # Inject keypad wiring into the <script>
        script_add = '''
      // UPGRADE-8: keypad wiring
      document.querySelectorAll('.sauron-keypad button').forEach(btn=>{
        btn.addEventListener('click',()=>{
          const k=btn.dataset.k;
          if(k==='clear'){boxes.forEach(b=>b.value='');boxes[0].focus();}
          else if(k==='back'){
            for(let i=boxes.length-1;i>=0;i--){if(boxes[i].value){boxes[i].value='';boxes[i].focus();break;}}
          } else {
            for(let i=0;i<boxes.length;i++){if(!boxes[i].value){boxes[i].value=k;if(i<boxes.length-1)boxes[i+1].focus();break;}}
          }
          document.getElementById('pinFinal').value=boxes.map(x=>x.value).join('');
        });
      });
'''
        txt = txt.replace("</script>", script_add + "\n    </script>", 1)
        p.write_text(txt, encoding="utf-8")
        print("  injected keypad markup + CSS + JS into login_pin.html")

# =================================================================
# STEP 4 — Funding rate panel on liquidations page
# =================================================================
print("\n[4/5] Funding rate panel on liquidations page …")

patch("dashboard/liquidations_view.py",
      '''@login_required
def liquidations_page(request):
    from market_data.models import LiquidationEvent
    symbol = (request.GET.get("symbol") or "BTCUSDT").upper()
    window = request.GET.get("window", "24h")
    hours = WINDOWS.get(window, 24)
    agg = _aggregate(symbol, hours)
    # Symbol choices: distinct symbols that have liquidations in last 7d
    symbols = list(LiquidationEvent.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=7)
    ).values_list("symbol", flat=True).distinct()[:30])
    if symbol not in symbols: symbols.insert(0, symbol)
    recent = list(LiquidationEvent.objects.filter(symbol=symbol).values(
        "side","price","qty","notional_usd","timestamp")[:30])
    return render(request, "dashboard/liquidations.html", {
        "page_id": "liquidations", "symbol": symbol, "window": window,
        "hours": hours, "agg": agg, "symbols": symbols, "recent": recent,
        "windows": list(WINDOWS.keys()),
    })''',
      '''@login_required
def liquidations_page(request):
    from market_data.models import LiquidationEvent, FundingRate
    symbol = (request.GET.get("symbol") or "BTCUSDT").upper()
    window = request.GET.get("window", "24h")
    hours = WINDOWS.get(window, 24)
    agg = _aggregate(symbol, hours)
    symbols = list(LiquidationEvent.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=7)
    ).values_list("symbol", flat=True).distinct()[:30])
    if symbol not in symbols: symbols.insert(0, symbol)
    recent = list(LiquidationEvent.objects.filter(symbol=symbol).values(
        "side","price","qty","notional_usd","timestamp")[:30])

    # Funding panel data — top symbols by recent funding activity
    funding_symbols = list(FundingRate.objects.filter(
        timestamp__gte=timezone.now() - timedelta(hours=24)
    ).values_list("symbol", flat=True).distinct()[:8])
    funding_data = []
    for sym in funding_symbols:
        rows = list(FundingRate.objects.filter(
            symbol=sym, timestamp__gte=timezone.now() - timedelta(hours=24)
        ).order_by("timestamp").values("funding_rate","mark_price","timestamp")[:200])
        if not rows: continue
        rates = [float(r["funding_rate"] or 0) for r in rows]
        cur = rates[-1]
        avg = sum(rates) / len(rates) if rates else 0
        extreme = abs(cur) >= 0.001
        sign_flips = sum(1 for i in range(1, len(rates)) if rates[i]*rates[i-1] < 0)
        funding_data.append({
            "symbol": sym,
            "current": cur,
            "current_pct": cur * 100,
            "avg_pct": avg * 100,
            "mark": float(rows[-1]["mark_price"] or 0),
            "extreme": extreme,
            "sign_flips": sign_flips,
            "spark": rates[-60:],
            "samples": len(rates),
        })
    funding_data.sort(key=lambda x: abs(x["current"]), reverse=True)

    return render(request, "dashboard/liquidations.html", {
        "page_id": "liquidations", "symbol": symbol, "window": window,
        "hours": hours, "agg": agg, "symbols": symbols, "recent": recent,
        "windows": list(WINDOWS.keys()),
        "funding_data": funding_data,
    })''',
      marker="funding_data")

# Inject funding panel HTML into the liquidations template
p = ROOT / "templates/dashboard/liquidations.html"
if p.exists():
    txt = p.read_text(encoding="utf-8")
    if "funding-panel" in txt:
        print("  funding panel already present in liquidations.html")
    else:
        FUNDING_PANEL = '''
      <!-- UPGRADE-8: Funding rate panel -->
      <div class="card funding-panel" style="margin-top:18px;">
        <div class="card-header">
          <div class="card-title">💸 FUNDING RATES (24H)</div>
          <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
            Positive = longs pay shorts · Negative = shorts pay longs · |≥0.1%| = extreme
          </div>
        </div>
        {% if funding_data %}
        <div class="funding-grid">
          {% for f in funding_data %}
          <div class="funding-card {% if f.extreme %}extreme{% endif %}">
            <div class="funding-head">
              <span class="funding-sym">{{ f.symbol }}</span>
              {% if f.extreme %}<span class="funding-badge">EXTREME</span>{% endif %}
              {% if f.sign_flips > 0 %}<span class="funding-flip">⚡{{ f.sign_flips }}</span>{% endif %}
            </div>
            <div class="funding-rate" style="color:{% if f.current > 0 %}var(--accent-red){% elif f.current < 0 %}var(--accent){% else %}var(--text-muted){% endif %};">
              {% if f.current >= 0 %}+{% endif %}{{ f.current_pct|floatformat:4 }}%
            </div>
            <div class="funding-meta">
              <span>MARK ${{ f.mark|floatformat:2 }}</span>
              <span>AVG {{ f.avg_pct|floatformat:4 }}%</span>
            </div>
            <canvas class="funding-spark" data-spark="{{ f.spark|join:',' }}" data-current="{{ f.current }}" height="32"></canvas>
          </div>
          {% endfor %}
        </div>
        {% else %}
          <div style="padding:24px;text-align:center;color:var(--text-muted);font-family:var(--font-mono);font-size:11px;">
            No funding data yet. Make sure <code>stream_binance_futures</code> is running.
          </div>
        {% endif %}
      </div>

      <style>
        .funding-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
        .funding-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px 16px;transition:all .2s}
        .funding-card:hover{border-color:var(--border-glow);transform:translateY(-2px)}
        .funding-card.extreme{border-color:var(--accent-gold);box-shadow:0 0 20px rgba(216,176,32,.12)}
        .funding-head{display:flex;align-items:center;gap:8px;margin-bottom:6px}
        .funding-sym{font-family:var(--font-display);font-size:13px;font-weight:700;color:var(--text-primary)}
        .funding-badge{font-family:var(--font-mono);font-size:8px;letter-spacing:1px;padding:2px 6px;border-radius:4px;background:rgba(216,176,32,.15);color:var(--accent-gold);font-weight:700}
        .funding-flip{font-family:var(--font-mono);font-size:10px;color:var(--accent-gold);margin-left:auto}
        .funding-rate{font-family:var(--font-display);font-size:22px;font-weight:900;margin-bottom:6px}
        .funding-meta{display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:9px;color:var(--text-muted);margin-bottom:8px}
        .funding-spark{width:100%;display:block}
      </style>

      <script>
      (function(){
        document.querySelectorAll('.funding-spark').forEach(function(c){
          var raw=(c.dataset.spark||'').split(',').filter(Boolean).map(parseFloat);
          var cur=parseFloat(c.dataset.current||0);
          if(!raw.length)return;
          c.width=c.offsetWidth;var W=c.width,H=c.height;
          var ctx=c.getContext('2d');
          var mn=Math.min.apply(null,raw),mx=Math.max.apply(null,raw);
          if(mn===mx)mx=mn+1e-6;
          var zy=H-(0-mn)/(mx-mn)*H;
          ctx.strokeStyle='#133020';ctx.setLineDash([2,2]);ctx.beginPath();
          ctx.moveTo(0,zy);ctx.lineTo(W,zy);ctx.stroke();ctx.setLineDash([]);
          ctx.strokeStyle=cur>=0?'#e83030':'#00e868';ctx.lineWidth=1.5;ctx.beginPath();
          raw.forEach(function(v,i){var x=i/(raw.length-1)*W;var y=H-(v-mn)/(mx-mn)*H;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
          ctx.stroke();
        });
      })();
      </script>
'''
        # Insert just before the recent liquidations card
        marker = '<!-- Recent liquidations feed -->'
        if marker in txt:
            txt = txt.replace(marker, FUNDING_PANEL + "\n      " + marker, 1)
            p.write_text(txt, encoding="utf-8")
            print("  inserted funding panel into liquidations.html")
        else:
            # Fallback: before {% endblock %}
            txt = txt.replace("{% endblock %}", FUNDING_PANEL + "\n    {% endblock %}", 1)
            p.write_text(txt, encoding="utf-8")
            print("  inserted funding panel into liquidations.html (fallback)")

# =================================================================
# STEP 5 — Live status pill in topbar + /api/live/health endpoint
# =================================================================
print("\n[5/5] Live status indicator in topbar …")

write("dashboard/live_health.py", '''
    """Streamer health endpoint — reports freshness per data source."""
    from datetime import timedelta
    from django.contrib.auth.decorators import login_required
    from django.http import JsonResponse
    from django.utils import timezone
    from django.views.decorators.cache import never_cache


    @never_cache
    @login_required
    def live_health(request):
        """Returns freshness for each `source` value seen in LiveQuote.
        Status: green (<60s old), yellow (<10min), red (older or missing)."""
        from market_data.models import LiveQuote
        try:
            from django.db.models import Max
            now = timezone.now()
            # Group by source, take freshest updated_at
            by_src = (LiveQuote.objects.values("source")
                      .annotate(latest=Max("updated_at")))
            sources = []
            for row in by_src:
                src = (row["source"] or "unknown").strip()
                if not src or src == "unknown":
                    continue
                latest = row["latest"]
                if not latest:
                    state = "red"; age_s = None
                else:
                    age_s = (now - latest).total_seconds()
                    if age_s < 60: state = "green"
                    elif age_s < 600: state = "yellow"
                    else: state = "red"
                sources.append({
                    "source": src, "state": state, "age_seconds": age_s,
                    "latest": latest.isoformat() if latest else None,
                })
            sources.sort(key=lambda s: s["source"])

            # Recent liquidations + funding as bonus health signals
            from market_data.models import LiquidationEvent, FundingRate
            try:
                last_liq = LiquidationEvent.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()
                last_fund = FundingRate.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()
            except Exception:
                last_liq = last_fund = None
            return JsonResponse({
                "sources": sources,
                "last_liquidation_age": (now - last_liq).total_seconds() if last_liq else None,
                "last_funding_age":     (now - last_fund).total_seconds() if last_fund else None,
            })
        except Exception as e:
            return JsonResponse({"error": str(e), "sources": []}, status=200)
''')

# Wire URL
patch("dashboard/urls.py",
      'path("api/live/metrics/", __import__("dashboard.news_detail", fromlist=["live_metrics_json"]).live_metrics_json, name="live_metrics"),',
      '''path("api/live/metrics/", __import__("dashboard.news_detail", fromlist=["live_metrics_json"]).live_metrics_json, name="live_metrics"),
    path("api/live/health/", __import__("dashboard.live_health", fromlist=["live_health"]).live_health, name="live_health"),''',
      marker="live_health")

# Inject the topbar pill markup
LIVE_PILL = '''<!-- UPGRADE-8: Live status pill -->
                <div class="live-status-pill" id="liveStatusPill" title="Live data sources">
                  <span class="lsp-dot lsp-flat"></span>
                  <span class="lsp-label">LIVE</span>
                  <div class="lsp-dropdown" id="liveStatusDropdown">
                    <div class="lsp-head">DATA SOURCES</div>
                    <div class="lsp-body" id="lspBody">
                      <div class="lsp-empty">checking…</div>
                    </div>
                  </div>
                </div>
                '''

p = ROOT / "templates/base.html"
btxt = p.read_text(encoding="utf-8")
if "live-status-pill" in btxt:
    print("  live status pill already present")
else:
    use_crlf = "\r\n" in btxt
    norm = _norm(btxt)
    # Insert just before the existing .notif-bell div
    marker_bell = '<!-- Notification Bell -->'
    if marker_bell in norm:
        new_norm = norm.replace(marker_bell, LIVE_PILL + "\n                " + marker_bell, 1)
        out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
        p.write_text(out, encoding="utf-8")
        print("  inserted live status pill into topbar")
    else:
        print("  could not find notification bell anchor for live pill")

# Inject the pill CSS + JS
LIVE_PILL_CSS = '''
        /* UPGRADE-8: Live status pill */
        .live-status-pill{position:relative;display:flex;align-items:center;gap:6px;padding:5px 10px;border:1px solid var(--border);border-radius:14px;cursor:pointer;font-family:var(--font-mono);font-size:10px;letter-spacing:1.5px;color:var(--text-secondary);transition:all .2s}
        .live-status-pill:hover{border-color:var(--accent);color:var(--accent)}
        .lsp-dot{width:8px;height:8px;border-radius:50%}
        .lsp-dot.lsp-green{background:var(--accent);box-shadow:0 0 8px var(--accent);animation:lspPulse 2s infinite}
        .lsp-dot.lsp-yellow{background:var(--accent-gold);box-shadow:0 0 6px var(--accent-gold)}
        .lsp-dot.lsp-red{background:var(--accent-red);box-shadow:0 0 6px var(--accent-red)}
        .lsp-dot.lsp-flat{background:var(--text-muted)}
        @keyframes lspPulse{0%,100%{opacity:1}50%{opacity:.5}}
        .lsp-dropdown{display:none;position:absolute;top:calc(100% + 6px);right:0;min-width:280px;background:var(--bg-card);border:1px solid var(--border-glow);border-radius:var(--radius-lg);padding:12px 14px;z-index:300;box-shadow:0 12px 40px rgba(0,0,0,.6)}
        .live-status-pill:hover .lsp-dropdown{display:block}
        .lsp-head{font-family:var(--font-mono);font-size:9px;letter-spacing:2px;color:var(--text-muted);margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid var(--border)}
        .lsp-row{display:flex;align-items:center;gap:10px;padding:6px 0;font-family:var(--font-mono);font-size:11px}
        .lsp-row + .lsp-row{border-top:1px dashed var(--border)}
        .lsp-row .lsp-src{flex:1;color:var(--text-primary)}
        .lsp-row .lsp-age{color:var(--text-muted);font-size:10px}
        .lsp-empty{color:var(--text-muted);font-size:10px;text-align:center;padding:10px}
'''

if "UPGRADE-8: Live status pill" not in p.read_text(encoding="utf-8"):
    patch("templates/base.html",
          "</style>{% block extra_css %}{% endblock %}",
          LIVE_PILL_CSS + "\n        </style>{% block extra_css %}{% endblock %}",
          marker="UPGRADE-8: Live status pill")

LIVE_PILL_JS = '''
<script>
/* UPGRADE-8: Live status poller */
(function(){
  function fmt(s){if(s==null)return '—';if(s<60)return Math.round(s)+'s';if(s<3600)return Math.round(s/60)+'m';return Math.round(s/3600)+'h';}
  function tick(){
    fetch('/api/live/health/',{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(d=>{
      if(!d)return;
      var dot=document.querySelector('#liveStatusPill .lsp-dot');
      var label=document.querySelector('#liveStatusPill .lsp-label');
      var body=document.getElementById('lspBody');
      if(!body||!dot)return;
      var srcs=d.sources||[];
      // Worst-case state for the pill
      var hasGreen=srcs.some(s=>s.state==='green');
      var hasYellow=srcs.some(s=>s.state==='yellow');
      var hasRed=srcs.some(s=>s.state==='red');
      dot.className='lsp-dot '+(hasRed?'lsp-red':hasYellow?'lsp-yellow':hasGreen?'lsp-green':'lsp-flat');
      label.textContent=hasGreen?'LIVE':'STALE';
      if(!srcs.length){body.innerHTML='<div class="lsp-empty">No streamers connected.<br>Start one: <code>python manage.py stream_binance</code></div>';return;}
      body.innerHTML=srcs.map(function(s){
        return '<div class="lsp-row"><span class="lsp-dot lsp-'+s.state+'"></span><span class="lsp-src">'+s.source+'</span><span class="lsp-age">'+fmt(s.age_seconds)+' ago</span></div>';
      }).join('');
    }).catch(function(){});
  }
  setInterval(tick,10000);
  setTimeout(tick,1500);
})();
</script>
'''

if "UPGRADE-8: Live status poller" not in p.read_text(encoding="utf-8"):
    btxt = p.read_text(encoding="utf-8")
    if "</body>" in btxt:
        btxt = btxt.replace("</body>", LIVE_PILL_JS + "\n</body>", 1)
        p.write_text(btxt, encoding="utf-8")
        print("  injected live status poller JS")

print("\n" + "━" * 60)
print(" ✓ UPGRADE PASS 8 COMPLETE")
print("━" * 60)
print("""
Restart the dev server (no migrations):
  python manage.py runserver

What to look for:
  • Profile page → top of the page now has a "🔒 SECURITY — ACCESS PIN"
    card. Set a new PIN with current-PIN verification (or initial set
    if you don't have one).
  • Bot Configure page → fully redesigned with grouped sections (Mode &
    Market, Capital & Universe, Risk Management, Strategy Weights,
    Entry & Timing) and proper input styling.
  • Login PIN page → 12-key Sauron-styled keypad below the digit
    boxes. Tap-friendly on mobile, also works with mouse.
  • Liquidations page → new "FUNDING RATES (24H)" card showing top
    symbols by funding magnitude with sparklines, EXTREME badges,
    and sign-flip counters. Data populates as stream_binance_futures
    runs.
  • Topbar → new pulsing "● LIVE" pill next to the notification bell.
    Hover for a dropdown showing every data source (binance_ws,
    binance_futures, finnhub, oanda, etc.) with green/yellow/red
    health based on freshness of the latest LiveQuote per source.
""")
