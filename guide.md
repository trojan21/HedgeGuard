Spot Exposure Hedging Bot Documentation

Overview

The Spot Exposure Hedging Bot is a risk management system that monitors real-time cryptocurrency positions, forecasts volatility, calculates risk metrics (like VaR and Greeks), and provides actionable alerts and automated hedging suggestions via Telegram.

Features

1. Telegram Bot Interface

User interaction via commands (/hedge_now, /forecast_volatility, /pnl_report, etc.)

Inline button support for immediate hedging (Hedge Now button)

2. Real-Time Monitoring

Exposure Monitor: Detects when exposure exceeds user-defined risk thresholds.

Auto Hedging Monitor: Triggers alerts when hedge value changes by more than 1%.

3. Risk Management Tools

Volatility Forecasting: GARCH-based short-term volatility forecast.

VaR (Value at Risk): Historical simulation to estimate worst-case losses.

Greeks Calculation: Delta, Gamma, Vega, Theta estimation for options.

Correlation Matrix: Understand diversification risk.

Max Drawdown: Measures largest historical loss.

Stress Scenarios: Simulate market crashes and estimate portfolio impact.

4. Hedging Strategies Supported

Manual Perpetual Shorting

Protective Puts via Deribit

Auto Rebalancing Alerts

File Structure

main.py

Loads environment

Initializes DB and tables

Starts Telegram bot and auto-hedging loop

Cleans up invalid hedges

monitor_risk.py

monitor_auto_hedging_loop(): Alerts if hedge value changes ≥1%

monitor_exposure_loop(): Alerts if exposure exceeds user-defined risk threshold

Uses alert hashes to avoid duplicate messages

handlers.py

Contains Telegram handlers for all commands:

/start, /hedge_now, /forecast_volatility, /pnl_report, /greeks, etc.

Handles inline button callbacks for executing hedge

services/risk_metrics.py

calculate_portfolio_var()

calculate_correlation_matrix()

get_portfolio_max_drawdown()

simulate_stress_scenarios()

calculate_portfolio_greeks()

get_portfolio_pnl()

exchanges/price_fetcher.py

Price & orderbook fetchers using ccxt

Historical OHLCV fetcher

Close exchange connections (Bybit, Deribit, OKX)

exchanges/options_utils.py

Deribit put options screener (ATM/OTM)

Option info fetcher for Greeks

services/greeks.py

Black-Scholes-based Greek calculator

db/database.py

SQLite interface

Initializes tables for:

monitored_positions

auto_hedges

Connection handler

Alerts Logic

Auto Hedge Alert Trigger:

Every 60s, checks:

If hedge_cost changes ≥1% from last_hedge_amount

If yes and not already alerted (via hash), sends alert

Exposure Alert Trigger:

Every 30s, checks:

If current exposure > (threshold % of exposure)

If yes and not already alerted, sends warning

Setup Instructions

Clone repository

Install dependencies:

pip install -r requirements.txt

Set environment variables in .env

Run bot:

python main.py




Commands Summary

Command

        

/start

Register user and show menu

/hedge_now <asset>

Manually trigger hedge

/forecast_volatility <asset>

Forecast volatility using GARCH

/pnl_report

Portfolio-level P&L report

/greeks

Compute portfolio Greeks

/hedge_options <asset>

Suggest optimal option for hedge




Future Extensions

Machine Learning-based volatility forecast (LSTM, Prophet)

Full execution support via ccxt (live orders)

Sentiment-based risk adjustments

Multi-user Telegram support