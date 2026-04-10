"""On-chain data adapter — whale tracking, exchange flows, DeFi metrics."""
import os
import logging
import requests

logger = logging.getLogger(__name__)


class OnChainAdapter:
    """Fetch on-chain analytics data."""

    def __init__(self):
        self.glassnode_key = os.getenv('GLASSNODE_API_KEY', '')

    def get_exchange_flows(self, asset='BTC', exchange=None):
        """Get exchange inflow/outflow data.

        Uses free public APIs as primary, Glassnode as premium.
        """
        # Try CryptoQuant free endpoint first
        try:
            return self._cryptoquant_flows(asset)
        except Exception:
            pass

        # Fallback: derive from Binance deposit/withdrawal activity
        try:
            return self._estimate_flows_from_volume(asset)
        except Exception as e:
            logger.error(f"Exchange flow fetch failed: {e}")
            return {'error': str(e)}

    def get_whale_transactions(self, asset='BTC', min_value_usd=1000000):
        """Get recent large transactions (whale alerts)."""
        try:
            # Use blockchain.info or similar free API
            if asset.upper() == 'BTC':
                return self._btc_large_transactions(min_value_usd)
            elif asset.upper() == 'ETH':
                return self._eth_large_transactions(min_value_usd)
            else:
                return {'transactions': [], 'note': f'on-chain not supported for {asset}'}
        except Exception as e:
            logger.error(f"Whale transaction fetch failed: {e}")
            return {'error': str(e)}

    def get_network_metrics(self, asset='BTC'):
        """Get network health metrics (hash rate, active addresses, etc.)."""
        try:
            resp = requests.get(
                'https://api.blockchain.info/stats',
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                return {
                    'hash_rate': data.get('hash_rate', 0),
                    'difficulty': data.get('difficulty', 0),
                    'n_tx': data.get('n_tx', 0),
                    'total_btc_sent': data.get('total_btc_sent', 0),
                    'market_price_usd': data.get('market_price_usd', 0),
                    'miners_revenue': data.get('miners_revenue_usd', 0),
                }
        except Exception as e:
            logger.error(f"Network metrics failed: {e}")
        return {}

    def get_defi_tvl(self, protocol=None):
        """Get DeFi Total Value Locked data from DeFi Llama."""
        try:
            if protocol:
                resp = requests.get(f'https://api.llama.fi/protocol/{protocol}', timeout=10)
            else:
                resp = requests.get('https://api.llama.fi/protocols', timeout=10)

            if resp.ok:
                data = resp.json()
                if protocol:
                    return {
                        'name': data.get('name'),
                        'tvl': data.get('currentChainTvls', {}),
                        'total_tvl': sum(data.get('currentChainTvls', {}).values()),
                        'category': data.get('category'),
                        'chains': data.get('chains', []),
                    }
                else:
                    # Top 20 protocols
                    return [{
                        'name': p.get('name'),
                        'tvl': p.get('tvl', 0),
                        'category': p.get('category'),
                        'change_1d': p.get('change_1d'),
                        'change_7d': p.get('change_7d'),
                    } for p in data[:20]]
        except Exception as e:
            logger.error(f"DeFi TVL fetch failed: {e}")
        return {}

    def _cryptoquant_flows(self, asset):
        """Fetch from CryptoQuant public API."""
        resp = requests.get(
            'https://api.cryptoquant.com/v1/btc/exchange-flows/netflow',
            params={'window': 'day', 'limit': 7},
            timeout=10,
        )
        if resp.ok:
            return resp.json()
        return {'note': 'CryptoQuant API requires key for detailed data'}

    def _estimate_flows_from_volume(self, asset):
        """Estimate exchange flows from volume data."""
        from market_data.models import LiveQuote
        from instruments.models import Instrument

        inst = Instrument.objects.filter(
            symbol__icontains=asset, asset_class='crypto'
        ).first()

        if not inst:
            return {'error': f'instrument not found for {asset}'}

        try:
            quote = LiveQuote.objects.get(instrument=inst)
            return {
                'symbol': inst.symbol,
                'volume_24h': quote.volume,
                'price': float(quote.last),
                'volume_usd': float(quote.last) * quote.volume,
                'note': 'estimated from exchange volume',
            }
        except LiveQuote.DoesNotExist:
            return {'error': 'no live quote available'}

    def _btc_large_transactions(self, min_value_usd):
        """Get large BTC transactions from blockchain.info."""
        resp = requests.get(
            'https://blockchain.info/unconfirmed-transactions?format=json',
            timeout=10,
        )
        if not resp.ok:
            return {'transactions': []}

        data = resp.json()
        large_txs = []

        for tx in data.get('txs', [])[:100]:
            total_output = sum(o.get('value', 0) for o in tx.get('out', [])) / 1e8
            # Rough USD estimate (would need current price)
            if total_output > 10:  # > 10 BTC as proxy for whale
                large_txs.append({
                    'hash': tx.get('hash', '')[:16] + '...',
                    'btc_amount': round(total_output, 4),
                    'n_inputs': len(tx.get('inputs', [])),
                    'n_outputs': len(tx.get('out', [])),
                    'time': tx.get('time'),
                })

        return {'transactions': large_txs[:20]}

    def _eth_large_transactions(self, min_value_usd):
        """Placeholder for ETH whale tracking."""
        return {'transactions': [], 'note': 'ETH whale tracking requires Etherscan API key'}
