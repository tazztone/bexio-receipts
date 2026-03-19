# --- Builder Stage ---
FROM python:3.12-slim AS builder

# Install system dependencies needed for build (optional if only installing wheels)
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv using the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Change the working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Use a cache mount to speed up dependency installation
# Copy only the dependency files first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the rest of the source code and sync the project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Production Stage ---
FROM python:3.12-slim

# Install runtime system dependencies
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Ensure the app's bin is in the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Ensure the server is accessible from outside the container
CMD ["bexio-receipts", "serve", "--host", "0.0.0.0"]
