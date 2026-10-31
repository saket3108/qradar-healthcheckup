FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MPLBACKEND=Agg

# Node 20 is required by the pptxgenjs-based PowerPoint generator.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg fonts-dejavu-core libjpeg62-turbo libfreetype6 tini \
 && mkdir -p /etc/apt/keyrings \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update && apt-get install -y --no-install-recommends nodejs \
 && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pptx_gen/package.json pptx_gen/
RUN cd pptx_gen && npm install --omit=dev --no-audit --no-fund

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY pptx_gen/generate.js pptx_gen/generate.js

RUN useradd --system --uid 10001 --create-home qhc && mkdir -p /data && chown -R qhc:qhc /data /app
USER qhc
ENV QHC_ENVIRONMENT=production QHC_STORAGE_DIR=/data/storage
VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
