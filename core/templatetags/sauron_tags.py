from django import template
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
