from django import template
register = template.Library()


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
