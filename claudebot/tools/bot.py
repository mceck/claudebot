from telegram import BotCommand, Update
from telegram.ext import ApplicationBuilder, ContextTypes

from claudebot.settings import settings
from claudebot.tools.scheduler import scheduler

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
        BotCommand("kill", "Kill an active Claude session"),
        BotCommand("clear", "Clear the current Claude session"),
        BotCommand("checklogin", "Check if the bot is logged in to Claude"),
    ]
    await application.bot.set_my_commands(commands)
    scheduler.start()

    if settings.DATABASE_URL:
        from claudebot.tools.logger import Base, engine

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

async def send_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str, **kwargs
):
    if len(message) > MAX_MESSAGE_LENGTH:
        truncate_length = (MAX_MESSAGE_LENGTH - 10) // 2
        message = message[:truncate_length] + "\n...\n" + message[-truncate_length:]

    if not update.message:
        if not update.effective_chat:
            return
        return await context.bot.send_message(
            chat_id=update.effective_chat.id, text=message, **kwargs
        )
    return await update.message.reply_text(message, **kwargs)

async def send_direct_message(chat_id: int, message: str, **kwargs):
    if len(message) > MAX_MESSAGE_LENGTH:
        truncate_length = (MAX_MESSAGE_LENGTH - 10) // 2
        message = message[:truncate_length] + "\n...\n" + message[-truncate_length:]

    print(f"Sending message to chat {chat_id}\n")
    return await app.bot.send_message(chat_id=chat_id, text=message, **kwargs)