FROM mcr.microsoft.com/devcontainers/universal:noble
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN curl -fsSL https://claude.ai/install.sh | bash
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
COPY . .
RUN uv sync

CMD ["python", "main.py"]