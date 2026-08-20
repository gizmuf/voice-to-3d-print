FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOME=/home/pulsai

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        prusa-slicer \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN addgroup --system pulsai \
    && adduser --system --ingroup pulsai --home /home/pulsai pulsai \
    && mkdir -p /app/data/output /app/data/telemetry \
    && chown -R pulsai:pulsai /app/data/output /app/data/telemetry /home/pulsai

USER pulsai

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
