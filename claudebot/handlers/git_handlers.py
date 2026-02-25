import os
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes
from claudebot.tools.shell import run_command
from claudebot.settings import settings
from claudebot.tools.auth import authenticated
from claudebot.tools.messages import send_message
from claudebot.tools.context import ctx


@authenticated
async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, ctx.current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {ctx.current_project}"
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
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, ctx.current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {ctx.current_project}"
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
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, ctx.current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {ctx.current_project}"
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
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, ctx.current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {ctx.current_project}"
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
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, ctx.current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {ctx.current_project}"
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
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, ctx.current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {ctx.current_project}"
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
