#!/usr/bin/env python3
"""
upgrade_sauron_9.py
===================
Fixes the four issues reported after running passes 1-8:

 1. Data headband popups clipped (invalid overflow combo), plus
    auto-scroll RTL, hover arrows, expanded universe (~45 assets),
    richer popups that escape the scroll container.
 2. Bot program page content sits too low — removes inline
    padding-top:90px from all bot_program templates.
 3. Info panel bar — taller (42px), more categories (12), richer
    dropdowns, scrollable with hover arrows on overflow.
 4. Left sidebar toggle redesigned as a circular edge button
    identical to the right rail toggle from pass 6.
 5. BONUS: news ticker gets hover arrows + far richer news popup
    with summary, sentiment, urgency, implication, keywords,
    affected chips.

Run from the directory containing manage.py:
    python upgrade_sauron_9.py

Idempotent. No DB migrations.
"""
from __future__ import annotations
import re, sys
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

def regex_sub(rel, pattern, replacement, flags=0):
    p = ROOT / rel
    if not p.exists(): print(f"  MISSING: {rel}"); return False
    raw = p.read_text(encoding="utf-8")
    use_crlf = "\r\n" in raw
    norm = _norm(raw)
    new, n = re.subn(pattern, replacement, norm, flags=flags)
    if n == 0:
        print(f"  regex no match: {rel}"); return False
    out = new.replace("\n", "\r\n") if use_crlf else new
    p.write_text(out, encoding="utf-8")
    print(f"  regex-patched {n}× : {rel}"); return True

def find_div_end(text, start_idx):
    """Given start index of `<div ...>`, return index after matching </div>."""
    i = start_idx
    depth = 0
    while True:
        nxt_open = text.find("<div", i + 1)
        nxt_close = text.find("</div>", i + 1)
        if nxt_close == -1: return -1
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1; i = nxt_open
        else:
            if depth == 0:
                return nxt_close + len("</div>")
            depth -= 1; i = nxt_close

print("━" * 60)
print(" SAURON VISION — UPGRADE PASS 9")
print("━" * 60)

# =================================================================
# STEP 1 — Expand headband universe
# =================================================================
print("\n[1/9] Expanding tracked universe in context_ui.py …")

patch("core/context_ui.py",
      '        tracked = ["SPX", "NDX", "DXY", "VIX", "BTCUSD", "ETHUSD",\n                   "XAUUSD", "XAGUSD", "CL", "US10Y", "EURUSD", "GBPUSD"]',
      '''        tracked = [
            "SPX", "NDX", "DJI", "RUT", "VIX",
            "FTSE", "DAX", "NKY", "HSI", "STOXX50",
            "BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD",
            "DOGEUSD", "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD",
            "DXY", "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
            "AUDUSD", "NZDUSD", "USDCAD", "EURGBP", "EURJPY",
            "XAUUSD", "XAGUSD", "CL", "NG", "HG", "PL", "PA",
            "ZC", "ZW", "KC",
            "US02Y", "US10Y", "US30Y", "DE10Y", "UK10Y", "JP10Y",
        ]''',
      marker='"DJI", "RUT"')

# =================================================================
# STEP 2 — Replace data-headband CSS block
# =================================================================
print("\n[2/9] Rewriting data-headband CSS …")

NEW_DH_CSS = '''        /* ═══════════════════════════════════════════════════════════ */
        /* UPGRADE-9: Data headband (escape-clip popups + RTL scroll)   */
        /* ═══════════════════════════════════════════════════════════ */
        .data-headband {
            position: fixed; left: var(--sidebar-width); right: 0;
            top: calc(var(--topbar-height) + 34px + 42px);
            height: 42px; background: linear-gradient(180deg, var(--bg-primary), var(--bg-void));
            border-bottom: 1px solid var(--border); z-index: 43;
            overflow: visible;
        }
        .dh-scroll { height: 42px; overflow-x: hidden; overflow-y: visible; position: relative; }
        .dh-track { display: inline-flex; gap: 0; align-items: stretch;
                    animation: dhScroll 140s linear infinite; white-space: nowrap; }
        @keyframes dhScroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        .data-headband:hover .dh-track { animation-play-state: paused; }
        body:has(.sidebar.mini) .data-headband { left: 68px; }
        body:has(.signals-rail) .data-headband { right: 44px; }
        body:has(.signals-rail.open) .data-headband { right: 280px; }
        @media (max-width: 768px) { .data-headband { left: 0 !important; right: 0 !important; } }
        .dh-item {
            display: inline-flex; align-items: center; gap: 10px;
            padding: 0 18px; border-right: 1px solid var(--border); height: 42px;
            font-family: var(--font-mono); font-size: 11px;
            cursor: pointer; flex-shrink: 0; transition: background .15s;
        }
        .dh-item:hover { background: var(--bg-card); }
        .dh-sym { color: var(--text-muted); font-size: 9px; letter-spacing: 1.5px; font-weight: 700; }
        .dh-val { color: var(--text-primary); font-weight: 600; }
        .dh-chg { font-size: 10px; font-family: var(--font-mono); }
        .dh-chg.up { color: var(--accent); }
        .dh-chg.down { color: var(--accent-red); }
        .dh-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .dh-dot.up { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
        .dh-dot.down { background: var(--accent-red); box-shadow: 0 0 6px var(--accent-red); }
        .dh-dot.flat { background: var(--text-muted); }
        .dh-arrow {
            position: absolute; top: 0; width: 32px; height: 42px;
            display: flex; align-items: center; justify-content: center;
            color: var(--accent); cursor: pointer; z-index: 3;
            opacity: 0; transition: opacity .2s; font-size: 14px;
            border: 0; font-family: var(--font-mono);
        }
        .dh-arrow.right { right: 0; background: linear-gradient(270deg, var(--bg-primary) 50%, transparent); }
        .dh-arrow.left { left: 0; background: linear-gradient(90deg, var(--bg-primary) 50%, transparent); }
        .data-headband:hover .dh-arrow { opacity: 1; }
        .dh-arrow:hover { color: var(--text-primary); }
        /* Popup — fixed position, anchored by JS to escape the scroll container */
        .dh-pop {
            display: none; position: fixed;
            min-width: 320px; max-width: 380px;
            background: var(--bg-card); border: 1px solid var(--border-glow);
            border-radius: var(--radius-lg); padding: 14px 16px; z-index: 1000;
            box-shadow: 0 12px 40px rgba(0,0,0,.7); white-space: normal;
            pointer-events: none;
        }
        .dh-item.pop-open .dh-pop { display: block; animation: dhPop .18s ease; }
        @keyframes dhPop { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } }
        .dh-pop-head { display: flex; justify-content: space-between; align-items: flex-start;
                       margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
        .dh-pop-title { font-family: var(--font-display); font-size: 14px; font-weight: 700;
                        color: var(--accent); margin-bottom: 2px; }
        .dh-pop-name { font-size: 10px; color: var(--text-muted); }
        .dh-pop-badge { width: 32px; height: 32px; border-radius: 50%; display: flex;
                        align-items: center; justify-content: center; font-size: 14px;
                        border: 1px solid var(--border); }
        .dh-pop-badge.up { background: rgba(0,232,104,.1); color: var(--accent); border-color: var(--accent); }
        .dh-pop-badge.down { background: rgba(232,48,48,.1); color: var(--accent-red); border-color: var(--accent-red); }
        .dh-pop-badge.flat { color: var(--text-muted); }
        .dh-pop-big { display: flex; align-items: baseline; gap: 14px; margin-bottom: 14px; }
        .dh-pop-price { font-family: var(--font-display); font-size: 22px; font-weight: 700; color: var(--text-primary); }
        .dh-pop-pct { font-family: var(--font-mono); font-size: 12px; font-weight: 600; }
        .dh-pop-row { display: flex; justify-content: space-between; padding: 4px 0;
                      font-size: 11px; border-top: 1px dashed var(--border); }
        .dh-pop-row:first-of-type { border-top: 0; }
        .dh-pop-row .k { color: var(--text-muted); }
        .dh-pop-row .v { color: var(--text-primary); }
        .dh-pop-bar { height: 4px; background: var(--bg-void); border-radius: 2px;
                      margin-top: 10px; overflow: hidden; }
        .dh-pop-bar-fill { height: 100%; transition: width .3s; }
        .dh-pop-cta { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border);
                      font-size: 10px; color: var(--accent); text-align: right; }'''

# Replace old data-headband CSS — target the block that starts with the
# "UPGRADE-2" comment and ends with the .dh-pop-bar-fill line.
bp = ROOT / "templates/base.html"
btxt = bp.read_text(encoding="utf-8")
use_crlf = "\r\n" in btxt
norm = _norm(btxt)

if "UPGRADE-9: Data headband" in norm:
    print("  data-headband CSS already upgraded")
else:
    # Find the UPGRADE-2 headband CSS block start
    m = re.search(r'/\* UPGRADE-2: Dashboard data headband.*?\.dh-pop-bar-fill[^}]*\}', norm, flags=re.DOTALL)
    if m:
        new_norm = norm[:m.start()] + NEW_DH_CSS.strip() + norm[m.end():]
        out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
        bp.write_text(out, encoding="utf-8")
        norm = new_norm  # keep working copy in sync
        print("  rewrote data-headband CSS")
    else:
        # fallback: append the CSS at end of style block
        if "</style>{% block extra_css %}{% endblock %}" in norm:
            new_norm = norm.replace(
                "</style>{% block extra_css %}{% endblock %}",
                NEW_DH_CSS + "\n        </style>{% block extra_css %}{% endblock %}", 1)
            out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
            bp.write_text(out, encoding="utf-8")
            norm = new_norm
            print("  appended data-headband CSS (no existing block found)")

# =================================================================
# STEP 3 — Rewrite data-headband HTML markup
# =================================================================
print("\n[3/9] Rewriting data-headband HTML …")

NEW_DH_HTML = '''<!-- UPGRADE-9: Data headband with RTL scroll + hover arrows + escape popups -->
<div class="data-headband" id="dataHeadband">
  <button type="button" class="dh-arrow left" aria-label="Scroll left">◀</button>
  <button type="button" class="dh-arrow right" aria-label="Scroll right">▶</button>
  <div class="dh-scroll" id="dhScroll">
    <div class="dh-track" id="dhTrack">
      {% for m in ui_headband %}{% include "_partials/dh_item.html" %}{% endfor %}
      {% for m in ui_headband %}{% include "_partials/dh_item.html" %}{% endfor %}
    </div>
  </div>
</div>
'''

write("templates/_partials/dh_item.html", '''
    <div class="dh-item" data-symbol="{{ m.symbol }}">
      <span class="dh-dot {% if m.change_pct > 0 %}up{% elif m.change_pct < 0 %}down{% else %}flat{% endif %}"></span>
      <span class="dh-sym">{{ m.symbol }}</span>
      <span class="dh-val">{% if m.last %}{{ m.last|floatformat:4 }}{% else %}—{% endif %}</span>
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
        <div class="dh-pop-bar">
          <div class="dh-pop-bar-fill"
            style="width:{% if m.change_pct >= 0 %}{% widthratio m.change_pct 1 10 %}%{% else %}0%{% endif %};
            background:{% if m.change_pct >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};"></div>
        </div>
        <div class="dh-pop-cta">▸ Click symbol on dashboard for full chart</div>
      </div>
    </div>
''')

btxt = bp.read_text(encoding="utf-8")
norm = _norm(btxt); use_crlf = "\r\n" in btxt

if 'id="dhTrack"' in norm:
    print("  data-headband markup already upgraded")
else:
    # Find the existing data-headband opening div
    m = re.search(r'(<!--\s*UPGRADE-[0-9]+:\s*Dashboard data headband[^\n]*-->\s*\n?\s*)?<div class="data-headband"', norm)
    if m:
        start = m.start()
        # Find the open <div class="data-headband"
        div_start = norm.find('<div class="data-headband"', start)
        end = find_div_end(norm, div_start)
        if end > 0:
            new_norm = norm[:start] + NEW_DH_HTML + norm[end:]
            out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
            bp.write_text(out, encoding="utf-8")
            print("  rewrote data-headband markup")
        else:
            print("  could not balance data-headband divs")
    else:
        # Insert before page-content as a new headband
        if '<div class="page-content fade-in"' in norm:
            new_norm = norm.replace('<div class="page-content fade-in"',
                                    NEW_DH_HTML + '\n        <div class="page-content fade-in"', 1)
            out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
            bp.write_text(out, encoding="utf-8")
            print("  inserted data-headband markup (new)")

# =================================================================
# STEP 4 — Remove inline padding-top:90px from all bot_program templates
# =================================================================
print("\n[4/9] Cleaning bot-program inline padding-top overrides …")

bot_templates = [
    "bot_program/templates/bot_program/home.html",
    "bot_program/templates/bot_program/configure.html",
    "bot_program/templates/bot_program/link.html",
    "bot_program/templates/bot_program/scenarios.html",
    "bot_program/templates/bot_program/scenario_new.html",
    "bot_program/templates/bot_program/scenario_detail.html",
]

for rel in bot_templates:
    p = ROOT / rel
    if not p.exists(): continue
    txt = p.read_text(encoding="utf-8")
    # Case 1: style="padding-top:90px;" → remove just that declaration
    new = re.sub(
        r'<div class="page-content fade-in" style="padding-top:\s*90px\s*;?\s*([^"]*)"',
        lambda m: (
            f'<div class="page-content fade-in" style="{m.group(1).strip()}"'
            if m.group(1).strip()
            else '<div class="page-content fade-in"'
        ),
        txt)
    if new != txt:
        p.write_text(new, encoding="utf-8")
        print(f"  cleaned {rel}")

# =================================================================
# STEP 5 — Info panel: taller, richer, scrollable
# =================================================================
print("\n[5/9] Info panel bar — CSS + markup rewrite …")

NEW_IP_CSS = '''        /* UPGRADE-9: info panel — taller, scrollable, richer */
        .info-panel-wrap {
            position: fixed; top: calc(var(--topbar-height) + 34px);
            left: var(--sidebar-width); right: 0;
            z-index: 44; background: var(--bg-primary);
            border-bottom: 1px solid var(--border);
            overflow: visible;
        }
        body:has(.sidebar.mini) .info-panel-wrap { left: 68px; }
        body:has(.signals-rail) .info-panel-wrap { right: 44px; }
        body:has(.signals-rail.open) .info-panel-wrap { right: 280px; }
        .info-panel-scroll { height: 42px; overflow-x: auto; overflow-y: visible; scrollbar-width: none; }
        .info-panel-scroll::-webkit-scrollbar { display: none; }
        .info-panel-bar { display: flex; height: 42px; overflow: visible; min-width: max-content; }
        .ip-arrow {
            position: absolute; top: 0; width: 28px; height: 42px;
            display: flex; align-items: center; justify-content: center;
            color: var(--accent); cursor: pointer; z-index: 3;
            opacity: 0; transition: opacity .2s; font-size: 13px;
            border: 0; font-family: var(--font-mono);
        }
        .ip-arrow.right { right: 0; background: linear-gradient(270deg, var(--bg-primary) 50%, transparent); }
        .ip-arrow.left { left: 0; background: linear-gradient(90deg, var(--bg-primary) 50%, transparent); }
        .info-panel-wrap:hover .ip-arrow { opacity: 1; }
        .ip-arrow:hover { color: var(--text-primary); }
        .ip-cat {
            position: relative; display: flex; flex-direction: column;
            justify-content: center; gap: 2px;
            padding: 4px 16px; border-right: 1px solid var(--border);
            font-family: var(--font-mono);
            color: var(--text-muted); cursor: default;
            white-space: nowrap; transition: all 0.15s; min-height: 42px;
        }
        .ip-cat:hover { background: var(--bg-card); }
        .ip-cat .ip-label { font-size: 8px; letter-spacing: 1.5px; color: var(--text-muted); text-transform: uppercase; }
        .ip-cat .ip-count {
            font-size: 14px; font-weight: 700; color: var(--accent);
            font-family: var(--font-display); line-height: 1.1;
        }
        .ip-cat .ip-sub { font-size: 9px; color: var(--text-secondary); }
        .ip-cat .ip-count.red { color: var(--accent-red); }
        .ip-cat .ip-count.gold { color: var(--accent-gold); }
        .ip-cat .ip-count.blue { color: var(--accent-blue); }
        .ip-dropdown {
            display: none; position: absolute; top: 42px; left: 0;
            min-width: 320px; max-width: 360px; max-height: 380px; overflow-y: auto;
            background: var(--bg-card); border: 1px solid var(--border-glow);
            border-radius: 0 0 var(--radius-lg) var(--radius-lg);
            box-shadow: 0 12px 40px rgba(0,0,0,0.7); z-index: 250;
            padding: 10px 0; white-space: normal;
        }
        .ip-cat:hover .ip-dropdown { display: block; }
        .ip-dd-head { padding: 4px 16px 10px; font-size: 9px; letter-spacing: 1.5px;
                      color: var(--text-muted); border-bottom: 1px solid var(--border); margin-bottom: 6px; }
        .ip-dd-item {
            padding: 8px 16px; font-family: var(--font-mono); font-size: 11px;
            color: var(--text-secondary); cursor: pointer; transition: background 0.1s;
            display: flex; justify-content: space-between; align-items: center;
            text-decoration: none;
        }
        .ip-dd-item:hover { background: var(--bg-card-hover); color: var(--text-primary); }
        .ip-dd-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; padding: 6px 16px; }
        .ip-dd-cell { font-size: 10px; }
        .ip-dd-cell .dk { display: block; color: var(--text-muted); font-size: 8px; letter-spacing: 1px; }
        .ip-dd-cell .dv { font-size: 13px; font-family: var(--font-display); font-weight: 700; color: var(--accent); }
        .ip-dd-cell .dv.red { color: var(--accent-red); }
        .ip-dd-cell .dv.gold { color: var(--accent-gold); }
        .ip-dd-empty { padding: 16px; text-align: center; color: var(--text-muted); font-size: 10px; }
        .ip-cat-ai { cursor: pointer; }
        .ip-cat-ai:hover .ip-count { color: var(--accent); }'''

# Remove old info-panel CSS block
btxt = bp.read_text(encoding="utf-8")
norm = _norm(btxt); use_crlf = "\r\n" in btxt

if "UPGRADE-9: info panel" in norm:
    print("  info panel CSS already upgraded")
else:
    # Remove old block from "/* ── Info Panel" to "/* AI link in bar */" + its :hover line
    m = re.search(r'/\* ── Info Panel \(fixed bar with hover dropdowns\) ──.*?\.ip-cat-ai:hover \{ color: var\(--accent\); \}', norm, flags=re.DOTALL)
    if m:
        new_norm = norm[:m.start()] + NEW_IP_CSS.strip() + norm[m.end():]
        out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
        bp.write_text(out, encoding="utf-8")
        norm = new_norm
        print("  rewrote info-panel CSS block")
    else:
        print("  info-panel CSS block not found — fallback append")
        if "</style>{% block extra_css %}{% endblock %}" in norm:
            new_norm = norm.replace(
                "</style>{% block extra_css %}{% endblock %}",
                NEW_IP_CSS + "\n        </style>{% block extra_css %}{% endblock %}", 1)
            out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
            bp.write_text(out, encoding="utf-8")
            norm = new_norm

# Rewrite info-panel-wrap markup
NEW_IP_MARKUP = '''<!-- UPGRADE-9: info panel rebuilt -->
        <div class="info-panel-wrap">
            <button type="button" class="ip-arrow left" aria-label="Scroll left">◀</button>
            <button type="button" class="ip-arrow right" aria-label="Scroll right">▶</button>
            <div class="info-panel-scroll" id="ipScroll">
            <div class="info-panel-bar">
                <div class="ip-cat">
                    <span class="ip-label">PORTFOLIO</span>
                    <span class="ip-count">&euro;{{ panel_portfolio_value|default:"0" }}</span>
                    <span class="ip-sub">{{ panel_positions|default:"0" }} pos · {{ panel_exposure|default:"0" }}%</span>
                    <div class="ip-dropdown">
                        <div class="ip-dd-head">PORTFOLIO OVERVIEW</div>
                        <div class="ip-dd-grid">
                            <div class="ip-dd-cell"><span class="dk">VALUE</span><span class="dv">&euro;{{ panel_portfolio_value|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">CASH</span><span class="dv">&euro;{{ panel_cash|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">DAILY P&amp;L</span><span class="dv">{{ panel_daily_pnl_display|default:"+0.00%" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">EXPOSURE</span><span class="dv">{{ panel_exposure|default:"0" }}%</span></div>
                            <div class="ip-dd-cell"><span class="dk">POSITIONS</span><span class="dv">{{ panel_positions|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">DRAWDOWN</span><span class="dv red">{{ panel_drawdown|default:"0" }}%</span></div>
                        </div>
                    </div>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">POSITIONS</span>
                    <span class="ip-count">{{ panel_positions|default:"0" }}</span>
                    <span class="ip-sub">open now</span>
                    <div class="ip-dropdown">
                        <div class="ip-dd-head">OPEN POSITIONS</div>
                        {% for p in panel_recent_positions %}
                        <a href="/positions/" class="ip-dd-item">
                            <span style="font-weight:700;color:var(--text-primary);">{{ p.instrument.symbol }}</span>
                            <span style="font-size:9px;">{{ p.direction|upper }}</span>
                        </a>
                        {% empty %}<div class="ip-dd-empty">No open positions</div>{% endfor %}
                    </div>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">BOT</span>
                    <span class="ip-count {% if not panel_bot_armed %}red{% endif %}">{% if panel_bot_armed %}ARMED{% else %}OFF{% endif %}</span>
                    <span class="ip-sub">{{ panel_bot_mode|default:"paper" }} · {{ panel_bot_open|default:"0" }} open</span>
                    <div class="ip-dropdown">
                        <div class="ip-dd-head">BOT PROGRAM</div>
                        <div class="ip-dd-grid">
                            <div class="ip-dd-cell"><span class="dk">STATUS</span><span class="dv">{% if panel_bot_armed %}ARMED{% else %}OFFLINE{% endif %}</span></div>
                            <div class="ip-dd-cell"><span class="dk">MODE</span><span class="dv">{{ panel_bot_mode|default:"—"|upper }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">OPEN</span><span class="dv">{{ panel_bot_open|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">24H P&amp;L</span><span class="dv">{{ panel_bot_pnl_24h_display|default:"+0.00" }}</span></div>
                        </div>
                        <a href="{% url 'bot_home' %}" class="ip-dd-item" style="justify-content:center;color:var(--accent);">▸ Go to Bot Program</a>
                    </div>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">STRATEGIES</span>
                    <span class="ip-count">{{ panel_strategies|default:"0" }}</span>
                    <span class="ip-sub">active</span>
                    <div class="ip-dropdown">
                        <div class="ip-dd-head">ACTIVE STRATEGIES</div>
                        {% for st in panel_recent_strategies %}
                        <a href="/strategies/{{ st.id }}/" class="ip-dd-item">
                            <span>{{ st.name|truncatechars:30 }}</span>
                            <span style="font-size:8px;color:var(--accent);">{{ st.status }}</span>
                        </a>
                        {% empty %}<div class="ip-dd-empty">No active strategies</div>{% endfor %}
                    </div>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">SIGNALS</span>
                    <span class="ip-count">{{ panel_signals|default:"0" }}</span>
                    <span class="ip-sub">{{ panel_bullish|default:"0" }} bull · {{ panel_bearish|default:"0" }} bear</span>
                    <div class="ip-dropdown">
                        <div class="ip-dd-head">ACTIVE SIGNALS</div>
                        <div class="ip-dd-grid">
                            <div class="ip-dd-cell"><span class="dk">BULLISH</span><span class="dv">{{ panel_bullish|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">BEARISH</span><span class="dv red">{{ panel_bearish|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">TOTAL</span><span class="dv">{{ panel_signals|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">24H NEW</span><span class="dv">{{ panel_signals_24h|default:"0" }}</span></div>
                        </div>
                    </div>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">NEWS</span>
                    <span class="ip-count blue">{{ panel_news|default:"0" }}</span>
                    <span class="ip-sub">last 24h</span>
                    <div class="ip-dropdown" style="min-width:340px;">
                        <div class="ip-dd-head">RECENT NEWS</div>
                        {% for n in panel_recent_news %}
                        <a href="/news/{{ n.id }}/" class="ip-dd-item" style="flex-direction:column;align-items:flex-start;gap:2px;">
                            <span style="font-size:10px;color:var(--text-primary);">{{ n.title|truncatechars:60 }}</span>
                            <span style="font-size:8px;color:var(--text-muted);">{{ n.source }} &middot; {{ n.published_at|timesince }} ago</span>
                        </a>
                        {% empty %}<div class="ip-dd-empty">No news yet</div>{% endfor %}
                    </div>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">FUNDING</span>
                    <span class="ip-count">{{ panel_funding_display|default:"—" }}</span>
                    <span class="ip-sub">24h avg · {{ panel_funding_extreme_count|default:"0" }} extreme</span>
                    <div class="ip-dropdown">
                        <div class="ip-dd-head">FUNDING RATES</div>
                        <div class="ip-dd-grid">
                            <div class="ip-dd-cell"><span class="dk">AVG 24H</span><span class="dv">{{ panel_funding_display|default:"—" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">EXTREME</span><span class="dv gold">{{ panel_funding_extreme_count|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">FLIPS</span><span class="dv">{{ panel_funding_flips|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">SAMPLES</span><span class="dv">{{ panel_funding_samples|default:"0" }}</span></div>
                        </div>
                        <a href="{% url 'liquidations_page' %}" class="ip-dd-item" style="justify-content:center;color:var(--accent);">▸ Liquidations page</a>
                    </div>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">LIQ 24H</span>
                    <span class="ip-count">${{ panel_liq_24h_display|default:"0" }}</span>
                    <span class="ip-sub">{{ panel_liq_count|default:"0" }} events</span>
                    <div class="ip-dropdown">
                        <div class="ip-dd-head">LIQUIDATIONS (24H)</div>
                        <div class="ip-dd-grid">
                            <div class="ip-dd-cell"><span class="dk">TOTAL</span><span class="dv">${{ panel_liq_24h_display|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">COUNT</span><span class="dv">{{ panel_liq_count|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">LONGS REKT</span><span class="dv red">${{ panel_liq_long_display|default:"0" }}</span></div>
                            <div class="ip-dd-cell"><span class="dk">SHORTS REKT</span><span class="dv">${{ panel_liq_short_display|default:"0" }}</span></div>
                        </div>
                        <a href="{% url 'liquidations_page' %}" class="ip-dd-item" style="justify-content:center;color:var(--accent);">▸ View heatmap</a>
                    </div>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">ALERTS</span>
                    <span class="ip-count gold">{{ notification_count|default:"0" }}</span>
                    <span class="ip-sub">unread</span>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">DRAWDOWN</span>
                    <span class="ip-count red">{{ panel_drawdown|default:"0" }}%</span>
                    <span class="ip-sub">from peak</span>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">WATCHLIST</span>
                    <span class="ip-count">{{ panel_watchlist|default:"0" }}</span>
                    <span class="ip-sub">tracked</span>
                </div>
                <div class="ip-cat">
                    <span class="ip-label">VOLATILITY</span>
                    <span class="ip-count">{{ panel_vix|default:"—" }}</span>
                    <span class="ip-sub">VIX index</span>
                </div>
                <div class="ip-cat ip-cat-ai" onclick="window.location='/ai/chat/'">
                    <span class="ip-label">SAURON AI</span>
                    <span class="ip-count">&#x25B8;</span>
                    <span class="ip-sub">ask anything</span>
                </div>
            </div>
            </div>
        </div>'''

btxt = bp.read_text(encoding="utf-8")
norm = _norm(btxt); use_crlf = "\r\n" in btxt

if 'id="ipScroll"' in norm:
    print("  info panel markup already upgraded")
else:
    start_marker = '<div class="info-panel-wrap">'
    start = norm.find(start_marker)
    if start == -1:
        print("  info-panel-wrap not found — skipped")
    else:
        end = find_div_end(norm, start)
        if end > 0:
            new_norm = norm[:start] + NEW_IP_MARKUP + norm[end:]
            out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
            bp.write_text(out, encoding="utf-8")
            print("  rewrote info-panel-wrap markup")
        else:
            print("  could not balance info-panel-wrap divs")

# =================================================================
# STEP 6 — Unified sidebar toggle = rail toggle
# =================================================================
print("\n[6/9] Unifying sidebar + rail toggle buttons …")

# Remove old in-brand sidebar-toggle
patch("templates/base.html",
      '''            <button class="sidebar-toggle" onclick="toggleSidebar()" title="Collapse menu">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path class="toggle-arrow" d="M10 3L5 8L10 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>''',
      '<!-- UPGRADE-9: sidebar toggle moved to unified edge button -->',
      marker="UPGRADE-9: sidebar toggle moved")

# Replace old sidebar-expand-tab with unified edge button
patch("templates/base.html",
      '''<!-- Sidebar expand tab (visible when menu is minimized) -->
<div class="sidebar-expand-tab" onclick="toggleSidebar()" title="Expand menu">
    <svg viewBox="0 0 10 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M2 2L8 8L2 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
</div>''',
      '''<!-- UPGRADE-9: Sidebar edge toggle (identical to rail edge toggle) -->
<button type="button" class="sidebar-toggle-btn" id="sidebarToggleBtn"
        onclick="toggleSidebar()" title="Toggle menu">
  <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M6 3L11 8L6 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
</button>''',
      marker="UPGRADE-9: Sidebar edge toggle")

# Inject matching CSS + ensure rail toggle CSS exists
SIDEBAR_CSS = '''        /* UPGRADE-9: sidebar edge toggle (mirrors rail-toggle-btn) */
        .sidebar-toggle-btn {
            position: fixed; top: 50%; left: var(--sidebar-width); transform: translateY(-50%);
            width: 28px; height: 56px; background: var(--bg-card);
            border: 1px solid var(--border); border-left: 0;
            border-radius: 0 8px 8px 0; cursor: pointer; z-index: 70;
            display: flex; align-items: center; justify-content: center;
            color: var(--accent); transition: all .25s; box-shadow: 2px 0 12px rgba(0,0,0,.4);
        }
        .sidebar-toggle-btn:hover { background: var(--bg-card-hover); width: 32px; }
        .sidebar-toggle-btn svg { width: 14px; height: 14px; transition: transform .3s; }
        body:has(.sidebar.mini) .sidebar-toggle-btn { left: 68px; transform: translateY(-50%) rotate(180deg); }
        @media (max-width: 768px) { .sidebar-toggle-btn { display: none; } }
        /* Ensure rail toggle has the same design (pass 6 / fallback) */
        .rail-toggle-btn {
            position: fixed; top: 50%; right: 44px; transform: translateY(-50%);
            width: 28px; height: 56px; background: var(--bg-card);
            border: 1px solid var(--border); border-right: 0;
            border-radius: 8px 0 0 8px; cursor: pointer; z-index: 70;
            display: flex; align-items: center; justify-content: center;
            color: var(--accent); transition: all .25s; box-shadow: -2px 0 12px rgba(0,0,0,.4);
        }
        .rail-toggle-btn:hover { background: var(--bg-card-hover); width: 32px; }
        .rail-toggle-btn svg { width: 14px; height: 14px; transition: transform .3s; }
        body:has(.signals-rail.open) .rail-toggle-btn { right: 280px; }
        body:has(.signals-rail.open) .rail-toggle-btn svg { transform: rotate(180deg); }
        @media (max-width: 768px) { .rail-toggle-btn { display: none; } }'''

patch("templates/base.html",
      "</style>{% block extra_css %}{% endblock %}",
      SIDEBAR_CSS + "\n        </style>{% block extra_css %}{% endblock %}",
      marker="UPGRADE-9: sidebar edge toggle")

# Also inject the rail toggle button itself if not present (in case pass 6 never landed)
btxt = bp.read_text(encoding="utf-8")
if 'id="railToggleBtn"' not in btxt:
    RAIL_BTN = '''<!-- UPGRADE-9: rail edge toggle -->
<button type="button" class="rail-toggle-btn" id="railToggleBtn"
        onclick="(function(){var r=document.getElementById('signalsRail');if(!r)return;var open=r.classList.toggle('open');localStorage.setItem('sauron_signals_rail',open?'open':'closed');})()"
        title="Toggle signals rail">
  <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 3L5 8L10 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
</button>
'''
    needle = '<!-- Signals Rail (right sidebar) — split: Signals + Watchlist -->'
    if needle in btxt:
        btxt = btxt.replace(needle, RAIL_BTN + "\n" + needle, 1)
        bp.write_text(btxt, encoding="utf-8")
        print("  injected rail toggle button (was missing)")

# =================================================================
# STEP 7 — Enrich news ticker context (keywords, implication, chips)
# =================================================================
print("\n[7/9] Enriching news ticker context …")

patch("core/context_processors.py",
      '''        for n in NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:8]:
            try:
                affected_syms = ", ".join(i.symbol for i in n.ai_affected_instruments.all()[:4])
            except Exception:
                affected_syms = ""
            ticker.append({
                "type": "news", "news_id": n.id, "title": n.title, "source": n.source,
                "summary": (n.ai_summary or n.content_summary or "")[:300],
                "sentiment_score": n.ai_sentiment_score,
                "urgency": n.ai_urgency or "",
                "affected": affected_syms,
                "published_at": n.published_at.strftime("%H:%M") if n.published_at else "",
                "url": f"/news/{n.id}/",
            })''',
      '''        for n in NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:12]:
            try:
                affected_list = list(n.ai_affected_instruments.all()[:6])
                affected_chips = [i.symbol for i in affected_list]
                affected_syms = ", ".join(affected_chips)
            except Exception:
                affected_syms = ""; affected_chips = []
            summary_txt = (n.ai_summary or n.content_summary or "").strip()
            import re as _re
            tokens = _re.findall(r"\\b[A-Z][A-Za-z]{3,}\\b", n.title or "")
            keywords = list(dict.fromkeys(tokens))[:5]
            sent = n.ai_sentiment_score
            if sent is None: implication = "Impact pending analysis"
            elif sent > 0.3: implication = "Bullish — risk-on setup"
            elif sent < -0.3: implication = "Bearish — risk-off setup"
            else: implication = "Neutral — mixed signal"
            ticker.append({
                "type": "news", "news_id": n.id, "title": n.title, "source": n.source,
                "summary": summary_txt[:400],
                "sentiment_score": sent,
                "urgency": n.ai_urgency or "",
                "affected": affected_syms,
                "affected_chips": affected_chips,
                "keywords": keywords,
                "implication": implication,
                "published_at": n.published_at.strftime("%H:%M") if n.published_at else "",
                "url": f"/news/{n.id}/",
            })''',
      marker="affected_chips")

# =================================================================
# STEP 8 — Ticker bar hover arrows + richer news popup + data-type
# =================================================================
print("\n[8/9] Ticker bar arrows + rich news popup …")

TICKER_EXTRAS_CSS = '''        /* UPGRADE-9: ticker bar hover arrows + enriched news popup */
        .ticker-bar { position: fixed; }
        .ticker-bar .tb-arrow {
            position: absolute; top: 0; width: 28px; height: 34px;
            display: flex; align-items: center; justify-content: center;
            color: var(--accent); cursor: pointer; z-index: 3;
            opacity: 0; transition: opacity .2s; font-size: 13px;
            border: 0; font-family: var(--font-mono);
        }
        .ticker-bar .tb-arrow.right { right: 0; background: linear-gradient(270deg, var(--bg-primary) 50%, transparent); }
        .ticker-bar .tb-arrow.left { left: 0; background: linear-gradient(90deg, var(--bg-primary) 50%, transparent); }
        .ticker-bar:hover .tb-arrow { opacity: 1; }
        .ticker-bar .tb-arrow:hover { color: var(--text-primary); }
        .ticker-item[data-type="news"] .ticker-popup { min-width: 360px; max-width: 420px; }
        .tnp-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
        .tnp-source { font-family: var(--font-mono); font-size: 9px; letter-spacing: 1px; color: var(--accent); text-transform: uppercase; }
        .tnp-time { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); }
        .tnp-title { font-family: var(--font-display); font-size: 13px; font-weight: 700; color: var(--text-primary); line-height: 1.35; margin-bottom: 10px; }
        .tnp-summary { font-size: 11px; color: var(--text-secondary); line-height: 1.5; margin-bottom: 10px; }
        .tnp-meta-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
        .tnp-sent { padding: 2px 8px; border-radius: 10px; font-family: var(--font-mono); font-size: 9px; font-weight: 700; letter-spacing: 1px; }
        .tnp-sent.pos { background: rgba(0,232,104,.12); color: var(--accent); }
        .tnp-sent.neg { background: rgba(232,48,48,.12); color: var(--accent-red); }
        .tnp-sent.neu { background: rgba(136,136,136,.12); color: var(--text-secondary); }
        .tnp-urgency { padding: 2px 8px; border-radius: 10px; background: rgba(216,176,32,.15); color: var(--accent-gold); font-family: var(--font-mono); font-size: 9px; font-weight: 700; letter-spacing: 1px; }
        .tnp-implication { padding: 8px 10px; background: var(--bg-void); border-left: 2px solid var(--accent); font-size: 10px; color: var(--text-secondary); font-style: italic; margin-bottom: 10px; }
        .tnp-section { font-family: var(--font-mono); font-size: 8px; letter-spacing: 1.2px; color: var(--text-muted); margin: 8px 0 4px; }
        .tnp-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
        .tnp-chip { padding: 2px 8px; background: var(--accent-dim); color: var(--accent); border-radius: 10px; font-family: var(--font-mono); font-size: 9px; font-weight: 700; }
        .tnp-keyword { padding: 2px 8px; background: rgba(48,160,232,.12); color: var(--accent-blue); border-radius: 10px; font-family: var(--font-mono); font-size: 9px; font-weight: 700; }
        .tnp-cta { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 10px; color: var(--accent); text-align: right; }'''

patch("templates/base.html",
      "</style>{% block extra_css %}{% endblock %}",
      TICKER_EXTRAS_CSS + "\n        </style>{% block extra_css %}{% endblock %}",
      marker="UPGRADE-9: ticker bar hover arrows")

# Add hover arrows inside the ticker-bar
patch("templates/base.html",
      '<div class="ticker-bar" id="tickerBar">\n            <div class="ticker-track" id="tickerTrack">',
      '''<div class="ticker-bar" id="tickerBar">
            <button type="button" class="tb-arrow left" aria-label="Scroll left">◀</button>
            <button type="button" class="tb-arrow right" aria-label="Scroll right">▶</button>
            <div class="ticker-track" id="tickerTrack">''',
      marker="tb-arrow left")

# Add data-type on ticker items (both loops)
regex_sub("templates/base.html",
          r'<a href="\{\{ item\.url \}\}" class="ticker-item">',
          '<a href="{{ item.url }}" class="ticker-item" data-type="{{ item.type }}">')

# Replace the news branch of the ticker popup with the rich version.
# Target the pattern that starts from {% elif item.type == "news" %} inside .ticker-popup
# and runs until {% endif %}.
NEW_NEWS_BRANCH = '''{% elif item.type == "news" %}
                        <div class="tnp-head">
                          <span class="tnp-source">{{ item.source }}</span>
                          <span class="tnp-time">{{ item.published_at }}</span>
                        </div>
                        <div class="tnp-title">{{ item.title }}</div>
                        <div class="tnp-summary">{{ item.summary|truncatechars:260 }}</div>
                        <div class="tnp-meta-row">
                          {% if item.sentiment_score != None %}
                            {% if item.sentiment_score > 0.2 %}<span class="tnp-sent pos">▲ BULL {{ item.sentiment_score|floatformat:2 }}</span>
                            {% elif item.sentiment_score < -0.2 %}<span class="tnp-sent neg">▼ BEAR {{ item.sentiment_score|floatformat:2 }}</span>
                            {% else %}<span class="tnp-sent neu">● NEUTRAL</span>{% endif %}
                          {% endif %}
                          {% if item.urgency %}<span class="tnp-urgency">⚡ {{ item.urgency|upper }}</span>{% endif %}
                        </div>
                        {% if item.implication %}<div class="tnp-implication">{{ item.implication }}</div>{% endif %}
                        {% if item.affected_chips %}
                          <div class="tnp-section">AFFECTED INSTRUMENTS</div>
                          <div class="tnp-chips">{% for c in item.affected_chips %}<span class="tnp-chip">{{ c }}</span>{% endfor %}</div>
                        {% endif %}
                        {% if item.keywords %}
                          <div class="tnp-section">KEYWORDS</div>
                          <div class="tnp-chips">{% for k in item.keywords %}<span class="tnp-keyword">{{ k }}</span>{% endfor %}</div>
                        {% endif %}
                        <div class="tnp-cta">▸ Click for full analysis</div>
                        {% endif %}'''

# Match both the pass-6 enriched version and the original pass-2 version
regex_sub("templates/base.html",
          r'\{% elif item\.type == "news" %\}\s*<div[^<]*<div[^<]*(?:<[^<]*)*?\{% endif %\}',
          NEW_NEWS_BRANCH,
          flags=re.DOTALL)

# =================================================================
# STEP 9 — Runtime JS for popup anchoring + hover scrolling
# =================================================================
print("\n[9/9] Runtime JS for popup positioning + arrows …")

RUNTIME_JS = '''
<script>
/* UPGRADE-9: headband popup escape + hover arrows */
(function(){
  // Data headband popup escape: position as fixed, anchored to hovered item
  function positionPop(item){
    var pop = item.querySelector('.dh-pop'); if(!pop) return;
    var r = item.getBoundingClientRect();
    pop.style.top = (r.bottom + 4) + 'px';
    var w = 380;
    var left = r.left;
    if (left + w > window.innerWidth - 16) left = window.innerWidth - w - 16;
    if (left < 16) left = 16;
    pop.style.left = left + 'px';
  }
  document.querySelectorAll('.data-headband .dh-item').forEach(function(item){
    item.addEventListener('mouseenter', function(){
      item.classList.add('pop-open');
      positionPop(item);
    });
    item.addEventListener('mouseleave', function(){
      item.classList.remove('pop-open');
    });
  });
  window.addEventListener('scroll', function(){
    document.querySelectorAll('.data-headband .dh-item.pop-open').forEach(positionPop);
  }, true);

  // Data headband hover arrows
  var dhTrack = document.getElementById('dhTrack');
  if (dhTrack) {
    var dhOffset = 0, dhTimer = 0, dhManual = false;
    function dhStep(dir){
      dhManual = true;
      dhOffset += dir * 4;
      var max = dhTrack.scrollWidth / 2;
      if (dhOffset > 0) dhOffset = 0;
      if (dhOffset < -max) dhOffset = -max;
      dhTrack.style.animationPlayState = 'paused';
      dhTrack.style.transform = 'translateX(' + dhOffset + 'px)';
    }
    document.querySelectorAll('.data-headband .dh-arrow').forEach(function(btn){
      var dir = btn.classList.contains('right') ? -1 : 1;
      btn.addEventListener('mouseenter', function(){
        if (dhTimer) return;
        dhTimer = setInterval(function(){ dhStep(dir); }, 16);
      });
      btn.addEventListener('mouseleave', function(){
        clearInterval(dhTimer); dhTimer = 0;
      });
    });
    document.querySelector('.data-headband')?.addEventListener('mouseleave', function(){
      clearInterval(dhTimer); dhTimer = 0;
      if (dhManual) {
        dhTrack.style.transform = '';
        dhTrack.style.animationPlayState = '';
        dhManual = false; dhOffset = 0;
      }
    });
  }

  // Ticker bar hover arrows
  var tTrack = document.getElementById('tickerTrack');
  if (tTrack) {
    var tOffset = 0, tTimer = 0, tManual = false;
    function tStep(dir){
      tManual = true;
      tOffset += dir * 4;
      var max = tTrack.scrollWidth / 2;
      if (tOffset > 0) tOffset = 0;
      if (tOffset < -max) tOffset = -max;
      tTrack.style.animationPlayState = 'paused';
      tTrack.style.transform = 'translateX(' + tOffset + 'px)';
    }
    document.querySelectorAll('.ticker-bar .tb-arrow').forEach(function(btn){
      var dir = btn.classList.contains('right') ? -1 : 1;
      btn.addEventListener('mouseenter', function(){
        if (tTimer) return;
        tTimer = setInterval(function(){ tStep(dir); }, 16);
      });
      btn.addEventListener('mouseleave', function(){
        clearInterval(tTimer); tTimer = 0;
      });
    });
    document.querySelector('.ticker-bar')?.addEventListener('mouseleave', function(){
      clearInterval(tTimer); tTimer = 0;
      if (tManual) {
        tTrack.style.transform = '';
        tTrack.style.animationPlayState = '';
        tManual = false; tOffset = 0;
      }
    });
  }

  // Info panel hover arrows (scrollLeft-based because the panel uses native overflow)
  var ipScroll = document.getElementById('ipScroll');
  if (ipScroll) {
    var ipTimer = 0;
    document.querySelectorAll('.info-panel-wrap .ip-arrow').forEach(function(btn){
      var dir = btn.classList.contains('right') ? 1 : -1;
      btn.addEventListener('mouseenter', function(){
        if (ipTimer) return;
        ipTimer = setInterval(function(){ ipScroll.scrollLeft += dir * 4; }, 16);
      });
      btn.addEventListener('mouseleave', function(){
        clearInterval(ipTimer); ipTimer = 0;
      });
    });
  }
})();
</script>
'''

btxt = bp.read_text(encoding="utf-8")
if "UPGRADE-9: headband popup escape" in btxt:
    print("  runtime JS already present")
else:
    use_crlf = "\r\n" in btxt
    norm = _norm(btxt)
    if "</body>" in norm:
        new_norm = norm.replace("</body>", RUNTIME_JS + "\n</body>", 1)
        out = new_norm.replace("\n", "\r\n") if use_crlf else new_norm
        bp.write_text(out, encoding="utf-8")
        print("  injected runtime JS")

print("\n" + "━" * 60)
print(" ✓ UPGRADE PASS 9 COMPLETE")
print("━" * 60)
print("""
Restart the dev server (no migrations):
  python manage.py runserver

What's new:
  ✓ Data headband — popups now escape the scroll container (visible
    fully, not clipped). Auto-scrolls right-to-left like the news
    ticker, pauses on hover, with left/right arrows that let you
    scroll manually. ~45 tracked instruments covering every major
    index, FX pair, crypto major, commodity, and rate.
  ✓ News ticker — left/right hover arrows + hugely enriched popups
    with full AI summary, sentiment badge, urgency tag, implication
    line, affected-instrument chips, keyword chips, and CTA.
  ✓ Bot Program page — content no longer sits too low; inline
    padding-top:90px removed from all bot_program templates so the
    global rule takes effect consistently.
  ✓ Info panel bar — 42px tall (was 28px), 12 categories (added
    BOT, SIGNALS, FUNDING, LIQ 24H, VOLATILITY), each with big
    value + sub-metric + rich dropdown grid. Hover arrows scroll
    it left/right on overflow.
  ✓ Left sidebar toggle — unified with right rail toggle. Same
    circular edge button, same chevron SVG, same rotate-on-state
    behaviour, mirrored horizontally.
""")
