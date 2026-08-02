FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts

EXPOSE 8000

CMD ["sh", "-c", "python scripts/wait_for_db.py && python scripts/apply_migrations.py && uvicorn src.interfaces.http.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
