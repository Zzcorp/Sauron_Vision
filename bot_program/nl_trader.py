"""Natural language trade parser — convert text commands to trade actions."""
import re
import logging
import json

logger = logging.getLogger(__name__)


class NLTradeParser:
    """Parse natural language trade instructions into structured orders."""

    PATTERNS = {
        # "Buy 100 shares of AAPL at market"
        'market_order': re.compile(
            r'(buy|sell|long|short)\s+(\d+(?:\.\d+)?)\s+(?:shares?\s+(?:of\s+)?)?([A-Z]{1,10})\s+(?:at\s+)?market',
            re.IGNORECASE
        ),
        # "Buy AAPL at 150.50"
        'limit_order': re.compile(
            r'(buy|sell|long|short)\s+(?:(\d+(?:\.\d+)?)\s+(?:shares?\s+(?:of\s+)?)?)?([A-Z]{1,10})\s+at\s+\$?(\d+(?:\.\d+)?)',
            re.IGNORECASE
        ),
        # "Close AAPL" or "Exit AAPL position"
        'close': re.compile(
            r'(?:close|exit|flatten|sell\s+all)\s+(?:my\s+)?([A-Z]{1,10})\s*(?:position)?',
            re.IGNORECASE
        ),
        # "Set stop loss on AAPL at 145"
        'stop_loss': re.compile(
            r'(?:set\s+)?stop\s*(?:loss)?\s+(?:on\s+)?([A-Z]{1,10})\s+(?:at\s+)?\$?(\d+(?:\.\d+)?)',
            re.IGNORECASE
        ),
        # "Set take profit on AAPL at 180"
        'take_profit': re.compile(
            r'(?:set\s+)?(?:take\s*profit|tp|target)\s+(?:on\s+)?([A-Z]{1,10})\s+(?:at\s+)?\$?(\d+(?:\.\d+)?)',
            re.IGNORECASE
        ),
    }

    def parse(self, text):
        """Parse a natural language trade command.

        Returns dict with:
            action: str (buy, sell, close, set_sl, set_tp)
            symbol: str
            quantity: float or None
            price: float or None (None = market)
            order_type: str (market, limit)
            confidence: float 0-1
            raw_text: str
        """
        text = text.strip()

        # Try market order
        match = self.PATTERNS['market_order'].search(text)
        if match:
            action = self._normalize_action(match.group(1))
            return {
                'action': action,
                'symbol': match.group(3).upper(),
                'quantity': float(match.group(2)),
                'price': None,
                'order_type': 'market',
                'confidence': 0.9,
                'raw_text': text,
            }

        # Try limit order
        match = self.PATTERNS['limit_order'].search(text)
        if match:
            action = self._normalize_action(match.group(1))
            return {
                'action': action,
                'symbol': match.group(3).upper(),
                'quantity': float(match.group(2)) if match.group(2) else None,
                'price': float(match.group(4)),
                'order_type': 'limit',
                'confidence': 0.85,
                'raw_text': text,
            }

        # Try close
        match = self.PATTERNS['close'].search(text)
        if match:
            return {
                'action': 'close',
                'symbol': match.group(1).upper(),
                'quantity': None,
                'price': None,
                'order_type': 'market',
                'confidence': 0.9,
                'raw_text': text,
            }

        # Try stop loss
        match = self.PATTERNS['stop_loss'].search(text)
        if match:
            return {
                'action': 'set_sl',
                'symbol': match.group(1).upper(),
                'price': float(match.group(2)),
                'quantity': None,
                'order_type': 'modify',
                'confidence': 0.85,
                'raw_text': text,
            }

        # Try take profit
        match = self.PATTERNS['take_profit'].search(text)
        if match:
            return {
                'action': 'set_tp',
                'symbol': match.group(1).upper(),
                'price': float(match.group(2)),
                'quantity': None,
                'order_type': 'modify',
                'confidence': 0.85,
                'raw_text': text,
            }

        # No pattern matched — try AI parsing
        return {
            'action': 'unknown',
            'raw_text': text,
            'confidence': 0,
            'error': 'Could not parse trade command. Try: "Buy 100 AAPL at market"',
        }

    def _normalize_action(self, action):
        """Normalize action keywords."""
        action = action.lower()
        if action in ('buy', 'long'):
            return 'buy'
        elif action in ('sell', 'short'):
            return 'sell'
        return action

    def execute(self, parsed_order, user):
        """Execute a parsed trade order.

        Validates against portfolio limits before execution.
        Returns result dict.
        """
        if parsed_order.get('action') == 'unknown':
            return {'status': 'error', 'message': parsed_order.get('error', 'Unknown command')}

        if parsed_order.get('confidence', 0) < 0.5:
            return {'status': 'error', 'message': 'Low confidence parse — please be more specific'}

        from instruments.models import Instrument
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import Position
        from market_data.models import LiveQuote
        from django.utils import timezone

        symbol = parsed_order['symbol']

        # Validate instrument exists
        instrument = Instrument.objects.filter(symbol=symbol).first()
        if not instrument:
            return {'status': 'error', 'message': f'Unknown instrument: {symbol}'}

        portfolio = get_or_create_default_portfolio(user=user)

        action = parsed_order['action']

        if action == 'close':
            # Close existing position
            position = Position.objects.filter(
                portfolio=portfolio, instrument=instrument, closed_at__isnull=True
            ).first()
            if not position:
                return {'status': 'error', 'message': f'No open position in {symbol}'}

            position.closed_at = timezone.now()
            try:
                quote = LiveQuote.objects.get(instrument=instrument)
                position.current_price = quote.last
            except LiveQuote.DoesNotExist:
                pass
            position.save()

            return {'status': 'executed', 'action': 'close', 'symbol': symbol}

        elif action in ('set_sl', 'set_tp'):
            # Modify existing position
            position = Position.objects.filter(
                portfolio=portfolio, instrument=instrument, closed_at__isnull=True
            ).first()
            if not position:
                return {'status': 'error', 'message': f'No open position in {symbol}'}

            if action == 'set_sl':
                position.stop_loss = parsed_order['price']
            else:
                position.take_profit = parsed_order['price']
            position.save()

            return {'status': 'executed', 'action': action, 'symbol': symbol, 'price': parsed_order['price']}

        elif action in ('buy', 'sell'):
            # Open new position
            try:
                quote = LiveQuote.objects.get(instrument=instrument)
                current_price = quote.last
            except LiveQuote.DoesNotExist:
                return {'status': 'error', 'message': f'No live price for {symbol}'}

            entry_price = parsed_order.get('price') or current_price
            quantity = parsed_order.get('quantity', 1)

            # Check portfolio limits
            position_value = float(entry_price) * float(quantity)
            max_position = float(portfolio.current_value) * float(portfolio.max_single_position_pct) / 100

            if position_value > max_position:
                return {
                    'status': 'error',
                    'message': f'Position value ${position_value:.2f} exceeds limit ${max_position:.2f}',
                }

            direction = 'long' if action == 'buy' else 'short'

            # The same one-bet-one-ticket and theme-leg gates every other
            # entry path passes. Both REFUSE here — the manual popup can
            # warn a human and record the override, but a chat reply has
            # no confirm step to carry a warning into, so an advisory
            # would be a gate that only ever said yes. config_id=None:
            # nothing this path opens is "its own config adding a clip".
            from portfolio.risk_gate import duplicate_state, theme_state
            dup = duplicate_state(user, symbol=instrument.symbol,
                                  side=action, config_id=None)
            if not dup['ok']:
                return {'status': 'error', 'message': dup['reason']}
            theme = theme_state(user, symbol=instrument.symbol, side=action,
                                asset_class=instrument.asset_class)
            if not theme['ok']:
                return {'status': 'error', 'message': theme['reason']}

            Position.objects.create(
                portfolio=portfolio,
                instrument=instrument,
                direction=direction,
                quantity=quantity,
                entry_price=entry_price,
                current_price=current_price,
                opened_at=timezone.now(),
            )

            return {
                'status': 'executed',
                'action': action,
                'symbol': symbol,
                'quantity': quantity,
                'price': float(entry_price),
                'direction': direction,
            }

        return {'status': 'error', 'message': f'Unsupported action: {action}'}
