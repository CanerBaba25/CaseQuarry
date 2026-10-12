FROM ghcr.io/astral-sh/uv:0.12.24 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY apps/api ./apps/api
COPY apps/cli ./apps/cli
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev && useradd --uid 10001 --create-home casequarry && mkdir /app/private-data && chown casequarry:casequarry /app/private-data
USER casequarry
EXPOSE 8000
CMD ["uvicorn", "casequarry.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
