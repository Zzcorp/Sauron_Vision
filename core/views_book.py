# -*- coding: utf-8 -*-
"""THE BOOK OF SAURON, served at /book/ (2026-09-27).

A public page, like the Wall it sits beside: anyone may read it, signed in
or not, and an authenticated visitor is NOT sent to the dashboard (the Wall
does that; the book is worth reading from inside too).

What this view adds to the words in core.book_content:

  * the counted numbers. Every figure the platform can measure comes from
    core.wall_facts(), the Wall's own reader: cached, fenced, never raising.
    The text carries {key} placeholders and this view formats them, so the
    page can never print a count the Wall would contradict;
  * the road so far, grouped by era, each milestone's day in words;
  * ONE STAFF-ONLY CHAPTER that is not in this repository at all (the
    repository is public). It is read at runtime from a JSON file outside
    git, and only when a signed-in STAFF user asks: nobody else ever causes
    the read, and the template is given nothing to hide. The file is the
    one the BOOK_STAFF_CHAPTER environment variable names, else
    private/book_staff_chapter.json under the project (.gitignore keeps
    private/ out of git; the image build copies it). Its shape:
        {"label": "...", "note": "...", "lang": "fr",
         "chapter": {"id", "title", "kicker", "paragraphs", "items"}}
    The chapter must be word for word the text verified on 2026-09-26: the
    sha256 of json.dumps(chapter, sort_keys=True, ensure_ascii=False) is
    pinned below. A file that is missing renders nothing; one that cannot
    be read, is shaped otherwise or differs by one character renders
    nothing and logs why (never a word of it). A staff answer is marked
    private and not stored by any cache.

The page renders WITHOUT the request's context processors: a story page
pays none of a dashboard's reads. The template receives the request as a
plain value for one thing only, the absolute address of its card image
({% static_abs %}).

Read-only: no write, no broker, no order, no secret.
"""
import copy
import datetime
import hashlib
import json
import logging
import os
import re
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.cache import patch_cache_control, patch_vary_headers

from core import book_content as book
from core.wall_facts import wall_facts

logger = logging.getLogger(__name__)

#: "{tests_green}" in the book's text: a core.wall_facts key.
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

#: What a placeholder the facts do not carry reads as. Never 0: an unknown
#: is not a measurement (the platform's own rule).
UNKNOWN = "—"

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

#: The environment variable that names the staff-only chapter's file, and
#: the file read when it names none (relative paths are the project's).
STAFF_CHAPTER_ENV = "BOOK_STAFF_CHAPTER"
STAFF_CHAPTER_DEFAULT = Path("private") / "book_staff_chapter.json"

#: sha256 of the staff-only chapter as verified on 2026-09-26 (json.dumps,
#: sorted keys, UTF-8). Word for word or not at all.
STAFF_CHAPTER_SHA256 = (
    "7d66280d3431279d7f6453858589640c7d40bec75093d4b8a6188fbac70cfb1c")

#: A language tag for the chapter's lang attribute.
LANG_TAG = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def shown(value) -> str:
    """A count as a person reads it: 8424 -> "8,424"; not a count -> dash."""
    try:
        return "{:,}".format(int(value))
    except (TypeError, ValueError):
        return UNKNOWN


def count_of(value):
    """The integer the page counts up to, or None when there is none."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def fill(text: str, words: dict) -> str:
    """Put the formatted counts into one sentence of the book."""
    return PLACEHOLDER.sub(lambda m: words.get(m.group(1), UNKNOWN), text)


def _filled(node, words):
    """Every string of a copied structure, with its placeholders filled."""
    if isinstance(node, str):
        return fill(node, words)
    if isinstance(node, list):
        return [_filled(item, words) for item in node]
    if isinstance(node, dict):
        return {key: _filled(value, words) for key, value in node.items()}
    return node


def day_words(iso: str) -> str:
    """ "2026-09-27" -> "27 September 2026"."""
    day = datetime.date.fromisoformat(iso)
    return "%d %s %d" % (day.day, MONTHS[day.month - 1], day.year)


def _counts(rows, facts, words):
    """[{key, label}] -> the cells the template draws and counts up."""
    return [{"key": row["key"], "label": row["label"],
             "shown": words.get(row["key"], UNKNOWN),
             "count": count_of(facts.get(row["key"]))} for row in rows]


def build(facts: dict) -> dict:
    """Everything the template draws, out of the book and the facts."""
    words = {key: shown(value) for key, value in facts.items()}
    chapters = _filled(copy.deepcopy(book.CHAPTERS), words)
    for chapter in chapters:
        for item in chapter.get("items", ()):
            if "count" in item:
                item["count"] = count_of(facts.get(item["count"]))
    eras = []
    for era in book.ERAS:
        milestones = [
            {"date": day, "day": day_words(day), "title": title,
             "text": fill(text, words), "commit": commit}
            for day, era_id, title, text, commit in book.MILESTONES
            if era_id == era["id"]]
        eras.append(dict(_filled(era, words), milestones=milestones))
    by_id = {chapter["id"]: chapter for chapter in chapters}
    by_id["in-progress"]["items"] = _filled(
        copy.deepcopy(book.IN_PROGRESS), words)
    by_id["in-progress"]["road"] = _filled(copy.deepcopy(book.GO_LIVE), words)
    return {
        "hero": _filled(dict(book.HERO), words),
        "hero_stats": _counts(book.HERO_STATS, facts, words),
        "counted": _counts(book.COUNTED, facts, words),
        "chapters": chapters,
        "eras": eras,
        "lexicon": _filled(copy.deepcopy(book.LEXICON), words),
        "written": book.WRITTEN_WORDS,
        "written_iso": book.WRITTEN,
    }


def is_staff(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)
                and (getattr(user, "is_staff", False)
                     or getattr(user, "is_superuser", False)))


# ── The staff-only chapter, read from outside git ───────────────────────────

def staff_chapter_path() -> Path:
    """The file the staff-only chapter is read from."""
    named = (os.environ.get(STAFF_CHAPTER_ENV) or "").strip()
    path = Path(named) if named else STAFF_CHAPTER_DEFAULT
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    return path


def chapter_digest(chapter) -> str:
    """The sha256 the verified text is pinned by."""
    blob = json.dumps(chapter, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _said(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _shaped(data) -> bool:
    """The file's shape: a label, and a chapter of plain strings."""
    if not isinstance(data, dict) or not _said(data.get("label")):
        return False
    if not isinstance(data.get("note", ""), str):
        return False
    chapter = data.get("chapter")
    if not isinstance(chapter, dict):
        return False
    if not (_said(chapter.get("title")) and _said(chapter.get("kicker"))):
        return False
    paragraphs, items = chapter.get("paragraphs"), chapter.get("items")
    return (isinstance(paragraphs, list) and bool(paragraphs)
            and all(_said(p) for p in paragraphs)
            and isinstance(items, list)
            and all(isinstance(i, dict) and _said(i.get("label"))
                    and _said(i.get("text")) for i in items))


def load_staff_chapter():
    """The staff-only chapter as the template draws it, or None.

    Never raises, and never logs a word of the chapter: a missing file is
    silence; a file that cannot be read, is shaped otherwise or is not the
    verified text is a warning that names only the reason.
    """
    path = staff_chapter_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("the book's staff-only chapter could not be read "
                       "(%s); not rendered", type(exc).__name__)
        return None
    if not _shaped(data):
        logger.warning("the book's staff-only chapter is not shaped as the "
                       "book reads it; not rendered")
        return None
    chapter = data["chapter"]
    if chapter_digest(chapter) != STAFF_CHAPTER_SHA256:
        logger.warning("the book's staff-only chapter is not the verified "
                       "text (sha256 differs); not rendered")
        return None
    lang = str(data.get("lang") or "").strip()
    return {
        "label": data["label"].strip(),
        "note": data.get("note", "").strip(),
        "lang": lang if LANG_TAG.match(lang) else "fr",
        "title": chapter["title"],
        "kicker": chapter["kicker"],
        "paragraphs": list(chapter["paragraphs"]),
        "items": [{"label": i["label"], "text": i["text"]}
                  for i in chapter["items"]],
    }


def the_book(request):
    """/book/ — the story, the machine and the road so far. Public."""
    staff = is_staff(request.user)
    context = {
        "book": build(wall_facts()),
        # Read for a signed-in staff user only: for anyone else the file is
        # never opened and the template renders nothing (not something
        # hidden).
        "staff_chapter": load_staff_chapter() if staff else None,
        # For {% static_abs %} alone: the page renders without the context
        # processors.
        "request": request,
    }
    response = HttpResponse(render_to_string("landing/the_book.html", context))
    # The page differs for staff, and staff is decided by the session.
    patch_vary_headers(response, ("Cookie",))
    if staff:
        patch_cache_control(response, private=True, no_store=True)
    return response
