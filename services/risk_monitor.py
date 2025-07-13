from telegram import Bot
from db.database import get_connection
from exchanges.price_fetcher import get_price
import logging
import asyncio
import hashlib
import time
from exchanges.price_fetcher import get_price, get_orderbook
from db.database import get_connection
from telegram import Bot
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
chat_id = None  # Will be set by /start command in the bot
triggered_alerts = set()  # Stores hashes of already sent alerts
sent_hedge_alerts = set()

def generate_hedge_hash(asset: str, hedge_cost: float) -> str:
    """Generate a hash based on asset and hedge cost (rounded to 2 decimals)."""
    raw = f"{asset.upper()}_{round(hedge_cost, 2)}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def monitor_auto_hedging_loop(bot: Bot):
    while True:
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT asset, rebalance_interval, last_hedge_amount FROM auto_hedges")
            auto_hedges = cur.fetchall()
            conn.close()

            for asset, interval, last_amount in auto_hedges:
                # Check if asset is still monitored
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("SELECT position_size FROM monitored_positions WHERE asset = ?", (asset,))
                row = cur.fetchone()
                conn.close()

                if not row:
                    logging.warning(f"[auto hedge] {asset}: Skipped (not in monitored_positions)")
                    continue

                position_size = row[0]

                try:
                    # Try fetching price/orderbook early
                    spot_price = await get_price(asset, source="okx")
                    orderbook = await get_orderbook(asset, source="okx")
                    best_ask = orderbook["asks"][0][0]
                except Exception as e:
                    logging.warning(f"[auto hedge] {asset}: Asset not available on okx ({e})")
                    continue

                hedge_cost = best_ask * position_size

                if abs(hedge_cost - last_amount) / hedge_cost >= 0.01:  # ≥ 1% change
                    hedge_hash = generate_hedge_hash(asset, hedge_cost)

                    # Prevent duplicate alert
                    if hedge_hash in sent_hedge_alerts:
                        continue
                    sent_hedge_alerts.add(hedge_hash)

                    message = (
                        f"*Auto Rebalancing Alert for {asset}*\n\n"
                        f"• Spot Price: ${spot_price:,.2f}\n"
                        f"• Perpetual Best Ask: ${best_ask:,.2f}\n"
                        f"• Position Size: {position_size} {asset}\n"
                        f"• Updated Hedge Cost: ${hedge_cost:,.2f}"
                    )

                    if chat_id:
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("Hedge Now", callback_data=f"hedge_now_{asset}")]
                        ])
                        await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown", reply_markup=keyboard)

                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE auto_hedges SET last_hedge_amount = ?, last_hedge_time = ? WHERE asset = ?",
                        (hedge_cost, time.time(), asset)
                    )
                    conn.commit()
                    conn.close()

        except Exception as e:
            logging.error(f"[monitor_auto_hedging_loop] Loop error: {e}")

        await asyncio.sleep(60)

def generate_alert_hash(asset: str, size: float, threshold: float) -> str:
    """Generate a unique hash for a specific risk setup (based on user inputs)."""
    raw = f"{asset.upper()}_{size}_{threshold}"
    return hashlib.sha256(raw.encode()).hexdigest()

async def monitor_exposure_loop(bot: Bot):
    global chat_id

    while True:
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT asset, position_size, risk_threshold FROM monitored_positions")
            rows = cur.fetchall()
            conn.close()

            for asset, size, threshold_pct in rows:
                try:
                    price = await get_price(asset)
                    exposure = size * price
                    allowed_exposure = exposure * (threshold_pct / 100)

                    alert_hash = generate_alert_hash(asset, size, threshold_pct)

                    if exposure > allowed_exposure and chat_id:
                        if alert_hash not in triggered_alerts:
                            message = (
                                f"Risk Breach Detected!\n\n"
                                f"Asset: {asset}\n"
                                f"Position Size: {size}\n"
                                f"Price: ${price:,.2f}\n"
                                f"Exposure: ${exposure:,.2f}\n"
                                f"Threshold: {threshold_pct:.2f}% of exposure (${allowed_exposure:,.2f})\n\n"
                                f"Use /hedge_now {asset} to hedge."
                            )
                            await bot.send_message(chat_id=chat_id, text=message)
                            triggered_alerts.add(alert_hash)

                except Exception as e:
                    logging.error(f"[Price Error] {asset}: {e}")

            await asyncio.sleep(30)

        except Exception as e:
            logging.error(f"[Monitor Loop] {e}")
            await asyncio.sleep(30)
