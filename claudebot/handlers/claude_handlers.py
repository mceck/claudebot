import os
import httpx
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes,
)
from claudebot.tools.claude import Claude
from claudebot.settings import settings
from claudebot.tools.auth import authenticated
from claudebot.tools.messages import send_message
from claudebot.tools.context import ctx


async def process_claude_prompt(message: str):
    if not ctx.current_project:
        raise ValueError("No project selected. Please select a project using /select.")
    claude_session = Claude(os.path.join(settings.projects_dir, ctx.current_project))
    ctx.claude_sessions[ctx.current_project] = claude_session
    resume_session = not message.startswith("!")
    if not resume_session:
        message = message[1:]
    plan_mode = message.startswith("?")
    if plan_mode:
        message = message[1:]
    ret, resp = await claude_session.send(
        message, resume_session=resume_session, plan_mode=plan_mode
    )
    ctx.claude_sessions.pop(ctx.current_project, None)
    if ret != 0:
        print(f"Claude process exited with code {ret}")
    return resp.strip()


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
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    claude_session = ctx.claude_sessions.get(ctx.current_project)
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
async def kill_claude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    project = context.args[0] if context.args else None

    if project:
        claude_session = ctx.claude_sessions.pop(project, None)
        if claude_session:
            await claude_session.kill()
            await send_message(update, context, f"Claude session for *{project}* killed successfully.", parse_mode="Markdown")
        else:
            await send_message(update, context, f"No active Claude session for *{project}*.", parse_mode="Markdown")
        return

    active_sessions = list(ctx.claude_sessions.keys())
    if not active_sessions:
        await send_message(update, context, "No active Claude sessions to kill.")
        return

    keyboard = [
        [InlineKeyboardButton(proj, callback_data=f"kill_{proj}")]
        for proj in active_sessions
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, context, "Select a session to kill:", reply_markup=reply_markup)


@authenticated
async def select_session_to_kill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    option = query.data or ""
    if option.startswith("kill_"):
        project = option.split("_", 1)[1]
        await query.edit_message_text(text=f"Killing session: {project}")
        context.args = [project]
        await kill_claude(update, context)

@authenticated
async def get_active_claude_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    active_sessions = list(ctx.claude_sessions.keys())
    if active_sessions:
        session_list = "\n".join(f"- {proj}" for proj in active_sessions)
        await send_message(
            update,
            context,
            f"Active Claude sessions for projects:\n{session_list}",
            parse_mode="Markdown",
        )
    else:
        await send_message(update, context, "No active Claude sessions found.")

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
