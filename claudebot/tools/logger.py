import logging
import json
from datetime import datetime
from claudebot.settings import settings
from telegram import Update
from claudebot.tools.context import ctx

logging.basicConfig(level=logging.INFO)

if settings.DATABASE_URL:
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.orm import declarative_base, mapped_column, Mapped
    from sqlalchemy import DateTime, Text, BigInteger, func

    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
    )

    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False, autocommit=False)

    Base = declarative_base()

    class ClaudebotLog(Base):
        __tablename__ = "claudebot_logs"

        id: Mapped[int] = mapped_column(primary_key=True)
        project: Mapped[str | None]
        user_id: Mapped[int | None] = mapped_column(BigInteger)
        username: Mapped[str | None]
        first_name: Mapped[str | None]
        last_name: Mapped[str | None]
        lang: Mapped[str | None]
        is_bot: Mapped[bool | None]
        is_premium: Mapped[bool | None]
        chat_id: Mapped[int | None] = mapped_column(BigInteger)
        chat_type: Mapped[str | None]
        forwarded_origin: Mapped[str | None]
        web_app_data: Mapped[str | None]
        message_id: Mapped[int | None] = mapped_column(BigInteger)
        message: Mapped[str | None] = mapped_column(Text)
        timestamp: Mapped[datetime | None]
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now().astimezone(),
            server_default=func.now(),
        )

    class ClaudeResponseLog(Base):
        __tablename__ = "claude_response_logs"

        id: Mapped[int] = mapped_column(primary_key=True)
        project: Mapped[str | None]
        message_id: Mapped[int | None]
        response: Mapped[str | None] = mapped_column(Text)
        created_at: Mapped[DateTime] = mapped_column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now().astimezone(),
            server_default=func.now(),
        )

    async def log(update: Update) -> None:
        user = update.effective_user
        chat = update.effective_chat
        msg = update.effective_message
        logged_message = ClaudebotLog(
            project=ctx.current_project,
            user_id=user.id if user else None,
            username=user.username if user else None,
            first_name=user.first_name if user else None,
            last_name=user.last_name if user else None,
            lang=user.language_code if user else None,
            is_bot=user.is_bot if user else None,
            is_premium=user.is_premium if user else None,
            chat_id=chat.id if chat else None,
            chat_type=chat.type if chat else None,
            forwarded_origin=msg.forward_origin.type if msg and msg.forward_origin else None,
            web_app_data=msg.web_app_data.data if msg and msg.web_app_data else None,
            message=msg.text if msg and msg.text else None,
            timestamp=msg.date if msg else None,
        )
        async with Session() as session:
            session.add(logged_message)
            await session.commit()

    async def log_claude_response(message_id: int, project: str, response: str) -> None:
        logged_response = ClaudeResponseLog(
            message_id=message_id,
            project=project,
            response=response,
        )
        async with Session() as session:
            session.add(logged_response)
            await session.commit()
else:
    async def log(update: Update) -> None:
        user = update.effective_user
        chat = update.effective_chat
        msg = update.effective_message
        
        log_data = {
            "project": ctx.current_project,
            "user_id": user.id if user else None,
            "username": user.username if user else None,
            "first_name": user.first_name if user else None,
            "last_name": user.last_name if user else None,
            "lang": user.language_code if user else None,
            "is_bot": user.is_bot if user else None,
            "is_premium": user.is_premium if user else None,
            "chat_id": chat.id if chat else None,
            "chat_type": chat.type if chat else None,
            "forwarded_origin": msg.forward_origin.type if msg and msg.forward_origin else None,
            "web_app_data": msg.web_app_data.data if msg and msg.web_app_data else None,
            "message": msg.text if msg and msg.text else None,
            "timestamp": msg.date.isoformat() if msg and msg.date else None,
        }
        
        logging.info(f"Received message:\n{json.dumps(log_data, indent=2)}")

    async def log_claude_response(message_id: int, project: str, response: str) -> None:
        logging.info(f"Claude response for message {message_id} in project {project}:\n{response}")