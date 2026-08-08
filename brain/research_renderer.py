"""Phase 59 — render markers in research-agent messages.

The agent emits structured markers in its markdown that the template
post-processes into clickable links + actionable buttons:

  <<RULE:rule_name>>          → link to /generated/ (rule context)
  <<HYP:42>>                  → link to /hypotheses/
  <<REPORT:17>>               → link to /brain/
  <<AUDIT:1234>>              → link to /audit/
  <<BRIEFING:9>>              → link to /briefing/

  ```strategy-draft           → fenced code block whose JSON contents
  {<proposal payload>}        →   are parsed into a draft strategy.
  ```                            The template renders a "Save as draft"
                                  button next to it.

This keeps the agent's authorship of citations + proposals explicit (via
markers) while the template owns rendering. Plain markdown text without
markers passes through unchanged — backward compatible.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ── Marker patterns ──────────────────────────────────────────────────────

# All markers share the same enclosing form: `<<KIND:value>>`
_MARKER_RE = re.compile(r"<<\s*(?P<kind>[A-Z_]+)\s*:\s*(?P<value>[^>]+?)\s*>>")

# Strategy-draft fenced code block. Match anything between ```strategy-draft
# (case-insensitive) and the next ``` fence. DOTALL so newlines match `.`.
_DRAFT_BLOCK_RE = re.compile(
    r"```\s*strategy-draft\s*\n(.*?)\n\s*```",
    re.IGNORECASE | re.DOTALL,
)


# ── Marker → URL mapping ─────────────────────────────────────────────────

def _url_for_marker(kind: str, value: str) -> Optional[str]:
    """Return a URL path for a marker, or None if the marker shouldn't link."""
    kind = (kind or "").upper()
    value = (value or "").strip()
    if not value:
        return None
    if kind == "RULE":
        return "/generated/"
    if kind == "HYP":
        return "/hypotheses/"
    if kind == "REPORT":
        return "/brain/"
    if kind == "AUDIT":
        return "/audit/"
    if kind == "BRIEFING":
        return "/briefing/"
    if kind == "EARNINGS":
        return "/earnings-reviews/"
    if kind == "KNOWLEDGE":
        return "/knowledge/"
    return None


def _label_for_marker(kind: str, value: str) -> str:
    """Human-friendly link text. Trim long values so the link doesn't dominate."""
    kind_lower = (kind or "").lower()
    short = value if len(value) <= 40 else value[:37] + "…"
    if kind_lower == "rule":
        return f"rule {short}"
    if kind_lower == "hyp":
        return f"hypothesis #{short}"
    if kind_lower == "report":
        return f"BrainReport #{short}"
    if kind_lower == "audit":
        return f"audit #{short}"
    if kind_lower == "briefing":
        return f"briefing #{short}"
    if kind_lower == "earnings":
        return f"earnings #{short}"
    if kind_lower == "knowledge":
        return f"knowledge #{short}"
    return short


# ── Public renderer ──────────────────────────────────────────────────────

def render_markers(text: str) -> str:
    """Replace `<<KIND:value>>` markers in `text` with markdown links.

    Unknown kinds are kept verbatim so the agent can use new markers
    we haven't taught the renderer yet without breaking. Returns
    plain markdown text safe to pass through Django's `linebreaksbr`.
    """
    if not text:
        return ""

    def _sub(match: re.Match) -> str:
        kind = match.group("kind")
        value = match.group("value").strip()
        url = _url_for_marker(kind, value)
        if url is None:
            # Unknown marker — leave it as plain text so we don't lose info.
            return match.group(0)
        label = _label_for_marker(kind, value)
        return f"[{label} →]({url})"

    return _MARKER_RE.sub(_sub, text)


def extract_strategy_draft(text: str) -> Optional[dict]:
    """If the message contains a fenced ```strategy-draft block, parse and
    return the proposal dict. Returns None when missing or unparseable.

    Accepts the same shape Phase-41 generator uses, so we can pipe directly
    into `signals.strategy_generator.validate_proposal` + `_persist_proposal`.
    """
    if not text:
        return None
    m = _DRAFT_BLOCK_RE.search(text)
    if not m:
        return None
    raw = (m.group(1) or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.info("[research-renderer] strategy-draft JSON parse failed: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    return data


def has_strategy_draft(text: str) -> bool:
    """Cheap pre-check: does the message contain a strategy-draft block?"""
    return bool(text) and bool(_DRAFT_BLOCK_RE.search(text))


# ── Phase 60: Action markers (staff-only inline buttons) ─────────────────

# These markers expand to inline POST-form buttons. Unlike link markers
# (RULE/HYP/REPORT/etc.) they do NOT appear inline in the message body —
# they're stripped out and surfaced as action panels below the message
# (only visible to staff users who have permission to take the action).

_ACTION_MARKER_RE = re.compile(
    r"<<\s*(?P<kind>APPROVE|REJECT|RESTORE)\s*:\s*(?P<value>[^>]+?)\s*>>")


def _action_for_marker(kind: str, value: str) -> Optional[dict]:
    """Map an action marker to the form spec the template renders.

    Returns a dict with:
      - kind:    "approve" | "reject" | "restore"
      - label:   human button text
      - url:     existing admin endpoint URL
      - css:     "primary" | "danger" | "secondary" — for button styling

    Returns None for invalid values (non-int proposal_id, empty rule_name).
    Existing admin endpoints (Phase 41 + Phase 42) are reused — no new
    mutation surface.
    """
    kind = (kind or "").upper()
    value = (value or "").strip()
    if not value:
        return None

    if kind in ("APPROVE", "REJECT"):
        try:
            pk = int(value)
        except (TypeError, ValueError):
            return None
        if kind == "APPROVE":
            return {
                "kind": "approve",
                "label": f"+ Approve proposal #{pk}",
                "url": f"/generated/{pk}/approve/",
                "css": "primary",
            }
        return {
            "kind": "reject",
            "label": f"✗ Reject proposal #{pk}",
            "url": f"/generated/{pk}/reject/",
            "css": "danger",
        }
    if kind == "RESTORE":
        # rule_name allowed to contain alphanumerics + underscores;
        # value passes through to URL — Django URL resolver enforces shape.
        return {
            "kind": "restore",
            "label": f"↻ Restore rule {value}",
            "url": f"/generated/restore/{value}/",
            "css": "secondary",
        }
    return None


def extract_action_markers(text: str) -> tuple[str, list[dict]]:
    """Pull action markers out of `text`. Returns `(cleaned_text, actions)`.

    `cleaned_text` has the markers removed (no inline traces — they become
    button panels below the message). `actions` is a list of dicts ready
    to render as forms (see `_action_for_marker` shape).

    Order is preserved (first marker → first action). Invalid markers are
    left in the text so they don't silently disappear.
    """
    if not text:
        return "", []

    actions: list[dict] = []
    seen_keys: set[str] = set()  # dedupe identical markers in one msg

    def _sub(match: re.Match) -> str:
        kind = match.group("kind")
        value = match.group("value").strip()
        spec = _action_for_marker(kind, value)
        if spec is None:
            return match.group(0)  # leave verbatim — invalid value
        key = f"{spec['kind']}:{value}"
        if key in seen_keys:
            return ""  # already captured this action; just remove the marker
        seen_keys.add(key)
        actions.append(spec)
        return ""  # strip the marker from the text

    cleaned = _ACTION_MARKER_RE.sub(_sub, text)
    # Collapse double-spaces left behind by stripped markers.
    cleaned = re.sub(r"  +", " ", cleaned).strip()
    return cleaned, actions
