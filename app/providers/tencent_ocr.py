import base64
import datetime
import hashlib
import hmac
import io
import json
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

import requests
from PIL import Image

from ..config import Settings


OCR_HOST = "ocr.tencentcloudapi.com"
OCR_VERSION = "2018-11-19"


@dataclass
class QuestionDetection:
    questions: list[Any]
    width: int
    height: int


class TencentQuestionSplitter:
    def __init__(self, cfg: Settings):
        if not cfg.tencent_secret_id or not cfg.tencent_secret_key:
            raise RuntimeError("缺少 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")

        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.ocr.v20181119 import ocr_client

        http_profile = HttpProfile()
        http_profile.endpoint = "ocr.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        cred = credential.Credential(cfg.tencent_secret_id, cfg.tencent_secret_key)
        self.client = ocr_client.OcrClient(cred, cfg.tencent_region, client_profile)
        self.use_new_model = cfg.tencent_use_new_model

    def detect(self, image_path: Path, page: int, output_path: Path) -> QuestionDetection:
        from tencentcloud.ocr.v20181119 import models

        from ..pipeline import Question, image_base64_under_limit, parse_question_label

        req = models.QuestionSplitOCRRequest()
        req.ImageBase64 = image_base64_under_limit(image_path)
        req.EnableImageCrop = True
        req.EnableOnlyDetectBorder = False
        req.UseNewModel = self.use_new_model

        resp = self.client.QuestionSplitOCR(req)
        data = json.loads(resp.to_json_string())
        return self._save_detection(data, output_path, page, Question, parse_question_label)

    def _save_detection(self, data, output_path, page, question_cls, label_parser) -> QuestionDetection:
        # The service may dewarp the page without changing its dimensions.
        # Its boxes belong to the returned image, not to the submitted image.
        infos = data.get("QuestionInfo") or []
        if len(infos) != 1:
            raise RuntimeError("单页题目识别未返回唯一的页面结果")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostic = {
            "RequestId": data.get("RequestId"),
            "EnableImageCrop": True,
            "QuestionInfo": [{key: value for key, value in info.items() if key != "ImageBase64"} for info in infos],
        }
        output_path.with_suffix(".json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
        info = infos[0]
        encoded = info.get("ImageBase64")
        if not encoded:
            raise RuntimeError("题目识别未返回校正图，无法安全定位题框，请重试")
        with Image.open(io.BytesIO(_decode_image_value(encoded))) as image:
            width, height = image.size
            if (info.get("Width") and int(info["Width"]) != width) or (info.get("Height") and int(info["Height"]) != height):
                raise RuntimeError("题目识别返回的图片与坐标尺寸不一致，请重试")
            questions = self._parse_response(data, page, question_cls, label_parser)
            if not questions:
                raise RuntimeError(f"第 {page} 页未识别到题目区域")
            image.convert("RGB").save(output_path, format="PNG")
        return QuestionDetection(questions=questions, width=width, height=height)

    def _parse_response(self, data: dict[str, Any], page: int, question_cls, label_parser):
        questions = []
        result_items = []
        for info in data.get("QuestionInfo") or []:
            result_items.extend(info.get("ResultList") or [])

        for idx, item in enumerate(result_items, start=1):
            bbox = _bbox_from_result_item(item)
            if not bbox:
                continue
            text = _extract_question_text(item)
            label = label_parser(text, f"第 {page} 页-{idx}")
            questions.append(
                question_cls(
                    id=f"p{page}-q{idx}",
                    page=page,
                    index=idx,
                    label=label,
                    bbox=bbox,
                    text=text[:160],
                    source="tencent",
                )
            )
        return questions


class TencentHandwritingEraser:
    def __init__(self, cfg: Settings):
        if not cfg.tencent_secret_id or not cfg.tencent_secret_key:
            raise RuntimeError("缺少 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")
        self.secret_id = cfg.tencent_secret_id
        self.secret_key = cfg.tencent_secret_key
        self.region = cfg.tencent_region

    def erase(self, image_path: Path, output_path: Path) -> dict[str, Any]:
        response = self._call("EraseHandwrittenImageOCR", {"ImageBase64": _image_base64_under_limit(image_path)})
        image_value = _first_present(response, ("Image", "ImageBase64", "ResultImage", "ResultImageBase64"))
        if not image_value:
            raise RuntimeError(f"腾讯云手写擦除成功但未返回图片字段，返回字段：{','.join(sorted(response.keys()))}")

        image_bytes = _decode_image_value(image_value)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.convert("RGB").save(output_path, format="PNG")
        with Image.open(output_path) as image:
            image.verify()
        return {"request_id": response.get("RequestId"), "bytes": output_path.stat().st_size}

    def _call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":"))
        timestamp = int(time.time())
        date = datetime.datetime.fromtimestamp(timestamp, datetime.UTC).strftime("%Y-%m-%d")
        service = "ocr"
        algorithm = "TC3-HMAC-SHA256"
        canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{OCR_HOST}\nx-tc-action:{action.lower()}\n"
        signed_headers = "content-type;host;x-tc-action"
        hashed_payload = hashlib.sha256(body.encode("utf-8")).hexdigest()
        canonical_request = "\n".join(["POST", "/", "", canonical_headers, signed_headers, hashed_payload])
        credential_scope = f"{date}/{service}/tc3_request"
        string_to_sign = "\n".join(
            [
                algorithm,
                str(timestamp),
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = _tc3_signing_key(self.secret_key, date, service)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            f"{algorithm} Credential={self.secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": OCR_HOST,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": OCR_VERSION,
            "X-TC-Region": self.region,
        }
        resp = requests.post(f"https://{OCR_HOST}", data=body.encode("utf-8"), headers=headers, timeout=90)
        data = resp.json()
        response = data.get("Response", {})
        error = response.get("Error") if isinstance(response, dict) else None
        if error:
            raise RuntimeError(f"[TencentCloudAPI] code:{error.get('Code')} message:{error.get('Message')} requestId:{response.get('RequestId')}")
        if not resp.ok:
            raise RuntimeError(f"腾讯云 HTTP {resp.status_code}: {resp.text[:300]}")
        return response


def _extract_question_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for element in item.get("Question") or []:
        text = element.get("Text")
        if text:
            parts.append(text)
    if not parts and item.get("Text"):
        parts.append(item["Text"])
    return " ".join(parts).strip()


def _image_base64_under_limit(image_path: Path, limit_chars: int = 9_500_000) -> str:
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        scale = 1.0
        quality = 90
        while True:
            candidate = image
            if scale < 1.0:
                candidate = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            candidate.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            encoded = base64.b64encode(data)
            if len(encoded) <= limit_chars:
                return encoded.decode("ascii")
            if quality > 68:
                quality -= 8
            else:
                scale *= 0.86


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _decode_image_value(value: str) -> bytes:
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def _tc3_signing_key(secret_key: str, date: str, service: str) -> bytes:
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, service)
    return _hmac_sha256(secret_service, "tc3_request")


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _bbox_from_polygons(polygons: Any) -> list[int] | None:
    if not polygons:
        return None
    if isinstance(polygons, dict):
        polygons = [polygons]

    xs: list[int] = []
    ys: list[int] = []
    for polygon in polygons:
        for key in ("LeftTop", "RightTop", "RightBottom", "LeftBottom"):
            point = polygon.get(key) if isinstance(polygon, dict) else None
            if not point:
                continue
            x = point.get("X")
            y = point.get("Y")
            if x is not None and y is not None:
                xs.append(int(x))
                ys.append(int(y))

    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_from_result_item(item: dict[str, Any]) -> list[int] | None:
    bboxes: list[list[int]] = []
    primary = _bbox_from_polygons(item.get("Coord"))
    if primary:
        bboxes.append(primary)

    for key in ("Question", "Option", "Answer", "Figure", "Table", "Parse"):
        for element in item.get(key) or []:
            if not isinstance(element, dict):
                continue
            bbox = _bbox_from_polygons(element.get("Coord"))
            if bbox:
                bboxes.append(bbox)

    if not bboxes:
        return None
    return [
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    ]
