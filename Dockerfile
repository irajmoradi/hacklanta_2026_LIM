# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY full_app/production_frontend/package*.json ./
RUN npm ci
COPY full_app/production_frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ARG INSTALL_WHISPER=false
ARG INSTALL_OCR=false
ARG INSTALL_SAM2=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && if [ "$INSTALL_OCR" = "true" ]; then apt-get install -y --no-install-recommends tesseract-ocr; fi \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/full_app
COPY full_app/requirements*.txt ./
RUN for req in requirements*.txt; do pip install -r "$req"; done \
    && pip install gunicorn \
    && if [ "$INSTALL_WHISPER" = "true" ]; then pip install faster-whisper; fi \
    && if [ "$INSTALL_OCR" = "true" ]; then pip install pytesseract rapidocr-onnxruntime; fi \
    && if [ "$INSTALL_SAM2" = "true" ]; then SAM2_BUILD_CUDA=0 pip install sam2; fi
COPY full_app/ ./
# Existing Flask routes serve frontend/; replace its index and assets in the image.
COPY --from=frontend /build/dist/ ./frontend/
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p workspace && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/info', timeout=4)"
# One process preserves the legacy in-memory job store; threads permit status polling.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "1800", "app:app"]
