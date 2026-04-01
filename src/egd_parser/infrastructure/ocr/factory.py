from egd_parser.domain.ports.ocr_engine import OCREngine
from egd_parser.infrastructure.ocr.easyocr_engine import EasyOCREngine
from egd_parser.infrastructure.ocr.mock_engine import MockOCREngine
from egd_parser.infrastructure.ocr.paddleocr_engine import PaddleOCREngine
from egd_parser.infrastructure.ocr.tesseract_engine import TesseractOCREngine
from egd_parser.infrastructure.settings import Settings


def create_ocr_engine(settings: Settings) -> OCREngine:
    if settings.ocr_engine == "paddleocr":
        return PaddleOCREngine(
            language=settings.paddleocr_language,
            use_angle_cls=settings.paddleocr_use_angle_cls,
            base_dir=str(settings.paddleocr_base_dir),
            det_model_name=settings.paddleocr_det_model_name,
            rec_model_name=settings.paddleocr_rec_model_name,
            textline_orientation_model_name=settings.paddleocr_textline_orientation_model_name,
            det_model_dir=str(settings.paddleocr_det_model_dir),
            rec_model_dir=str(settings.paddleocr_rec_model_dir),
            textline_orientation_model_dir=str(settings.paddleocr_textline_orientation_model_dir),
        )
    if settings.ocr_engine == "easyocr":
        return EasyOCREngine()
    if settings.ocr_engine == "tesseract":
        return TesseractOCREngine()
    if settings.ocr_engine == "mock":
        return MockOCREngine()
    raise ValueError(f"Unsupported OCR engine: {settings.ocr_engine}")
