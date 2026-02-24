import os
import httpx
import traceback
from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.error import NetworkError, BadRequest, TimedOut
from claudebot.claude import Claude
from claudebot.shell import run_command
from claudebot.settings import settings

claude_sessions: dict[str, Claude] = {}
current_project: str | None = None


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
        BotCommand("kill", "Kill the current Claude session"),
        BotCommand("checklogin", "Check if the bot is logged in to Claude"),
    ]
    await application.bot.set_my_commands(commands)


async def send_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str, **kwargs
):
    MAX_MESSAGE_LENGTH = 4096

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


async def check_user(context: ContextTypes.DEFAULT_TYPE) -> bool:
    allowed_user_ids = settings.ALLOWED_USER_IDS
    if context._user_id not in allowed_user_ids:
        try:
            await context.bot.send_message(
                chat_id=allowed_user_ids[0],
                text=f"Unauthorized access attempt by user ID: {context._user_id}",
            )
        except Exception as e:
            print(f"Failed to send unauthorized access message: {e}")
        return False
    return True


def authenticated(func):
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ):
        if not await check_user(context):
            await send_message(
                update, context, "Unauthorized access. This incident has been reported."
            )
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


@authenticated
async def greet_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_message(
        update,
        context,
        "Hello! I am ClaudeBot, your assistant for managing Claude sessions and projects. Use /select to choose a project to work on.",
    )


@authenticated
async def check_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_logged_in = await Claude.check_login()
    if is_logged_in:
        await send_message(update, context, "You are logged in to Claude.")
    else:
        await send_message(
            update,
            context,
            "You are not logged in to Claude. Please review your credentials.",
        )


@authenticated
async def pick_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_project
    if not context.args:
        projects = [
            d
            for d in os.listdir(settings.projects_dir)
            if os.path.isdir(os.path.join(settings.projects_dir, d))
            and not d.startswith(".")
            and not d.startswith("_")
        ]
        if projects:
            keyboard = [
                [
                    InlineKeyboardButton(
                        project, callback_data=f"selectproject_{project}"
                    )
                ]
                for project in projects
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_message(
                update, context, "Pick a project:", reply_markup=reply_markup
            )
        else:
            await send_message(
                update,
                context,
                "No projects found. Clone a new project using /gclone command",
            )
        return
    if not context.args:
        await send_message(
            update,
            context,
            "Please specify a project name. Usage: /select <project_name>",
        )
        return
    current_project = context.args[0]
    ret_code, output = await run_command(
        "git rev-parse --abbrev-ref HEAD",
        cwd=os.path.join(settings.projects_dir, current_project),
    )
    current_branch = output.strip() if ret_code == 0 else "unknown branch"
    await send_message(
        update,
        context,
        f"Session started successfully with project:\n*{current_project}* on branch *{current_branch}*",
        parse_mode="Markdown",
    )


@authenticated
async def get_current_project(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if current_project:
        ret_code, output = await run_command(
            "git rev-parse --abbrev-ref HEAD",
            cwd=os.path.join(settings.projects_dir, current_project),
        )
        current_branch = output.strip() if ret_code == 0 else "unknown branch"
        await send_message(
            update,
            context,
            f"*{current_project}* on branch *{current_branch}*",
            parse_mode="Markdown",
        )
    else:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )


async def process_claude_prompt(message: str):
    if not current_project:
        raise ValueError("No project selected. Please select a project using /select.")
    claude_session = Claude(os.path.join(settings.projects_dir, current_project))
    claude_sessions[current_project] = claude_session
    resume_session = not message.startswith("!")
    if not resume_session:
        message = message[1:]
    plan_mode = message.startswith("?")
    if plan_mode:
        message = message[1:]
    ret, resp = await claude_session.send(
        message, resume_session=resume_session, plan_mode=plan_mode
    )
    claude_sessions.pop(current_project, None)
    if ret != 0:
        print(f"Claude process exited with code {ret}")
    return resp.strip()

@authenticated
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    claude_session = claude_sessions.get(current_project)
    if claude_session:
        await send_message(
            update,
            context,
            "A Claude session is already processing a message. Please wait for it to finish before sending another message.",
        )
        return
    if update.message and update.message.text:
        await send_message(update, context, "Processing your message...")
        resp = await process_claude_prompt(update.message.text)
        await send_message(
            update,
            context,
            resp or "No response received from Claude.",
            parse_mode="Markdown",
        )
    else:
        await send_message(update, context, "No message found.")


@authenticated
async def select_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    option = query.data or "_"
    if option.startswith("selectproject_"):
        project_name = option[len("selectproject_") :]
        context.args = [project_name]
        await query.edit_message_text(
            text=f"Starting Claude with project: {project_name}"
        )
        await pick_project(update, context)
    else:
        await query.edit_message_text(text="Unknown option selected.")


@authenticated
async def kill_claude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    claude_session = claude_sessions.pop(current_project, None)
    if claude_session:
        await claude_session.kill()
        await send_message(update, context, "Claude session killed successfully.")
    else:
        await send_message(update, context, "No active Claude session to kill.")


@authenticated
async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {current_project}"
        )
        return

    ret_code, output = await run_command("git status", cwd=project_path)

    if ret_code != 0:
        await send_message(
            update,
            context,
            f"Git status failed with code {ret_code}:\n```\n{output}\n```",
            parse_mode="Markdown",
        )
    else:
        await send_message(
            update, context, f"```\n{output}\n```", parse_mode="Markdown"
        )


@authenticated
async def git_diff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {current_project}"
        )
        return

    ret_code, output = await run_command("git diff", cwd=project_path)

    if ret_code != 0:
        await send_message(
            update,
            context,
            f"Git diff failed with code {ret_code}:\n```\n{output}\n```",
            parse_mode="Markdown",
        )
    else:
        if output.strip():
            await send_message(
                update, context, f"```diff\n{output}\n```", parse_mode="Markdown"
            )
        else:
            await send_message(update, context, "No changes detected.")


@authenticated
async def git_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {current_project}"
        )
        return

    ret_code, output = await run_command("git reset --hard", cwd=project_path)

    if ret_code != 0:
        await send_message(
            update, context, f"Git reset failed with code {ret_code}:\n{output}"
        )
    else:
        _, output_clean = await run_command("git clean -fd", cwd=project_path)
        output += "\n" + output_clean
        ret_code_pull, output_pull = await run_command(
            "git pull --rebase", cwd=project_path
        )
        output += "\n" + output_pull
        if ret_code_pull != 0:
            await send_message(
                update,
                context,
                f"Git pull failed with code {ret_code_pull}:\n{output_pull}",
            )
        else:
            await send_message(update, context, f"Git reset successful:\n{output}")


@authenticated
async def git_clone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo_url = " ".join(context.args) if context.args else None
    if not repo_url:
        await send_message(
            update,
            context,
            "Please specify a repository URL. Usage: /gclone <repo_url>",
        )
        return

    if not repo_url.startswith("https://") and not repo_url.startswith("git@"):
        repo_url = f"git@github.com:{repo_url}"

    ret_code, output = await run_command(
        f"git clone {repo_url}", cwd=settings.projects_dir
    )

    if ret_code != 0:
        await send_message(
            update, context, f"Git clone failed with code {ret_code}:\n{output}"
        )
    else:
        await send_message(update, context, f"Git clone successful:\n{output}")


@authenticated
async def git_push(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {current_project}"
        )
        return

    branch = " ".join(context.args) if context.args else None

    if not branch:
        ret_code, output = await run_command("git branch", cwd=project_path)

        if ret_code != 0:
            await send_message(update, context, f"Failed to get branches:\n{output}")
            return

        branches = [
            line.strip().lstrip("* ")
            for line in output.strip().split("\n")
            if line.strip()
        ]

        if not branches:
            await send_message(update, context, "No branches found in the repository.")
            return

        keyboard = [
            [InlineKeyboardButton(branch, callback_data=f"gpush_{branch}")]
            for branch in branches
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_message(
            update, context, "Select branch to push:", reply_markup=reply_markup
        )
        return

    ret_code, output = await run_command("git branch --show-current", cwd=project_path)
    if ret_code != 0:
        await send_message(update, context, f"Failed to get current branch:\n{output}")
        return

    current_branch = output.strip()

    if current_branch != branch:
        ret_code, output = await run_command(
            f"git checkout -b {branch}", cwd=project_path
        )
        if ret_code != 0:
            await send_message(update, context, f"Failed to create branch:\n{output}")
            return

    ret_add, output_add = await run_command("git add .", cwd=project_path)
    if ret_add != 0:
        print(f"Git add failed with code {ret_add}:\n{output_add}")
    ret_commit, output_commit = await run_command(
        'git commit -m "Update from ClaudeBot"', cwd=project_path
    )
    if ret_commit != 0:
        print(f"Git commit failed with code {ret_commit}:\n{output_commit}")
    ret_code, output = await run_command(
        f"git push -u origin {branch}", cwd=project_path
    )

    if ret_code != 0:
        await send_message(
            update, context, f"Git push failed with code {ret_code}:\n{output}"
        )
    else:
        await send_message(update, context, f"Git push successful:\n{output}")


@authenticated
async def git_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {current_project}"
        )
        return

    ret_code, output = await run_command("git fetch", cwd=project_path)

    if ret_code != 0:
        await send_message(
            update, context, f"Git fetch failed with code {ret_code}:\n{output}"
        )
    else:
        await send_message(update, context, f"Git fetch successful:\n{output}")


@authenticated
async def git_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {current_project}"
        )
        return

    branch = " ".join(context.args) if context.args else None

    if not branch:
        ret_code, output = await run_command("git branch", cwd=project_path)

        if ret_code != 0:
            await send_message(update, context, f"Failed to get branches:\n{output}")
            return

        branches = [
            line.strip().lstrip("* ")
            for line in output.strip().split("\n")
            if line.strip()
        ]

        if not branches:
            await send_message(update, context, "No branches found in the repository.")
            return

        keyboard = [
            [InlineKeyboardButton(branch, callback_data=f"gco_{branch}")]
            for branch in branches
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_message(
            update, context, "Select branch to checkout:", reply_markup=reply_markup
        )
        return

    ret_code, output = await run_command(f"git checkout {branch}", cwd=project_path)

    if ret_code != 0:
        ret_code, output = await run_command(
            f"git checkout -b {branch}", cwd=project_path
        )
        if ret_code != 0:
            await send_message(
                update, context, f"Git checkout failed with code {ret_code}:\n{output}"
            )
            return
        else:
            await send_message(update, context, f"New branch created:\n{output}")
    else:
        ret_code_pull, output_pull = await run_command("git pull", cwd=project_path)
        output += "\n" + output_pull
        if ret_code_pull != 0:
            await send_message(
                update,
                context,
                f"Git pull failed with code {ret_code_pull}:\n{output_pull}",
            )
        else:
            await send_message(update, context, f"Git checkout successful:\n{output}")


@authenticated
async def select_branch_for_checkout(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    option = query.data or "_"
    if option.startswith("gpush_") or option.startswith("gco_"):
        branch = option.split("_", 1)[1]
        context.args = [branch]
        if option.startswith("gco_"):
            await query.edit_message_text(text=f"Checking out branch: {branch}")
            await git_checkout(update, context)
        else:
            await query.edit_message_text(text=f"Pushing branch: {branch}")
            await git_push(update, context)
    else:
        await query.edit_message_text(text="Unknown option selected.")


@authenticated
async def voice_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.message.voice:
        await send_message(update, context, "No voice message found.")
        return
    if context.user_data is None:
        await send_message(update, context, "User data not available.")
        return
    if not settings.MISTRAL_API_KEY:
        await send_message(
            update,
            context,
            "Mistral API key not configured. Please set MISTRAL_API_KEY in the settings.",
        )
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    file_bytes = await file.download_as_bytearray()
    files = {
        "file": (f"{update.message.voice.file_id}.ogg", bytes(file_bytes), "audio/ogg")
    }
    data = {
        "model": "voxtral-mini-latest",
        "language": settings.TRANSCRIPTION_LANGUAGE,
        "context_bias": "coding",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.mistral.ai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.MISTRAL_API_KEY}"},
            data=data,
            files=files,
            timeout=60,
        )
        if response.status_code != 200:
            await send_message(
                update,
                context,
                f"Mistral API error {response.status_code}: {response.text}",
            )
            return
        transcription = response.json().get("text", "").strip()
        context.user_data["pending_transcription"] = transcription
        await send_message(
            update,
            context,
            transcription or "No transcription received from Mistral.",
            reply_markup=(
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Send to Claude",
                                callback_data="transcription_to_claude",
                            )
                        ]
                    ]
                )
                if transcription
                else None
            ),
        )


@authenticated
async def transcription_to_claude_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not context.user_data:
        await send_message(update, context, "No transcription found to send to Claude.")
        return
    transcription = context.user_data.pop("pending_transcription", None)
    if not transcription:
        await send_message(update, context, "No transcription found to send to Claude.")
        return
    if not update.callback_query:
        return
    await update.callback_query.answer()
    await send_message(update, context, "Processing message with Claude...")
    resp = await process_claude_prompt(transcription)
    await send_message(
        update,
        context,
        resp or "No response received from Claude.",
        parse_mode="Markdown",
    )


@authenticated
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Exception while handling an update:\n{context.error}")

    if context.error:
        tb_list = traceback.format_exception(
            type(context.error), context.error, context.error.__traceback__
        )
        tb_string = "".join(tb_list)

        print(f"Traceback:\n{tb_string}")

    try:
        if isinstance(update, Update) and update.effective_message:
            error_message = (
                "An error occurred while processing your request.\n"
                f"Error: {type(context.error).__name__}"
            )

            if isinstance(context.error, NetworkError):
                error_message += (
                    "\n\nThis appears to be a network issue. Please try again."
                )
            elif isinstance(context.error, TimedOut):
                error_message += "\n\nThe request timed out. Please try again."
            elif isinstance(context.error, BadRequest):
                error_message += f"\n\nDetails: {str(context.error)}"

            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=error_message
                )
    except Exception as e:
        print(f"Failed to send error message to user: {e}")


app = (
    ApplicationBuilder()
    .token(settings.TELEGRAM_BOT_TOKEN)
    .post_init(setup_commands)
    .build()
)

app.add_error_handler(error_handler)

app.add_handler(CommandHandler("start", greet_user))
app.add_handler(CommandHandler("select", pick_project))
app.add_handler(CommandHandler("current", get_current_project))
app.add_handler(CommandHandler("kill", kill_claude))
app.add_handler(CommandHandler("gstat", git_status))
app.add_handler(CommandHandler("gdiff", git_diff))
app.add_handler(CommandHandler("greset", git_reset))
app.add_handler(CommandHandler("gclone", git_clone))
app.add_handler(CommandHandler("gpush", git_push))
app.add_handler(CommandHandler("gfetch", git_fetch))
app.add_handler(CommandHandler("gco", git_checkout))
app.add_handler(CommandHandler("checklogin", check_login))
app.add_handler(CallbackQueryHandler(select_project, pattern="^selectproject_"))
app.add_handler(
    CallbackQueryHandler(select_branch_for_checkout, pattern="^(gco_|gpush_)")
)
app.add_handler(
    CallbackQueryHandler(
        transcription_to_claude_handler, pattern="^transcription_to_claude$"
    )
)
app.add_handler(MessageHandler(filters.VOICE, voice_message_handler))
app.add_handler(MessageHandler(filters.TEXT, message_handler))


def run():
    app.run_polling()
