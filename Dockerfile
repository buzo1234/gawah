# Gawah's server image: Python 3.12 with uv, a headless Chrome to print the agreement PDF,
# Devanagari fonts for it, and the app. Built on the server by tools/deploy/deploy.sh.
FROM python:3.12-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv

# chromium-headless-shell: Chromium's headless-only build (no window system), enough for
# --print-to-pdf. fonts-noto-core has Noto Serif Devanagari, which the agreement asks for.
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium-headless-shell fonts-noto-core \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 gawah \
 && mkdir -p /data /app && chown gawah:gawah /data /app
USER gawah
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH \
    DATABASE_PATH=/data/gawah.db \
    GAWAH_CHROME_NO_SANDBOX=1

COPY --chown=gawah:gawah pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=gawah:gawah . .
# The bridge writes recordings next to the code (app/call/session.py); keep them on the volume.
RUN ln -s /data/recordings /app/recordings

EXPOSE 8000
# --proxy-headers: links and cookies see https and the public host that Caddy was asked for.
CMD ["sh", "-c", "mkdir -p /data/recordings && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
