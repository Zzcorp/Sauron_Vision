from django import forms
from django.contrib import admin
from .models import BinanceAccount, BotConfig, BotTrade, BotScenario


#: The Django admin never arms a LIVE bot (2026-10-23): that takes the
#: trading PIN, which this page never asks for.
NEVER_ARMS = ("Arming a LIVE bot takes your trading PIN, and this admin page "
              "never asks for one: arm it from the bot page with your PIN. "
              "Nothing was saved.")


class BotConfigAdminForm(forms.ModelForm):
    """Refuses, with a form error, any save that would leave a legacy
    crypto bot armed LIVE that was not (OFF -> ON in live mode, or an
    enabled config moved to live; core.trading_pin.arms_live), on the
    change form and the add form alike. Turning one off stays free, and
    paper is unchanged. `clean()` runs before the instance takes the POST;
    the stored state is re-read anyway. `_request` is set per request on
    the form class the admin builds."""

    _request = None

    class Meta:
        model = BotConfig
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        from core.trading_pin import arms_live, no_pin_here
        inst = self.instance
        want_enabled = cleaned.get("enabled", inst.enabled) \
            if "enabled" in self.fields else inst.enabled
        want_mode = cleaned.get("mode", inst.mode) \
            if "mode" in self.fields else inst.mode
        stored = None
        if inst.pk:
            stored = BotConfig.objects.filter(pk=inst.pk).values_list(
                "enabled", "mode").first()
        was_enabled, was_mode = stored if stored else (False, "paper")
        if arms_live(was_enabled=was_enabled, was_mode=was_mode,
                     want_enabled=want_enabled, want_mode=want_mode):
            no_pin_here(self._request, act="arm a live bot (Django admin)",
                        via="django_admin",
                        user=getattr(self._request, "user", None))
            self.add_error("enabled" if "enabled" in self.fields else None,
                           NEVER_ARMS)
        return cleaned


@admin.register(BotConfig)
class BotConfigAdmin(admin.ModelAdmin):
    form = BotConfigAdminForm

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        form._request = request     # a fresh class per call
        return form


admin.site.register(BinanceAccount)
admin.site.register(BotTrade)
admin.site.register(BotScenario)
