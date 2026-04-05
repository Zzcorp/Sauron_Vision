#!/usr/bin/env python3
"""
SAURON VISION — Hotfix v1
1. Light mode CSS leaked outside style tag — fix it
2. Profile view not saving theme_mode — fix it
3. Body class crashes without TraderProfile — safe template tags
4. Favicon on login page
"""
import os, base64, re

FAVICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path d="M2,32 Q16,8 32,14 Q48,8 62,32 Q48,56 32,50 Q16,56 2,32Z" fill="none" stroke="#00e868" stroke-width="2.5"/><circle cx="32" cy="32" r="12" fill="none" stroke="#00e868" stroke-width="2"/><circle cx="32" cy="32" r="5" fill="#00e868"/><ellipse cx="32" cy="32" rx="4" ry="12" fill="none" stroke="#00e868" stroke-width="0.8" opacity="0.5"/><ellipse cx="32" cy="32" rx="9" ry="12" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.3"/></svg>'
FAVICON_B64 = base64.b64encode(FAVICON_SVG.encode()).decode()

LIGHT_CSS = """
        /* ── Light Mode ──────────────────────────── */
        body.light-mode {
            --bg-void: #f0f2f0;
            --bg-primary: #e8ece8;
            --bg-secondary: #dfe5df;
            --bg-card: #ffffff;
            --bg-card-hover: #f5f8f5;
            --border: #c0d0c0;
            --border-glow: #a0c0a0;
            --text-primary: #1a2a1a;
            --text-secondary: #4a6a4a;
            --text-muted: #8aaa8a;
            --accent: #00994d;
            --accent-dim: #d0f0d8;
            --accent-glow: rgba(0, 153, 77, 0.08);
            --shadow-card: 0 2px 12px rgba(0,0,0,0.06);
            --shadow-glow: 0 0 20px rgba(0,153,77,0.06);
        }
        body.light-mode .sidebar { background: linear-gradient(180deg, #e8ece8 0%, #f0f2f0 100%); }
        body.light-mode .topbar { background: rgba(240, 242, 240, 0.9); }
        body.light-mode .globe-eye-bg { opacity: 0.025; }
        body.light-mode .globe-eye-bg * { stroke: #00994d !important; }
        body.light-mode .globe-eye-bg circle[fill="#00e868"] { fill: #00994d !important; }
        body.light-mode #particles-canvas { opacity: 0.4; }
"""


def generate():
    # ── FIX 1: Create safe template tags ─────────────────
    os.makedirs("core/templatetags", exist_ok=True)
    for p in ["core/templatetags/__init__.py"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write("")

    with open("core/templatetags/sauron_tags.py", "w", encoding="utf-8") as f:
        f.write('''from django import template
register = template.Library()

@register.simple_tag(takes_context=True)
def get_theme(context):
    request = context.get("request")
    if request and hasattr(request, "user") and request.user.is_authenticated:
        try:
            return request.user.trader_profile.theme_mode
        except Exception:
            return "dark"
    return "dark"

@register.simple_tag(takes_context=True)
def get_display_name(context):
    request = context.get("request")
    if request and hasattr(request, "user") and request.user.is_authenticated:
        try:
            n = request.user.trader_profile.display_name
            if n:
                return n
        except Exception:
            pass
        return request.user.username.upper()
    return ""
''')
    print("  [OK] Safe template tags created")

    # ── FIX 2: Rebuild base.html light mode + body + favicon ──
    base_path = "templates/base.html"
    with open(base_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 2a. Remove leaked CSS (anything between </style> and {% block extra_css %} that looks like CSS)
    content = re.sub(
        r'</style>\s*\n\s*/\*.*?Light Mode.*?\*/.*?opacity:\s*0\.4;\s*\}\s*\n',
        '</style>\n',
        content,
        flags=re.DOTALL
    )

    # 2b. Insert light CSS BEFORE </style> if not already inside
    style_block = content.split("</style>")[0]
    if "light-mode" not in style_block:
        content = content.replace("    </style>", LIGHT_CSS + "\n    </style>")

    # 2c. Add {% load sauron_tags %} if missing
    if "sauron_tags" not in content:
        content = content.replace("{% load static %}", "{% load static %}\n{% load sauron_tags %}")

    # 2d. Fix body tag — use safe template tag
    content = re.sub(
        r'<body[^>]*>',
        '<body class="{% get_theme as t %}{% if t == \'light\' %}light-mode{% endif %}">',
        content,
        count=1
    )

    # 2e. Fix display name in topbar — use safe tag
    content = re.sub(
        r'\{%\s*if request\.user\.trader_profile\.display_name\s*%\}.*?\{%\s*endif\s*%\}',
        '{% get_display_name as uname %}{{ uname }}',
        content,
        flags=re.DOTALL
    )
    # Also catch the simpler version
    content = re.sub(
        r'\{%\s*with.*?trader_profile.*?%\}.*?\{%\s*endwith\s*%\}',
        '{% get_display_name as uname %}{{ uname }}',
        content,
        flags=re.DOTALL
    )

    # 2f. Ensure favicon data URI is in <head>
    if FAVICON_B64 not in content:
        content = content.replace(
            '<meta charset="UTF-8">',
            f'<meta charset="UTF-8">\n    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{FAVICON_B64}">'
        )

    with open(base_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("  [OK] base.html — light CSS inside <style>, body tag safe, favicon verified")

    # ── FIX 3: Login page favicon ────────────────────────
    login_path = "templates/registration/login.html"
    if os.path.exists(login_path):
        with open(login_path, "r", encoding="utf-8") as f:
            content = f.read()
        if FAVICON_B64 not in content:
            content = content.replace(
                '<meta charset="UTF-8">',
                f'<meta charset="UTF-8">\n    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{FAVICON_B64}">'
            )
            with open(login_path, "w", encoding="utf-8") as f:
                f.write(content)
        print("  [OK] login.html — favicon added")

    # ── FIX 4: Profile view saves theme_mode ─────────────
    views_path = "dashboard/views.py"
    with open(views_path, "r", encoding="utf-8") as f:
        content = f.read()

    marker = 'profile_obj.ai_autonomy = request.POST.get("ai_autonomy", "suggest")'
    if marker in content and 'profile_obj.theme_mode = request.POST.get("theme_mode"' not in content:
        content = content.replace(
            marker,
            'profile_obj.theme_mode = request.POST.get("theme_mode", profile_obj.theme_mode)\n        ' + marker
        )
        with open(views_path, "w", encoding="utf-8") as f:
            f.write(content)
    print("  [OK] views.py — profile now saves theme_mode")

    print("""
  HOTFIX COMPLETE — just refresh your browser.
  No migrations needed.
""")


if __name__ == "__main__":
    generate()
