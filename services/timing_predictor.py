import pandas as pd
import numpy as np
from arch import arch_model
from exchanges.price_fetcher import get_historical_prices

# Predict optimal hedge time based on vol forecast
async def predict_optimal_hedge_time(asset: str, exchange: str = "okx", forecast_horizon: int = 12, threshold: float = 2.5):
    """
    
    Returns:
    - dict: {
        "should_hedge": bool,
        "high_vol_hours": int,
        "vol_forecast": list,
        "hedge_hours": list[int],
        "recommended_hour": int
    }
    """
    raw_data = await get_historical_prices(asset, exchange, timeframe="1h", limit=500)

    df = pd.DataFrame(raw_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    df["log_return"] = np.log(df["close"] / df["close"].shift(1))
    df.dropna(inplace=True)

    returns = df["log_return"] * 100

    model = arch_model(returns, vol="Garch", p=1, q=1)
    res = model.fit(disp="off")

    forecast = res.forecast(horizon=forecast_horizon)
    variance_array = forecast.variance.values[-1]
    vol_forecast = np.sqrt(variance_array)

    # which hours exceed the threshold
    hedge_hours = [i for i, v in enumerate(vol_forecast) if v > threshold]
    recommended_hour = int(np.argmax(vol_forecast))  
    # always pick max vol hour

    high_vol_hours = len(hedge_hours)
    should_hedge = high_vol_hours > forecast_horizon / 2

    return {
        "should_hedge": should_hedge,
        "high_vol_hours": high_vol_hours,
        "vol_forecast": vol_forecast.tolist(),
        "hedge_hours": hedge_hours,
        "recommended_hour": recommended_hour
    }
