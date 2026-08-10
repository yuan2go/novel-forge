FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/src

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY skills ./skills

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e '.[industrial]'

RUN groupadd --gid 10001 novel-forge \
    && useradd --uid 10001 --gid 10001 --no-create-home novel-forge \
    && mkdir -p /runtime/objects /runtime/tmp \
    && chown -R 10001:10001 /runtime

USER 10001:10001

EXPOSE 8000

CMD ["python", "-m", "novel_forge.cli", "serve-api", "--host", "0.0.0.0", "--port", "8000"]
