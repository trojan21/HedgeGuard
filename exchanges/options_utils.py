import datetime
import ccxt.async_support as ccxt
import logging

# Initialize Deribit exchange instance
deribit = ccxt.deribit({
    'enableRateLimit': True,
    'options': {'defaultType': 'option'}
})

# Fetch All Deribit Options for an Asset
async def get_deribit_options(asset: str):
    try:
        markets = await deribit.fetch_markets()
        return [m for m in markets if m.get('option') and asset.upper() in m['symbol']]
    except Exception as e:
        logging.error(f"[get_deribit_options] Error fetching markets: {e}")
        return []

#  Spot Price 
async def get_spot_price(asset: str):
    try:
        ticker = await deribit.fetch_ticker(f"{asset}/USD")
        return ticker['info']['underlying_price']
    except Exception as e:
        logging.error(f"[get_spot_price] {e}")
        return None

# Best Protective Put Option 
async def get_best_put_option(asset: str, spot_price: float = None):
    options = await get_deribit_options(asset)
    if not spot_price:
        spot_price = await get_spot_price(asset)
    if not spot_price:
        raise ValueError("Failed to fetch spot price.")

    now = datetime.datetime.utcnow()
    cutoff = now + datetime.timedelta(days=10)
    puts = []

    for opt in options:
        if opt['optionType'] != 'put':
            continue
        try:
            expiry_ts = int(opt['info']['expiration_timestamp']) / 1000
            expiry = datetime.datetime.utcfromtimestamp(expiry_ts)
            strike = float(opt['strike'])

            if expiry > cutoff:
                continue

            if 0.85 * spot_price <= strike <= 0.99 * spot_price:
                puts.append((expiry, abs(strike - spot_price), opt))
        except Exception as e:
            logging.warning(f"[put_option_loop] Skipping option due to error: {e}")

    if not puts:
        raise ValueError("No suitable put options found.")
    
    _, _, best_put = sorted(puts, key=lambda x: (x[0], x[1]))[0]
    return best_put

# Best Covered Call Option 
async def get_best_call_option(asset: str, spot_price: float = None):
    options = await get_deribit_options(asset)
    if not spot_price:
        spot_price = await get_spot_price(asset)
    if not spot_price:
        raise ValueError("Failed to fetch spot price.")

    now = datetime.datetime.utcnow()
    cutoff = now + datetime.timedelta(days=10)
    calls = []

    for opt in options:
        if opt['optionType'] != 'call':
            continue
        try:
            expiry_ts = int(opt['info']['expiration_timestamp']) / 1000
            expiry = datetime.datetime.utcfromtimestamp(expiry_ts)
            strike = float(opt['strike'])

            if expiry > cutoff:
                continue

            if 1.01 * spot_price <= strike <= 1.15 * spot_price:
                calls.append((expiry, abs(strike - spot_price), opt))
        except Exception as e:
            logging.warning(f"[call_option_loop] Skipping option due to error: {e}")

    if not calls:
        raise ValueError("No suitable call options found.")
    
    _, _, best_call = sorted(calls, key=lambda x: (x[0], x[1]))[0]
    return best_call

# Get mid price of an Option 
async def get_option_price(option_symbol: str) -> float:
    try:
        ob = await deribit.fetch_order_book(option_symbol)
        best_bid = ob['bids'][0][0] if ob['bids'] else 0
        best_ask = ob['asks'][0][0] if ob['asks'] else 0
        if best_bid and best_ask:
            return (best_bid + best_ask) / 2

        # Fallback: try ticker last_price
        ticker = await deribit.fetch_ticker(option_symbol)
        return ticker.get("last", 0) or 0
    except Exception as e:
        logging.error(f"[get_option_price] Error fetching order book/ticker: {e}")
        return 0

# Properly close Deribit connection 
async def close_deribit():
    await deribit.close()
