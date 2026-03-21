import os
import traceback
from telegram import (
    Update,
    InlineKeyboardButton,
)
from telegram.ext import ContextTypes
from telegram.error import NetworkError, BadRequest, TimedOut
from codebot.tools.shell import run_command
from codebot.settings import settings
from codebot.tools.auth import authenticated
from codebot.tools.bot import send_message, build_keyboard
from codebot.tools.context import ctx


@authenticated
async def greet_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_message(
        update,
        context,
        "Hello! I am codebot, your assistant for managing Claude sessions and projects. Use /select to choose a project to work on.",
    )


@authenticated
async def pick_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        projects = [
            d
            for d in os.listdir(settings.projects_dir)
            if os.path.isdir(os.path.join(settings.projects_dir, d))
            and not d.startswith(".")
            and not d.startswith("_")
        ]
        if projects:
            reply_markup = build_keyboard([
                InlineKeyboardButton(
                    project, callback_data=f"selectproject_{project}"
                )
                for project in projects
            ])
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
    ctx.set_current_project(context.args[0])
    ret_code, output = await run_command(
        "git rev-parse --abbrev-ref HEAD",
        cwd=os.path.join(settings.projects_dir, ctx.current_project),  # type: ignore
    )
    current_branch = output.strip() if ret_code == 0 else "unknown branch"
    await send_message(
        update,
        context,
        f"Session started successfully with project:\n*{ctx.current_project}* on branch *{current_branch}*",
        parse_mode="Markdown",
    )


@authenticated
async def get_current_project(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if ctx.current_project:
        ret_code, output = await run_command(
            "git rev-parse --abbrev-ref HEAD",
            cwd=os.path.join(settings.projects_dir, ctx.current_project),
        )
        current_branch = output.strip() if ret_code == 0 else "unknown branch"
        await send_message(
            update,
            context,
            f"*{ctx.current_project}* on branch *{current_branch}*",
            parse_mode="Markdown",
        )
    else:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )


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
            MAX_MSG_LEN = 4000

            error_type = type(context.error).__name__ if context.error else "Unknown"
            error_str = str(context.error) if context.error else "No details"

            error_message = (
                f"Error: {error_type}\n"
                f"Details: {error_str}\n"
            )

            if isinstance(context.error, NetworkError):
                error_message += "\nThis appears to be a network issue. Please try again."
            elif isinstance(context.error, TimedOut):
                error_message += "\nThe request timed out. Please try again."

            if context.error and context.error.__traceback__:
                error_message += "\n\nStacktrace:\n"
                remaining = MAX_MSG_LEN - len(error_message) - 10
                if remaining > 0:
                    error_message += tb_string[-remaining:]

            if len(error_message) > MAX_MSG_LEN:
                error_message = error_message[:MAX_MSG_LEN]

            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=error_message
                )
    except Exception as e:
        print(f"Failed to send error message to user: {e}")
