#!/usr/bin/env python3
"""
upgrade_sauron_9b.py
====================
Tiny follow-up to pass 9 — replaces the basic news popup branch in
templates/base.html with the rich tnp-* version. Pass 9's regex
missed because of indentation specifics.

Run after upgrade_sauron_9.py:
    python upgrade_sauron_9b.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run from directory containing manage.py"); sys.exit(1)

p = ROOT / "templates/base.html"
txt = p.read_text(encoding="utf-8")
use_crlf = "\r\n" in txt

OLD = '''                        {% elif item.type == "news" %}
                        <div style="font-size:11px;color:var(--text-secondary);">{{ item.summary|truncatechars:150 }}</div>
                        <div style="margin-top:4px;font-size:9px;color:var(--text-muted);">{{ item.source }}</div>
                        {% endif %}'''

NEW = '''                        {% elif item.type == "news" %}
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

# CRLF-aware match
def _norm(s): return s.replace("\r\n", "\n").replace("\r", "\n")
norm = _norm(txt)
norm_old = _norm(OLD)
norm_new = _norm(NEW)

if 'class="tnp-summary"' in norm:
    print("  already patched")
elif norm_old not in norm:
    print("  anchor not found")
    sys.exit(1)
else:
    out = norm.replace(norm_old, norm_new, 1)
    if use_crlf: out = out.replace("\n", "\r\n")
    p.write_text(out, encoding="utf-8")
    print("  ✓ rich news popup applied")
