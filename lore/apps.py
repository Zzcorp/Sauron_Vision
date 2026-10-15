from django.apps import AppConfig


class LoreConfig(AppConfig):
    """The Lore (2026-10-14): Sauron's library of strategies, fund playbooks,
    past episodes and market concepts, written in our own words with their
    sources. Reference data for agents, never an instruction."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "lore"
    verbose_name = "The Lore"
