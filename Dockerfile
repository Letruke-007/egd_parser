FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=prod \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    API_PREFIX=/api/v1 \
    LOG_LEVEL=INFO \
    OCR_ENGINE=paddleocr \
    PDF_RENDER_DPI=300 \
    JOBS_DB_PATH=/data/jobs.sqlite3 \
    UPLOADS_DIR=/data/uploads \
    JOBS_RETENTION_DAYS=30 \
    JOB_WORKER_THREADS=4 \
    RENDERED_PAGES_DIR=/app/tmp/rendered_pages \
    RENDERED_PAGES_RETENTION_HOURS=24 \
    PADDLEOCR_LANGUAGE=ru \
    PADDLEOCR_USE_ANGLE_CLS=false \
    PADDLEOCR_BASE_DIR=/models \
    PADDLEOCR_DET_MODEL_NAME=PP-OCRv5_mobile_det \
    PADDLEOCR_REC_MODEL_NAME=cyrillic_PP-OCRv5_mobile_rec \
    PADDLEOCR_TEXTLINE_ORIENTATION_MODEL_NAME=PP-LCNet_x0_25_textline_ori \
    PADDLEOCR_DET_MODEL_DIR=/models/PP-OCRv5_mobile_det_infer \
    PADDLEOCR_REC_MODEL_DIR=/models/cyrillic_PP-OCRv5_mobile_rec_infer \
    PADDLEOCR_TEXTLINE_ORIENTATION_MODEL_DIR=/models/PP-LCNet_x0_25_textline_ori_infer \
    PADDLE_PDX_CACHE_HOME=/data/pdx-cache

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md .env.example /app/
COPY src /app/src
COPY scripts /app/scripts

RUN pip install --upgrade pip \
    && pip install -e . \
    && pip install paddlepaddle==3.0.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
    && pip install paddleocr

RUN mkdir -p /data/uploads /data/pdx-cache /app/tmp/rendered_pages

EXPOSE 8000

CMD ["sh", "-c", "uvicorn egd_parser.api.app:app --host ${APP_HOST} --port ${APP_PORT}"]
