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
from claudebot.tools.claude import Claude
from claudebot.tools.logger import log_claude_response
from claudebot.tools.shell import run_command
from claudebot.settings import settings
from claudebot.tools.auth import authenticated
from claudebot.tools.bot import send_message
from claudebot.tools.context import ctx
from claudebot.tools.scheduler import scheduler
from claudebot.tools.bot import send_direct_message



async def process_claude_prompt(message: str, project: str):
    claude_session = Claude(os.path.join(settings.projects_dir, project))
    ctx.claude_sessions[project] = claude_session
    resume_session = not message.startswith("!")
    if not resume_session:
        message = message[1:]
    plan_mode = message.startswith("?")
    if plan_mode:
        message = message[1:]
    ret, resp = await claude_session.send(
        message, resume_session=resume_session, plan_mode=plan_mode
    )
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

    return resp


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
        await send_message(
            update,
            context,
            "A Claude session is already processing a message. Please wait for it to finish before sending another message.",
        )
        return
    if update.message and update.message.text:
        await send_message(update, context, "Processing your message...")
        await process_claude_prompt_and_answer(update.message.chat_id, update.message.text)

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
    if not update.callback_query.message:
        await send_message(update, context, "No message found to reply to.")
        return
    await send_message(update, context, "Processing message with Claude...")
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
        process_claude_prompt_and_answer,
        trigger=DateTrigger(run_date=scheduled_time),
        args=[update.message.chat_id, message_to_send, ctx.current_project],
        id=f"scheduled_message_{update.message.message_id}",
        replace_existing=True,
    )
    await send_message(update, context, f"Message scheduled to be sent at {scheduled_time.strftime('%H:%M on %d/%m/%Y')}.")

@authenticated
async def show_scheduled_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = scheduler.get_jobs()
    if not jobs:
        await send_message(update, context, "No messages currently scheduled.")
        return
    message_lines = ["*Scheduled messages:*\n"]
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
        await send_message(update, context, "Invalid time format in callback data.")
        return
    
    scheduler.add_job(
        process_claude_prompt_and_answer,
        trigger=DateTrigger(run_date=scheduled_time),
        args=[update.callback_query.message.chat.id, "continue", ctx.current_project],
        id=f"scheduled_message_{update.callback_query.message.message_id}",
        replace_existing=True,
    )
    await send_message(update, context, f"Message scheduled to be sent at {scheduled_time.strftime('%H:%M on %Y-%m-%d')}.")

@authenticated
async def delete_scheduled_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = scheduler.get_jobs()
    if not jobs:
        await send_message(update, context, "No messages currently scheduled.")
        return
    message_lines = ["*Delete schedule message*"]
    
    buttons = []
    for job in jobs:
        run_time = job.next_run_time.strftime('%d/%m %H:%M') if job.next_run_time else "N/A"
        project_name = ""
        if job.args and len(job.args) >= 3:
            project_name = job.args[2]
        
        button_label = f"{project_name} - {run_time}" if project_name else f"{run_time}"
        buttons.append([InlineKeyboardButton(button_label, callback_data=f"delete_schedule_{job.id}")])
    
    reply_markup = InlineKeyboardMarkup(buttons)
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
        await send_message(update, context, f"Scheduled job `{job_id}` deleted successfully.", parse_mode="Markdown")
    except Exception as e:
        await send_message(update, context, f"Error deleting scheduled job `{job_id}`: {e}", parse_mode="Markdown")
