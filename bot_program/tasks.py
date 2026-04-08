from celery import shared_task
from .engine.runner import run_bot_tick
from .engine.backtest import run_scenario
from .models import BotConfig, BotScenario

@shared_task
def tick_all_bots():
    for cfg in BotConfig.objects.filter(enabled=True):
        try:
            run_bot_tick(cfg.user_id)
        except Exception as e:
            print(f"tick failed for user={cfg.user_id}: {e}")

@shared_task
def run_scenario_task(scenario_id: int):
    try:
        run_scenario(BotScenario.objects.get(id=scenario_id))
    except Exception as e:
        print(f"scenario failed {scenario_id}: {e}")
