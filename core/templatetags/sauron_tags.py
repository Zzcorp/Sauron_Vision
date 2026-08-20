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
