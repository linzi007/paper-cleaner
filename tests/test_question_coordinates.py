import base64
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config import settings
from app.pipeline import PageInfo, Question, detect_job_questions, detect_questions, export_pdf, parse_question_label
from app.providers.tencent_ocr import TencentQuestionSplitter


def response_for(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {
        "RequestId": "test-request",
        "QuestionInfo": [{
            "Angle": 0, "Width": image.width, "Height": image.height,
            "OrgWidth": 100, "OrgHeight": 100,
            "ImageBase64": base64.b64encode(buffer.getvalue()).decode(),
            "ResultList": [{"Text": "1. Example", "Coord": [{
                "LeftTop": {"X": 10, "Y": 20}, "RightTop": {"X": 60, "Y": 20},
                "RightBottom": {"X": 60, "Y": 40}, "LeftBottom": {"X": 10, "Y": 40},
            }]}],
        }],
    }


class QuestionCoordinatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.splitter = TencentQuestionSplitter.__new__(TencentQuestionSplitter)

    def tearDown(self):
        self.temp.cleanup()

    def test_same_dimensions_still_preserve_returned_pixels(self):
        # Dewarping can keep the canvas size and still move its contents.
        corrected = Image.new("RGB", (100, 100), "white")
        corrected.paste("black", (10, 20, 60, 40))
        destination = self.root / "question_pages/page-001.png"
        result = self.splitter._save_detection(response_for(corrected), destination, 1, Question, parse_question_label)
        with Image.open(destination) as saved:
            self.assertEqual(saved.getpixel((15, 25)), (0, 0, 0))
        self.assertEqual(result.questions[0].bbox, [10, 20, 60, 40])
        self.assertEqual((result.width, result.height), (100, 100))
        diagnostic = json.loads(destination.with_suffix(".json").read_text())
        self.assertNotIn("ImageBase64", diagnostic["QuestionInfo"][0])
        self.assertEqual(diagnostic["RequestId"], "test-request")

    def test_missing_corrected_image_does_not_fall_back_to_wrong_image(self):
        data = response_for(Image.new("RGB", (100, 100)))
        del data["QuestionInfo"][0]["ImageBase64"]
        with self.assertRaisesRegex(RuntimeError, "未返回校正图"):
            self.splitter._save_detection(data, self.root / "page.png", 1, Question, parse_question_label)

    def test_inconsistent_dimensions_are_rejected(self):
        data = response_for(Image.new("RGB", (100, 100)))
        data["QuestionInfo"][0]["Width"] = 200
        with self.assertRaisesRegex(RuntimeError, "尺寸不一致"):
            self.splitter._save_detection(data, self.root / "page.png", 1, Question, parse_question_label)

    def test_metadata_and_exports_use_the_detection_image(self):
        cfg = replace(settings, data_dir=self.root)
        job_id, owner = "1234567890abcdef", "10000000000"
        job = self.root / "jobs/by-user" / owner / job_id
        (job / "cleaned_pages").mkdir(parents=True)
        Image.new("RGB", (100, 100), "white").save(job / "cleaned_pages/page-001.png")
        meta = {"job_id": job_id, "pages": [vars(PageInfo(1, "original", "cleaned", 100, 100))], "questions": []}
        (job / "meta.json").write_text(json.dumps(meta))

        def detect(*, image_path, page, output_path):
            return self.splitter._save_detection(response_for(Image.new("RGB", (160, 120), "black")), output_path, page, Question, parse_question_label)

        with patch("app.pipeline.TencentQuestionSplitter") as factory:
            factory.return_value.detect.side_effect = detect
            result = detect_job_questions(job_id, owner, cfg)
        self.assertEqual(result["pages"][0]["width"], 100)
        self.assertEqual(result["pages"][0]["question_width"], 160)
        self.assertEqual(result["pages"][0]["question_height"], 120)

        with patch("app.pipeline.normalize_print_background", side_effect=lambda image, **kwargs: image.copy()), patch("app.pipeline.build_a4_pdf") as build:
            export_pdf(job_id, owner, ["p1-q1"], cfg=cfg)
            self.assertEqual(build.call_args.args[0][0].getpixel((0, 0)), (0, 0, 0))
            export_pdf(job_id, owner, [], cfg=cfg)
            self.assertEqual(build.call_args.args[0][0].getpixel((0, 0)), (255, 255, 255))

        (job / "question_pages/page-001.png").unlink()
        with self.assertRaisesRegex(RuntimeError, "选题图片不存在"):
            export_pdf(job_id, owner, ["p1-q1"], cfg=cfg)

    def test_legacy_metadata_has_optional_question_geometry(self):
        page = PageInfo(**{"page": 1, "image_url": "original", "cleaned_image_url": "cleaned", "width": 100, "height": 100})
        self.assertIsNone(page.question_image_url)

    def test_later_page_failure_keeps_previous_detection_image(self):
        (self.root / "cleaned_pages").mkdir()
        (self.root / "question_pages").mkdir()
        for index in (1, 2):
            Image.new("RGB", (100, 100), "white").save(self.root / f"cleaned_pages/page-{index:03d}.png")
        previous = self.root / "question_pages/page-001.png"
        Image.new("RGB", (100, 100), "white").save(previous)

        def detect(*, image_path, page, output_path):
            if page == 2:
                raise RuntimeError("second page failed")
            return self.splitter._save_detection(response_for(Image.new("RGB", (100, 100), "black")), output_path, page, Question, parse_question_label)

        with patch("app.pipeline.TencentQuestionSplitter") as factory:
            factory.return_value.detect.side_effect = detect
            with self.assertRaisesRegex(RuntimeError, "second page failed"):
                detect_questions(self.root, [PageInfo(i, "original", "cleaned", 100, 100) for i in (1, 2)], settings)
        with Image.open(previous) as saved:
            self.assertEqual(saved.getpixel((0, 0)), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
