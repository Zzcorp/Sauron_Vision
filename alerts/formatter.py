"""Alert message formatting."""


def format_signal_alert(signal) -> tuple:
    """Format a Signal into alert title and message."""
    emoji = "🟢" if signal.direction == "bullish" else "🔴" if signal.direction == "bearish" else "🟡"

    title = f"{emoji} {signal.title}"
    message = (
        f"Instrument: {signal.instrument.symbol}\n"
        f"Type: {signal.signal_type}\n"
        f"Direction: {signal.direction.upper()}\n"
        f"Urgency: {signal.urgency.upper()}\n"
        f"Score: {signal.score:.2f}\n"
        f"Price: {signal.price_at_signal}\n"
    )

    if signal.suggested_entry:
        message += f"Entry: {signal.suggested_entry}\n"
    if signal.suggested_stop:
        message += f"Stop: {signal.suggested_stop}\n"
    if signal.suggested_target:
        message += f"Target: {signal.suggested_target}\n"
    if signal.risk_reward_ratio:
        message += f"R:R: {signal.risk_reward_ratio:.1f}\n"
    if signal.portfolio_impact:
        message += f"\nPortfolio Impact: {signal.portfolio_impact}\n"

    message += f"\n{signal.description}"

    return title, message
