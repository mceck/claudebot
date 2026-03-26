import os
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes
from codebot.tools.shell import run_command
from codebot.settings import settings
from codebot.tools.auth import authenticated
from codebot.tools.bot import send_message, build_keyboard
from codebot.tools.context import ctx


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
            output,
            parse_mode="Markdown",
            chunk_wrap=("```\n", "\n```"),
        )
    else:
        await send_message(
            update, context, output, parse_mode="Markdown",
            chunk_wrap=("```\n", "\n```"),
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
            output,
            parse_mode="Markdown",
            chunk_wrap=("```\n", "\n```"),
        )
    else:
        if output.strip():
            await send_message(
                update, context, output, parse_mode="Markdown",
                chunk_wrap=("```diff\n", "\n```"),
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
        repo_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
        reply_markup = build_keyboard([
            InlineKeyboardButton(
                f"📂 Select {repo_name}",
                callback_data=f"selectproject_{repo_name}",
            )
        ])
        await send_message(
            update, context, f"Git clone successful:\n{output}",
            reply_markup=reply_markup,
        )


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
        ret_code, output = await run_command("git branch --show-current", cwd=project_path)

        if ret_code != 0:
            await send_message(update, context, f"Failed to get current branch:\n{output}")
            return

        current_branch = output.strip()
        if not current_branch:
            await send_message(update, context, "No current branch found (detached HEAD?).")
            return

        reply_markup = build_keyboard([
            InlineKeyboardButton("Yes", callback_data=f"gpush_{current_branch}"),
            InlineKeyboardButton("No", callback_data="gpush_no"),
        ])
        await send_message(
            update, context, f"Push branch `{current_branch}` to origin?", reply_markup=reply_markup
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
        'git commit -m "Update from codebot"', cwd=project_path
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

        reply_markup = build_keyboard([
            InlineKeyboardButton(branch, callback_data=f"gco_{branch}")
            for branch in branches
        ])
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
async def git_delete_branch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            if line.strip() and not line.strip().startswith("*")
        ]

        if not branches:
            await send_message(update, context, "No branches available for deletion.")
            return

        reply_markup = build_keyboard([
            InlineKeyboardButton(branch, callback_data=f"gdel_{branch}")
            for branch in branches
        ])
        await send_message(
            update, context, "Select branch to delete:", reply_markup=reply_markup
        )
        return

    ret_code, output = await run_command(f"git branch -d {branch}", cwd=project_path)

    if ret_code != 0:
        await send_message(
            update, context, f"Git branch delete failed with code {ret_code}:\n{output}"
        )
    else:
        await send_message(update, context, f"Branch *{branch}* deleted successfully.", parse_mode="Markdown")


@authenticated
async def git_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.current_project:
        await send_message(
            update, context,
            "No project selected. Please select a project using /select.",
        )
        return
    project_path = os.path.join(settings.projects_dir, ctx.current_project)
    if not os.path.exists(project_path):
        await send_message(
            update, context, f"Project directory not found: {ctx.current_project}"
        )
        return

    ret_code, output = await run_command(
        'git log -10 --format="%h|%an|%s|%ad" --date=format:"%d/%m %H:%M"',
        cwd=project_path,
    )
    if ret_code != 0:
        await send_message(update, context, f"Failed to get history:\n{output}")
        return

    lines = [l for l in output.strip().split("\n") if l.strip()]
    if not lines:
        await send_message(update, context, "No commits found.")
        return

    buttons = []
    for line in lines:
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        sha, author, message, date = parts
        label = f"{date} - {author} - {message}"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append(
            InlineKeyboardButton(label, callback_data=f"ghist_{sha}")
        )

    reply_markup = InlineKeyboardMarkup([[b] for b in buttons])
    await send_message(
        update, context, f"📋 Last commits ({ctx.current_project}):",
        reply_markup=reply_markup,
    )


@authenticated
async def git_history_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    sha = (query.data or "").split("_", 1)[1]

    if not ctx.current_project:
        await query.edit_message_text("No project selected.")
        return
    project_path = os.path.join(settings.projects_dir, ctx.current_project)

    await query.edit_message_text(f"Loading diff for {sha}...")

    ret_code, output = await run_command(
        f"git show --stat --patch {sha}", cwd=project_path
    )
    if ret_code != 0:
        await send_message(update, context, f"Failed to get diff:\n{output}")
        return

    if output.strip():
        await send_message(
            update, context, output, parse_mode="Markdown",
            chunk_wrap=("```diff\n", "\n```"),
        )
    else:
        await send_message(update, context, "Empty diff.")


@authenticated
async def select_branch_for_checkout(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    option = query.data or "_"
    if option == "gpush_no":
        await query.edit_message_text(text="Push cancelled.")
    elif option.startswith("gpush_") or option.startswith("gco_") or option.startswith("gdel_"):
        branch = option.split("_", 1)[1]
        context.args = [branch]
        if option.startswith("gco_"):
            await query.edit_message_text(text=f"Checking out branch: {branch}")
            await git_checkout(update, context)
        elif option.startswith("gdel_"):
            await query.edit_message_text(text=f"Deleting branch: {branch}")
            await git_delete_branch(update, context)
        else:
            await query.edit_message_text(text=f"Pushing branch: {branch}")
            await git_push(update, context)
    else:
        await query.edit_message_text(text="Unknown option selected.")
