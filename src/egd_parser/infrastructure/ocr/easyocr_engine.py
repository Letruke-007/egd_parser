from pathlib import Path

from egd_parser.domain.models.ocr import OCRPageResult, OCRWord
from egd_parser.domain.models.page import PageImage
from egd_parser.domain.ports.ocr_engine import OCREngine
from egd_parser.domain.value_objects.bbox import BoundingBox
from egd_parser.utils.text import normalize_whitespace


class EasyOCREngine(OCREngine):
    def __init__(self) -> None:
        self._reader = None

    def recognize(self, pages: list[PageImage]) -> list[OCRPageResult]:
        reader = self._get_reader()
        results: list[OCRPageResult] = []

        for page in pages:
            if not page.image_path:
                results.append(OCRPageResult(page_number=page.number, text=""))
                continue

            raw_blocks = reader.readtext(page.image_path, detail=1, paragraph=False)
            words: list[OCRWord] = []
            text_lines: list[tuple[float, float, str]] = []

            for block in raw_blocks:
                polygon, text, confidence = block
                xs = [point[0] for point in polygon]
                ys = [point[1] for point in polygon]
                bbox = BoundingBox(
                    left=int(min(xs)),
                    top=int(min(ys)),
                    width=int(max(xs) - min(xs)),
                    height=int(max(ys) - min(ys)),
                )
                normalized_text = normalize_whitespace(text)
                if not normalized_text:
                    continue
                words.append(
                    OCRWord(
                        text=normalized_text,
                        confidence=float(confidence),
                        bbox=bbox,
                    )
                )
                text_lines.append((bbox.top, bbox.left, normalized_text))

            ordered_text = "\n".join(
                entry[2] for entry in sorted(text_lines, key=lambda entry: (entry[0], entry[1]))
            )
            results.append(
                OCRPageResult(
                    page_number=page.number,
                    text=ordered_text,
                    image_path=page.image_path,
                    words=words,
                )
            )

        return results

    def _get_reader(self):
        if self._reader is None:
            import easyocr

            model_storage = Path(".venv/easyocr-models")
            user_network = Path(".venv/easyocr-user")
            model_storage.mkdir(parents=True, exist_ok=True)
            user_network.mkdir(parents=True, exist_ok=True)
            self._reader = easyocr.Reader(
                ["ru", "en"],
                gpu=False,
                model_storage_directory=str(model_storage),
                user_network_directory=str(user_network),
                download_enabled=True,
            )
        return self._reader
