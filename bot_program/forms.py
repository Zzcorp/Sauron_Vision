from django import forms
from .models import BotConfig, BinanceAccount, BotScenario

class BinanceLinkForm(forms.ModelForm):
    api_key = forms.CharField(widget=forms.PasswordInput(render_value=True),
                              required=True, label="API Key")
    api_secret = forms.CharField(widget=forms.PasswordInput(render_value=True),
                                 required=True, label="API Secret")
    class Meta:
        model = BinanceAccount
        fields = ["label", "testnet"]

class BotConfigForm(forms.ModelForm):
    class Meta:
        model = BotConfig
        exclude = ["user", "updated_at"]
        widgets = {"symbols": forms.Textarea(attrs={"rows":2,
            "placeholder":'["BTCUSDT","ETHUSDT","SOLUSDT"]'})}

class ScenarioForm(forms.ModelForm):
    class Meta:
        model = BotScenario
        fields = ["name", "description", "symbols", "start_date", "end_date",
                  "initial_capital", "params"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type":"date"}),
            "end_date":   forms.DateInput(attrs={"type":"date"}),
            "symbols":    forms.Textarea(attrs={"rows":2}),
            "params":     forms.Textarea(attrs={"rows":4,
                "placeholder":'{"position_size_pct": 3, "stop_loss_pct": 2}'}),
        }
