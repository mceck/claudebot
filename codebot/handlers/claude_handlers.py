import asyncio
import os
import re
import httpx
from datetime import datetime, timedelta
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes,
)
from apscheduler.triggers.date import DateTrigger
from codebot.tools.claude import Claude
from codebot.tools.logger import log_claude_response, log_session_event, get_session_events, get_recent_sessions, get_claude_session_id, get_events_by_group
from codebot.tools.shell import run_command
from codebot.settings import settings
from codebot.tools.auth import authenticated
from codebot.tools.bot import send_message, send_direct_message, build_keyboard, app as bot_app
from codebot.tools.context import ctx
from codebot.tools.scheduler import scheduler



def _build_processing_status(message: str, project: str | None = None) -> str:
    prefix_parts = []
    msg = message
    cleared = msg.startswith("!")
    if cleared:
        prefix_parts.append("[CLEARED]")
        msg = msg[1:]
    if msg.startswith("?"):
        prefix_parts.append("[PLAN]")
    if not cleared and project and project in ctx.resume_claude_session_id:
        prefix_parts.append("[RESUME]")
    prefix = " ".join(prefix_parts)
    status = f"{prefix} Processing..." if prefix else "Processing..."
    return f"{status}\n\n💡 Use /stream to follow the progress live."


async def process_claude_prompt(message: str, project: str):
    claude_session = Claude(os.path.join(settings.projects_dir, project))
    ctx.claude_sessions[project] = claude_session
    resume_session = not message.startswith("!")
    if not resume_session:
        message = message[1:]
    plan_mode = message.startswith("?")
    if plan_mode:
        message = message[1:]

    async def on_event(session_uuid, claude_session_id, event_type, content):
        await log_session_event(
            session_uuid=session_uuid,
            claude_session_id=claude_session_id,
            project=project,
            prompt=message,
            event_type=event_type,
            content=content,
        )

    resume_session_id = ctx.resume_claude_session_id.pop(project, None)
    if not resume_session:
        resume_session_id = None

    try:
        ret, resp = await claude_session.send(
            message, resume_session=resume_session, plan_mode=plan_mode,
            on_event=on_event, resume_session_id=resume_session_id,
        )
    finally:
        ctx.claude_sessions.pop(project, None)
    if ret != 0:
        print(f"Claude process exited with code {ret}")
    return resp.strip()

async def process_claude_prompt_and_answer(chat_id: int, message: str, project: str | None = None):
    current_project = project or ctx.current_project
    if not current_project:
        raise ValueError("No project selected. Please select a project using /select.")
    resp = await process_claude_prompt(message, current_project)
    reply_markup = None
    if "You've hit your limit" in resp:
        ts_match = re.search(r"resets (\d+)(am|pm)", resp, re.IGNORECASE)
        if ts_match:
            hour = int(ts_match.group(1))
            period = ts_match.group(2).lower()
            
            # 24-hour format
            if period == "am":
                if hour == 12:
                    hour = 0
            else:  # pm
                if hour != 12:
                    hour += 12
            
            time_str = f"{hour:02d}:00"
            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Schedule continue", callback_data=f"schedule_continue_{time_str}")]]
            )
    await send_direct_message(
        chat_id,
        resp or "No response received from Claude.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    await log_claude_response(current_project, resp)

    # Process next queued message if any
    await _run_queued_message(current_project)

    return resp


async def scheduled_process_claude_prompt_and_answer(chat_id: int, message: str, project: str | None = None):
    """Wrapper for scheduled jobs: sends a notification before processing."""
    preview = message[:50] + "..." if len(message) > 50 else message
    status = _build_processing_status(message)
    await send_direct_message(chat_id, f"⏰ Running scheduled task: _{preview}_\n\n{status}", parse_mode="Markdown")
    return await process_claude_prompt_and_answer(chat_id, message, project)


@authenticated
async def check_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    resp = await Claude.check_login()
    if resp.logged_in:
        await send_message(update, context, f"You are logged in to Claude with: *{resp.email or resp.auth_method}*", parse_mode="Markdown")
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
        if ctx.queued_messages.get(ctx.current_project):
            await send_message(
                update, context,
                "A message is already queued for this project. Use /deljob to cancel it first.",
            )
            return
        if update.message and update.message.text:
            ctx.pending_queue[ctx.current_project] = {
                "chat_id": update.message.chat_id,
                "message": update.message.text,
            }
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Yes", callback_data=f"queue_yes_{ctx.current_project}"),
                InlineKeyboardButton("No", callback_data=f"queue_no_{ctx.current_project}"),
            ]])
            preview = update.message.text[:50] + "..." if len(update.message.text) > 50 else update.message.text
            await send_message(
                update, context,
                f"A session is already active. Queue this message to run after the current one finishes?\n\n_{preview}_",
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        return
    if update.message and update.message.text:
        await send_message(update, context, _build_processing_status(update.message.text, ctx.current_project))
        await process_claude_prompt_and_answer(update.message.chat_id, update.message.text)

    else:
        await send_message(update, context, "No message found.")


@authenticated
async def queue_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data.startswith("queue_yes_"):
        project = data[10:]
        pending = ctx.pending_queue.pop(project, None)
        if not pending:
            await query.edit_message_text("No pending message to queue.")
            return
        # If session already finished, run immediately
        if project not in ctx.claude_sessions:
            await query.edit_message_text("Session completed. Running message now...")
            status = _build_processing_status(pending["message"], project)
            await send_direct_message(pending["chat_id"], status, parse_mode="Markdown")
            await process_claude_prompt_and_answer(pending["chat_id"], pending["message"], project)
            return
        ctx.queued_messages[project] = pending
        preview = pending["message"][:50] + "..." if len(pending["message"]) > 50 else pending["message"]
        await query.edit_message_text(
            f"Message queued for *{project}*: _{preview}_\n\nUse /deljob to cancel.",
            parse_mode="Markdown",
        )

    elif data.startswith("queue_no_"):
        project = data[9:]
        ctx.pending_queue.pop(project, None)
        await query.edit_message_text("Message not queued.")


async def _run_queued_message(project: str):
    """Check and run the next queued message for a project after session completes."""
    queued = ctx.queued_messages.pop(project, None)
    if not queued:
        return
    preview = queued["message"][:50] + "..." if len(queued["message"]) > 50 else queued["message"]
    status = _build_processing_status(queued["message"], project)
    await send_direct_message(
        queued["chat_id"],
        f"▶️ Running queued message: _{preview}_\n\n{status}",
        parse_mode="Markdown",
    )
    await process_claude_prompt_and_answer(queued["chat_id"], queued["message"], project)


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

    reply_markup = build_keyboard([
        InlineKeyboardButton(proj, callback_data=f"kill_{proj}")
        for proj in active_sessions
    ])
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
    active_sessions = list(ctx.claude_sessions.items())
    if active_sessions:
        buttons = []
        for proj, cs in active_sessions:
            label = proj
            if cs.prompt:
                preview = cs.prompt[:30] + "..." if len(cs.prompt) > 30 else cs.prompt
                label = f"{proj}: {preview}"
            buttons.append(
                InlineKeyboardButton(label, callback_data=f"slog_{proj}")
            )
        reply_markup = build_keyboard(buttons)
        await send_message(
            update,
            context,
            "Active Claude sessions:",
            reply_markup=reply_markup,
        )
    else:
        await send_message(update, context, "No active Claude sessions found.")


@authenticated
async def show_session_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data.startswith("slog_"):
        # Active session: lookup by project name
        proj = data[5:]
        cs = ctx.claude_sessions.get(proj)
        if not cs:
            await query.edit_message_text(f"Session for {proj} not found or already completed.")
            return
        events = await get_session_events(cs.session_uuid)
        prompt = cs.prompt
        project = proj
    elif data.startswith("hslog_"):
        # Historical session: show all linked sessions
        partial_key = data[6:]
        recent = await get_recent_sessions(limit=50)
        target = next((s for s in recent if s["group_key"].startswith(partial_key)), None)
        if not target:
            await query.edit_message_text("Session not found.")
            return
        events = await get_events_by_group(target["group_key"])
        project = target["project"]
        prompt = target.get("prompt", "")
    else:
        return

    if not events:
        await query.edit_message_text(
            f"No events logged yet for session: {project or 'unknown'}"
        )
        return

    lines = []
    if project:
        lines.append(f"*Session:* {project}")
    if prompt:
        preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
        lines.append(f"*Prompt:* _{preview}_")
    lines.append("")

    prev_session_uuid = None
    for event in events:
        # Show separator when session_uuid changes (resumed sessions)
        session_uuid = event.get("session_uuid")
        if session_uuid and session_uuid != prev_session_uuid and prev_session_uuid is not None:
            event_prompt = event.get("prompt", "")
            resume_preview = event_prompt[:60] + "..." if event_prompt and len(event_prompt) > 60 else (event_prompt or "")
            lines.append(f"\n--- *Resume:* _{resume_preview}_ ---\n")
        prev_session_uuid = session_uuid

        ts = event["created_at"].strftime("%H:%M:%S") if event.get("created_at") else ""
        etype = event.get("event_type", "")
        content = event.get("content", "")

        if etype == "assistant":
            lines.append(f"`[{ts}]` {content}")
        elif etype == "tool_use":
            lines.append(f"`[{ts}]` *Tools:* {content}")
        elif etype == "result":
            lines.append(f"`[{ts}]` *Done* ({content})")
        else:
            lines.append(f"`[{ts}]` {etype}: {content}")

    text = "\n".join(lines)
    chat_id = query.message.chat_id if query.message else None
    if not chat_id:
        return
    await query.edit_message_text("Session log:")
    await send_direct_message(chat_id, text, parse_mode="Markdown")


@authenticated
async def resume_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    partial_key = data[6:]  # strip "hsres_"

    recent = await get_recent_sessions(limit=50)
    target = next((s for s in recent if s["group_key"].startswith(partial_key)), None)
    if not target:
        await query.edit_message_text("Session not found.")
        return
    project = target["project"] or ctx.current_project
    if not project:
        await query.edit_message_text("Could not determine the project for this session.")
        return
    claude_sid = target.get("claude_session_id")
    if not claude_sid:
        await query.edit_message_text("Could not find Claude session ID for this session.")
        return
    prompt_preview = target["prompt"][:60] + "..." if target.get("prompt") and len(target["prompt"]) > 60 else (target.get("prompt", "") or "")

    if project != ctx.current_project:
        ctx.pending_recovery = {
            "claude_sid": claude_sid,
            "project": project,
            "prompt_preview": prompt_preview,
        }
        await query.edit_message_text(
            f"This session belongs to *{project}* but current project is *{ctx.current_project}*.\n"
            f"Switch project and recover session?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Yes", callback_data="recover_yes"),
                InlineKeyboardButton("No", callback_data="recover_no"),
            ]]),
        )
        return

    ctx.resume_claude_session_id[project] = claude_sid
    await query.edit_message_text(
        f"Session recovered for *{project}*\n"
        f"_{prompt_preview}_",
        parse_mode="Markdown",
    )


@authenticated
async def get_last_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sessions = await get_recent_sessions(limit=10)
    if not sessions:
        await send_message(update, context, "No session history found.")
        return

    for s in reversed(sessions):
        proj = s.get("project", "?")
        prompt = s.get("prompt", "")
        ts = s["last_event"].strftime("%d/%m %H:%M") if s.get("last_event") else ""
        preview = prompt[:120] + "..." if prompt and len(prompt) > 120 else (prompt or "-")
        gk = s["group_key"][:53]
        text = f"*{proj}*\n{preview}\n_{ts}_"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Log", callback_data=f"hslog_{gk}"),
                InlineKeyboardButton("Resume", callback_data=f"hsres_{gk}"),
            ]
        ])
        await send_message(update, context, text, reply_markup=keyboard, parse_mode="Markdown")

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
    if not update.callback_query.message:
        await send_message(update, context, "No message found to reply to.")
        return
    await update.callback_query.edit_message_reply_markup(reply_markup=None)
    await send_message(update, context, _build_processing_status(transcription))
    await process_claude_prompt_and_answer(update.callback_query.message.chat.id, transcription, ctx.current_project)


@authenticated
async def clear_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    cmd = 'ls -t ~/.claude/projects/$(echo $PWD | sed "s|/|-|g")/*.jsonl 2>/dev/null | head -1 | xargs rm -f'
    await run_command(cmd, cwd=os.path.join(settings.projects_dir, ctx.current_project))
    await send_message(update, context, "Claude session cleared successfully.")

@authenticated
async def schedule_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ctx.current_project:
        await send_message(
            update,
            context,
            "No project selected. Please select a project using /select.",
        )
        return
    if not update.message or not update.message.text:
        await send_message(update, context, "No message found to schedule.")
        return
    parts = update.message.text.split(maxsplit=2)
    if len(parts) < 3:
        await send_message(update, context, "Invalid command format. Use: /schedule <hh[:mm]> <message>")
        return
    try:
        time_parts = parts[1].split(":")
        if len(time_parts) == 1:
            hour = int(time_parts[0])
            minute = 0
        elif len(time_parts) == 2:
            hour = int(time_parts[0])
            minute = int(time_parts[1])
        else:
            raise ValueError("Invalid time format")
        
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Hour must be 0-23 and minute must be 0-59")
    except ValueError as e:
        await send_message(update, context, f"Invalid time format. Use: /schedule <hh[:mm]> <message>. Error: {e}")
        return
    
    message_to_send = parts[2]
    
    now = datetime.now()
    scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled_time <= now:
        scheduled_time += timedelta(days=1)
    
    scheduler.add_job(
        scheduled_process_claude_prompt_and_answer,
        trigger=DateTrigger(run_date=scheduled_time),
        args=[update.message.chat_id, message_to_send, ctx.current_project],
        id=f"scheduled_message_{update.message.message_id}",
        replace_existing=True,
    )
    await send_message(update, context, f"Message scheduled to be sent at {scheduled_time.strftime('%H:%M on %d/%m/%Y')}.")

@authenticated
async def show_scheduled_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = scheduler.get_jobs()
    queued = dict(ctx.queued_messages)
    if not jobs and not queued:
        await send_message(update, context, "No messages currently scheduled.")
        return
    message_lines = ["*Scheduled messages:*\n"]
    for project, q in queued.items():
        message_text = q["message"]
        message_preview = message_text[:30] + "..." if len(message_text) > 30 else message_text
        message_preview = message_preview.replace("\n", " ")
        message_lines.append(f"• *Project:* {project}")
        message_lines.append(f"   *Message:* _{message_preview}_")
        message_lines.append(f"   *When:* ▶️ After current session\n")
    for job in jobs:
        run_time = job.next_run_time.strftime('%d/%m %H:%M') if job.next_run_time else "N/A"

        message_preview = ""
        project_name = ""
        if job.args and len(job.args) >= 3:
            message_text = job.args[1]
            project_name = job.args[2]
            message_preview = message_text[:30] + "..." if len(message_text) > 30 else message_text
            message_preview = message_preview.replace("\n", " ")

        message_lines.append(f"• *Project:* {project_name}")
        message_lines.append(f"   *Message:* _{message_preview}_")
        message_lines.append(f"   *When:* {run_time}\n")
    await send_message(update, context, "\n".join(message_lines), parse_mode="Markdown")

@authenticated
async def schedule_continue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    await update.callback_query.answer()
    if not update.callback_query.message:
        await send_message(update, context, "No message found to continue.")
        return
    data = update.callback_query.data or ""
    time_str = data.split("schedule_continue_")[-1]
    try:
        scheduled_time = datetime.strptime(time_str, "%H:%M").replace(
            year=datetime.now().year,
            month=datetime.now().month,
            day=datetime.now().day
        )
        if scheduled_time <= datetime.now():
            scheduled_time += timedelta(days=1)
    except ValueError:
        await update.callback_query.edit_message_text("Invalid time format in callback data.")
        return

    scheduler.add_job(
        scheduled_process_claude_prompt_and_answer,
        trigger=DateTrigger(run_date=scheduled_time),
        args=[update.callback_query.message.chat.id, "continue", ctx.current_project],
        id=f"scheduled_message_{update.callback_query.message.message_id}",
        replace_existing=True,
    )
    await update.callback_query.edit_message_text(f"Message scheduled to be sent at {scheduled_time.strftime('%H:%M on %Y-%m-%d')}.")

@authenticated
async def delete_scheduled_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = scheduler.get_jobs()
    queued = dict(ctx.queued_messages)
    if not jobs and not queued:
        await send_message(update, context, "No messages currently scheduled.")
        return
    message_lines = ["*Delete scheduled message*"]

    buttons = []
    for project in queued:
        button_label = f"[Queued] {project}"
        buttons.append(InlineKeyboardButton(button_label, callback_data=f"delete_queue_{project}"))
    for job in jobs:
        run_time = job.next_run_time.strftime('%d/%m %H:%M') if job.next_run_time else "N/A"
        project_name = ""
        if job.args and len(job.args) >= 3:
            project_name = job.args[2]

        button_label = f"{project_name} - {run_time}" if project_name else f"{run_time}"
        buttons.append(InlineKeyboardButton(button_label, callback_data=f"delete_schedule_{job.id}"))

    reply_markup = build_keyboard(buttons)
    await send_message(update, context, "\n".join(message_lines), parse_mode="Markdown", reply_markup=reply_markup)

@authenticated
async def delete_scheduled_job_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    await update.callback_query.answer()
    data = update.callback_query.data or ""
    job_id = data.split("delete_schedule_")[-1]
    try:
        scheduler.remove_job(job_id)
        await update.callback_query.edit_message_text(f"Scheduled job deleted successfully.")
    except Exception as e:
        await update.callback_query.edit_message_text(f"Error deleting scheduled job: {e}")


@authenticated
async def delete_queued_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    await update.callback_query.answer()
    data = update.callback_query.data or ""
    project = data.split("delete_queue_")[-1]
    removed = ctx.queued_messages.pop(project, None)
    if removed:
        await update.callback_query.edit_message_text(
            f"Queued message for *{project}* cancelled.", parse_mode="Markdown"
        )
    else:
        await update.callback_query.edit_message_text("No queued message found to cancel.")


@authenticated
async def recover_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    pending = ctx.pending_recovery
    ctx.pending_recovery = None

    if data == "recover_no" or not pending:
        await query.edit_message_text("Session recovery cancelled.")
        return

    # recover_yes: switch project and set resume ID
    project = pending["project"]
    old_project = ctx.current_project
    ctx.set_current_project(project)
    ctx.resume_claude_session_id[project] = pending["claude_sid"]
    prompt_preview = pending.get("prompt_preview", "")
    await query.edit_message_text(
        f"Session recovered for *{project}* (switched from {old_project})\n"
        f"_{prompt_preview}_",
        parse_mode="Markdown",
    )


@authenticated
async def stream_active_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    active_sessions = list(ctx.claude_sessions.items())
    if not active_sessions:
        await send_message(update, context, "No active Claude sessions found.")
        return
    buttons = []
    for proj, cs in active_sessions:
        label = proj
        if cs.prompt:
            preview = cs.prompt[:30] + "..." if len(cs.prompt) > 30 else cs.prompt
            label = f"{proj}: {preview}"
        buttons.append(
            InlineKeyboardButton(label, callback_data=f"stream_{proj}")
        )
    reply_markup = build_keyboard(buttons)
    await send_message(
        update, context, "Select a session to stream:", reply_markup=reply_markup,
    )


@authenticated
async def start_stream_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    if not data.startswith("stream_"):
        return
    proj = data[7:]
    cs = ctx.claude_sessions.get(proj)
    if not cs:
        await query.edit_message_text(f"Session for {proj} not found or already completed.")
        return
    if proj in ctx.active_streams:
        await query.edit_message_text(f"Already streaming session: {proj}")
        return

    chat_id = query.message.chat_id if query.message else None
    if not chat_id:
        return

    ctx.active_streams.add(proj)
    await query.edit_message_text(f"*Streaming:* {proj}\n\n_Waiting for events..._", parse_mode="Markdown")
    message_id = query.message.message_id
    asyncio.create_task(_stream_session_task(chat_id, message_id, proj, cs.session_uuid))


def _format_event(event: dict) -> str:
    ts = event["created_at"].strftime("%H:%M:%S") if event.get("created_at") else ""
    etype = event.get("event_type", "")
    content = event.get("content", "")
    if etype == "assistant":
        return f"`[{ts}]` {content}"
    elif etype == "tool_use":
        return f"`[{ts}]` *Tools:* {content}"
    elif etype == "result":
        return f"`[{ts}]` *Done* ({content})"
    return f"`[{ts}]` {etype}: {content}"


MAX_STREAM_MSG_LENGTH = 3500


async def _edit_stream_message(chat_id: int, message_id: int, text: str):
    try:
        await bot_app.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown",
        )
    except Exception:
        try:
            await bot_app.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text,
            )
        except Exception:
            pass


async def _stream_session_task(chat_id: int, message_id: int, project: str, session_uuid: str):
    seen_count = 0
    lines: list[str] = []
    current_msg_id = message_id
    header = f"*Streaming:* {project}\n"

    try:
        while True:
            await asyncio.sleep(5)
            events = await get_session_events(session_uuid)
            new_events = events[seen_count:]
            seen_count = len(events)

            if new_events:
                for event in new_events:
                    lines.append(_format_event(event))

                text = header + "\n".join(lines)

                if len(text) > MAX_STREAM_MSG_LENGTH:
                    # Freeze current message, start a new one
                    msg = await send_direct_message(chat_id, "_continuing..._", parse_mode="Markdown")
                    if msg:
                        current_msg_id = msg.message_id
                    overflow = len(new_events)
                    lines = lines[-overflow:]
                    text = header + "\n".join(lines)

                await _edit_stream_message(chat_id, current_msg_id, text)

            if project not in ctx.claude_sessions:
                lines.append("\n_Stream ended._")
                text = header + "\n".join(lines)
                await _edit_stream_message(chat_id, current_msg_id, text)
                break
    except Exception as e:
        print(f"Stream task error for {project}: {e}")
    finally:
        ctx.active_streams.discard(project)
