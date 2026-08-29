FROM python:3.13.1-slim-bookworm

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    stockfish \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && stockfish --help 2>&1 | head -5 || echo "stockfish installed"

RUN pip install --no-cache-dir poetry==2.1.1

ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY chat/pyproject.toml /app/chat/
COPY chat/poetry.lock* /app/chat/
WORKDIR /app/chat
RUN poetry check --lock || poetry lock --no-update --no-interaction; \
    poetry install --no-root --no-interaction --no-ansi

COPY ./chat /app/chat/

COPY ./data /app/data

RUN useradd -m app && chown -R app:app /app
USER app

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

EXPOSE 8501
CMD ["poetry", "run", "streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
