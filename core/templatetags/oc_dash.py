"""The Operations Center's named dashes (OC0, 2026-11-07).

A dash means no figure here, and its line says why; 0 is a measured zero
(the Operations Center spec, §5.7). The page had eight meanings for one
"—" and printed none of them. Here every dash carries its reason as a
title, and the foot of the page (or of the fragment) lists, under "What a
dash means here", every reason drawn above it — once each, in the order
they were drawn:

    {% load oc_dash %}
    {% dash "nothing closed in this world in 24 h" %}
        a dash, with its reason
    <td title="{{ m.title }}">{{ m.value }}</td>{% dash_note m.value m.title %}
        a cell that holds a figure or a dash: noted when it is the dash
    {% dash_legend %}
        the list, at the foot

The reasons are written down in the context's `oc_dashes` list, which the
view hands in (a page with no such list draws its dashes and lists
nothing: /eye/ shares the Eye body). Display only: nothing here reads data.
"""
from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()

DASH = "—"
LEDGER = "oc_dashes"


def _note(context, why):
    ledger = context.get(LEDGER)
    why = " ".join(str(why or "").split())
    if isinstance(ledger, list) and why and why not in ledger:
        ledger.append(why)
    return why


@register.simple_tag(takes_context=True)
def dash(context, why, cls="sv-unknown"):
    """The dash, with its reason as its title (and noted for the legend)."""
    why = _note(context, why)
    return format_html('<span class="{}" title="{}">{}</span>', cls, why, DASH)


@register.simple_tag(takes_context=True)
def dash_note(context, value, why):
    """Notes `why` for the legend when `value` is the dash; prints nothing.
    For a cell whose figure may be a dash and whose title says why."""
    if str(value if value is not None else "").strip() == DASH:
        _note(context, why)
    return ""


@register.simple_tag(takes_context=True)
def dash_legend(context):
    """What a dash means here: every reason drawn above, once each."""
    ledger = context.get(LEDGER) or []
    if not ledger:
        return ""
    items = format_html_join("", '<li data-oc-why>{}</li>',
                             ((why,) for why in ledger))
    return format_html(
        '<div class="oc-dash-legend" data-oc-dash-legend>'
        '<span class="oc-dash-legend-head">What a dash means here</span>'
        '<ul>{}</ul></div>', items)
