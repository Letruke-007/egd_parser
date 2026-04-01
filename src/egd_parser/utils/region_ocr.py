from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _get_reader():
    import easyocr

    model_storage = Path(".venv/easyocr-models")
    user_network = Path(".venv/easyocr-user")
    model_storage.mkdir(parents=True, exist_ok=True)
    user_network.mkdir(parents=True, exist_ok=True)
    return easyocr.Reader(
        ["ru", "en"],
        gpu=False,
        model_storage_directory=str(model_storage),
        user_network_directory=str(user_network),
        download_enabled=True,
    )


def read_crop_text(
    image_path: str,
    crop_box: tuple[int, int, int, int],
    allowlist: str | None = None,
) -> str:
    from PIL import Image
    import numpy as np

    with Image.open(image_path) as image:
        width, height = image.size
        left, top, right, bottom = crop_box
        left = max(0, min(left, width))
        top = max(0, min(top, height))
        right = max(left + 1, min(right, width))
        bottom = max(top + 1, min(bottom, height))
        cropped = image.crop((left, top, right, bottom))

    pieces = _get_reader().readtext(
        np.array(cropped),
        detail=0,
        paragraph=False,
        allowlist=allowlist,
    )
    return " ".join(str(piece).strip() for piece in pieces if str(piece).strip())
