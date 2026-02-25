from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from claudebot.tools.claude import Claude
from claudebot.settings import settings
from claudebot.handlers.generic_handlers import (
    greet_user,
    pick_project,
    get_current_project,
    select_project,
    error_handler,
)
from claudebot.handlers.git_handlers import (
    select_branch_for_checkout,
    git_status,
    git_diff,
    git_reset,
    git_clone,
    git_push,
    git_fetch,
    git_checkout,
    git_delete_branch,
)
from claudebot.handlers.claude_handlers import (
    check_login,
    message_handler,
    kill_claude,
    select_session_to_kill,
    get_active_claude_sessions,
    transcription_to_claude_handler,
    voice_message_handler,
    clear_session
)


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
        BotCommand("sessions", "List active Claude sessions"),
        BotCommand("kill", "Kill an active Claude session"),
        BotCommand("clear", "Clear the current Claude session"),
        BotCommand("checklogin", "Check if the bot is logged in to Claude"),
    ]
    await application.bot.set_my_commands(commands)


app = (
    ApplicationBuilder()
    .token(settings.TELEGRAM_BOT_TOKEN)
    .post_init(setup_commands)
    .concurrent_updates(True)
    .build()
)

app.add_error_handler(error_handler)

app.add_handler(CommandHandler("start", greet_user))
app.add_handler(CommandHandler("select", pick_project))
app.add_handler(CommandHandler("current", get_current_project))
app.add_handler(CommandHandler("sessions", get_active_claude_sessions))
app.add_handler(CommandHandler("kill", kill_claude))
app.add_handler(CommandHandler("clear", clear_session))
app.add_handler(CommandHandler("gstat", git_status))
app.add_handler(CommandHandler("gdiff", git_diff))
app.add_handler(CommandHandler("greset", git_reset))
app.add_handler(CommandHandler("gclone", git_clone))
app.add_handler(CommandHandler("gpush", git_push))
app.add_handler(CommandHandler("gfetch", git_fetch))
app.add_handler(CommandHandler("gco", git_checkout))
app.add_handler(CommandHandler("gdel", git_delete_branch))
app.add_handler(CommandHandler("checklogin", check_login))
app.add_handler(CallbackQueryHandler(select_project, pattern="^selectproject_"))
app.add_handler(
    CallbackQueryHandler(select_branch_for_checkout, pattern="^(gco_|gpush_|gdel_)")
)
app.add_handler(CallbackQueryHandler(select_session_to_kill, pattern="^kill_"))
app.add_handler(
    CallbackQueryHandler(
        transcription_to_claude_handler, pattern="^transcription_to_claude$"
    )
)
app.add_handler(MessageHandler(filters.VOICE, voice_message_handler))
app.add_handler(MessageHandler(filters.TEXT, message_handler))


def run():
    app.run_polling()
