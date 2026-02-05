"""Scheduled job definitions for daily cause list notifications."""

import asyncio
import logging

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import database as db
from bot.config import SCHEDULED_CL_TYPES
from bot.formatter import format_causelist_message
from causelist.client import CauseListClient
from causelist.config import CAUSELIST_TYPE_NAMES
from causelist.date_utils import format_date_for_api, next_working_day
from causelist.parser import parse_to_records

logger = logging.getLogger(__name__)


async def scheduled_fetch_and_notify(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main scheduled job: fetch cause lists and notify all active users.

    Runs at 7 AM and 10 PM IST. For each cause list type (Daily, Supplementary):
    1. Groups users by lawyer_name to avoid redundant fetches.
    2. Fetches the cause list HTML once per unique (lawyer_name, cl_type, date).
    3. Parses and formats the result.
    4. Sends messages to each user, with deduplication.
    """
    target_date = format_date_for_api(next_working_day())
    users = await db.get_active_users()

    if not users:
        logger.info("No active users, skipping scheduled fetch.")
        return

    logger.info(f"Scheduled run: {len(users)} active users, date={target_date}")

    # Group users by lawyer_name to minimize fetches
    users_by_name: dict[str, list] = {}
    for user in users:
        users_by_name.setdefault(user["lawyer_name"], []).append(user)

    for cl_type in SCHEDULED_CL_TYPES:
        type_name = CAUSELIST_TYPE_NAMES[cl_type]

        for lawyer_name, user_group in users_by_name.items():
            try:
                # Fetch once per lawyer_name + cl_type
                client = CauseListClient()
                html_result = await asyncio.to_thread(
                    client.search_causelist, lawyer_name, target_date, cl_type
                )

                if html_result:
                    records = parse_to_records(html_result)
                    messages = format_causelist_message(
                        records, cl_type, target_date, lawyer_name
                    )
                else:
                    messages = [
                        f"No cases found in <b>{type_name}</b> cause list "
                        f"for <b>{target_date}</b> "
                        f"(Advocate: <b>{lawyer_name}</b>)."
                    ]

                # Send to each user in this group
                notified_count = 0
                for user in user_group:
                    # Deduplication check
                    if await db.was_notified(user["id"], cl_type, target_date):
                        logger.info(
                            f"Skipping duplicate for user {user['telegram_id']} "
                            f"({cl_type}/{target_date})"
                        )
                        continue

                    try:
                        for msg in messages:
                            await context.bot.send_message(
                                chat_id=user["chat_id"],
                                text=msg,
                                parse_mode=ParseMode.HTML,
                            )
                            # Small delay to avoid Telegram rate limits
                            await asyncio.sleep(0.05)

                        await db.log_notification(
                            user["id"], cl_type, target_date, len(messages)
                        )
                        notified_count += 1
                    except Exception as send_err:
                        logger.error(
                            f"Failed to send to {user['telegram_id']}: {send_err}"
                        )

                await db.log_fetch(cl_type, target_date, notified_count, "success")
                logger.info(
                    f"Sent {type_name} for '{lawyer_name}' to {notified_count} users"
                )

            except Exception as fetch_err:
                logger.error(
                    f"Fetch failed for {lawyer_name}/{cl_type}/{target_date}: {fetch_err}"
                )
                await db.log_fetch(
                    cl_type, target_date, 0, "error", str(fetch_err)[:500]
                )
