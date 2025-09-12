# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TEMPLATE_GLOBS="*.yml:*.yaml"

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

USER root
COPY scripts/template-configs.sh /usr/local/bin/template-configs
RUN chmod +x /usr/local/bin/template-configs && chown appuser:appuser /usr/local/bin/template-configs
USER appuser

ENTRYPOINT ["/usr/local/bin/template-configs"]
CMD ["python", "run.py"]
