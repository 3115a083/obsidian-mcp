FROM python:3.12-alpine@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8 AS app
ARG BUILD_REVISION=development
LABEL org.opencontainers.image.source="https://github.com/3115a083/obsidian-mcp" \
      org.opencontainers.image.version="2.1.0" \
      org.opencontainers.image.revision=$BUILD_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp BUILD_REVISION=$BUILD_REVISION
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY app.py auth.py bridge.py connection.py deployment.py settings.py state.py ui.py vault.py web.py worker.py ./
USER 568:568
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]

FROM nginx:stable-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949 AS gateway
ARG BUILD_REVISION=development
LABEL org.opencontainers.image.source="https://github.com/3115a083/obsidian-mcp" \
      org.opencontainers.image.revision=$BUILD_REVISION
# Official image currently contains fixed curl/brotli findings. Apply distro
# security updates, scan this exact result and publish an immutable run tag.
RUN apk upgrade --no-cache
USER 568:568
