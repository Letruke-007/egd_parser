from pathlib import Path

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    ocr_engine: str = "paddleocr"
    pdf_render_dpi: int = 300
    attempts_dir: Path = Path("attempts")
    jobs_db_path: Path = Path("storage/jobs.sqlite3")
    uploads_dir: Path = Path("storage/uploads")
    jobs_retention_days: int = 30
    job_worker_threads: int = 4
    rendered_pages_dir: Path = Path("tmp/rendered_pages")
    rendered_pages_retention_hours: int = 24
    paddleocr_language: str = "ru"
    paddleocr_use_angle_cls: bool = False
    paddleocr_base_dir: Path = Path(".venv/paddleocr-models")
    paddleocr_det_model_name: str = "PP-OCRv5_mobile_det"
    paddleocr_rec_model_name: str = "cyrillic_PP-OCRv5_mobile_rec"
    paddleocr_textline_orientation_model_name: str = "PP-LCNet_x0_25_textline_ori"
    paddleocr_det_model_dir: Path = Path(".venv/paddleocr-models/models/PP-OCRv5_mobile_det_infer")
    paddleocr_rec_model_dir: Path = Path(
        ".venv/paddleocr-models/models/cyrillic_PP-OCRv5_mobile_rec_infer"
    )
    paddleocr_textline_orientation_model_dir: Path = Path(
        ".venv/paddleocr-models/models/PP-LCNet_x0_25_textline_ori_infer"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
