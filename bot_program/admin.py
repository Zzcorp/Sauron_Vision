from django.contrib import admin
from .models import BinanceAccount, BotConfig, BotTrade, BotScenario
admin.site.register(BinanceAccount)
admin.site.register(BotConfig)
admin.site.register(BotTrade)
admin.site.register(BotScenario)
