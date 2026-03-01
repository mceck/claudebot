import os
import traceback
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes
from telegram.error import NetworkError, BadRequest, TimedOut
from claudebot.tools.shell import run_command
from claudebot.settings import settings
from claudebot.tools.auth import authenticated
from claudebot.tools.bot import send_message
from claudebot.tools.context import ctx


@authenticated
async def greet_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_message(
        update,
        context,
        "Hello! I am ClaudeBot, your assistant for managing Claude sessions and projects. Use /select to choose a project to work on.",
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
