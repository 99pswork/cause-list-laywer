"""Telegram bot command and conversation handlers."""

import asyncio
import logging
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import database as db
from bot.formatter import format_causelist_message
from causelist.client import CauseListClient
from causelist.config import CAUSELIST_TYPE_NAMES
from causelist.date_utils import format_date_for_api, next_working_day
from causelist.parser import parse_to_records

logger = logging.getLogger(__name__)

# Conversation states — registration
AWAITING_LAWYER_NAME = 0

# Conversation states — fetch flow
FETCH_DATE, FETCH_NAME_CHOICE, FETCH_CUSTOM_NAME = range(10, 13)


def _get_date_options() -> list[tuple[str, str]]:
    """Return list of (label, dd/mm/yyyy) for today and the next 2 working days."""
    today = date.today()
    options = [(f"Today ({today.strftime('%d/%m/%Y')})", format_date_for_api(today))]

    d = today
    for _ in range(2):
        d = next_working_day(d)
        weekday = d.strftime("%A")
        options.append(
            (f"{weekday} ({d.strftime('%d/%m/%Y')})", format_date_for_api(d))
        )

    return options


# ---- /start conversation ----


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: greet user and ask for lawyer name."""
    user = await db.get_user(update.effective_user.id)
    if user and user["is_active"]:
        await update.message.reply_text(
            f"Welcome back! You are registered as <b>{user['lawyer_name']}</b>.\n\n"
            f"Commands:\n"
            f"/fetch - Get cause list now\n"
            f"/update - Change your lawyer name\n"
            f"/status - Show registration info\n"
            f"/stop - Unsubscribe from notifications",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Welcome to the <b>Rajasthan HC Cause List Bot</b>!\n\n"
        "I will send you your cause list every morning at 7 AM "
        "and evening at 10 PM IST.\n\n"
        "To get started, please send me the <b>lawyer/advocate name</b> "
        "to search for (minimum 3 characters).\n\n"
        "Example: <code>RAHUL SHARMA</code>",
        parse_mode=ParseMode.HTML,
    )
    return AWAITING_LAWYER_NAME


async def receive_lawyer_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Process the lawyer name and complete registration."""
    name = update.message.text.strip().upper()

    if len(name) < 3:
        await update.message.reply_text(
            "Name must be at least 3 characters. Please try again."
        )
        return AWAITING_LAWYER_NAME

    await db.upsert_user(
        telegram_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        lawyer_name=name,
    )

    await update.message.reply_text(
        f"Registered successfully as <b>{name}</b>!\n\n"
        f"You will receive Daily and Supplementary cause lists "
        f"at 7 AM and 10 PM IST every day.\n\n"
        f"Commands:\n"
        f"/fetch - Get cause list now\n"
        f"/update - Change your lawyer name\n"
        f"/status - Show registration info\n"
        f"/stop - Unsubscribe from notifications",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current conversation."""
    await update.message.reply_text("Cancelled. Send /start to begin registration.")
    return ConversationHandler.END


# ---- /update command ----


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allow user to change their registered lawyer name."""
    await update.message.reply_text(
        "Send me the new <b>lawyer/advocate name</b> to search for:",
        parse_mode=ParseMode.HTML,
    )
    return AWAITING_LAWYER_NAME


# ---- /fetch conversation ----


async def fetch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the fetch flow: show date options."""
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_active"]:
        await update.message.reply_text("Please /start first to register.")
        return ConversationHandler.END

    date_options = _get_date_options()
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"date:{date_str}")]
        for label, date_str in date_options
    ]

    await update.message.reply_text(
        "Select the <b>date</b> for cause list:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return FETCH_DATE


async def fetch_date_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle date selection, then ask about lawyer name."""
    query = update.callback_query
    await query.answer()

    selected_date = query.data.split(":", 1)[1]
    context.user_data["fetch_date"] = selected_date

    user = await db.get_user(update.effective_user.id)
    registered_name = user["lawyer_name"]

    keyboard = [
        [
            InlineKeyboardButton(
                f"My name ({registered_name})",
                callback_data="name:registered",
            )
        ],
        [
            InlineKeyboardButton(
                "Use a different name",
                callback_data="name:custom",
            )
        ],
    ]

    await query.edit_message_text(
        f"Date: <b>{selected_date}</b>\n\n" f"Whose cause list do you want to fetch?",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return FETCH_NAME_CHOICE


async def fetch_name_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle name choice — use registered or ask for custom."""
    query = update.callback_query
    await query.answer()

    choice = query.data.split(":", 1)[1]

    if choice == "registered":
        user = await db.get_user(update.effective_user.id)
        context.user_data["fetch_name"] = user["lawyer_name"]
        await query.edit_message_text(
            f"Fetching cause lists for <b>{user['lawyer_name']}</b> "
            f"on <b>{context.user_data['fetch_date']}</b>...\n"
            f"This may take a moment.",
            parse_mode=ParseMode.HTML,
        )
        await _do_fetch(update, context)
        return ConversationHandler.END
    else:
        await query.edit_message_text(
            f"Date: <b>{context.user_data['fetch_date']}</b>\n\n"
            f"Send me the <b>lawyer/advocate name</b> to search for:",
            parse_mode=ParseMode.HTML,
        )
        return FETCH_CUSTOM_NAME


async def fetch_custom_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive custom lawyer name, then fetch."""
    name = update.message.text.strip().upper()

    if len(name) < 3:
        await update.message.reply_text(
            "Name must be at least 3 characters. Please try again."
        )
        return FETCH_CUSTOM_NAME

    context.user_data["fetch_name"] = name
    await update.message.reply_text(
        f"Fetching cause lists for <b>{name}</b> "
        f"on <b>{context.user_data['fetch_date']}</b>...\n"
        f"This may take a moment.",
        parse_mode=ParseMode.HTML,
    )
    await _do_fetch(update, context)
    return ConversationHandler.END


async def _do_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Perform the actual cause list fetch and send results."""
    target_date = context.user_data["fetch_date"]
    lawyer_name = context.user_data["fetch_name"]
    chat_id = update.effective_chat.id

    for cl_type in ["D", "S"]:
        type_name = CAUSELIST_TYPE_NAMES[cl_type]
        try:
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
                    f"No records found for <b>{type_name}</b> cause list on {target_date}."
                ]

            for msg in messages:
                await context.bot.send_message(
                    chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML
                )

        except Exception as e:
            logger.error(f"Fetch error for {lawyer_name}/{cl_type}: {e}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Error fetching {type_name} cause list: {str(e)[:200]}",
            )


async def fetch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the fetch flow."""
    await update.message.reply_text("Fetch cancelled.")
    return ConversationHandler.END


# ---- /status command ----


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user their current registration status."""
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(
            "You are not registered. Send /start to register."
        )
        return

    status = "Active" if user["is_active"] else "Inactive"
    await update.message.reply_text(
        f"<b>Registration Status</b>\n\n"
        f"Lawyer name: <b>{user['lawyer_name']}</b>\n"
        f"Status: <b>{status}</b>\n"
        f"Registered: {user['created_at'].strftime('%d/%m/%Y %H:%M')}\n"
        f"Last updated: {user['updated_at'].strftime('%d/%m/%Y %H:%M')}",
        parse_mode=ParseMode.HTML,
    )


# ---- /stop command ----


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deactivate the user's subscription."""
    deactivated = await db.deactivate_user(update.effective_user.id)
    if deactivated:
        await update.message.reply_text(
            "You have been unsubscribed. You will no longer receive scheduled notifications.\n"
            "Send /start to re-subscribe at any time."
        )
    else:
        await update.message.reply_text("You are not currently subscribed.")


# ---- /help command ----


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands."""
    await update.message.reply_text(
        "<b>Available Commands</b>\n\n"
        "/start - Register or re-activate\n"
        "/fetch - Fetch cause list now\n"
        "/update - Change your lawyer name\n"
        "/status - Show registration info\n"
        "/stop - Unsubscribe from notifications\n"
        "/help - Show this help message",
        parse_mode=ParseMode.HTML,
    )


def build_conversation_handler() -> ConversationHandler:
    """Build the ConversationHandler for /start and /update registration flows."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("update", update_command),
        ],
        states={
            AWAITING_LAWYER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lawyer_name),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("help", help_command),
            CommandHandler("fetch", fetch_command),
            CommandHandler("status", status_command),
            CommandHandler("stop", stop_command),
            CommandHandler("start", start_command),
        ],
    )


def build_fetch_handler() -> ConversationHandler:
    """Build the ConversationHandler for /fetch flow (date + name selection)."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("fetch", fetch_command),
        ],
        states={
            FETCH_DATE: [
                CallbackQueryHandler(fetch_date_selected, pattern=r"^date:"),
            ],
            FETCH_NAME_CHOICE: [
                CallbackQueryHandler(fetch_name_choice, pattern=r"^name:"),
            ],
            FETCH_CUSTOM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fetch_custom_name),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", fetch_cancel),
            CommandHandler("help", help_command),
            CommandHandler("start", start_command),
        ],
        per_message=False,
    )
