import ccxt.async_support as ccxt
import logging
# Initialize exchange clients
okx = ccxt.okx()

deribit = ccxt.deribit()
bybit = ccxt.bybit({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',  # Needed to fetch perpetual contracts
    }
})


# Mapping of supported symbols per exchange
EXCHANGE_SYMBOLS = {
    "okx": {
        "BTC": "BTC/USDT",
        "ETH": "ETH/USDT",
    },
    "bybit": {
        "BTC": "BTC/USDT",
        "ETH": "ETH/USDT",
    },
    "deribit": {
        "BTC": "BTC-PERPETUAL",
        "ETH": "ETH-PERPETUAL",
    }
}

# Mapping of exchange names to objects
EXCHANGE_OBJECTS = {
    "okx": okx,
    "bybit": bybit,
    "deribit": deribit
}

async def get_bybit_perp_orderbook(asset: str = "BTC/USDT:USDT"):
    """
    Fetch order book for a given asset from Bybit perpetual futures.
    """
    try:
        ob = await bybit.fetch_order_book(asset)
        return {
            "bid": ob['bids'][0] if ob['bids'] else [0, 0],
            "ask": ob['asks'][0] if ob['asks'] else [0, 0],
        }
    except Exception as e:
        logging.error(f"[get_bybit_perp_orderbook] {e}")
        return {"bid": [0, 0], "ask": [0, 0]}

async def close_bybit():
    """
    Properly close Bybit connection.
    """
    await bybit.close()

#Live Price
async def get_price(asset: str, source: str = "okx") -> float:
    asset = asset.upper()
    source = source.lower()

    if source not in EXCHANGE_OBJECTS:
        raise ValueError(f" Exchange '{source}' not supported")

    if asset not in EXCHANGE_SYMBOLS[source]:
        raise ValueError(f"Asset '{asset}' not available on {source}")

    symbol = EXCHANGE_SYMBOLS[source][asset]
    exchange = EXCHANGE_OBJECTS[source]

    ticker = await exchange.fetch_ticker(symbol)
    return ticker["last"]

# Orderbook 
async def get_orderbook(asset: str, source: str = "okx", depth: int = 5) -> dict:
    asset = asset.upper()
    source = source.lower()

    if source not in EXCHANGE_OBJECTS:
        raise ValueError(f"Exchange '{source}' not supported")

    if asset not in EXCHANGE_SYMBOLS[source]:
        raise ValueError(f"Asset '{asset}' not available on {source}")

    symbol = EXCHANGE_SYMBOLS[source][asset]
    exchange = EXCHANGE_OBJECTS[source]

    ob = await exchange.fetch_order_book(symbol)
    return {
        "bids": ob["bids"][:depth],
        "asks": ob["asks"][:depth]
    }

# historical prices 
async def get_historical_prices(asset: str, source: str = "okx", timeframe: str = "1h", limit: int = 100) -> list:
    asset = asset.upper()
    source = source.lower()

    if source not in EXCHANGE_OBJECTS:
        raise ValueError(f" Exchange '{source}' not supported")

    if asset not in EXCHANGE_SYMBOLS[source]:
        raise ValueError(f"Asset '{asset}' not available on {source}")

    symbol = EXCHANGE_SYMBOLS[source][asset]
    exchange = EXCHANGE_OBJECTS[source]

    return await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

# cleanup 
async def close_all_exchanges():
    for exchange in EXCHANGE_OBJECTS.values():
        await exchange.close()
