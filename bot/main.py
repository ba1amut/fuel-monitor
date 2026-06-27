import asyncio
import os
import logging

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from bot.handlers import report, query

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = "/bot"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"


async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(query.router)
    dp.include_router(report.router)
    dp.startup.register(on_startup)

    app = web.Application()
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logging.info("Bot started on 0.0.0.0:8080")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
