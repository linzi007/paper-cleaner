from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import (
    authenticate_user,
    clear_login_cookie,
    create_job_access_token,
    ensure_auth_storage,
    get_request_user,
    require_user,
    set_login_cookie,
    verify_job_access_token,
)
from .cleanup import start_cleanup_worker
from .config import settings
from .pipeline import (
    create_job,
    detect_job_questions,
    export_pdf,
    job_dir_for,
    list_user_jobs,
    read_job_metadata,
)


app = FastAPI(title="Paper Cleaner", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class ExportRegion(BaseModel):
    id: str | None = None
    page: int
    bbox: list[int]
    label: str | None = None
    question_ids: list[str] = Field(default_factory=list)


class ExportRequest(BaseModel):
    question_ids: list[str] = Field(default_factory=list)
    regions: list[ExportRegion] = Field(default_factory=list)


class LoginRequest(BaseModel):
    phone: str
    password: str


@app.on_event("startup")
def startup() -> None:
    ensure_auth_storage()
    start_cleanup_worker()


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    template = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(
        template.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "tencent_configured": bool(settings.tencent_secret_id and settings.tencent_secret_key),
    }


@app.post("/api/auth/login")
def login(request: LoginRequest, response: Response) -> dict:
    user = authenticate_user(request.phone, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="手机号或密码错误")
    set_login_cookie(response, user)
    return {"authenticated": True, "user": user}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    clear_login_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(require_user)) -> dict:
    return {"authenticated": True, "user": user}


@app.get("/api/jobs")
def list_jobs(user: dict = Depends(require_user)) -> dict:
    return {"jobs": list_user_jobs(user["phone"])}


@app.post("/api/jobs")
def upload(files: list[UploadFile] = File(...), user: dict = Depends(require_user)) -> dict:
    try:
        metadata = create_job(
            [(file.file, file.filename or f"upload-{index}") for index, file in enumerate(files, start=1)],
            user,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return hydrate_metadata_urls(metadata)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: dict = Depends(require_user)) -> dict:
    try:
        metadata = read_job_metadata(job_id, user["phone"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found")
    return hydrate_metadata_urls(metadata)


@app.post("/api/jobs/{job_id}/questions")
def detect_questions(job_id: str, user: dict = Depends(require_user)) -> dict:
    try:
        metadata = detect_job_questions(job_id, user["phone"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return hydrate_metadata_urls(metadata)


@app.get("/api/jobs/{job_id}/pages/{page}")
def original_page_image(job_id: str, page: int, user: dict = Depends(require_user)):
    image_path = job_dir_for(user["phone"], job_id) / "pages" / f"page-{page:03d}.png"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="page not found")
    return FileResponse(image_path, media_type="image/png")


@app.get("/api/jobs/{job_id}/cleaned-pages/{page}")
def cleaned_page_image(job_id: str, page: int, user: dict = Depends(require_user)):
    image_path = job_dir_for(user["phone"], job_id) / "cleaned_pages" / f"page-{page:03d}.png"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="cleaned page not found")
    return FileResponse(image_path, media_type="image/png")


@app.post("/api/jobs/{job_id}/export")
def export(job_id: str, request: ExportRequest, user: dict = Depends(require_user)) -> dict:
    try:
        output = export_pdf(job_id, user["phone"], request.question_ids, [region.model_dump() for region in request.regions])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    access_token = create_job_access_token(user["phone"], job_id)
    return {
        "preview_pdf_url": f"/api/jobs/{job_id}/preview.pdf?access_token={access_token}",
        "download_pdf_url": f"/api/jobs/{job_id}/export.pdf?access_token={access_token}",
        "path": str(output),
    }


@app.get("/api/jobs/{job_id}/question-pages/{page}")
def question_page_image(job_id: str, page: int, user: dict = Depends(require_user)):
    image_path = job_dir_for(user["phone"], job_id) / "question_pages" / f"page-{page:03d}.png"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="question page not found")
    return FileResponse(image_path, media_type="image/png")


@app.get("/api/jobs/{job_id}/preview.pdf")
def preview_file(job_id: str, request: Request, access_token: str | None = None):
    phone = resolve_job_file_phone(request, job_id, access_token)
    output = job_dir_for(phone, job_id) / "output.pdf"
    if not output.exists():
        raise HTTPException(status_code=404, detail="export not found")
    return FileResponse(
        output,
        media_type="application/pdf",
        filename=f"paper-cleaner-{job_id}.pdf",
        content_disposition_type="inline",
    )


@app.get("/api/jobs/{job_id}/export.pdf")
def export_file(job_id: str, request: Request, access_token: str | None = None):
    phone = resolve_job_file_phone(request, job_id, access_token)
    output = job_dir_for(phone, job_id) / "output.pdf"
    if not output.exists():
        raise HTTPException(status_code=404, detail="export not found")
    return FileResponse(
        output,
        media_type="application/pdf",
        filename=f"paper-cleaner-{job_id}.pdf",
        content_disposition_type="attachment",
    )


def resolve_job_file_phone(request: Request, job_id: str, access_token: str | None) -> str:
    token_phone = verify_job_access_token(access_token, job_id)
    if token_phone:
        return token_phone

    user = get_request_user(request)
    if user:
        return user["phone"]

    raise HTTPException(status_code=401, detail="not authenticated")


def hydrate_metadata_urls(metadata: dict) -> dict:
    job_id = metadata["job_id"]
    for page in metadata["pages"]:
        page["image_url"] = page["image_url"].replace("{job_id}", job_id)
        page["cleaned_image_url"] = page["cleaned_image_url"].replace("{job_id}", job_id)
        if page.get("question_image_url"):
            page["question_image_url"] = page["question_image_url"].replace("{job_id}", job_id)
    return metadata
