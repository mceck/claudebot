FROM python:3.14-slim AS base
FROM base AS builder
WORKDIR /
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock /
RUN uv sync --no-dev --frozen

FROM base
WORKDIR /app
COPY --from=builder /.venv /.venv
ENV PATH="/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y curl vim git && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
RUN curl -fsSL https://claude.ai/install.sh | bash
COPY . .

CMD ["python", "main.py"]