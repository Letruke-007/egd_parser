import shutil

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck(request: Request) -> dict:
    settings = request.app.state.settings
    det_model_dir = settings.paddleocr_det_model_dir
    rec_model_dir = settings.paddleocr_rec_model_dir
    ori_model_dir = settings.paddleocr_textline_orientation_model_dir

    return {
        "status": "ok",
        "app_env": settings.app_env,
        "ocr_engine": settings.ocr_engine,
        "pdftoppm_available": shutil.which("pdftoppm") is not None,
        "storage": {
            "jobs_db_path": str(settings.jobs_db_path),
            "uploads_dir": str(settings.uploads_dir),
            "rendered_pages_dir": str(settings.rendered_pages_dir),
        },
        "models": {
            "det_model_dir": str(det_model_dir),
            "det_model_exists": det_model_dir.exists(),
            "rec_model_dir": str(rec_model_dir),
            "rec_model_exists": rec_model_dir.exists(),
            "orientation_model_dir": str(ori_model_dir),
            "orientation_model_exists": ori_model_dir.exists(),
        },
    }
