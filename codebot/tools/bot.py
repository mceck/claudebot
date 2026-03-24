from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, ContextTypes

from codebot.settings import settings
from codebot.tools.scheduler import scheduler

async def setup_commands(application):
    """Set up bot commands for autocomplete"""
    commands = [
        BotCommand("select", "Select a project to work on"),
        BotCommand("current", "Show the current project"),
        BotCommand("gdiff", "Show git diff of the current project"),
        BotCommand(
            "gco", "Checkout a branch in the git repository of the current project"
        ),
        BotCommand("gpush", "Push the current project to a git repository"),
        BotCommand("gstat", "Show git status of the current project"),
        BotCommand("greset", "Reset and pull git repository of the current project"),
        BotCommand("gclone", "Clone a new git repository"),
        BotCommand(
            "gfetch", "Fetch updates from the git repository of the current project"
        ),
        BotCommand("gdel", "Delete a git branch"),
        BotCommand("schedule", "Schedule a message to be sent to Claude"),
        BotCommand("showjobs", "Show scheduled messages"),
        BotCommand("deljob", "Delete a scheduled message"),
        BotCommand("sessions", "List active Claude sessions"),
        BotCommand("lastsessions", "Show last 10 Claude sessions"),
        BotCommand("kill", "Kill an active Claude session"),
        BotCommand("clear", "Clear the current Claude session"),
        BotCommand("checklogin", "Check if the bot is logged in to Claude"),
    ]
    await application.bot.set_my_commands(commands)
    scheduler.start()

    if settings.DATABASE_URL:
        from codebot.tools.logger import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


app = (
    ApplicationBuilder()
    .token(settings.TELEGRAM_BOT_TOKEN)
    .post_init(setup_commands)
    .concurrent_updates(True)
    .build()
)

MAX_MESSAGE_LENGTH = 4096
MAX_TOTAL_LENGTH = 40000  # above this, last chunk gets truncated

def _split_message(message: str, chunk_wrap: tuple[str, str] | None = None) -> list[str]:
    """Split a message into chunks of MAX_MESSAGE_LENGTH, respecting newlines.

    If chunk_wrap is provided as (prefix, suffix), each chunk is wrapped individually.
    """
    if chunk_wrap:
        prefix, suffix = chunk_wrap
        wrap_overhead = len(prefix) + len(suffix)
    else:
        prefix, suffix = "", ""
        wrap_overhead = 0

    max_chunk = MAX_MESSAGE_LENGTH - wrap_overhead

    if len(message) <= max_chunk:
        return [f"{prefix}{message}{suffix}"] if chunk_wrap else [message]

    if len(message) > MAX_TOTAL_LENGTH:
        message = message[:MAX_TOTAL_LENGTH]

    chunks = []
    while len(message) > max_chunk:
        split_at = message.rfind("\n", 0, max_chunk)
        if split_at == -1 or split_at < max_chunk // 2:
            split_at = max_chunk
        chunks.append(f"{prefix}{message[:split_at]}{suffix}")
        message = message[split_at:].lstrip("\n")
    if message:
        chunks.append(f"{prefix}{message}{suffix}")
    return chunks

def build_keyboard(buttons: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    if len(buttons) > 3:
        keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    else:
        keyboard = [[b] for b in buttons]
    return InlineKeyboardMarkup(keyboard)

async def _do_send(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Send a single message chunk, retrying without parse_mode on BadRequest."""
    try:
        if not update.message:
            if not update.effective_chat:
                return
            return await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text, **kwargs
            )
        return await update.message.reply_text(text, **kwargs)
    except BadRequest:
        if "parse_mode" not in kwargs:
            raise
        kwargs.pop("parse_mode")
        print("Retrying message without parse_mode due to BadRequest")
        if not update.message:
            if not update.effective_chat:
                return
            return await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text, **kwargs
            )
        return await update.message.reply_text(text, **kwargs)

async def send_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str,
    chunk_wrap: tuple[str, str] | None = None, **kwargs
):
    chunks = _split_message(message, chunk_wrap=chunk_wrap)
    result = None
    for chunk in chunks:
        result = await _do_send(update, context, chunk, **kwargs)
    return result

async def _do_send_direct(chat_id: int, text: str, **kwargs):
    """Send a single direct message chunk, retrying without parse_mode on BadRequest."""
    try:
        return await app.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except BadRequest:
        if "parse_mode" not in kwargs:
            raise
        kwargs.pop("parse_mode")
        print("Retrying message without parse_mode due to BadRequest")
        return await app.bot.send_message(chat_id=chat_id, text=text, **kwargs)

async def send_direct_message(chat_id: int, message: str,
                              chunk_wrap: tuple[str, str] | None = None, **kwargs):
    print(f"Sending message to chat {chat_id}\n")
    chunks = _split_message(message, chunk_wrap=chunk_wrap)
    result = None
    for chunk in chunks:
        result = await _do_send_direct(chat_id, chunk, **kwargs)
    return result