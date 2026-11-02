FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ARG BUILD_REVISION=development
LABEL org.opencontainers.image.source="https://github.com/3115a083/obsidian-mcp" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.revision=$BUILD_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp BUILD_REVISION=$BUILD_REVISION
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY app.py auth.py bridge.py deployment.py settings.py state.py ui.py vault.py web.py worker.py ./
USER 568:568
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
