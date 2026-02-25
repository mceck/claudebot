import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    PROJECTS_DIR: str = "projects"
    TELEGRAM_BOT_TOKEN: str = "xxx"
    ALLOWED_USER_IDS: list[int] = []
    MODEL: str = "opus"
    EFFORT: str = "high"
    MISTRAL_API_KEY: str = ""
    TRANSCRIPTION_LANGUAGE: str = "en"

    @property
    def projects_dir(self) -> str:
        return os.path.abspath(self.PROJECTS_DIR)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = AppSettings()
