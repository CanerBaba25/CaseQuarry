FROM ghcr.io/astral-sh/uv:0.12.24 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app
ARG INSTALL_OCR=true
RUN if [ "$INSTALL_OCR" = "true" ]; then apt-get update && apt-get install --yes --no-install-recommends tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*; fi
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md LICENSE NOTICE THIRD_PARTY_NOTICES.md ./
COPY apps/api/casequarry/*.py ./apps/api/casequarry/
COPY apps/cli/casequarry_cli/*.py ./apps/cli/casequarry_cli/
COPY migrations/env.py migrations/schema_signatures.json migrations/script.py.mako ./migrations/
COPY migrations/versions/*.py ./migrations/versions/
COPY alembic.ini ./
RUN uv sync --frozen --no-dev && useradd --uid 10001 --create-home casequarry && mkdir /app/private-data && chown casequarry:casequarry /app/private-data
USER casequarry
EXPOSE 8000
CMD ["uvicorn", "casequarry.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
