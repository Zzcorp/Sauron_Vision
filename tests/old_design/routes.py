"""Every routed page of the URL conf, against the measured scenes (the
review of B0: PAGES was the sweep's list, frozen, and the test that held
the scenes to it read PAGES on both sides, so /popout/ and /strategies/new/
went unmeasured and a page added later would have been too).

A route is a page when its view renders a whole document: a template with
its own <html>, or one that extends one (base.html and the standalone
pages). The view's source names its templates (render(), a template_name,
a TemplateResponse); the template's own text, read through its extends,
says whether it is a document. Read from the code, never by requesting a
route: no view runs here."""
import inspect
import re

from django.template.loader import get_template
from django.urls import URLPattern, URLResolver, get_resolver

_TEMPLATE_NAME = re.compile(r"""['"]([\w./-]+\.html)['"]""")
_DOC_CACHE = {}


def url_patterns():
    """(route, pattern) of every URL the conf routes, '/'-rooted."""
    def walk(patterns, prefix):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                yield prefix + str(p.pattern), p
    for raw, p in walk(get_resolver().url_patterns, ""):
        yield "/" + raw.replace("^", "").replace("$", "").replace("\\Z", ""), p


def view_templates(callback):
    """The templates a view's source names."""
    seen = []
    targets = [callback]
    cls = getattr(callback, "view_class", None)
    if cls is not None:
        targets.append(cls)
        name = getattr(cls, "template_name", None)
        if name:
            seen.append(name)
    fn = callback
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
        targets.append(fn)
    for target in targets:
        try:
            src = inspect.getsource(target)
        except (OSError, TypeError):
            continue
        seen += _TEMPLATE_NAME.findall(src)
    out = []
    for name in seen:
        if name not in out:
            out.append(name)
    return out


def is_document(name, depth=0):
    """Whether a template renders a whole page: its own <html>, or an
    extends that does."""
    if name in _DOC_CACHE:
        return _DOC_CACHE[name]
    try:
        text = get_template(name).template.source
    except Exception:
        _DOC_CACHE[name] = False
        return False
    found = bool(re.search(r"<!doctype\s+html|<html[\s>]", text, re.I))
    if not found and depth < 8:
        m = re.search(r"{%\s*extends\s+['\"]([^'\"]+)['\"]", text)
        found = bool(m) and is_document(m.group(1), depth + 1)
    _DOC_CACHE[name] = found
    return found


def page_routes():
    """{route: [document templates]} of every route whose view renders a
    whole page."""
    out = {}
    for route, p in url_patterns():
        docs = [t for t in view_templates(p.callback) if is_document(t)]
        if docs:
            out[route] = docs
    return out


#: Routes that render a page and are not a scene, each with its reason.
NOT_MEASURED = {
    "/logout/": "ends the session (registration/logged_out.html is never shown: the view redirects)",
}
