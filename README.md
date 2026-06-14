# Paper Cleaner

[English](./README.en.md)

Paper Cleaner 是一个用于清理试卷做题痕迹、重新生成可打印练习卷的轻量 Web 服务。

它的核心流程是：

1. 上传一份 PDF，或一次上传多张试卷图片。
2. 调用腾讯云 OCR 清除手写做题痕迹。
3. 直接预览、打印整张清痕后的试卷。
4. 可选：识别题目区域，选择需要重做的题目，手动微调题目框，再合并导出 PDF。

项目偏向自用和家庭场景，前端以手机 H5 操作为主，后端使用 FastAPI，本地文件存储用户、历史任务和导出结果。

## 开源仓库

```text
https://github.com/linzi007/paper-cleaner
```

## 功能

- 使用腾讯云 `EraseHandwrittenImageOCR` 清除试卷手写痕迹。
- 使用腾讯云 `QuestionSplitOCR` 识别题目区域。
- 支持 PDF 和常见图片格式上传。
- 支持一次上传多张图片，多张图片会作为同一个任务的多页处理。
- 支持整卷预览、打印、下载。
- 支持选择部分题目，生成错题或专项重练 PDF。
- 支持手动调整 OCR 识别出的题目框。
- 支持手机号和密码登录。
- 按用户隔离历史任务。
- 定时清理旧任务和日志。
- Docker Compose 部署，默认只监听 `127.0.0.1:8091`，适合用 Nginx 反向代理到公网。

## 不会提交到仓库的内容

以下内容属于运行时密钥、用户数据或上传文件，已经通过 `.gitignore` 排除，不应该提交到 GitHub：

- `.env`
- `.env.*`
- `data/`
- `data/users.json`
- `data/auth_secret.txt`
- `data/jobs/`
- 用户上传的试卷图片
- 生成的清痕图片和 PDF
- IDE 配置、Python 缓存、日志、虚拟环境

发布前建议检查：

```bash
git status --ignored --short
git ls-files
```

正常情况下，仓库里只应该包含源码、示例配置、Docker 配置和文档。

## 环境要求

- Python 3.12+
- Docker 和 Docker Compose，可选但推荐
- 已开通腾讯云 OCR
- 腾讯云 API 密钥具备 OCR 相关接口权限

## 配置

复制示例配置：

```bash
cp .env.example .env
```

填写腾讯云 OCR 密钥：

```bash
TENCENTCLOUD_SECRET_ID=your-secret-id
TENCENTCLOUD_SECRET_KEY=your-secret-key
TENCENTCLOUD_REGION=ap-guangzhou
PAPER_CLEANER_TENCENT_USE_NEW_MODEL=true
PAPER_CLEANER_MAX_PAGES=20
PAPER_CLEANER_DEFAULT_ADMIN_PHONE=13800000000
```

说明：

- `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY` 不要提交到 git。
- `PAPER_CLEANER_DEFAULT_ADMIN_PHONE` 只在首次启动且 `data/users.json` 不存在时生效。
- `PAPER_CLEANER_MAX_PAGES` 用于限制单个任务最多处理页数。

当前项目没有本地清痕兜底逻辑。如果腾讯云清痕或题目识别失败，本次任务会直接失败。

## 本地运行

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8091
```

打开：

```text
http://127.0.0.1:8091
```

## Docker 运行

```bash
docker compose up -d --build
```

服务默认监听：

```text
127.0.0.1:8091
```

容器会把当前目录下的 `./data` 挂载到容器内 `/data`。生产环境中需要持久化这个目录，但不要把它提交到仓库。

## 第一次登录

首次启动时，如果 `data/users.json` 不存在，系统会自动创建一个 `admin` 用户：

- 手机号：`PAPER_CLEANER_DEFAULT_ADMIN_PHONE`，默认 `13800000000`
- 密码：随机生成，并写入 `data/admin-password.txt`

查看初始密码：

```bash
cat data/admin-password.txt
```

添加或更新用户：

```bash
python -m app.auth add-user <用户名> <手机号> <密码>
python -m app.auth list-users
```

Docker 环境下：

```bash
docker exec -it paper-cleaner python -m app.auth add-user <用户名> <手机号> <密码>
docker exec -it paper-cleaner python -m app.auth list-users
```

## Nginx 反向代理

示例配置：

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

公网部署建议启用 HTTPS。PDF 预览和下载使用短期签名链接，方便移动端在微信、系统浏览器或 PDF 查看器之间切换时仍能打开文件。

## 数据保留

任务和日志默认保存在 `data/` 下，可以通过以下环境变量控制清理策略：

```bash
PAPER_CLEANER_JOB_RETENTION_DAYS=7
PAPER_CLEANER_LOG_RETENTION_DAYS=7
PAPER_CLEANER_CLEANUP_INTERVAL_MINUTES=360
```

## 许可证

当前还没有添加开源许可证文件。正式接受外部贡献前，建议补充 `LICENSE`。
