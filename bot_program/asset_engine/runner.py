"""AssetBot runners — invoked from Celery tasks or admin "Run Now" buttons.

Two entry points:
  - run_asset_bot_tick(config_id) → run one config's tick
  - run_all_asset_bots() → tick every enabled config; aggregate result

Both swallow per-bot exceptions (one bot's failure must not stop others).
"""
import logging

from .base import make_bot

logger = logging.getLogger(__name__)


def run_asset_bot_tick(config_id: int) -> dict:
    """Run one tick for the given AssetBotConfig. Returns the bot's summary dict
    (or an error dict if the config is missing / disabled)."""
    from bot_program.models import AssetBotConfig

    cfg = AssetBotConfig.objects.filter(id=config_id).first()
    if cfg is None:
        return {"status": "error", "reason": "config_not_found", "config_id": config_id}
    if not cfg.enabled:
        return {"status": "skipped", "reason": "disabled", "config_id": config_id}

    try:
        bot = make_bot(cfg)
    except Exception as e:
        return {"status": "error", "reason": f"make_bot_failed: {e}",
                "config_id": config_id}

    try:
        return {"status": "ok", **bot.tick()}
    except Exception as e:
        logger.exception("[asset_bot] tick raised for cfg=%s", config_id)
        return {"status": "error", "reason": str(e), "config_id": config_id}


def run_all_asset_bots() -> dict:
    """Tick every enabled AssetBotConfig. Returns aggregate summary."""
    from bot_program.models import AssetBotConfig

    summaries = []
    for cfg in AssetBotConfig.objects.filter(enabled=True):
        summaries.append(run_asset_bot_tick(cfg.id))

    return {
        "status": "ok",
        "configs_ticked": len(summaries),
        "summaries": summaries,
    }
