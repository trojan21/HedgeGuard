import os
import asyncio
import signal
import nest_asyncio
from dotenv import load_dotenv
from services.risk_monitor import monitor_auto_hedging_loop
from db.database import init_db, create_auto_hedge_table, get_connection
from telegram_bot.bot import start_bot, stop_bot
from exchanges.price_fetcher import close_all_exchanges, close_bybit
from exchanges.options_utils import close_deribit


nest_asyncio.apply()

def clean_invalid_auto_hedges():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM auto_hedges
        WHERE asset NOT IN (SELECT asset FROM monitored_positions)
    """)
    conn.commit()
    conn.close()

async def on_shutdown():
    await close_bybit()
    await close_deribit()
    await close_all_exchanges()

async def main():
    load_dotenv()
    init_db()
    create_auto_hedge_table()
    clean_invalid_auto_hedges()

    print("Database initialized.")
    print(f"DB location: {os.path.abspath('db/perpetuals.db')}")
    print("Starting bot...")

    # Start bot and monitoring
    await start_bot()
    asyncio.create_task(monitor_auto_hedging_loop())

    # Wait for bot to finish (blocking)
    await stop_bot()

    await on_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Graceful exit on Ctrl+C")
