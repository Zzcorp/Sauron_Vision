from django import template
register = template.Library()

#: What an unmeasured value looks like, everywhere on this platform.
DASH = "—"


@register.filter
def measured(value, places=2):
    """A number, or an em-dash when there was never a number.

    `{{ price|floatformat:4 }}` renders None as the EMPTY STRING. Not a
    zero, not a dash — nothing at all. So a closed position whose exit
    price was never booked drew a detail grid of labels with blank space
    under them, and it read as the panel being broken rather than as the
    price being unknown. The operator reported it as "no prices on closed
    positions", which is exactly what it looked like.

    This is the same rule the rest of the platform already follows in
    longhand (`{% if x is not None %}{{ x }}{% else %}&mdash;{% endif %}`).
    A price cell earns its dash the same way a P&L cell does: None means
    NOT MEASURED, and it must never be shown as blank or as a confident 0.
    """
    from django.template.defaultfilters import floatformat

    if value is None or value == "":
        return DASH
    out = floatformat(value, places)
    # floatformat itself returns "" for anything non-numeric.
    return out if out != "" else DASH


@register.filter
def measured_pct(value, places=2):
    """`measured`, wearing its percent sign — and dropping it when there
    is nothing to qualify. A bare "%" is not a reading."""
    out = measured(value, places)
    return out if out == DASH else f"{out}%"


@register.filter
def sign_class(value):
    """"up", "down", or "flat" for a value nobody measured.

    Django's smart-if swallows the TypeError from `{% if None >= 0 %}` and
    evaluates it False, so every unmeasured number was silently painted in
    the loss colour — the platform stating a loss it had not measured.
    """
    if value is None:
        return "flat"
    try:
        return "up" if float(value) >= 0 else "down"
    except (TypeError, ValueError):
        return "flat"


@register.simple_tag(takes_context=True)
def static_abs(context, path):
    """An ABSOLUTE URL for a static file — scheme, host and all.

    `{% static %}` returns "/static/logo/og-card.png", and every link
    preview on the platform shipped that into `og:image`. Facebook,
    LinkedIn, Slack, X and iMessage all require an absolute URL there and
    all silently drop a relative one, so every link anybody has ever shared
    to Sauron Vision has been previewing with no image at all. It fails
    quietly, on somebody else's server, which is why it survived.

    The host comes from the request, which Django has already validated
    against ALLOWED_HOSTS by the time a template renders — so a spoofed Host
    header cannot point the card at another domain. Behind the reverse proxy
    the scheme comes from SECURE_PROXY_SSL_HEADER, the same way every other
    absolute URL on the platform is built.

    Falls back to the plain static path when there is no request in context
    (a management command rendering a template, a test). A relative URL is a
    worse card, but it is still a working <img> — inventing a hostname would
    point the card somewhere that may not exist.
    """
    from django.templatetags.static import static as static_url

    url = static_url(path)
    request = context.get("request")
    if request is None or not hasattr(request, "build_absolute_uri"):
        return url
    return request.build_absolute_uri(url)

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
def tour_pending(context):
    """True when this user should see the guided tour: authenticated with
    no TraderProfile row yet, or a profile whose tour_completed_at is
    null. A lazy tag rather than a context-processor key — it renders
    only where used, and the context processor is already the hottest
    per-request code on the platform."""
    request = context.get("request")
    if not (request and hasattr(request, "user")
            and request.user.is_authenticated):
        return False
    from django.core.exceptions import ObjectDoesNotExist
    try:
        return request.user.trader_profile.tour_completed_at is None
    except ObjectDoesNotExist:
        # No profile row yet — profiles are created lazily, and a brand
        # new user is exactly who the tour is for.
        return True
    except Exception:
        # Anything ELSE (a DB error, the deploy window before migration
        # 0009 applies) fails CLOSED: autostarting the tour for every
        # user on every page — with a completion endpoint that would 500
        # in the same broken state — is an unescapable loop.
        return False


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


@register.filter
def briefing_md(value):
    """Markdown-lite for briefing prose: escape EVERYTHING first, then
    allow exactly **bold** and `code`, and split paragraphs (first one
    is the lead). The strategist writes emphasis, not documents — a
    full markdown engine here would be an HTML injection surface run on
    LLM output, traded for features the briefing never uses.
    """
    import re

    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    text = escape(str(value or "")).replace("\r\n", "\n").strip()
    if not text:
        return ""
    out = []
    # Paragraphs FIRST, inline passes per paragraph: a ** pair whose
    # members straddle a blank line used to open <strong> in one <p>
    # and close it in the next — unbalanced markup shipped via
    # mark_safe, and the browser's recovery bolded both fragments.
    for i, para in enumerate(
            p.strip() for p in text.split("\n\n") if p.strip()):
        para = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", para,
                      flags=re.S)
        para = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", para)
        cls = "brf-p brf-lead" if i == 0 else "brf-p"
        out.append(f'<p class="{cls}">' + para.replace("\n", "<br>")
                   + "</p>")
    return mark_safe("".join(out))


@register.filter
def research_md(value):
    """Markdown-lite for Ask Sauron answers: escape EVERYTHING first, then
    grow exactly the shapes the research agent writes — fenced code,
    `code`, **bold**, [label →](url) links, ##/### headings, bullet and
    numbered lists, paragraphs (first one is the lead). It runs on LLM
    output, so links are the one place this can hurt: a URL is honoured
    only when it is a same-site path (single leading "/") or https://,
    and anything else — javascript:, data:, protocol-relative // — is
    printed as its label, plain. No markdown library: a full engine here
    would be an HTML injection surface bought for features unused.
    """
    import re

    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    text = escape(str(value or "")).replace("\r\n", "\n").strip()
    if not text:
        return ""

    # Fences come out FIRST, as whole lines, so the inline passes never
    # bold or link something inside a code block.
    fences = []

    def _fence(m):
        fences.append('<pre class="rs-pre"><code>'
                      + m.group(1).strip("\n") + "</code></pre>")
        return "\x00%d\x00" % (len(fences) - 1)

    text = re.sub(r"(?m)^```[^\n]*\n(.*?)^```[ \t]*$", _fence, text,
                  flags=re.S)

    def _link(m):
        label, url = m.group(1), m.group(2)
        # A backslash is a SLASH to every browser's URL parser, so
        # "/\evil.com" is protocol-relative and leaves the site.
        if "\\" not in url and re.match(r"^(?:/(?![/\\])|https://)", url):
            return f'<a class="rs-link" href="{url}">{label}</a>'
        return label

    def _inline(s):
        s = re.sub(r"`([^`\n]+)`", r'<code class="rs-code">\1</code>', s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        # One level of parentheses inside the URL, so a refused
        # javascript:alert(1) is swallowed whole rather than leaving a
        # stray ")" after its label.
        return re.sub(r"\[([^\]\n]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)",
                      _link, s)

    out, para, items, list_tag, n_para = [], [], [], None, 0

    def _flush_para():
        nonlocal n_para
        if para:
            cls = "rs-p rs-lead" if n_para == 0 else "rs-p"
            out.append(f'<p class="{cls}">' + "<br>".join(para) + "</p>")
            n_para += 1
            para.clear()

    def _flush_list():
        if items:
            out.append(f'<{list_tag} class="rs-list">'
                       + "".join(f"<li>{i}</li>" for i in items)
                       + f"</{list_tag}>")
            items.clear()

    for line in text.split("\n"):
        s = line.strip()
        m_fence = re.fullmatch(r"\x00(\d+)\x00", s)
        m_head = re.match(r"^#{1,6}\s+(.+)$", s)
        m_ul = re.match(r"^[-*•]\s+(.+)$", s)
        m_ol = re.match(r"^\d+[.)]\s+(.+)$", s)
        if not s or m_fence or m_head:
            _flush_para()
            _flush_list()
            if m_fence:
                out.append(fences[int(m_fence.group(1))])
            elif m_head:
                out.append('<h4 class="rs-h">' + _inline(m_head.group(1))
                           + "</h4>")
        elif m_ul or m_ol:
            _flush_para()
            tag = "ul" if m_ul else "ol"
            if tag != list_tag:
                _flush_list()
                list_tag = tag
            items.append(_inline((m_ul or m_ol).group(1)))
        else:
            _flush_list()
            para.append(_inline(s))
    _flush_para()
    _flush_list()
    return mark_safe("".join(out))


@register.filter
def briefing_plain(value):
    """briefing_md's plain-text twin for data attributes and preview
    stubs: the emphasis markers come OFF instead of becoming markup —
    a dwell card showing literal asterisks is the same wart the page
    had, one surface over. Output is plain text; Django's attribute
    auto-escaping does the rest."""
    import re
    text = str(value or "")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return text


@register.simple_tag
def px(value, asset_class="", symbol="", dash="—"):
    """A price at the precision its own venue quotes it in.

    `{% px m.last m.asset_class m.symbol %}`

    Replaces `floatformat:4`, which rendered AAPL as 227.5300 and a JPY
    cross one digit past what the broker's ticket shows. See
    core.price_format for the convention.
    """
    from core.price_format import format_price
    return format_price(value, asset_class, symbol, dash)


@register.simple_tag
def px_decimals(value, asset_class="", symbol=""):
    """Just the digit count, for a data-decimals attribute.

    The live painter repaints these cells on every tick, and it has only
    the symbol and the number — not the asset class. Rendering the count
    server-side, where the class IS known, is what stops a value being
    formatted one way on load and another one tick later.
    """
    from core.price_format import price_decimals
    return price_decimals(value, asset_class, symbol)
