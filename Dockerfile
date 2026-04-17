FROM python:3.13-slim

# Install system dependencies for python-magic and pillow
RUN apt-get update && apt-get install -y \
    libmagic1 \
    libmagic-dev \
    libjpeg-dev \
    libpng-dev \
    libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev || uv sync --no-dev

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

# Create data directories
RUN mkdir -p /data/media /data/tmp

EXPOSE 8000

# Run migrations then start server
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn eventdrop.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
