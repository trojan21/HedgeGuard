import ccxt.async_support as ccxt
import pandas as pd
import matplotlib.pyplot as plt
import io
from arch import arch_model
import numpy as np

# Fetch Historical OHLCV Data
async def fetch_ohlcv(asset: str, exchange: str = "okx", timeframe="1h", limit=500):
    ex = getattr(ccxt, exchange)()
    symbol = f"{asset}/USDT"
    ohlcv = await ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    await ex.close()

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df

# GARCH Forecast and Historical Volatility Plots
async def forecast_volatility(asset: str, exchange: str = "okx", forecast_steps: int = 10):
    df = await fetch_ohlcv(asset, exchange)

    # Compute log ret   
    df["log_return"] = np.log(df["close"] / df["close"].shift(1))
    df.dropna(inplace=True)

    # Compute rolling realized volatility (std dev of returns)
    df["realized_vol"] = df["log_return"].rolling(window=24).std() * np.sqrt(24) * 100  # annualized-ish for hourly

    # Fit GARCH(1,1) model on returns
    returns = df["log_return"] * 100  # % returns
    model = arch_model(returns, vol="Garch", p=1, q=1)
    res = model.fit(disp="off")

    # Forecast future volatility
    forecast = res.forecast(horizon=forecast_steps)
    forecast_vol = forecast.variance.values[-1] ** 0.5  # std dev

    future_dates = [df.index[-1] + pd.Timedelta(hours=i+1) for i in range(forecast_steps)]

    # Plot 1: Historical Realized Volatility 
    fig1, ax1 = plt.subplots(figsize=(10, 4))
    ax1.plot(df.index[-200:], df["realized_vol"].dropna()[-200:], label="Realized Volatility")
    ax1.set_title(f"Historical Realized Volatility for {asset}")
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Volatility (%)")
    ax1.legend()
    ax1.grid(True)

    buf1 = io.BytesIO()
    fig1.tight_layout()
    fig1.savefig(buf1, format="png")
    buf1.seek(0)
    plt.close(fig1)

    #Plot 2: Forecasted Volatility
    fig2, ax2 = plt.subplots(figsize=(10, 4))
    ax2.plot(future_dates, forecast_vol, label="Forecasted Volatility", color="red")
    ax2.set_title(f"GARCH Forecasted Volatility ({forecast_steps} steps ahead) for {asset}")
    ax2.set_xlabel("Future Time")
    ax2.set_ylabel("Volatility (%)")
    ax2.legend()
    ax2.grid(True)

    buf2 = io.BytesIO()
    fig2.tight_layout()
    fig2.savefig(buf2, format="png")
    buf2.seek(0)
    plt.close(fig2)

    return buf1.getvalue(), buf2.getvalue()
