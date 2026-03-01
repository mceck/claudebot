from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from claudebot.tools.bot import app
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
    clear_session,
    schedule_message,
    schedule_continue_handler,
    show_scheduled_jobs,
    delete_scheduled_job,
    delete_scheduled_job_handler,
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
app.add_handler(CommandHandler("schedule", schedule_message))
app.add_handler(CommandHandler("showjobs", show_scheduled_jobs))
app.add_handler(CommandHandler("deljob", delete_scheduled_job))
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
app.add_handler(
    CallbackQueryHandler(
        schedule_continue_handler, pattern="^schedule_continue_"
    )
)
app.add_handler(CallbackQueryHandler(delete_scheduled_job_handler, pattern="^delete_schedule_"))
app.add_handler(MessageHandler(filters.VOICE, voice_message_handler))
app.add_handler(MessageHandler(filters.TEXT, message_handler))


def run():
    app.run_polling()
