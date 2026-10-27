FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm

# Timezone configuration
ENV TZ=Europe/Bratislava

# Install timezone data
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# uv for Python, dependencies and tools (ruff, ty, pytest run through `uv run`); pinned for reproducible builds
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
# the project's .venv lives on the bind mount, so copy instead of hard-linking from uv's cache
ENV UV_LINK_MODE=copy
