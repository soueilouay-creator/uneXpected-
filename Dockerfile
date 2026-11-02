FROM node:22-bookworm-slim

ENV NODE_ENV=production PORT=10000 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY . /app

# Restore the reviewed Node UI base assets, then overlay the reviewed current gateway.
RUN base64 -d /app/source.tar.gz.b64 > /tmp/ue-source.tar.gz \
 && mkdir -p /tmp/ue-extracted \
 && tar -xzf /tmp/ue-source.tar.gz -C /tmp/ue-extracted \
 && cp -R /tmp/ue-extracted/uneXpected-ai-studio-v1.0.1/. /app/ \
 && rm -rf /tmp/ue-source.tar.gz /tmp/ue-extracted

COPY app.js /app/public/app.js
COPY server.js /app/server.js
COPY openrouter-ui.js /app/openrouter-ui.js
COPY taaft-integration.mjs /app/taaft-integration.mjs
COPY mobile-assets.mjs /app/mobile-assets.mjs

RUN cat /app/mobile-assets.parts/part-*.b64 > /tmp/mobile-assets.tar.gz.b64 \
 && printf '%s  %s\n' 'd9316477b654ea04bc842a2f7ae158b2fffe3eab85f057d7bc3aa7a749f9f55e' /tmp/mobile-assets.tar.gz.b64 | sha256sum -c - \
 && base64 -d /tmp/mobile-assets.tar.gz.b64 | tar -xz -C /app/public \
 && rm -f /tmp/mobile-assets.tar.gz.b64

COPY mobile-release/ /app/public/mobile/

RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements-runtime.txt \
 && python3 -m compileall -q /app/unexpected_runtime /app/tests \
 && node --check /app/server.js \
 && node --check /app/runtime-supervisor.mjs

EXPOSE 10000
USER node
CMD ["node", "runtime-supervisor.mjs"]
