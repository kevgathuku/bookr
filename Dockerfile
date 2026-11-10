# Bookr production image. Stages and why each exists:
#  1. spa: builds the member SPA (Django serves frontend/dist same-origin).
#  2. builder: resolves + installs locked Python deps into /app/.venv.
#  3. runtime: slim, non-root, code + venv + dist, collectstatic baked in.
# No secrets anywhere: SECRET_KEY/DATABASE_URL/etc. arrive as environment.

FROM node:20-slim AS spa
WORKDIR /spa
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
WORKDIR /app
RUN useradd --create-home --uid 10001 bookr
COPY --from=builder /app/.venv /app/.venv
COPY manage.py pyproject.toml ./
COPY --chmod=755 scripts/start-web.sh ./scripts/start-web.sh
COPY common/ ./common/
COPY config/ ./config/
COPY organizations/ ./organizations/
COPY scheduling/ ./scheduling/
COPY booking/ ./booking/
COPY passes/ ./passes/
COPY access/ ./access/
COPY aggregators/ ./aggregators/
COPY tests/ ./tests/
COPY --from=spa /spa/dist ./frontend/dist/
RUN SECRET_KEY=build-only DATABASE_URL=postgres://build:build@localhost:5432/build ALLOWED_HOSTNAMES=localhost \
    python manage.py collectstatic --noinput
USER bookr
EXPOSE 8000
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3"]
