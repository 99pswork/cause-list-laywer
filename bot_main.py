#!/usr/bin/env python3
"""Entry point for the Telegram bot."""

import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram.ext import ApplicationBuilder, CommandHandler

from bot import database as db
from bot.config import (
    DATABASE_URL,
    SCHEDULE_EVENING,
    SCHEDULE_MORNING,
    TELEGRAM_BOT_TOKEN,
    TIMEZONE_NAME,
)
from bot.handlers import (
    build_conversation_handler,
    build_fetch_handler,
    help_command,
    status_command,
    stop_command,
)
from bot.scheduler import scheduled_fetch_and_notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def post_init(application) -> None:
    """Called after the Application is initialized. Set up DB and schedule jobs."""
    await db.init_pool(DATABASE_URL)
    await db.ensure_schema()

    tz = ZoneInfo(TIMEZONE_NAME)
    job_queue = application.job_queue

    morning_time = time(
        hour=SCHEDULE_MORNING[0], minute=SCHEDULE_MORNING[1], tzinfo=tz
    )
    evening_time = time(
        hour=SCHEDULE_EVENING[0], minute=SCHEDULE_EVENING[1], tzinfo=tz
    )

    job_queue.run_daily(
        scheduled_fetch_and_notify, time=morning_time, name="morning_fetch"
    )
    job_queue.run_daily(
        scheduled_fetch_and_notify, time=evening_time, name="evening_fetch"
    )

    logger.info(f"Scheduled jobs: morning at {morning_time}, evening at {evening_time}")


async def post_shutdown(application) -> None:
    """Called when the Application shuts down. Clean up DB pool."""
    await db.close_pool()


def main() -> None:
    """Build and run the Telegram bot application."""
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register handlers
    app.add_handler(build_conversation_handler())
    app.add_handler(build_fetch_handler())
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("help", help_command))

    logger.info("Starting Telegram bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
