import unittest

import numpy as np
from PIL import Image, ImageDraw

from app.page_geometry import rectify_page_photo


class PaperGeometryTest(unittest.TestCase):
    def photo(self, clipped=False):
        image = Image.new("RGB", (800, 1100), (45, 35, 30))
        draw = ImageDraw.Draw(image)
        bottom = 1099 if clipped else 1040
        draw.polygon([(90, 100), (710, 60), (770, bottom), (20, bottom)], fill=(235, 235, 235))
        # Printed diagram, thin line, and colored content must all survive.
        draw.rectangle((240, 300, 560, 550), fill="black")
        draw.line((160, 730, 660, 730), fill="black", width=3)
        draw.rectangle((360, 800, 430, 880), fill=(0, 0, 240))
        return image

    def test_rectifies_paper_without_erasing_content(self):
        output = rectify_page_photo(self.photo())
        self.assertIsNotNone(output)
        pixels = np.asarray(output)
        desk = (pixels[:, :, 0] > 35) & (pixels[:, :, 0] < 60) & (pixels[:, :, 1] < 45)
        self.assertLess(desk.mean(), 0.01)
        self.assertGreater((pixels.mean(axis=2) < 25).sum(), 70_000)
        self.assertGreater(((pixels[:, :, 2] > 180) & (pixels[:, :, 0] < 40)).sum(), 4_000)

    def test_paper_touching_image_bottom_is_preserved(self):
        output = rectify_page_photo(self.photo(clipped=True))
        self.assertIsNotNone(output)
        self.assertGreater(output.height, 980)

    def test_flat_scan_is_left_alone(self):
        scan = Image.new("RGB", (800, 1100), "white")
        draw = ImageDraw.Draw(scan)
        draw.rectangle((100, 100, 700, 900), outline="black", width=2)
        self.assertIsNone(rectify_page_photo(scan))

    def test_small_bright_object_is_not_a_page(self):
        image = Image.new("RGB", (800, 1100), (45, 35, 30))
        ImageDraw.Draw(image).rectangle((200, 300, 600, 800), fill="white")
        self.assertIsNone(rectify_page_photo(image))

    def test_ambiguous_nonrectangular_region_is_not_warped(self):
        image = Image.new("RGB", (800, 1100), (45, 35, 30))
        ImageDraw.Draw(image).ellipse((10, 10, 790, 1090), fill="white")
        self.assertIsNone(rectify_page_photo(image))

    def test_small_input_is_left_alone(self):
        self.assertIsNone(rectify_page_photo(Image.new("RGB", (100, 100), "white")))


if __name__ == "__main__":
    unittest.main()
