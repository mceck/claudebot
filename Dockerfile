FROM mcr.microsoft.com/devcontainers/universal:noble
USER codespace
WORKDIR /home/codespace/claudebot
ENV PYTHONUNBUFFERED=1
RUN curl -fsSL https://claude.ai/install.sh | bash
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
ENV TZ="Europe/Rome"
COPY . .
RUN uv sync

CMD ["uv", "run", "python", "main.py"]