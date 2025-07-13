from services.timing_predictor import predict_optimal_hedge_time
from exchanges.options_utils import (
    get_best_put_option,
    get_best_call_option,
    get_option_price
)
import matplotlib.pyplot as plt
from services.portfolio_risk import calculate_portfolio_pnl
from arch import arch_model
import io
import logging
import asyncio
import datetime
from db.database import get_connection, create_auto_hedge_table
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
from telegram.ext import CallbackQueryHandler
from services.greeks import calculate_greeks
from services.risk_monitor import monitor_auto_hedging_loop

from db.database import get_connection
from services import risk_monitor
from services.risk_monitor import monitor_auto_hedging_loop, monitor_exposure_loop
from services.volatility import forecast_volatility
from exchanges.price_fetcher import get_orderbook, get_price
from exchanges.options_utils import get_best_put_option, get_best_call_option, get_option_price


from services.timing_predictor import predict_optimal_hedge_time



# --- Command: /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    risk_monitor.chat_id = update.effective_chat.id
    await update.effective_message.reply_text("Spot Exposure Hedging Bot is online!")
    bot = context.bot

    asyncio.create_task(risk_monitor.monitor_auto_hedging_loop(bot))
    asyncio.create_task(risk_monitor.monitor_exposure_loop(bot))

# --- Command: /help ---
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "*Available Commands:*\n\n"
        "/start - Initialize the bot\n"
        "/help - Show this help message\n"
        "/monitor\\_risk <asset> <position\\_size> <risk\\_threshold> - Start monitoring risk\n"
        "/hedge\\_now <asset> [exchange] - View hedge suggestion\n"
        "/hedge\\_options <asset> <strategy> - Hedge with options (protective\\_put, covered\\_call, collar)\n"
        "/forecast\\_volatility <asset> [steps_ahead] - Forecast volatility and view plots\n"
        "/predict\\_hedge <asset> - Predict whether and when to hedge based on forecasted volatility\n"
        "/status or /hedge\\_status <asset> - View hedge status\n"
        "/hedge\\_history <asset> - View historical hedge records\n"
        "/auto\\_hedge <asset> <interval\\_minutes> - Enable auto hedging for an asset\n"
        "/price - View latest prices (interactive buttons)\n"
        "/greeks <asset> <call/put> <strike> <expiry_days> <volatility> - Compute option Greeks\n"
        "/pnl\\_report - Show portfolio P&L report\n"
        "/show\\_db - View monitored positions\n"
        "/delete\\_all\\_db - Clear all monitored positions\n",
        parse_mode="Markdown"
    )


# --- Command: /monitor_risk ---
async def monitor_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        asset = context.args[0].upper()
        size = float(context.args[1])
        threshold = float(context.args[2].strip('%'))
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO monitored_positions (asset, position_size, risk_threshold)
            VALUES (?, ?, ?)
            ON CONFLICT(asset) DO UPDATE SET 
                position_size = excluded.position_size,
                risk_threshold = excluded.risk_threshold
        """, (asset, size, threshold))
        conn.commit()
        conn.close()
        await update.effective_message.reply_text(
            f"Now monitoring {asset}:\n• Size: {size}\n• Risk Threshold: {threshold}%"
        )
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /monitor_risk <asset> <position_size> <risk_threshold>")

# --- Command: /hedge_now ---
async def hedge_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 1:
            await update.effective_message.reply_text("Usage: /hedge_now <asset> [exchange]")
            return

        asset = context.args[0].upper()
        exchange = context.args[1].lower() if len(context.args) > 1 else "okx"

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT position_size FROM monitored_positions WHERE asset = ?", (asset,))
        row = cur.fetchone()

        if not row:
            conn.close()
            await update.effective_message.reply_text(f"No monitored position found for {asset}")
            return

        position_size = row[0]

        # Fetch orderbook from selected exchange
        orderbook = await get_orderbook(asset, exchange)
        best_ask = orderbook["asks"][0]
        hedge_price = best_ask[0]
        hedge_cost = hedge_price * position_size

        # Update hedge record
        cur.execute("UPDATE auto_hedges SET last_hedge_amount = ? WHERE asset = ?", (hedge_price, asset))
        conn.commit()
        conn.close()

        await update.effective_message.reply_text(
            f"Hedge Suggestion for {asset} on {exchange.upper()}:\n\n"
            f"Spot Position Size: {position_size} {asset}\n"
            f"Best Ask Price: ${hedge_price:,.2f}\n"
            f"Recommended Short (Perp): {position_size} {asset}\n"
            f"Estimated Hedge Cost: ${hedge_cost:,.2f}\n\n"
            
        )

    except Exception as e:
        logging.error(f"[hedge_now] {e}")
        await update.effective_message.reply_text("Error processing hedge request. Please try again.")


async def hedge_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("hedge_now_"):
        return
    asset = query.data.split("_", 2)[2]
    context.args = [asset]
    await hedge_now(update, context)

# --- Command: /hedge_options ---
async def hedge_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /hedge_options <asset> <strategy>\n"
            "Strategies: protective_put, covered_call, collar"
        )
        return

    asset = context.args[0].upper()
    strategy = context.args[1].lower()

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT position_size FROM monitored_positions WHERE asset = ?", (asset,))
        row = cur.fetchone()
        conn.close()

        if not row:
            await update.message.reply_text(f"No monitored position found for {asset}")
            return

        size = row[0]
        spot_price = await get_price(asset, source="okx")
        message = f"Hedging Strategy: {strategy.replace('_', ' ').title()} for {asset}\n\n"
        message += f"Spot Price: ${spot_price:.2f}\nPosition Size: {size} {asset}\n"
        buttons = []

        if strategy == "protective_put":
            option = await get_best_put_option(asset, spot_price)
            premium = await get_option_price(option['symbol'])
            expiry = datetime.datetime.utcfromtimestamp(int(option['info']['expiration_timestamp']) / 1000).strftime("%Y-%m-%d")
            message += (
                f"\nProtective Put:\n"
                f"• Option: {option['symbol']}\n"
                f"• Strike: {option['strike']}\n"
                f"• Expiry: {expiry}\n"
                f"• Premium: ${premium:.2f}\n"
                f"• Cost: ${premium * size:.2f}"
            )
            buttons = [[InlineKeyboardButton("Buy Put", callback_data=f"options_hedge_buy_put_{asset}")]]
        
        elif strategy == "covered_call":
            option = await get_best_call_option(asset, spot_price)
            premium = await get_option_price(option['symbol'])
            expiry = datetime.datetime.utcfromtimestamp(int(option['info']['expiration_timestamp']) / 1000).strftime("%Y-%m-%d")
            message += (
                f"\nCovered Call:\n"
                f"• Option: {option['symbol']}\n"
                f"• Strike: {option['strike']}\n"
                f"• Expiry: {expiry}\n"
                f"• Premium Received: ${premium:.2f}\n"
                f"• Income: ${premium * size:.2f}"
            )
            buttons = [[InlineKeyboardButton("Sell Call", callback_data=f"options_hedge_sell_call_{asset}")]]

        elif strategy == "collar":
            put = await get_best_put_option(asset, spot_price)
            call = await get_best_call_option(asset, spot_price)
            put_premium = await get_option_price(put['symbol'])
            call_premium = await get_option_price(call['symbol'])
            net_cost = put_premium - call_premium
            put_expiry = datetime.datetime.utcfromtimestamp(int(put['info']['expiration_timestamp']) / 1000).strftime("%Y-%m-%d")
            call_expiry = datetime.datetime.utcfromtimestamp(int(call['info']['expiration_timestamp']) / 1000).strftime("%Y-%m-%d")
            message += (
                f"\nCollar Strategy:\n"
                f"• Long Put: {put['symbol']} (Strike: {put['strike']}, Expiry: {put_expiry}, Premium: ${put_premium:.2f})\n"
                f"• Short Call: {call['symbol']} (Strike: {call['strike']}, Expiry: {call_expiry}, Premium: ${call_premium:.2f})\n"
                f"• Net Cost per Unit: ${net_cost:.2f}\n"
                f"• Total Cost: ${net_cost * size:.2f}"
            )
            buttons = [[
                InlineKeyboardButton("Buy Put", callback_data=f"options_hedge_buy_put_{asset}"),
                InlineKeyboardButton("Sell Call", callback_data=f"options_hedge_sell_call_{asset}")
            ]]
        else:
            await update.message.reply_text("Invalid strategy.")
            return

        await update.message.reply_text(message)

        if buttons:
            reply_markup = InlineKeyboardMarkup(buttons)
            await update.message.reply_text("Choose an option to proceed:", reply_markup=reply_markup)

    except Exception as e:
        logging.error(f"[hedge_options] {e}")
        await update.message.reply_text(f"Error processing hedge: {e}")

async def hedge_options_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split("_")
    if len(parts) < 5:
        await query.edit_message_text("Invalid hedge action.")
        return

    action = parts[2]  # buy/sell
    option_type = parts[3]  # put/call
    asset = parts[4].upper()

    await query.edit_message_text(
        f"Confirmed: {action.title()} {option_type.title()} option for {asset}.\n"
        f"Execution logic can be implemented here.)"
    )

async def auto_hedge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /auto_hedge <asset> <rebalance_interval_minutes>")
        return

    asset = context.args[0].upper()
    try:
        interval = int(context.args[1])

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO auto_hedges (asset, rebalance_interval)
            VALUES (?, ?)
            ON CONFLICT(asset) DO UPDATE SET rebalance_interval=excluded.rebalance_interval
        """, (asset, interval))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"Auto hedge for {asset} enabled.\nInterval: {interval} minutes.")

    except ValueError:
        await update.message.reply_text("Please provide a valid integer interval.")

# --- Command: /hedge_status ---
async def hedge_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 1:
            await update.message.reply_text("Usage: /hedge_status <asset>")
            return

        asset = context.args[0].upper()
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT rebalance_interval, last_hedge_amount, last_hedge_time
            FROM auto_hedges WHERE asset = ?
        """, (asset,))
        row = cur.fetchone()
        conn.close()

        if not row:
            await update.message.reply_text(f"No auto hedge data found for {asset}.")
            return

        interval, amount, timestamp = row
        time_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "N/A"

        message = (
            f"Auto Hedge Status for {asset}:\n\n"
            f"• Rebalance Interval: {interval} min\n"
            f"• Last Hedge Amount: ${amount:,.2f}\n"
            f"• Last Hedge Time: {time_str}"
        )

        buttons = [
            [InlineKeyboardButton("Hedge Now", callback_data=f"hedge_now_{asset}")],
            [InlineKeyboardButton("Forecast Vol", callback_data=f"forecast_vol_{asset}")]
        ]

        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        logging.error(f"[hedge_status] {e}")
        await update.message.reply_text("Failed to fetch hedge status.")



# --- Command: /hedge_history ---
async def hedge_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 1:
            await update.message.reply_text("Usage: /hedge_history <asset>")
            return

        asset = context.args[0].upper()
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT rebalance_interval, last_hedge_amount, last_hedge_time
            FROM auto_hedges WHERE asset = ?
        """, (asset,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text(f"No hedge history found for {asset}.")
            return

        response = f"📊 Hedge History for {asset}:\n\n"
        for interval, amount, timestamp in rows:
            time_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "N/A"
            response += f"• Interval: {interval} min, Amount: ${amount:.2f}, Time: {time_str}\n"

        await update.message.reply_text(response)
    except Exception as e:
        logging.error(f"[hedge_history] {e}")
        await update.message.reply_text("Error fetching hedge history.")


# --- Command: /show_db ---
async def show_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT asset, position_size, risk_threshold FROM monitored_positions")
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("No records in the database.")
            return

        for asset, size, threshold in rows:
            message = (
                f"Asset: {asset}\n"
                f"• Size: {size}\n"
                f"• Risk Threshold: {threshold}%"
            )
            buttons = [
                [
                    InlineKeyboardButton("Hedge Now", callback_data=f"hedge_now_{asset}"),
                    InlineKeyboardButton("Forecast Vol", callback_data=f"forecast_vol_{asset}")
                ],
                [InlineKeyboardButton("Delete", callback_data=f"delete_asset_{asset}")]
            ]
            await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        logging.error(f"[show_db] {e}")
        await update.message.reply_text("Failed to retrieve DB records.")

# async def monitor_auto_hedges():
#     await monitor_auto_hedging_loop(bot)

# --- Command: /delete_all_db ---
async def delete_all_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM monitored_positions")
        conn.commit()
        conn.close()
        await update.message.reply_text("All positions have been deleted from the database.")
    except Exception as e:
        logging.error(f"[delete_all_db] {e}")
        await update.message.reply_text("Failed to delete database contents.")

async def predict_hedge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /predict_hedge <asset>")
        return

    asset = context.args[0].upper()

    try:
        result = await predict_optimal_hedge_time(asset)
        should_hedge = result["should_hedge"]
        high_vol_hours = result["high_vol_hours"]
        forecast_vals = result["vol_forecast"]
        hedge_hours = result.get("hedge_hours", [])
        recommended_hour = result.get("recommended_hour")

        msg = (
            f" Volatility Forecast for {asset} (next {len(forecast_vals)}h):\n\n"
            f" High Volatility Hours (>2.5%): {high_vol_hours}\n"
            f" Should Hedge Now? {'Yes' if should_hedge else 'No'}\n"
        )

        if hedge_hours:
            msg += f"High-Volatility Expected At: {', '.join(f'{h}h' for h in hedge_hours)}\n"
        if recommended_hour is not None:
            msg += f"Recommended Hedge In ~{recommended_hour} hour(s)\n"

        msg += "\nForecasted Volatility:\n"
        msg += ", ".join(f"{v:.2f}%" for v in forecast_vals)

        await update.message.reply_text(msg)

    except Exception as e:
        import logging
        logging.error(f"[predict_hedge] {e}")
        await update.message.reply_text("Error predicting hedge timing.")


# --- Command: /forecast_volatility ---
async def forecast_volatility_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /forecast_volatility <asset> [steps_ahead]")
        return

    asset = context.args[0].upper()
    steps = int(context.args[1]) if len(context.args) > 1 else 10

    try:
        img1, img2 = await forecast_volatility(asset, forecast_steps=steps)
        await update.message.reply_photo(InputFile(io.BytesIO(img1), filename=f"{asset}_realized_vol.png"))
        await update.message.reply_photo(InputFile(io.BytesIO(img2), filename=f"{asset}_garch_forecast.png"))
    except Exception as e:
        logging.error(f"[forecast_volatility] {e}")
        await update.message.reply_text(f"Error: {e}")


# --- Command: /greeks ---
async def show_greeks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 5:
            await update.message.reply_text(
                "Usage: /greeks <asset> <call/put> <strike> <expiry_days> <volatility_decimal>\n"
                "Example: /greeks BTC call 60000 30 0.5"
            )
            return

        asset = context.args[0].upper()
        option_type = context.args[1].lower()
        strike = float(context.args[2])
        expiry_days = int(context.args[3])
        volatility = float(context.args[4])

        # Fetch live spot price from OKX
        S = await get_price(asset, source="okx")
        K = strike
        T = expiry_days / 365
        r = 0.05  # risk-free rate
        sigma = volatility

        greeks = calculate_greeks(option_type, S, K, T, r, sigma)

        await update.message.reply_text(
            f"Greeks for {asset.upper()} {option_type} option:\n\n"
            f"Spot Price: ${S:.2f}\n"
            f"Strike: ${K:.2f}\n"
            f"Expiry: {expiry_days} days\n"
            f"Volatility: {volatility:.2%}\n\n"
            f"Δ Delta: {greeks['delta']:.4f}\n"
            f"Γ Gamma: {greeks['gamma']:.4f}\n"
            f"ν Vega: {greeks['vega']:.4f}\n"
            f"Θ Theta: {greeks['theta']:.4f}"
        )

    except Exception as e:
        logging.error(f"[show_greeks] {e}")
        await update.message.reply_text("Failed to calculate Greeks. Please check your input.")



# --- Command: /pnl_report ---
async def pnl_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Calculating P&L report...")
    try:
        report = await calculate_portfolio_pnl()
        await update.message.reply_text(report)
    except Exception as e:
        logging.error(f"[pnl_report] {e}")
        await update.message.reply_text("Failed to calculate P&L report.")





# --- Command: /price ---
async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("BTC", callback_data="price_BTC"),
         InlineKeyboardButton("ETH", callback_data="price_ETH")],
        [InlineKeyboardButton("Cancel", callback_data="price_BACK")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select an asset to view price:", reply_markup=reply_markup)


# --- Button Callback: /price ---
async def price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "price_BACK":
        await query.edit_message_text("Cancelled.")
        return

    asset = data.split("_")[1]
    exchange = "okx"

    try:
        price = await get_price(asset, exchange)
        await query.edit_message_text(f"Current Price of {asset} on OKX:\n\n${price:,.2f}")
    except Exception as e:
        logging.error(f"[price_callback] {e}")
        await query.edit_message_text("Failed to fetch price.")

# --- Register All Handlers ---
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("monitor_risk", monitor_risk))
    app.add_handler(CommandHandler("hedge_now", hedge_now))
    app.add_handler(CommandHandler("hedge_options", hedge_options))
    app.add_handler(CommandHandler("forecast_volatility", forecast_volatility_cmd))
    app.add_handler(CommandHandler("status", hedge_status))
    app.add_handler(CommandHandler("show_db", show_db))
    app.add_handler(CommandHandler("delete_all_db", delete_all_db))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CallbackQueryHandler(price_callback, pattern=r"^price_"))
    app.add_handler(CommandHandler("auto_hedge", auto_hedge))
    app.add_handler(CommandHandler("greeks", show_greeks))  
    app.add_handler(CommandHandler("hedge_status", hedge_status))
    app.add_handler(CommandHandler("hedge_history", hedge_history))
    app.add_handler(CallbackQueryHandler(price_callback, pattern=r"^price_"))
    app.add_handler(CallbackQueryHandler(hedge_now_callback, pattern=r"^hedge_now_"))
    app.add_handler(CallbackQueryHandler(hedge_options_callback, pattern=r"^options_hedge_"))
    app.add_handler(CommandHandler("pnl_report", pnl_report))
    app.add_handler(CommandHandler("predict_hedge", predict_hedge))
