# Paper Cleaner

[中文](./README.md)

Paper Cleaner is a lightweight web service for cleaning marked exam papers and generating repeat-printable practice sheets.

Core workflow:

1. Upload one PDF or multiple paper images.
2. Remove handwriting traces with Tencent Cloud OCR.
3. Preview, print, or download the full cleaned paper.
4. Optionally detect question regions, select questions, adjust boxes manually, and export a merged PDF.

The project is designed for personal and family use. The UI is mobile-first, the backend is built with FastAPI, and runtime users, jobs, and exports are stored in local files.

## Repository

```text
https://github.com/linzi007/paper-cleaner
```

## Features

- Uses Tencent Cloud `EraseHandwrittenImageOCR` for handwriting removal.
- Uses Tencent Cloud `QuestionSplitOCR` for question region detection.
- Supports PDF and common image uploads.
- Supports uploading multiple images as multiple pages in one job.
- Supports full-paper preview, print, and download.
- Supports selecting specific questions for retry or mistake review sheets.
- Supports manual adjustment of OCR-detected question boxes.
- Supports phone-number and password login.
- Keeps job history separated by user.
- Cleans up old jobs and logs on a schedule.
- Deploys with Docker Compose on `127.0.0.1:8091`, suitable for an Nginx reverse proxy.

## What Is Not Committed

Runtime secrets, user data, and uploaded files are excluded by `.gitignore` and should not be committed:

- `.env`
- `.env.*`
- `data/`
- `data/users.json`
- `data/auth_secret.txt`
- `data/jobs/`
- uploaded paper images
- generated cleaned images and PDFs
- IDE files, Python caches, logs, and virtual environments

Before publishing, check:

```bash
git status --ignored --short
git ls-files
```

Only source code, sample configuration, Docker configuration, and documentation should be tracked.

## Requirements

- Python 3.12+
- Docker and Docker Compose, optional but recommended
- Tencent Cloud OCR enabled
- Tencent Cloud API credentials with OCR permissions

## Configuration

Copy the sample environment file:

```bash
cp .env.example .env
```

Fill in Tencent Cloud OCR credentials:

```bash
TENCENTCLOUD_SECRET_ID=your-secret-id
TENCENTCLOUD_SECRET_KEY=your-secret-key
TENCENTCLOUD_REGION=ap-guangzhou
PAPER_CLEANER_TENCENT_USE_NEW_MODEL=true
PAPER_CLEANER_MAX_PAGES=20
PAPER_CLEANER_DEFAULT_ADMIN_PHONE=13800000000
```

Notes:

- Do not commit `TENCENTCLOUD_SECRET_ID` or `TENCENTCLOUD_SECRET_KEY`.
- `PAPER_CLEANER_DEFAULT_ADMIN_PHONE` is only used on first startup when `data/users.json` does not exist.
- `PAPER_CLEANER_MAX_PAGES` limits the maximum pages per job.

There is no local handwriting-removal fallback. If Tencent Cloud cleanup or question detection fails, the current job fails directly.

## Local Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8091
```

Open:

```text
http://127.0.0.1:8091
```

## Docker

```bash
docker compose up -d --build
```

The service listens on:

```text
127.0.0.1:8091
```

The container mounts `./data` to `/data`. Keep this directory persistent in production, but do not commit it.

## First Login

On first startup, if `data/users.json` does not exist, the app creates an `admin` user:

- phone: value of `PAPER_CLEANER_DEFAULT_ADMIN_PHONE`, default `13800000000`
- password: randomly generated and written to `data/admin-password.txt`

Read the initial password:

```bash
cat data/admin-password.txt
```

Add or update users:

```bash
python -m app.auth add-user <username> <phone> <password>
python -m app.auth list-users
```

Inside Docker:

```bash
docker exec -it paper-cleaner python -m app.auth add-user <username> <phone> <password>
docker exec -it paper-cleaner python -m app.auth list-users
```

## Nginx Reverse Proxy

Example:

```nginx
server {
    server_name paper.example.com;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8091;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

Use HTTPS in production. PDF preview and download links use short-lived signed URLs so mobile browsers can hand files off between WeChat, system browsers, or PDF viewers without losing access.

## Data Retention

Jobs and logs are stored under `data/` by default. Retention is controlled by:

```bash
PAPER_CLEANER_JOB_RETENTION_DAYS=7
PAPER_CLEANER_LOG_RETENTION_DAYS=7
PAPER_CLEANER_CLEANUP_INTERVAL_MINUTES=360
```

## License

No open source license file is included yet. Add a `LICENSE` before accepting external contributions.
