"""THE PLAIN WORDS FOR A VOICE, OUTSIDE THE HORDE (dashboard/plain_words.py,
PR68). A voice's words are the debate's two sides, the reviewer's
reasoning and the operator's own thesis. The Orcs keep or show them as
written, or withhold them whole when they name an exception or may name an
amount of money. Nothing is ever cut out of them.

A voice's line is read against the row's own amounts by value, through
`row_marks`. That is the Horde's own reading (horde._debate_marks on the
row alone): the sizer's risk budget, and qty x |price - stop| x value per
unit over every price, stop and size the row records for its entry. The
council's record of the debate is never read here, so neither function
makes a query. Every Orc surface that shows a voice says what the Horde
says: the dossier, the thesis, /orc on Telegram, the positions line and
the close note.
"""
from dashboard.plain_words import LINE_MAX, scrub


def row_marks(trade):
    """The row's own amounts as plain_words.money_marks, read by value;
    None for no row, a row that states none, or one that cannot be read.
    No query: the row's debate record is left out, as the Horde's seat
    leaves it out (horde._orc_plain)."""
    if trade is None:
        return None
    try:
        from dashboard.horde import _debate_marks
        meta = trade.metadata if isinstance(
            getattr(trade, "metadata", None), dict) else {}
        return _debate_marks(trade, {k: v for k, v in meta.items()
                                     if k != "debate"})
    except Exception:  # noqa: BLE001 — no mark is a mark less, never a failure
        return None


def voice(text, marks=None, *, keep_lines=False) -> str:
    """A voice's words as written, or withheld whole (plain_words.scrub):
    plain_words.WITHHELD_ERROR when they name an exception, WITHHELD when
    they may name an amount of money. "" for no words. Never cut;
    `keep_lines` keeps the line breaks of a longer answer."""
    t = str(text or "")
    return scrub(t, max(len(t), LINE_MAX), marks, keep_lines=keep_lines)
