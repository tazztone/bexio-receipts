

FROM python:3.12-slim


# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.1 /uv /uvx /bin/

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY README.md ./

# Install dependencies
RUN uv sync --no-dev
CMD ["uv", "run", "bexio-receipts", "serve"]
