"""LE TRÉSOR — where the money is, and whether the broker agrees.

The page twin of `python manage.py tresor`. Both render
bot_program.broker_vision.vision(), so the screen and the terminal cannot
tell different stories about the same account.

Any signed-in user sees THEIR OWN brokers: the rows are on the user, the
computation is user-scoped, and nothing here writes or calls a broker.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

logger = logging.getLogger(__name__)


@login_required
def tresor_page(request):
    from bot_program.broker_vision import vision

    try:
        v = vision(request.user)
    except Exception as e:  # noqa: BLE001 — a money page that 500s tells the
        # operator nothing at the moment they most need it told.
        logger.error("tresor: vision failed for %s: %s", request.user, e)
        v = None
    return render(request, "dashboard/tresor.html",
                  {"page_id": "tresor", "v": v})
