from telegram import Update
from telegram.ext import ContextTypes


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
