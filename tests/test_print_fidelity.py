import io
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from app.pipeline import build_a4_pdf, normalize_print_background


class PrintFidelityTest(unittest.TestCase):
    def test_default_preserves_faint_lines_and_color(self):
        image = Image.new("RGB", (100, 100), "white")
        image.putpixel((30, 40), (220, 220, 220))
        image.putpixel((50, 60), (120, 60, 30))
        result = normalize_print_background(image)
        self.assertEqual(result.tobytes(), image.tobytes())

    def test_pdf_embeds_original_resolution_losslessly(self):
        image = Image.new("RGB", (2600, 3400), "white")
        ImageDraw.Draw(image).line((100, 200, 2500, 200), fill=(215, 215, 215), width=1)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "output.pdf"
            build_a4_pdf([image, image], target)
            with fitz.open(target) as document:
                self.assertEqual(len(document), 2)
                self.assertAlmostEqual(document[0].rect.width, 595, delta=1)
                info = document.extract_image(document[0].get_images()[0][0])
                with Image.open(io.BytesIO(info["image"])) as embedded:
                    self.assertEqual(embedded.size, image.size)
                    self.assertEqual(embedded.convert("RGB").tobytes(), image.tobytes())


if __name__ == "__main__":
    unittest.main()
