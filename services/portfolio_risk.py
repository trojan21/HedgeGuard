import asyncio
import datetime
import logging
from db.database import get_connection
from exchanges.price_fetcher import get_price, get_historical_prices
from exchanges.options_utils import get_best_put_option
from services.greeks import calculate_greeks
import numpy as np
import  pandas as pd



async def calculate_correlation_matrix(days: int = 90):
    """
    Calculates and returns the correlation matrix of asset returns in the portfolio.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset FROM monitored_positions")
        assets = [row[0] for row in cur.fetchall()]
        conn.close()

        if not assets:
            return "No monitored assets for correlation matrix."

        returns_dict = {}

        for asset in assets:
            try:
                prices = await get_historical_prices(asset, source="okx", days=days)
                closes = [p["close"] for p in prices]

                if len(closes) < 2:
                    continue

                daily_returns = np.diff(closes) / closes[:-1]
                returns_dict[asset] = daily_returns

            except Exception as e:
                logging.warning(f"[Correlation] Error for {asset}: {e}")

        if len(returns_dict) < 2:
            return "Not enough valid assets to compute correlation."

        # Normalize all return series to the same length
        min_len = min(len(r) for r in returns_dict.values())
        aligned_returns = {k: v[-min_len:] for k, v in returns_dict.items()}

        # Build DataFrame
        df = pd.DataFrame(aligned_returns)
        corr_matrix = df.corr()

        # Format result
        formatted = " Correlation Matrix (last 90 days):\n\n"
        formatted += corr_matrix.round(2).to_string()

        return formatted

    except Exception as e:
        logging.error(f"[calculate_correlation_matrix] {e}")
        return f"Error calculating correlation matrix: {e}"
    

async def calculate_portfolio_var(days: int = 90, confidence: float = 0.95):
    """
    Calculates Value at Risk (VaR) for the portfolio using historical simulation method.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset, position_size FROM monitored_positions")
        positions = cur.fetchall()
        conn.close()

        if not positions:
            return "No monitored positions for VaR calculation."

        historical_returns = {}
        exposures = {}
        all_dates = None

        for asset, size in positions:
            try:
                prices = await get_historical_prices(asset, source="okx", days=days)
                closes = [p["close"] for p in prices]

                if len(closes) < 2:
                    continue

                # Daily returns
                returns = np.diff(closes) / closes[:-1]
                historical_returns[asset] = returns

                # Exposure in USD
                spot_price = await get_price(asset, source="okx")
                exposures[asset] = spot_price * size

                # Capture shortest return series length
                if all_dates is None or len(returns) < len(all_dates):
                    all_dates = returns

            except Exception as e:
                logging.warning(f"[VaR] Error for {asset}: {e}")

        if not historical_returns:
            return " Insufficient return data for VaR calculation."

        # Normalize return lengths
        min_len = min(len(r) for r in historical_returns.values())
        for asset in historical_returns:
            historical_returns[asset] = historical_returns[asset][-min_len:]

        # Stack into array
        asset_names = list(historical_returns.keys())
        returns_matrix = np.stack([historical_returns[a] for a in asset_names], axis=1)

        # Portfolio weights based on exposure
        total_exposure = sum(exposures[a] for a in asset_names)
        weights = np.array([exposures[a] / total_exposure for a in asset_names])

        # Portfolio returns
        portfolio_returns = np.dot(returns_matrix, weights)

        # Calculate 5% percentile
        var_percentile = np.percentile(portfolio_returns, (1 - confidence) * 100)

        # Convert to USD loss
        portfolio_var = -var_percentile * total_exposure

        return (
            f"📉 Value at Risk (VaR @ {int(confidence * 100)}%) over {days}d:\n"
            f"• Total Exposure: ${total_exposure:,.2f}\n"
            f"• Portfolio VaR: ${portfolio_var:,.2f}"
        )

    except Exception as e:
        logging.error(f"[calculate_portfolio_var] {e}")
        return f"Error calculating VaR: {e}"
    
async def calculate_portfolio_greeks():
    """
    Aggregate Delta, Gamma, Vega, Theta across all monitored option positions.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset, position_size FROM monitored_positions")
        positions = cur.fetchall()
        conn.close()

        total_greeks = {
            "delta": 0.0,
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0
        }

        for asset, size in positions:
            try:
                spot = await get_price(asset, source="okx")
                option = await get_best_put_option(asset, spot)
                strike = float(option['strike'])

                expiry_ts = int(option['info']['expiration_timestamp']) / 1000
                expiry = datetime.datetime.utcfromtimestamp(expiry_ts)
                T = (expiry - datetime.datetime.utcnow()).days / 365

                r = 0.05  # Risk-free rate
                sigma = 0.5  # Assumed volatility

                greeks = calculate_greeks("put", spot, strike, T, r, sigma)

                total_greeks["delta"] += greeks["delta"] * size
                total_greeks["gamma"] += greeks["gamma"] * size
                total_greeks["vega"] += greeks["vega"] * size
                total_greeks["theta"] += greeks["theta"] * size

            except Exception as e:
                logging.warning(f"[Portfolio Greeks] Failed for {asset}: {e}")
                continue

        return total_greeks

    except Exception as e:
        logging.error(f"[calculate_portfolio_greeks] {e}")
        return None


def calculate_max_drawdown(prices: list[float]) -> float:
    """
    Calculate maximum drawdown from a list of historical prices.
    """
    peak = prices[0]
    max_dd = 0.0

    for price in prices:
        if price > peak:
            peak = price
        drawdown = (peak - price) / peak
        max_dd = max(max_dd, drawdown)

    return round(max_dd * 100, 2)


async def get_portfolio_max_drawdown(days=90):
    """
    Calculate weighted max drawdown across portfolio.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset, position_size FROM monitored_positions")
        positions = cur.fetchall()
        conn.close()

        if not positions:
            return "No monitored positions for drawdown calculation."

        message = f"Maximum Drawdown (last {days} days):\n\n"
        total_exposure = 0.0
        weighted_dd_sum = 0.0

        for asset, size in positions:
            try:
                prices = await get_historical_prices(asset, source="okx", days=days)
                closes = [p[4] for p in prices]  # Index 4 = close

                if len(closes) < 2:
                    continue

                drawdown_pct = calculate_max_drawdown(closes)
                spot_price = await get_price(asset, source="okx")
                exposure = size * spot_price

                total_exposure += exposure
                weighted_dd_sum += drawdown_pct * exposure

                message += f"• {asset}: {drawdown_pct:.2f}%\n"

            except Exception as e:
                logging.warning(f"[Drawdown] Error for {asset}: {e}")

        if total_exposure > 0:
            portfolio_dd = weighted_dd_sum / total_exposure
            message += f"\n Portfolio-Weighted Max Drawdown: {portfolio_dd:.2f}%"
        else:
            message += "\nNo valid price data for weighted drawdown."

        return message

    except Exception as e:
        logging.error(f"[get_portfolio_max_drawdown] {e}")
        return f"Error calculating drawdown: {e}"


async def simulate_stress_scenarios():
    """
    Simulate price shocks and evaluate impact on portfolio value and delta.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset, position_size FROM monitored_positions")
        positions = cur.fetchall()
        conn.close()

        if not positions:
            return "No monitored positions for stress testing."

        # Define stress scenarios: % drop in spot price
        shocks = [-0.05, -0.10, -0.20]  # -5%, -10%, -20%
        results = {f"{int(s * 100)}%": {"value": 0.0, "delta_pnl": 0.0} for s in shocks}
        total_initial_value = 0.0

        for asset, size in positions:
            try:
                spot = await get_price(asset, source="okx")
                option = await get_best_put_option(asset, spot)
                strike = float(option["strike"])
                expiry_ts = int(option["info"]["expiration_timestamp"]) / 1000
                expiry = datetime.datetime.utcfromtimestamp(expiry_ts)
                T = (expiry - datetime.datetime.utcnow()).days / 365
                r = 0.05
                sigma = 0.5

                initial_value = size * spot
                total_initial_value += initial_value

                greeks = calculate_greeks("put", spot, strike, T, r, sigma)
                delta = greeks["delta"]

                for s in shocks:
                    shocked_price = spot * (1 + s)
                    shocked_value = size * shocked_price
                    delta_pnl = delta * size * (shocked_price - spot)

                    label = f"{int(s * 100)}%"
                    results[label]["value"] += shocked_value
                    results[label]["delta_pnl"] += delta_pnl

            except Exception as e:
                logging.warning(f"[Stress Test] Error for {asset}: {e}")

        message = "Stress Testing Scenarios:\n(Price drops: impact on portfolio)\n\n"
        for label in results:
            value = results[label]["value"]
            delta_pnl = results[label]["delta_pnl"]
            loss_pct = ((total_initial_value - value) / total_initial_value) * 100
            message += (
                f"• {label} drop: Value = ${value:,.2f}, Loss = {loss_pct:.2f}%, "
                f"Delta PnL = ${delta_pnl:,.2f}\n"
            )

        return message

    except Exception as e:
        logging.error(f"[simulate_stress_scenarios] {e}")
        return f"Error simulating stress scenarios: {e}"


async def get_portfolio_pnl(days: int = 1):
    """
    Calculate portfolio-level P&L over the last N days.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset, position_size FROM monitored_positions")
        positions = cur.fetchall()
        conn.close()

        if not positions:
            return "No monitored positions for PnL calculation."

        total_pnl = 0.0
        message = f"Portfolio P&L (last {days} day(s)):\n\n"

        for asset, size in positions:
            try:
                prices = await get_historical_prices(asset, source="okx", days=days + 1)
                if len(prices) < 2:
                    continue

                past_price = prices[0]["close"]
                current_price = await get_price(asset, source="okx")

                pnl = (current_price - past_price) * size
                total_pnl += pnl

                sign = "🔺" if pnl >= 0 else "🔻"
                message += f"• {asset}: {sign} ${pnl:,.2f}\n"

            except Exception as e:
                logging.warning(f"[PnL] Error for {asset}: {e}")

        message += f"\nTotal P&L: {'🔺' if total_pnl >= 0 else '🔻'} ${total_pnl:,.2f}"
        return message

    except Exception as e:
        logging.error(f"[get_portfolio_pnl] {e}")
        return f"Error calculating PnL: {e}"

async def calculate_portfolio_pnl():
    """
    Placeholder implementation to calculate portfolio PnL.
    You should replace this with real logic using entry prices and current prices.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset, position_size FROM monitored_positions")
        positions = cur.fetchall()
        conn.close()

        if not positions:
            return "No monitored positions for PnL calculation."

        message = "Portfolio PnL Report:\n\n"
        total_value = 0.0

        for asset, size in positions:
            try:
                price = await get_price(asset, source="okx")
                value = price * size
                total_value += value
                message += f"• {asset}: ${price:.2f} × {size} = ${value:,.2f}\n"
            except Exception as e:
                logging.warning(f"[PnL] Error for {asset}: {e}")

        message += f"\nTotal Portfolio Value: ${total_value:,.2f}"
        return message

    except Exception as e:
        logging.error(f"[calculate_portfolio_pnl] {e}")
        return f"Error calculating portfolio PnL: {e}"
