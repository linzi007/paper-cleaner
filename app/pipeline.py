import base64
import io
import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageFilter, ImageMath, ImageOps

from .config import Settings, settings
from .providers.tencent_ocr import TencentHandwritingEraser, TencentQuestionSplitter


SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@dataclass
class PageInfo:
    page: int
    image_url: str
    cleaned_image_url: str
    width: int
    height: int


@dataclass
class Question:
    id: str
    page: int
    index: int
    label: str
    bbox: list[int]
    text: str
    source: str


def create_job(upload_files: list[tuple[Any, str]], owner: dict[str, str], cfg: Settings = settings) -> dict[str, Any]:
    if not upload_files:
        raise ValueError("请上传文件")
    if len(upload_files) > cfg.max_pages:
        raise ValueError(f"上传文件数超过上限 {cfg.max_pages} 个")

    job_id = uuid.uuid4().hex[:16]
    job_dir = job_dir_for(owner["phone"], job_id, cfg)
    pages_dir = job_dir / "pages"
    job_dir.mkdir(parents=True, exist_ok=False)
    pages_dir.mkdir(parents=True, exist_ok=True)

    source_paths: list[Path] = []
    for index, (upload_file, filename) in enumerate(upload_files, start=1):
        suffix = Path(filename or f"upload-{index}").suffix.lower()
        if len(upload_files) > 1 and suffix == ".pdf":
            raise ValueError("一次上传多个文件时只支持图片；PDF 请单独上传")
        upload_path = job_dir / f"source-{index:03d}{suffix or '.bin'}"
        with upload_path.open("wb") as out:
            shutil.copyfileobj(upload_file, out)
        source_paths.append(upload_path)

    pages = render_uploaded_pages(source_paths, pages_dir, cfg)
    cleaning = prepare_clean_pages(job_dir, pages, cfg)
    now = int(time.time())

    metadata = {
        "job_id": job_id,
        "filename": upload_files[0][1] if len(upload_files) == 1 else f"{len(upload_files)} files",
        "owner": {
            "username": owner["username"],
            "phone": owner["phone"],
        },
        "created_at": now,
        "updated_at": now,
        "pages": [asdict(page) for page in pages],
        "questions": [],
        "questions_detected": False,
        "cleaning": cleaning,
    }
    write_json(job_dir / "meta.json", metadata)
    return metadata


def list_user_jobs(owner_phone: str, cfg: Settings = settings) -> list[dict[str, Any]]:
    root = user_jobs_dir(owner_phone, cfg)
    if not root.exists():
        return []

    jobs: list[dict[str, Any]] = []
    for meta_path in root.glob("*/meta.json"):
        try:
            metadata = read_json(meta_path)
        except Exception:
            continue
        jobs.append(job_summary(metadata, meta_path.parent))
    return sorted(jobs, key=lambda item: item.get("created_at", 0), reverse=True)


def read_job_metadata(job_id: str, owner_phone: str, cfg: Settings = settings) -> dict[str, Any]:
    return read_json(job_dir_for(owner_phone, job_id, cfg) / "meta.json")


def job_dir_for(owner_phone: str, job_id: str, cfg: Settings = settings) -> Path:
    if not re.fullmatch(r"[0-9a-f]{16}", job_id):
        raise FileNotFoundError("job not found")
    return user_jobs_dir(owner_phone, cfg) / job_id


def user_jobs_dir(owner_phone: str, cfg: Settings = settings) -> Path:
    phone = normalize_owner_phone(owner_phone)
    root = cfg.data_dir / "jobs" / "by-user" / phone
    root.mkdir(parents=True, exist_ok=True)
    return root


def normalize_owner_phone(owner_phone: str) -> str:
    phone = "".join(character for character in str(owner_phone) if character.isdigit())
    if not phone:
        raise ValueError("用户手机号不能为空")
    return phone


def job_summary(metadata: dict[str, Any], job_dir: Path) -> dict[str, Any]:
    pages = metadata.get("pages") or []
    questions = metadata.get("questions") or []
    output_path = job_dir / "output.pdf"
    return {
        "job_id": metadata.get("job_id"),
        "filename": metadata.get("filename") or "未命名",
        "created_at": int(metadata.get("created_at") or job_dir.stat().st_mtime),
        "updated_at": int(metadata.get("updated_at") or job_dir.stat().st_mtime),
        "pages_count": len(pages),
        "questions_count": len(questions),
        "questions_detected": bool(metadata.get("questions_detected")),
        "has_output": output_path.exists(),
    }


def render_uploaded_pages(source_paths: list[Path], pages_dir: Path, cfg: Settings) -> list[PageInfo]:
    pages: list[PageInfo] = []
    next_page = 1
    for source_path in source_paths:
        rendered = render_pages(source_path, pages_dir, cfg, start_page=next_page)
        pages.extend(rendered)
        next_page += len(rendered)
        if len(pages) > cfg.max_pages:
            raise ValueError(f"页数超过上限 {cfg.max_pages} 页")
    return pages


def render_pages(upload_path: Path, pages_dir: Path, cfg: Settings, start_page: int = 1) -> list[PageInfo]:
    suffix = upload_path.suffix.lower()
    pages: list[PageInfo] = []

    if suffix == ".pdf":
        with fitz.open(upload_path) as document:
            if start_page + len(document) - 1 > cfg.max_pages:
                raise ValueError(f"PDF 页数超过上限 {cfg.max_pages} 页")
            scale = cfg.render_dpi / 72
            matrix = fitz.Matrix(scale, scale)
            for offset, page in enumerate(document):
                page_no = start_page + offset
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image_path = pages_dir / f"page-{page_no:03d}.png"
                pixmap.save(image_path)
                pages.append(
                    PageInfo(
                        page=page_no,
                        image_url=f"/api/jobs/{{job_id}}/pages/{page_no}",
                        cleaned_image_url=f"/api/jobs/{{job_id}}/cleaned-pages/{page_no}",
                        width=pixmap.width,
                        height=pixmap.height,
                    )
                )
        return pages

    if suffix not in SUPPORTED_IMAGES:
        raise ValueError("只支持 PDF、PNG、JPG、JPEG、BMP、WEBP")

    with Image.open(upload_path) as image:
        image = image.convert("RGB")
        image.thumbnail((2600, 3600), Image.Resampling.LANCZOS)
        image_path = pages_dir / f"page-{start_page:03d}.png"
        image.save(image_path)
        width, height = image.size
        pages.append(
            PageInfo(
                page=start_page,
                image_url=f"/api/jobs/{{job_id}}/pages/{start_page}",
                cleaned_image_url=f"/api/jobs/{{job_id}}/cleaned-pages/{start_page}",
                width=width,
                height=height,
            )
        )
    return pages


def detect_questions(job_dir: Path, pages: list[PageInfo], cfg: Settings) -> list[Question]:
    questions: list[Question] = []
    splitter = TencentQuestionSplitter(cfg)

    for page in pages:
        cleaned_path = job_dir / "cleaned_pages" / f"page-{page.page:03d}.png"
        if not cleaned_path.exists():
            raise RuntimeError(f"第 {page.page} 页清痕图不存在，无法识别题目")
        detected = splitter.detect(image_path=cleaned_path, page=page.page)
        if not detected:
            raise RuntimeError(f"第 {page.page} 页未识别到题目区域")
        questions.extend(detected)

    return questions


def detect_job_questions(job_id: str, owner_phone: str, cfg: Settings = settings) -> dict[str, Any]:
    job_dir = job_dir_for(owner_phone, job_id, cfg)
    meta_path = job_dir / "meta.json"
    metadata = read_json(meta_path)
    pages = [PageInfo(**page) for page in metadata["pages"]]
    questions = detect_questions(job_dir, pages, cfg)
    metadata["questions"] = [asdict(question) for question in questions]
    metadata["questions_detected"] = True
    metadata["updated_at"] = int(time.time())
    write_json(meta_path, metadata)
    return metadata


def export_pdf(
    job_id: str,
    owner_phone: str,
    question_ids: list[str],
    regions: list[dict[str, Any]] | None = None,
    cfg: Settings = settings,
) -> Path:
    job_dir = job_dir_for(owner_phone, job_id, cfg)
    meta = read_json(job_dir / "meta.json")
    if regions:
        selected = normalize_export_regions(regions)
    else:
        question_map = {item["id"]: item for item in meta["questions"]}
        selected = [question_map[qid] for qid in question_ids if qid in question_map]
    if not selected:
        return export_cleaned_pages(job_dir, meta)

    crops: list[Image.Image] = []
    for question in selected:
        page = int(question["page"])
        cleaned_page_path = job_dir / "cleaned_pages" / f"page-{page:03d}.png"
        if not cleaned_page_path.exists():
            raise RuntimeError(f"第 {page} 页清痕图不存在，无法导出")
        page_path = cleaned_page_path
        with Image.open(page_path) as page_image:
            page_image = page_image.convert("RGB")
            bbox = expand_bbox(question["bbox"], page_image.width, page_image.height, padding=14)
            crop = page_image.crop(tuple(bbox))
            crops.append(normalize_print_background(crop))

    output_path = job_dir / "output.pdf"
    build_a4_pdf(crops, output_path)
    meta["updated_at"] = int(time.time())
    meta["last_export"] = {
        "created_at": meta["updated_at"],
        "regions": selected,
        "question_ids": question_ids,
    }
    write_json(job_dir / "meta.json", meta)
    return output_path


def export_cleaned_pages(job_dir: Path, meta: dict[str, Any]) -> Path:
    pages: list[Image.Image] = []
    for page in meta["pages"]:
        page_no = int(page["page"])
        cleaned_page_path = job_dir / "cleaned_pages" / f"page-{page_no:03d}.png"
        if not cleaned_page_path.exists():
            raise RuntimeError(f"第 {page_no} 页清痕图不存在，无法导出")
        with Image.open(cleaned_page_path) as page_image:
            pages.append(normalize_print_background(page_image))

    output_path = job_dir / "output.pdf"
    build_a4_pdf(pages, output_path)
    meta["updated_at"] = int(time.time())
    meta["last_export"] = {
        "created_at": meta["updated_at"],
        "regions": [],
        "question_ids": [],
    }
    write_json(job_dir / "meta.json", meta)
    return output_path


def normalize_export_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, region in enumerate(regions, start=1):
        bbox = region.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"第 {index} 个导出区域 bbox 不合法")
        normalized.append(
            {
                "id": region.get("id") or f"region-{index}",
                "page": int(region["page"]),
                "bbox": [int(value) for value in bbox],
                "label": region.get("label") or f"区域 {index}",
                "question_ids": [str(value) for value in region.get("question_ids", [])],
            }
        )
    return normalized


def prepare_clean_pages(job_dir: Path, pages: list[PageInfo], cfg: Settings) -> dict[str, Any]:
    cleaned_dir = job_dir / "cleaned_pages"
    cleaned_dir.mkdir(parents=True, exist_ok=True)

    eraser = TencentHandwritingEraser(cfg)
    results: list[dict[str, Any]] = []
    for page in pages:
        page_no = page.page
        source_path = job_dir / "pages" / f"page-{page_no:03d}.png"
        target_path = cleaned_dir / f"page-{page_no:03d}.png"
        result = eraser.erase(source_path, target_path)
        with Image.open(target_path) as image:
            page.width, page.height = image.size
        results.append({"page": page_no, **result})
    return {"provider": "tencent", "pages": results}


def build_a4_pdf(images: list[Image.Image], output_path: Path) -> None:
    a4_width, a4_height = 1240, 1754
    margin = 70
    gap = 36
    pages: list[Image.Image] = []
    sheet = Image.new("RGB", (a4_width, a4_height), "white")
    cursor_y = margin

    for image in images:
        image = image.convert("RGB")
        max_width = a4_width - margin * 2
        max_height = a4_height - margin * 2
        scale = min(max_width / image.width, max_height / image.height, 1.0)
        target = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)

        if cursor_y + target.height > a4_height - margin and cursor_y > margin:
            pages.append(sheet)
            sheet = Image.new("RGB", (a4_width, a4_height), "white")
            cursor_y = margin

        x = margin
        sheet.paste(target, (x, cursor_y))
        cursor_y += target.height + gap

    pages.append(sheet)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(output_path, "PDF", save_all=True, append_images=pages[1:], resolution=150.0)


def normalize_print_background(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    gray = ImageOps.grayscale(image)
    gray = flatten_page_shadow(gray)
    histogram = gray.histogram()
    total = sum(histogram)
    if total <= 0:
        return image.copy()

    black_point = histogram_percentile(histogram, total, 0.03)
    paper_point = histogram_percentile(histogram, total, 0.72)
    if paper_point < 170:
        paper_point = histogram_percentile(histogram, total, 0.90)

    white_point = min(245, max(175, paper_point))
    black_point = max(0, min(125, black_point + 8))
    if white_point - black_point < 45:
        black_point = max(0, white_point - 90)

    span = max(1, white_point - black_point)
    lut: list[int] = []
    for pixel in range(256):
        if pixel <= black_point:
            lut.append(0)
        elif pixel >= white_point:
            lut.append(255)
        else:
            value = (pixel - black_point) / span
            lut.append(round(255 * (value ** 0.58)))

    normalized = gray.point(lut)
    normalized = normalized.point(lambda pixel: 255 if pixel >= 214 else pixel)
    return normalized.convert("RGB")


def flatten_page_shadow(gray: Image.Image) -> Image.Image:
    radius = max(18, min(96, min(gray.size) // 18))
    background = gray.filter(ImageFilter.GaussianBlur(radius=radius))
    background = background.point(lambda pixel: max(1, pixel))
    flattened = ImageMath.eval("convert(a * 255 / b, 'L')", a=gray, b=background)
    return ImageOps.autocontrast(flattened, cutoff=1)


def histogram_percentile(histogram: list[int], total: int, percentile: float) -> int:
    target = total * percentile
    count = 0
    for value, bucket in enumerate(histogram):
        count += bucket
        if count >= target:
            return value
    return 255


def image_base64_under_limit(image_path: Path, limit_chars: int = 9_500_000) -> str:
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


def parse_question_label(text: str, default_label: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    match = re.match(r"^([0-9]{1,3}[.、)）]|[一二三四五六七八九十]{1,4}[.、])", compact)
    if not match:
        return default_label
    return match.group(1).rstrip(".、)）")


def expand_bbox(bbox: list[int], width: int, height: int, padding: int) -> list[int]:
    return _clamp_bbox([bbox[0] - padding, bbox[1] - padding, bbox[2] + padding, bbox[3] + padding], width, height)


def _clamp_bbox(bbox: list[int], width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = bbox
    return [max(0, int(x1)), max(0, int(y1)), min(width, int(x2)), min(height, int(y2))]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
