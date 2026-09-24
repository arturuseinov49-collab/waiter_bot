"""Telegram entry point. Importing this module does not start polling."""
import asyncio
import logging
import os
import re
from pathlib import Path

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from waiterbot.app import TrainingBot
from waiterbot.catalog import Catalog, ROLES
from waiterbot.storage import Store

BASE_DIR = Path(__file__).resolve().parent


class RedactedFormatter(logging.Formatter):
    def format(self, record):
        return re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{20,}", "<BOT_TOKEN>", super().format(record))


async def main():
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Укажи BOT_TOKEN в .env рядом с bot.py")
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    db_path = Path(os.getenv("BOT_DB_PATH", "data/bot.sqlite3"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    catalog = Catalog(BASE_DIR)
    await asyncio.to_thread(catalog.reload)
    store = Store(db_path)
    await asyncio.to_thread(store.initialize)
    await asyncio.to_thread(store.migrate_legacy, BASE_DIR, ROLES)
    application = TrainingBot(store, catalog, admin_id)
    dispatcher = Dispatcher()
    dispatcher.include_router(application.router)
    async with Bot(token=token) as bot:
        logging.info("Question catalog and database ready; starting polling")
        await dispatcher.start_polling(bot, close_bot_session=False)


if __name__ == "__main__":
    handler = logging.StreamHandler()
    handler.setFormatter(RedactedFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    asyncio.run(main())
