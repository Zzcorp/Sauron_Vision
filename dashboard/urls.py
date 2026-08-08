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
from .views_brain import brain_dashboard, brain_run_now
from .views_brain_phase38 import (
    knowledge_dashboard, knowledge_node_history,
    hypotheses_dashboard, consolidation_dashboard,
    consolidation_run_now, critic_run_now,
    briefing_dashboard, briefing_run_now,
    generated_dashboard, generated_run_now,
    generated_approve, generated_reject,
    demoter_run_now, restore_rule_now,
    intelligence_hub,
    earnings_reviews_dashboard, earnings_reviewer_run_now,
    research_view, research_ask, research_new_conversation,
    research_save_as_draft, research_ask_ajax,
)

from .views_signals_htmx import signal_cards_htmx, signal_performance_htmx
from .views_performance import performance_dashboard
from .views_risk import risk_dashboard
from .views_ai_insights import ai_insights_dashboard
from .views_admin_hq import (
    run_signal_scan, run_smc_lifecycle, run_grade_signals,
    run_decay_investigation, run_daily_snapshot, run_recalc_exposure,
    run_nightly_cleanup, run_full_universe_scan, run_seed_components,
    save_oanda_credentials, save_alpaca_credentials, save_ibkr_credentials,
    disconnect_broker,
    hq_apply_rule_action, hq_reject_rule_action, hq_rollback_rule_action,
    hq_propose_allocation, hq_apply_allocation, hq_rollback_allocation,
    hq_reject_allocation,
    hq_run_promotions, hq_promote_rule, hq_demote_rule,
    hq_run_evolution, hq_apply_evolution, hq_reject_evolution,
    hq_run_opportunity_scan, hq_resolve_opportunities,
    hq_create_opportunity_setup, hq_toggle_opportunity_setup,
    hq_run_pattern_miner, hq_activate_discovery, hq_reject_discovery,
    hq_fire_test_event,
    hq_create_asset_bot, hq_toggle_asset_bot, hq_run_asset_bot, hq_run_all_asset_bots,
)
from .views_promotions import promotions_dashboard
from .views_evolution import evolution_dashboard
from .views_opportunities import opportunities_dashboard
from .views_discoveries import discoveries_dashboard
from .views_events import events_dashboard
from .views_asset_bots import asset_bots_dashboard
from .views_rule_control import rule_control_dashboard
from .views_calibration import calibration_dashboard
from .views_ai_models import ai_models_dashboard
from .views_system_health import system_health
from .views_forensics import forensics_list, forensics_detail
from .views_allocator import allocator_dashboard
from .views_eye import eye_dashboard, eye_partial
from .views_eye_drilldown import eye_gate_events, eye_fills, eye_exposure
from .views_command import (
    command_center, command_tab_live, command_tab_portfolio,
    command_tab_history, command_tab_bots,
)
from .views_bot_performance import bot_performance_dashboard
from .views_bot_backtest import (
    bot_backtest_list, bot_backtest_run, bot_backtest_detail,
)
from .views_audit import audit_dashboard, audit_export
from .views_tax_lots import tax_lots_dashboard, tax_lots_export
from .api import market_views, signal_views, strategy_views, portfolio_views, ai_views
from core.views import rate_limiter_stats, system_status

urlpatterns = [
    # ── Command Center (unified Dashboard + Eye merge) ───────
    path("command/", command_center, name="command_center"),
    path("command/tab/live/", command_tab_live, name="command_tab_live"),
    path("command/tab/portfolio/", command_tab_portfolio, name="command_tab_portfolio"),
    path("command/tab/history/", command_tab_history, name="command_tab_history"),
    path("command/tab/bots/", command_tab_bots, name="command_tab_bots"),

    # ── Frontend Pages ──────────────────────────────────────
    path("", views.dashboard, name="dashboard"),
    path("instruments/", views.instruments_list, name="instruments_list"),
    path("instruments/<str:symbol>/", views.instrument_detail, name="instrument_detail"),
    path("api/instrument-preview/<str:symbol>/", views.instrument_preview_api, name="instrument_preview_api"),
    path("quotes/", views.market_quotes, name="market_quotes"),
    path("calendar/", views.economic_calendar, name="economic_calendar"),
    path("signals/", views.signals_list, name="signals_list"),
    path("performance/", performance_dashboard, name="performance_dashboard"),
    path("risk/", risk_dashboard, name="risk_dashboard"),
    path("ai-journal/", ai_insights_dashboard, name="ai_journal_dashboard"),
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

    # ── Admin HQ Console: run-now endpoints ───────────────────
    path("admin-dashboard/run/signal-scan/", run_signal_scan, name="hq_run_signal_scan"),
    path("admin-dashboard/run/smc-lifecycle/", run_smc_lifecycle, name="hq_run_smc_lifecycle"),
    path("admin-dashboard/run/grade-signals/", run_grade_signals, name="hq_run_grade_signals"),
    path("admin-dashboard/run/decay-investigation/", run_decay_investigation, name="hq_run_decay_investigation"),
    path("admin-dashboard/run/daily-snapshot/", run_daily_snapshot, name="hq_run_daily_snapshot"),
    path("admin-dashboard/run/recalc-exposure/", run_recalc_exposure, name="hq_run_recalc_exposure"),
    path("admin-dashboard/run/nightly-cleanup/", run_nightly_cleanup, name="hq_run_nightly_cleanup"),
    path("admin-dashboard/run/full-universe-scan/", run_full_universe_scan, name="hq_run_full_universe_scan"),
    path("admin-dashboard/run/seed-components/", run_seed_components, name="hq_run_seed_components"),

    # ── Admin HQ Console: broker credentials ─────────────────
    path("admin-dashboard/brokers/oanda/save/", save_oanda_credentials, name="hq_save_oanda"),
    path("admin-dashboard/brokers/alpaca/save/", save_alpaca_credentials, name="hq_save_alpaca"),
    path("admin-dashboard/brokers/ibkr/save/", save_ibkr_credentials, name="hq_save_ibkr"),
    path("admin-dashboard/brokers/disconnect/", disconnect_broker, name="hq_disconnect_broker"),

    # ── Phase 5: Rule Actuator (closed-loop) ─────────────────
    path("admin-dashboard/actuator/apply/", hq_apply_rule_action, name="hq_apply_rule_action"),
    path("admin-dashboard/actuator/reject/", hq_reject_rule_action, name="hq_reject_rule_action"),
    path("admin-dashboard/actuator/rollback/", hq_rollback_rule_action, name="hq_rollback_rule_action"),
    path("rule-control/", rule_control_dashboard, name="rule_control_dashboard"),
    path("calibration/", calibration_dashboard, name="calibration_dashboard"),
    path("ai-models/", ai_models_dashboard, name="ai_models_dashboard"),
    path("health/", system_health, name="system_health"),
    path("forensics/", forensics_list, name="forensics_list"),
    path("forensics/<int:trade_id>/", forensics_detail, name="forensics_detail"),
    path("allocator/", allocator_dashboard, name="allocator_dashboard"),

    # ── Phase 7: Meta-Allocator ──────────────────────────────
    path("admin-dashboard/allocator/propose/", hq_propose_allocation, name="hq_propose_allocation"),
    path("admin-dashboard/allocator/apply/", hq_apply_allocation, name="hq_apply_allocation"),
    path("admin-dashboard/allocator/rollback/", hq_rollback_allocation, name="hq_rollback_allocation"),
    path("admin-dashboard/allocator/reject/", hq_reject_allocation, name="hq_reject_allocation"),

    # ── Phase 8: Promotion Pipeline ──────────────────────────
    path("admin-dashboard/promotions/run/", hq_run_promotions, name="hq_run_promotions"),
    path("admin-dashboard/promotions/promote/", hq_promote_rule, name="hq_promote_rule"),
    path("admin-dashboard/promotions/demote/", hq_demote_rule, name="hq_demote_rule"),
    path("promotions/", promotions_dashboard, name="promotions_dashboard"),

    # ── Phase 9: Strategy Evolution ──────────────────────────
    path("admin-dashboard/evolution/run/", hq_run_evolution, name="hq_run_evolution"),
    path("admin-dashboard/evolution/apply/", hq_apply_evolution, name="hq_apply_evolution"),
    path("admin-dashboard/evolution/reject/", hq_reject_evolution, name="hq_reject_evolution"),
    path("evolution/", evolution_dashboard, name="evolution_dashboard"),

    # ── Phase 10: Opportunity Scanner ────────────────────────
    path("admin-dashboard/opportunities/scan/", hq_run_opportunity_scan, name="hq_run_opportunity_scan"),
    path("admin-dashboard/opportunities/resolve/", hq_resolve_opportunities, name="hq_resolve_opportunities"),
    path("admin-dashboard/opportunities/create/", hq_create_opportunity_setup, name="hq_create_opportunity_setup"),
    path("admin-dashboard/opportunities/toggle/", hq_toggle_opportunity_setup, name="hq_toggle_opportunity_setup"),
    path("opportunities/", opportunities_dashboard, name="opportunities_dashboard"),

    # ── Phase 11: Pattern Miner / Discovered Setups ──────────
    path("admin-dashboard/discoveries/mine/", hq_run_pattern_miner, name="hq_run_pattern_miner"),
    path("admin-dashboard/discoveries/activate/", hq_activate_discovery, name="hq_activate_discovery"),
    path("admin-dashboard/discoveries/reject/", hq_reject_discovery, name="hq_reject_discovery"),
    path("discoveries/", discoveries_dashboard, name="discoveries_dashboard"),

    # ── Phase 12: Real-time Event Engine ─────────────────────
    path("admin-dashboard/events/fire/", hq_fire_test_event, name="hq_fire_test_event"),
    path("events/", events_dashboard, name="events_dashboard"),

    # ── Phase 13: Multi-Asset Bots ───────────────────────────
    path("admin-dashboard/asset-bots/create/", hq_create_asset_bot, name="hq_create_asset_bot"),
    path("admin-dashboard/asset-bots/toggle/", hq_toggle_asset_bot, name="hq_toggle_asset_bot"),
    path("admin-dashboard/asset-bots/tick/", hq_run_asset_bot, name="hq_run_asset_bot"),
    path("admin-dashboard/asset-bots/tick-all/", hq_run_all_asset_bots, name="hq_run_all_asset_bots"),
    path("asset-bots/", asset_bots_dashboard, name="asset_bots_dashboard"),

    # Phase 16 — Sauron's Eye (unified all-asset dashboard)
    path("eye/", eye_dashboard, name="eye_dashboard"),
    path("eye/partial/", eye_partial, name="eye_partial"),

    # Phase 21 — Eye drill-down panels
    path("eye/gate-events/", eye_gate_events, name="eye_gate_events"),
    path("eye/fills/", eye_fills, name="eye_fills"),
    path("eye/exposure/", eye_exposure, name="eye_exposure"),

    # Phase 17 — Bot-trade reinforcement loop / performance dashboard
    path("bot-performance/", bot_performance_dashboard, name="bot_performance_dashboard"),

    # Phase 18 — Bot-trade backtester
    path("bot-backtest/", bot_backtest_list, name="bot_backtest_list"),
    path("bot-backtest/run/", bot_backtest_run, name="bot_backtest_run"),
    path("bot-backtest/<int:run_id>/", bot_backtest_detail, name="bot_backtest_detail"),

    # Phase 28 — Immutable audit log (admin only)
    path("audit/", audit_dashboard, name="audit_dashboard"),
    path("audit/export/", audit_export, name="audit_export"),

    # Phase 27 — Tax-lot bookkeeping (per user)
    path("tax-lots/", tax_lots_dashboard, name="tax_lots_dashboard"),
    path("tax-lots/export/", tax_lots_export, name="tax_lots_export"),
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

    # ── Phase 37: Sauron's Mind dashboard ──────────────────────────────────────
    path("brain/", brain_dashboard, name="brain_dashboard"),
    path("brain/run/", brain_run_now, name="brain_run_now"),

    # ── Phase 38: knowledge graph + hypothesis market ──────────────────────────
    path("knowledge/", knowledge_dashboard, name="knowledge_dashboard"),
    path("knowledge/<str:kind>/<str:key>/", knowledge_node_history,
         name="knowledge_node_history"),
    path("hypotheses/", hypotheses_dashboard, name="hypotheses_dashboard"),
    path("hypotheses/critic-run/", critic_run_now, name="critic_run_now"),
    path("consolidation/", consolidation_dashboard, name="consolidation_dashboard"),
    path("consolidation/run/", consolidation_run_now, name="consolidation_run_now"),

    # ── Phase 40: Strategist Briefing ──────────────────────────────────────────
    path("briefing/", briefing_dashboard, name="briefing_dashboard"),
    path("briefing/run/", briefing_run_now, name="briefing_run_now"),

    # ── Phase 41: Strategy Generator ───────────────────────────────────────────
    path("generated/", generated_dashboard, name="generated_dashboard"),
    path("generated/run/", generated_run_now, name="generated_run_now"),
    path("generated/<int:pk>/approve/", generated_approve, name="generated_approve"),
    path("generated/<int:pk>/reject/", generated_reject, name="generated_reject"),

    # ── Phase 42: auto-demoter ─────────────────────────────────────────────────
    path("generated/demote-now/", demoter_run_now, name="demoter_run_now"),
    path("generated/restore/<str:rule_name>/", restore_rule_now, name="restore_rule_now"),

    # ── Phase 48: Intelligence hub (single-screen overview) ────────────────────
    path("intelligence/", intelligence_hub, name="intelligence_hub"),

    # ── Phase 49: Earnings reviewer ────────────────────────────────────────────
    path("earnings-reviews/", earnings_reviews_dashboard,
         name="earnings_reviews_dashboard"),
    path("earnings-reviews/run/", earnings_reviewer_run_now,
         name="earnings_reviewer_run_now"),

    # ── Phase 50: Research conversational tab ──────────────────────────────────
    path("research/", research_view, name="research_view"),
    path("research/ask/", research_ask, name="research_ask"),
    path("research/new/", research_new_conversation,
         name="research_new_conversation"),
    # Phase 59 — save a strategy-draft block from an assistant message.
    path("research/save-draft/<int:message_id>/", research_save_as_draft,
         name="research_save_as_draft"),
    # Phase 64 — JSON ask endpoint for the global floating chat widget.
    path("research/ask-ajax/", research_ask_ajax, name="research_ask_ajax"),
]
