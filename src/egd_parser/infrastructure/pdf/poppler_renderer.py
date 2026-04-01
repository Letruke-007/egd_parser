import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from egd_parser.domain.models.page import PageImage
from egd_parser.domain.ports.pdf_renderer import PDFRenderer
from egd_parser.infrastructure.settings import get_settings
from egd_parser.utils.image import ensure_directory


class PopplerPDFRenderer(PDFRenderer):
    def render(self, filename: str, content: bytes) -> list[PageImage]:
        settings = get_settings()
        work_dir = Path(tempfile.mkdtemp(prefix="egd_pdf_"))
        pdf_path = work_dir / filename
        pdf_path.write_bytes(content)

        output_prefix = work_dir / "page"
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                str(settings.pdf_render_dpi),
                str(pdf_path),
                str(output_prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        pages: list[PageImage] = []
        rendered_files = sorted(work_dir.glob("page-*.png"))
        cache_dir = ensure_directory(Path("tmp/rendered_pages"))

        for index, rendered_file in enumerate(rendered_files, start=1):
            final_path = cache_dir / f"{pdf_path.stem}-page-{index}.png"
            shutil.copyfile(rendered_file, final_path)
            with Image.open(final_path) as image:
                width, height = image.size
            pages.append(
                PageImage(
                    number=index,
                    width=width,
                    height=height,
                    image_path=str(final_path),
                    source_pdf=str(pdf_path),
                )
            )

        return pages
