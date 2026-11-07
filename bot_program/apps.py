from django.apps import AppConfig


class BotProgramConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bot_program"
    verbose_name = "Bot Program"

    def ready(self):
        # One IBKR session per process and purpose, closed when the request
        # or the worker child ends — see bot_program/engine/ibkr_sessions.
        from .engine.ibkr_sessions import install_signal_handlers
        install_signal_handlers()
        # THE ORCS (bot_program/orcs/lifecycle.py): the receiver that ends
        # an idea when its last leg closes. No query for a row with no Orc.
        from .orcs import lifecycle  # noqa: F401
        # THE FEED'S HARM COUNTERS (the eToro feed spec, F1,
        # bot_program/feed_harms.py): the receiver that counts how each
        # real exit was booked. No query and no write on a save's path.
        connect_harm_counters()


def connect_harm_counters() -> bool:
    """Register the harm counters' receiver. FENCED (2026-11-07, the review
    of F1): a counter that cannot load leaves the exit count off — told
    once — and never stops the app, its workers or its beat from starting.
    """
    try:
        from . import feed_harms  # noqa: F401
        return True
    except Exception as e:  # noqa: BLE001 — a counter, never the app
        try:
            from bot_program import feed_fence
            feed_fence.told("app start", "the harm counters' receiver", e)
        except Exception:  # noqa: BLE001
            pass
        return False
