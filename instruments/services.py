"""Instrument management — comprehensive asset seeding."""
from .models import Instrument


INSTRUMENTS_DATA = {
    # ── FOREX (49 pairs — matching eToro) ────────────────
    "forex": {
        "EURUSD": "Euro / US Dollar",
        "GBPUSD": "British Pound / US Dollar",
        "USDJPY": "US Dollar / Japanese Yen",
        "USDCHF": "US Dollar / Swiss Franc",
        "AUDUSD": "Australian Dollar / US Dollar",
        "USDCAD": "US Dollar / Canadian Dollar",
        "NZDUSD": "New Zealand Dollar / US Dollar",
        "EURGBP": "Euro / British Pound",
        "EURJPY": "Euro / Japanese Yen",
        "GBPJPY": "British Pound / Japanese Yen",
        "EURAUD": "Euro / Australian Dollar",
        "EURCAD": "Euro / Canadian Dollar",
        "EURCHF": "Euro / Swiss Franc",
        "EURNZD": "Euro / New Zealand Dollar",
        "GBPAUD": "British Pound / Australian Dollar",
        "GBPCAD": "British Pound / Canadian Dollar",
        "GBPCHF": "British Pound / Swiss Franc",
        "GBPNZD": "British Pound / New Zealand Dollar",
        "AUDCAD": "Australian Dollar / Canadian Dollar",
        "AUDCHF": "Australian Dollar / Swiss Franc",
        "AUDJPY": "Australian Dollar / Japanese Yen",
        "AUDNZD": "Australian Dollar / New Zealand Dollar",
        "CADJPY": "Canadian Dollar / Japanese Yen",
        "CADCHF": "Canadian Dollar / Swiss Franc",
        "CHFJPY": "Swiss Franc / Japanese Yen",
        "NZDJPY": "New Zealand Dollar / Japanese Yen",
        "NZDCAD": "New Zealand Dollar / Canadian Dollar",
        "NZDCHF": "New Zealand Dollar / Swiss Franc",
        "USDMXN": "US Dollar / Mexican Peso",
        "USDTRY": "US Dollar / Turkish Lira",
        "USDZAR": "US Dollar / South African Rand",
        "USDNOK": "US Dollar / Norwegian Krone",
        "USDSEK": "US Dollar / Swedish Krona",
        "USDSGD": "US Dollar / Singapore Dollar",
        "USDHKD": "US Dollar / Hong Kong Dollar",
        "USDPLN": "US Dollar / Polish Zloty",
        "USDHUF": "US Dollar / Hungarian Forint",
        "USDCZK": "US Dollar / Czech Koruna",
        "USDCNH": "US Dollar / Chinese Yuan Offshore",
        "EURPLN": "Euro / Polish Zloty",
        "EURNOK": "Euro / Norwegian Krone",
        "EURSEK": "Euro / Swedish Krona",
        "EURHUF": "Euro / Hungarian Forint",
        "GBPHUF": "British Pound / Hungarian Forint",
        "CHFHUF": "Swiss Franc / Hungarian Forint",
        "ZARJPY": "South African Rand / Japanese Yen",
        "USDRON": "US Dollar / Romanian Leu",
    },

    # ── COMMODITIES (32 — matching eToro) ────────────────
    "commodity": {
        "XAUUSD": ("Gold Spot", "COMEX"),
        "XAGUSD": ("Silver Spot", "COMEX"),
        "XPTUSD": ("Platinum", "NYMEX"),
        "XPDUSD": ("Palladium", "NYMEX"),
        "WTIUSD": ("WTI Crude Oil", "NYMEX"),
        "BRNUSD": ("Brent Crude Oil", "ICE"),
        "NGUSD": ("Natural Gas", "NYMEX"),
        "HGUSD": ("Copper", "COMEX"),
        "WHEATUSD": ("Wheat", "CBOT"),
        "CORNUSD": ("Corn", "CBOT"),
        "SOYUSD": ("Soybeans", "CBOT"),
        "COFFEEUSD": ("Coffee", "ICE"),
        "COCOAUSD": ("Cocoa", "ICE"),
        "COTTONUSD": ("Cotton", "ICE"),
        "SUGARUSD": ("Sugar #11", "ICE"),
        "HEATOILUSD": ("Heating Oil", "NYMEX"),
        "GASOLINEUSD": ("RBOB Gasoline", "NYMEX"),
        "ALUMUSD": ("Aluminum", "LME"),
        "ZINCUSD": ("Zinc", "LME"),
        "NICKELUSD": ("Nickel", "LME"),
        "LEADUSD": ("Lead", "LME"),
        "TINUSD": ("Tin", "LME"),
        "XAUGBP": ("Gold / GBP", "COMEX"),
        "XAUEUR": ("Gold / EUR", "COMEX"),
        "XAGEUR": ("Silver / EUR", "COMEX"),
        "OILFUTURES": ("Oil Futures", "NYMEX"),
        "LUMBER": ("Lumber", "CME"),
        "LIVECATTLE": ("Live Cattle", "CME"),
        "LEANHOGS": ("Lean Hogs", "CME"),
        "OATS": ("Oats", "CBOT"),
        "RICE": ("Rice", "CBOT"),
        "ORANGEJUICE": ("Orange Juice", "ICE"),
    },

    # ── INDICES (13 — matching eToro) ────────────────────
    "index": {
        "SPX500": ("S&P 500", "CME"),
        "NSDQ100": ("Nasdaq 100", "CME"),
        "DJ30": ("Dow Jones 30", "CME"),
        "RUSSELL2000": ("Russell 2000", "CME"),
        "FTSE100": ("FTSE 100", "ICE"),
        "DAX40": ("DAX 40", "EUREX"),
        "CAC40": ("CAC 40", "EURONEXT"),
        "STOXX50": ("Euro Stoxx 50", "EUREX"),
        "NIKKEI225": ("Nikkei 225", "OSE"),
        "HANGSENG": ("Hang Seng", "HKEX"),
        "ASX200": ("ASX 200", "ASX"),
        "IBEX35": ("IBEX 35", "BME"),
        "DXY": ("US Dollar Index", "ICE"),
    },

    # ── TOP STOCKS (50 most traded) ──────────────────────
    "stock": {
        "AAPL": ("Apple Inc", "NASDAQ"),
        "MSFT": ("Microsoft Corp", "NASDAQ"),
        "GOOGL": ("Alphabet Inc", "NASDAQ"),
        "AMZN": ("Amazon.com Inc", "NASDAQ"),
        "NVDA": ("NVIDIA Corp", "NASDAQ"),
        "META": ("Meta Platforms", "NASDAQ"),
        "TSLA": ("Tesla Inc", "NASDAQ"),
        "BRK.B": ("Berkshire Hathaway B", "NYSE"),
        "JPM": ("JPMorgan Chase", "NYSE"),
        "V": ("Visa Inc", "NYSE"),
        "JNJ": ("Johnson & Johnson", "NYSE"),
        "WMT": ("Walmart Inc", "NYSE"),
        "MA": ("Mastercard Inc", "NYSE"),
        "PG": ("Procter & Gamble", "NYSE"),
        "UNH": ("UnitedHealth Group", "NYSE"),
        "HD": ("Home Depot", "NYSE"),
        "DIS": ("Walt Disney Co", "NYSE"),
        "BAC": ("Bank of America", "NYSE"),
        "XOM": ("Exxon Mobil", "NYSE"),
        "NFLX": ("Netflix Inc", "NASDAQ"),
        "KO": ("Coca-Cola Co", "NYSE"),
        "PEP": ("PepsiCo Inc", "NASDAQ"),
        "ABBV": ("AbbVie Inc", "NYSE"),
        "CRM": ("Salesforce Inc", "NYSE"),
        "AMD": ("AMD Inc", "NASDAQ"),
        "INTC": ("Intel Corp", "NASDAQ"),
        "BA": ("Boeing Co", "NYSE"),
        "GS": ("Goldman Sachs", "NYSE"),
        "MS": ("Morgan Stanley", "NYSE"),
        "C": ("Citigroup Inc", "NYSE"),
        "PYPL": ("PayPal Holdings", "NASDAQ"),
        "UBER": ("Uber Technologies", "NYSE"),
        "SQ": ("Block Inc (Square)", "NYSE"),
        "COIN": ("Coinbase Global", "NASDAQ"),
        "PLTR": ("Palantir Technologies", "NYSE"),
        "NIO": ("NIO Inc", "NYSE"),
        "BABA": ("Alibaba Group", "NYSE"),
        "TSM": ("Taiwan Semiconductor", "NYSE"),
        "ASML": ("ASML Holding", "NASDAQ"),
        "SAP": ("SAP SE", "NYSE"),
        "TTE": ("TotalEnergies SE", "NYSE"),
        "SHEL": ("Shell PLC", "NYSE"),
        "BP": ("BP PLC", "NYSE"),
        "RIO": ("Rio Tinto", "NYSE"),
        "BHP": ("BHP Group", "NYSE"),
        "GOLD": ("Barrick Gold", "NYSE"),
        "NEM": ("Newmont Corp", "NYSE"),
        "CVX": ("Chevron Corp", "NYSE"),
        "COP": ("ConocoPhillips", "NYSE"),
        "LMT": ("Lockheed Martin", "NYSE"),
    },

    # ── TOP ETFs (20) ────────────────────────────────────
    "etf": {
        "SPY": ("SPDR S&P 500 ETF", "NYSE"),
        "QQQ": ("Invesco QQQ Trust", "NASDAQ"),
        "IWM": ("iShares Russell 2000", "NYSE"),
        "VTI": ("Vanguard Total Stock", "NYSE"),
        "EEM": ("iShares MSCI Emerging", "NYSE"),
        "EFA": ("iShares MSCI EAFE", "NYSE"),
        "GLD": ("SPDR Gold Shares", "NYSE"),
        "SLV": ("iShares Silver Trust", "NYSE"),
        "USO": ("United States Oil Fund", "NYSE"),
        "TLT": ("iShares 20+ Year Treasury", "NASDAQ"),
        "HYG": ("iShares High Yield Corp", "NYSE"),
        "XLF": ("Financial Select SPDR", "NYSE"),
        "XLE": ("Energy Select SPDR", "NYSE"),
        "XLK": ("Technology Select SPDR", "NYSE"),
        "ARKK": ("ARK Innovation ETF", "NYSE"),
        "VWO": ("Vanguard FTSE Emerging", "NYSE"),
        "AGG": ("iShares Core US Agg Bond", "NYSE"),
        "DIA": ("SPDR Dow Jones ETF", "NYSE"),
        "VNQ": ("Vanguard Real Estate", "NYSE"),
        "IBIT": ("iShares Bitcoin Trust", "NASDAQ"),
    },

    # ── TOP CRYPTO (15) ──────────────────────────────────
    "crypto": {
        "BTCUSD": ("Bitcoin", "CRYPTO"),
        "ETHUSD": ("Ethereum", "CRYPTO"),
        "XRPUSD": ("Ripple", "CRYPTO"),
        "SOLUSD": ("Solana", "CRYPTO"),
        "ADAUSD": ("Cardano", "CRYPTO"),
        "DOTUSD": ("Polkadot", "CRYPTO"),
        "AVAXUSD": ("Avalanche", "CRYPTO"),
        "DOGEUSD": ("Dogecoin", "CRYPTO"),
        "MATICUSD": ("Polygon", "CRYPTO"),
        "LINKUSD": ("Chainlink", "CRYPTO"),
        "UNIUSD": ("Uniswap", "CRYPTO"),
        "AAVEUSD": ("Aave", "CRYPTO"),
        "LTCUSD": ("Litecoin", "CRYPTO"),
        "ATOMUSD": ("Cosmos", "CRYPTO"),
        "NEARUSD": ("NEAR Protocol", "CRYPTO"),
    },
}


def seed_all_instruments():
    """Seed ALL instruments across all asset classes."""
    total = 0
    for asset_class, instruments in INSTRUMENTS_DATA.items():
        for symbol, data in instruments.items():
            if isinstance(data, tuple):
                name, exchange = data
            else:
                name = data
                exchange = "FOREX" if asset_class == "forex" else ""

            _, was_created = Instrument.objects.get_or_create(
                symbol=symbol,
                defaults={
                    "name": name,
                    "asset_class": asset_class,
                    "exchange": exchange,
                    "currency": "USD",
                    "is_active": True,
                }
            )
            if was_created:
                total += 1
    return total


def seed_forex_pairs():
    """Seed forex pairs only."""
    created = 0
    for symbol, name in INSTRUMENTS_DATA["forex"].items():
        _, was_created = Instrument.objects.get_or_create(
            symbol=symbol,
            defaults={"name": name, "asset_class": "forex", "exchange": "FOREX", "currency": "USD", "is_active": True}
        )
        if was_created:
            created += 1
    return created


def seed_commodities():
    """Seed commodities only."""
    created = 0
    for symbol, (name, exchange) in INSTRUMENTS_DATA["commodity"].items():
        _, was_created = Instrument.objects.get_or_create(
            symbol=symbol,
            defaults={"name": name, "asset_class": "commodity", "exchange": exchange, "currency": "USD", "is_active": True}
        )
        if was_created:
            created += 1
    return created
