from telegram import Update
from telegram.ext import ContextTypes
from claudebot.settings import settings
from claudebot.tools.bot import send_message
from claudebot.tools.logger import log


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
        await log(update)
        if not await check_user(context):
            await send_message(
                update, context, "Unauthorized access. This incident has been reported."
            )
            return
        return await func(update, context, *args, **kwargs)

    return wrapper
