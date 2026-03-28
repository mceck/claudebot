import os
from datetime import datetime, timezone

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from codebot.tools.auth import authenticated
from codebot.tools.bot import send_message

STATUS_EMOJI = {
    "operational": "🟢",
    "degraded_performance": "🟡",
    "partial_outage": "🟠",
    "major_outage": "🔴",
    "under_maintenance": "🔵",
}

INDICATOR_EMOJI = {
    "none": "🟢",
    "minor": "🟡",
    "major": "🟠",
    "critical": "🔴",
}


@authenticated
async def claude_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        summary_resp, incidents_resp = await _fetch_all(client)

    if summary_resp.is_error:
        await send_message(update, context, "Failed to fetch Claude status.")
        return

    summary = summary_resp.json()
    overall = summary.get("status", {})
    indicator = overall.get("indicator", "none")
    description = overall.get("description", "Unknown")
    emoji = INDICATOR_EMOJI.get(indicator, "⚪")

    lines = [f"*Claude Status:* {emoji} {description}", ""]

    components = summary.get("components", [])
    groups = {}
    children = {}
    for c in components:
        if c.get("group"):
            groups[c["id"]] = c
        else:
            gid = c.get("group_id")
            if gid:
                children.setdefault(gid, []).append(c)
            else:
                children.setdefault(None, []).append(c)

    for c in children.get(None, []):
        e = STATUS_EMOJI.get(c["status"], "⚪")
        lines.append(f"{e} {c['name']}")

    for gid, group in groups.items():
        e = STATUS_EMOJI.get(group["status"], "⚪")
        lines.append(f"\n*{e} {group['name']}*")
        for c in children.get(gid, []):
            e = STATUS_EMOJI.get(c["status"], "⚪")
            lines.append(f"  {e} {c['name']}")

    incidents = []
    if not incidents_resp.is_error:
        incidents = incidents_resp.json().get("incidents", [])
    if not incidents:
        incidents = summary.get("incidents", [])

    if incidents:
        lines.append("\n*⚠️ Active Incidents:*")
        for inc in incidents:
            name = inc.get("name", "Unknown")
            status = inc.get("status", "unknown")
            lines.append(f"• *{name}* — {status}")
            updates = inc.get("incident_updates", [])
            if updates:
                latest = updates[0]
                body = latest.get("body", "")
                if body:
                    lines.append(f"  _{body[:200]}_")

    maintenances = summary.get("scheduled_maintenances", [])
    if maintenances:
        lines.append("\n*🔧 Scheduled Maintenance:*")
        for m in maintenances:
            name = m.get("name", "Unknown")
            start = m.get("scheduled_for", "")
            lines.append(f"• {name} — {start}")

    await send_message(update, context, "\n".join(lines), parse_mode="Markdown")


async def _fetch_all(client: httpx.AsyncClient):
    import asyncio

    summary_task = client.get("https://status.claude.com/api/v2/summary.json")
    incidents_task = client.get(
        "https://status.claude.com/api/v2/incidents/unresolved.json"
    )
    return await asyncio.gather(summary_task, incidents_task)


@authenticated
async def claude_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        await send_message(update, context, "CLAUDE_CODE_OAUTH_TOKEN not set.")
        return

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={"Authorization": f"Bearer {token}"},
        )

    if resp.is_error:
        await send_message(
            update, context, f"Failed to fetch usage: {resp.status_code}"
        )
        return

    data = resp.json()

    lines = ["*Claude Usage*", ""]

    daily = data.get("daily", data.get("dailyUsage", {}))
    weekly = data.get("weekly", data.get("weeklyUsage", {}))

    if daily:
        pct = _calc_pct(daily)
        reset = _format_reset(daily.get("resetsAt", daily.get("reset_at", "")))
        bar = _progress_bar(pct)
        lines.append(f"*Daily:* {pct:.1f}%  {bar}")
        if reset:
            lines.append(f"  Reset: {reset}")
        lines.append("")

    if weekly:
        pct = _calc_pct(weekly)
        reset = _format_reset(weekly.get("resetsAt", weekly.get("reset_at", "")))
        bar = _progress_bar(pct)
        lines.append(f"*Weekly:* {pct:.1f}%  {bar}")
        if reset:
            lines.append(f"  Reset: {reset}")
        lines.append("")

    if not daily and not weekly:
        lines.append(f"```\n{resp.text[:1000]}\n```")

    await send_message(update, context, "\n".join(lines), parse_mode="Markdown")


def _calc_pct(bucket: dict) -> float:
    used = bucket.get("used", bucket.get("usage", 0))
    limit = bucket.get("limit", bucket.get("total", 0))
    if limit and limit > 0:
        return (used / limit) * 100
    pct = bucket.get("percent", bucket.get("percentage", bucket.get("percentUsed", -1)))
    if pct is not None and pct >= 0:
        return float(pct)
    return 0.0


def _format_reset(reset_str: str) -> str:
    if not reset_str:
        return ""
    try:
        dt = datetime.fromisoformat(reset_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = dt - now
        hours = int(delta.total_seconds() // 3600)
        minutes = int((delta.total_seconds() % 3600) // 60)
        if hours > 0:
            return f"{dt.strftime('%H:%M UTC')} (in {hours}h {minutes}m)"
        elif minutes > 0:
            return f"{dt.strftime('%H:%M UTC')} (in {minutes}m)"
        else:
            return dt.strftime("%H:%M UTC")
    except Exception:
        return reset_str


def _progress_bar(pct: float, length: int = 10) -> str:
    filled = int(pct / 100 * length)
    filled = max(0, min(filled, length))
    return "█" * filled + "░" * (length - filled)
