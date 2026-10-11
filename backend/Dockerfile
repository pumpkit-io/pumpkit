FROM python:3.13-slim

WORKDIR /app

# The image installs dependencies only, not the project, so `pumpkit` resolves from the source tree.
ENV PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y \
    # To compile C extensions
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt

COPY . .
