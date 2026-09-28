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
