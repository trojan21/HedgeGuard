from telegram.ext import ApplicationBuilder
from telegram_bot.handlers import register_handlers
from config.config import Config

application = None  # Global app instance for access in stop_bot()

async def start_bot():
    global application
    application = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    register_handlers(application)
    application.run_polling(close_loop=False)  # Prevents asyncio loop from closing

async def stop_bot():
    global application
    if application:
        await application.shutdown()
