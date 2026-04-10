"""Sauron Vision — Dashboard URL Configuration."""
from django.urls import path
from . import views
from .reports import generate_portfolio_report
from .views_metrics import (
    signals_metrics, strategies_metrics, news_metrics,
    backtest_metrics, portfolio_metrics, positions_metrics,
)
from .views_profile_modals import (
    pin_modal, password_modal, change_password, change_pin_modal,
)
from .views_admin_bots import (
    admin_bots_panel, admin_bot_toggle, admin_bot_shadow,
    admin_bot_reset_circuit, admin_bot_reconcile,
)
from .views_strategy_wizard import strategy_wizard, strategy_wizard_save
from .views_bot_console import bot_console, bot_pause

from .views_signals_htmx import signal_cards_htmx, signal_performance_htmx
from .api import market_views, signal_views, strategy_views, portfolio_views, ai_views
from core.views import rate_limiter_stats, system_status

urlpatterns = [
    # ── Frontend Pages ──────────────────────────────────────
    path("", views.dashboard, name="dashboard"),
    path("instruments/", views.instruments_list, name="instruments_list"),
    path("instruments/<str:symbol>/", views.instrument_detail, name="instrument_detail"),
    path("api/instrument-preview/<str:symbol>/", views.instrument_preview_api, name="instrument_preview_api"),
    path("quotes/", views.market_quotes, name="market_quotes"),
    path("calendar/", views.economic_calendar, name="economic_calendar"),
    path("signals/", views.signals_list, name="signals_list"),
    path("strategies/", views.strategies_list, name="strategies_list"),
    path("strategies/<int:pk>/", views.strategy_detail, name="strategy_detail"),
    path("news/", views.news_feed, name="news_feed"),
    path("news/<int:pk>/", __import__("dashboard.news_detail", fromlist=["news_detail"]).news_detail, name="news_detail"),
    path("api/live/metrics/", __import__("dashboard.news_detail", fromlist=["live_metrics_json"]).live_metrics_json, name="live_metrics"),
    path("api/live/health/", __import__("dashboard.live_health", fromlist=["live_health"]).live_health, name="live_health"),
    path("liquidations/", __import__("dashboard.liquidations_view", fromlist=["liquidations_page"]).liquidations_page, name="liquidations_page"),
    path("api/liquidations/", __import__("dashboard.liquidations_view", fromlist=["liquidations_json"]).liquidations_json, name="liquidations_json"),
    path("portfolio/", views.portfolio_overview, name="portfolio_overview"),
    path("positions/", views.positions_list, name="positions_list"),
    path("ai/", views.ai_insights, name="ai_insights"),
    path("ai/tasks/", views.ai_tasks_list, name="ai_tasks_list"),
    path("ai/chat/", views.ai_chat_page, name="ai_chat"),
    path("api/ai-chat/", views.ai_chat_api, name="ai_chat_api"),
    path("api/ai-chat/stream/", views.ai_chat_stream, name="ai_chat_stream"),
    path("backtest/", views.backtest_list, name="backtest_list"),
    path("backtest/create/", views.backtest_create, name="backtest_create"),
    path("profile/", views.profile, name="profile"),
    path("profile/change-pin/", __import__("dashboard.pin_views", fromlist=["change_pin"]).change_pin, name="change_pin"),
    path("setup/", views.setup, name="setup"),
    path("getting-started/", views.getting_started, name="getting_started"),
    path("toggle-theme/", views.toggle_theme, name="toggle_theme"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-dashboard/toggle/", views.admin_toggle_component, name="admin_toggle_component"),
    path("admin-dashboard/bulk-toggle/", views.admin_bulk_toggle, name="admin_bulk_toggle"),
    path("admin-dashboard/create-user/", views.admin_create_user, name="admin_create_user"),
    path("admin-dashboard/toggle-market/", views.admin_toggle_market, name="admin_toggle_market"),
    path("admin-dashboard/newsletters/", views.admin_newsletters, name="admin_newsletters"),
    path("notifications/", views.user_notifications, name="user_notifications"),
    path("notifications/read/<int:notif_id>/", views.mark_notification_read, name="mark_notification_read"),
    path("notifications/read-all/", views.mark_all_notifications_read, name="mark_all_notifications_read"),
    path("intro/", views.intro_page, name="intro"),

    # ── API Endpoints ───────────────────────────────────────
    path("api/instruments/", market_views.InstrumentListView.as_view(), name="api-instrument-list"),
    path("api/quotes/", market_views.LiveQuoteListView.as_view(), name="api-live-quotes"),
    path("api/calendar/", market_views.EconomicCalendarView.as_view(), name="api-economic-calendar"),
    path("api/signals/", signal_views.SignalListView.as_view(), name="api-signal-list"),
    path("api/signals/active/", signal_views.ActiveSignalListView.as_view(), name="api-active-signals"),
    path("api/strategies/", strategy_views.StrategyListView.as_view(), name="api-strategy-list"),
    path("api/strategies/<int:pk>/", strategy_views.StrategyDetailView.as_view(), name="api-strategy-detail"),
    path("api/portfolio/", portfolio_views.PortfolioView.as_view(), name="api-portfolio"),
    path("api/portfolio/positions/", portfolio_views.PositionListView.as_view(), name="api-positions"),
    path("api/portfolio/snapshots/", portfolio_views.SnapshotListView.as_view(), name="api-snapshots"),
    path("api/ai/tasks/", ai_views.AgentTaskListView.as_view(), name="api-ai-tasks"),
    path("api/ai/briefing/", ai_views.DailyBriefingView.as_view(), name="api-daily-briefing"),
    path("htmx/signal-cards/", signal_cards_htmx, name="htmx_signal_cards"),
    path("htmx/signal-performance/", signal_performance_htmx, name="htmx_signal_performance"),
    path("htmx/metrics/signals/", signals_metrics, name="metrics_signals"),
    path("htmx/metrics/strategies/", strategies_metrics, name="metrics_strategies"),
    path("htmx/metrics/news/", news_metrics, name="metrics_news"),
    path("htmx/metrics/backtest/", backtest_metrics, name="metrics_backtest"),
    path("htmx/metrics/portfolio/", portfolio_metrics, name="metrics_portfolio"),
    path("htmx/metrics/positions/", positions_metrics, name="metrics_positions"),
    path("htmx/profile/pin-modal/", pin_modal, name="pin_modal"),
    path("htmx/profile/password-modal/", password_modal, name="password_modal"),
    path("profile/change-password/", change_password, name="change_password"),
    path("profile/change-pin-modal/", change_pin_modal, name="change_pin_modal"),
    path("htmx/admin/bots/", admin_bots_panel, name="admin_bots_panel"),
    path("htmx/admin/bots/<int:config_id>/toggle/", admin_bot_toggle, name="admin_bot_toggle"),
    path("htmx/admin/bots/<int:config_id>/shadow/", admin_bot_shadow, name="admin_bot_shadow"),
    path("htmx/admin/bots/<int:config_id>/reset-circuit/", admin_bot_reset_circuit, name="admin_bot_reset_circuit"),
    path("htmx/admin/bots/<int:config_id>/reconcile/", admin_bot_reconcile, name="admin_bot_reconcile"),
    path("strategies/new/", strategy_wizard, name="strategy_wizard"),
    path("strategies/new/save/", strategy_wizard_save, name="strategy_wizard_save"),
    path("bot/console/", bot_console, name="bot_console"),
    path("bot/console/pause/", bot_pause, name="bot_pause"),

    # ── System Status APIs ─────────────────────────────────
    path("api/system/rate-limits/", rate_limiter_stats, name="rate_limiter_stats"),
    path("api/system/status/", system_status, name="system_status"),

    # ── Chart Data API ──────────────────────────────────────
    path("api/chart-data/", views.chart_data_api, name="chart_data_api"),

    # ── Risk API ──────────────────────────────────────────
    path("api/risk/", views.risk_dashboard_api, name="risk_dashboard_api"),

    # ── Dashboard Preset APIs ───────────────────────────────
    path("api/dashboard/presets/", views.dashboard_presets_api, name="dashboard_presets_api"),
    path("api/dashboard/presets/<int:preset_id>/activate/", views.dashboard_preset_activate, name="dashboard_preset_activate"),
    path("api/dashboard/presets/<int:preset_id>/delete/", views.dashboard_preset_delete, name="dashboard_preset_delete"),

    # ── Reports ────────────────────────────────────────────
    path("reports/portfolio/", generate_portfolio_report, name="portfolio_report"),

    # ── Annotations API ───────────────────────────────────
    path("api/annotations/", views.annotations_api, name="annotations_api"),
    path("api/annotations/<int:pk>/delete/", views.annotation_delete, name="annotation_delete"),

    # ── Pop-Out Panel ─────────────────────────────────────
    path("popout/", views.popout_panel, name="popout_panel"),

    # ── Kill Switch ────────────────────────────────────────
    path("api/kill-switch/", views.kill_switch_api, name="kill_switch_api"),

    # ── Price Alerts ───────────────────────────────────────
    path("api/price-alerts/", views.price_alerts_api, name="price_alerts_api"),
    path("api/price-alerts/<int:pk>/delete/", views.price_alert_delete, name="price_alert_delete"),

    # ── Audit Log ──────────────────────────────────────────
    path("api/audit-log/", views.audit_log_api, name="audit_log_api"),

    # ── Session Management ─────────────────────────────────
    path("api/sessions/", views.active_sessions_api, name="active_sessions_api"),

    # ── Backtesting / Simulation / Sizing APIs ─────────────
    path("api/monte-carlo/", views.monte_carlo_api, name="monte_carlo_api"),
    path("api/regime/", views.regime_api, name="regime_api"),
    path("api/position-sizing/", views.position_sizing_api, name="position_sizing_api"),

    # ── AI/Data Enhancement APIs ────────────────────────────
    path("api/sentiment-index/", views.sentiment_index_api, name="sentiment_index_api"),
    path("api/calibration/", views.agent_calibration_api, name="agent_calibration_api"),
    path("api/rag/search/", views.rag_search_api, name="rag_search_api"),

    # ── NLP / Rotation / Earnings / Journal APIs ───────────────────────────
    path("api/sector-rotation/", views.sector_rotation_api, name="sector_rotation_api"),
    path("api/earnings-predictor/", views.earnings_predictor_api, name="earnings_predictor_api"),
    path("api/trade-journal/", views.trade_journal_api, name="trade_journal_api"),

    # ── Webhook APIs ────────────────────────────────────────
    path("api/webhooks/", views.webhooks_api, name="webhooks_api"),
    path("api/webhooks/<int:pk>/delete/", views.webhook_delete, name="webhook_delete"),
    path("api/webhooks/<int:pk>/test/", views.webhook_test, name="webhook_test"),

    # ── On-Chain Analytics API ──────────────────────────────
    path("api/onchain/", views.onchain_api, name="onchain_api"),

    # ── NL Trade / Compliance / Commentary APIs ────────────────────────────────
    path("api/nl-trade/", views.nl_trade_api, name="nl_trade_api"),
    path("api/compliance/", views.compliance_api, name="compliance_api"),
    path("api/market-commentary/", views.market_commentary_api, name="market_commentary_api"),
]
