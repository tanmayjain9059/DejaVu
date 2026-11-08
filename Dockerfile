FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system lostlink && useradd --system --gid lostlink --home-dir /app lostlink \
    && mkdir -p /data/uploads /model-cache \
    && chown -R lostlink:lostlink /app /data /model-cache

COPY requirements.txt requirements-ml.txt ./
ARG INSTALL_ML=false
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && if [ "$INSTALL_ML" = "true" ]; then python -m pip install -r requirements-ml.txt; fi

COPY --chown=lostlink:lostlink app ./app
COPY --chown=lostlink:lostlink scripts ./scripts

USER lostlink
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
