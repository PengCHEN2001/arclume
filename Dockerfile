# Arclume application image for the first runnable project stage.
# The image uses the same Python minor version as the local development
# environment so that basic behavior is easier to reproduce.

FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY api ./api
COPY agents ./agents
COPY core ./core
COPY harness ./harness
COPY knowledge ./knowledge
COPY memory ./memory
COPY schemas ./schemas
COPY data ./data
COPY skills ./skills
COPY tools ./tools
COPY monitor ./monitor
COPY evaluation ./evaluation

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
