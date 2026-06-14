import base64
import hashlib
import hmac
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, Response, status

from .config import settings


SESSION_COOKIE = "paper_cleaner_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
JOB_ACCESS_MAX_AGE_SECONDS = 2 * 60 * 60
PASSWORD_ITERATIONS = 260_000


def ensure_auth_storage() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    get_auth_secret()
    load_user_store()


def authenticate_user(phone: str, password: str) -> dict[str, str] | None:
    phone = normalize_phone(phone)
    for user in load_user_store()["users"]:
        if normalize_phone(user.get("phone", "")) != phone:
            continue
        if not user.get("active", True):
            return None
        if verify_password(password, user.get("password_hash", "")):
            return public_user(user)
        return None
    return None


def require_user(request: Request) -> dict[str, str]:
    user = get_request_user(request)
    if user:
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")


def get_request_user(request: Request) -> dict[str, str] | None:
    token = request.cookies.get(SESSION_COOKIE)
    payload = decode_session_token(token)
    if not payload:
        return None

    phone = normalize_phone(str(payload.get("phone", "")))
    for user in load_user_store()["users"]:
        if normalize_phone(user.get("phone", "")) == phone and user.get("active", True):
            return public_user(user)
    return None


def set_login_cookie(response: Response, user: dict[str, str]) -> None:
    token = create_session_token(user["phone"])
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )


def clear_login_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def create_or_update_user(username: str, phone: str, password: str, *, active: bool = True) -> dict[str, Any]:
    store = load_user_store()
    phone = normalize_phone(phone)
    if not username.strip():
        raise ValueError("用户名不能为空")
    if not phone:
        raise ValueError("手机号不能为空")
    if not password:
        raise ValueError("密码不能为空")

    users = store["users"]
    for user in users:
        if normalize_phone(user.get("phone", "")) == phone:
            user.update(
                {
                    "username": username.strip(),
                    "phone": phone,
                    "password_hash": hash_password(password),
                    "active": active,
                    "updated_at": int(time.time()),
                }
            )
            write_user_store(store)
            return public_user(user)

    user = {
        "username": username.strip(),
        "phone": phone,
        "password_hash": hash_password(password),
        "active": active,
        "created_at": int(time.time()),
    }
    users.append(user)
    write_user_store(store)
    return public_user(user)


def load_user_store() -> dict[str, Any]:
    users_path = users_file()
    if not users_path.exists():
        create_default_user_store(users_path)

    raw = json.loads(users_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = {"users": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("users"), list):
        raise RuntimeError("用户文件格式错误，应为 {\"users\": [...]}")

    changed = False
    for user in raw["users"]:
        if not isinstance(user, dict):
            raise RuntimeError("用户文件格式错误，users 只能包含对象")
        user["username"] = str(user.get("username") or "").strip()
        user["phone"] = normalize_phone(str(user.get("phone") or ""))
        user["active"] = bool(user.get("active", True))

        plain_password = user.pop("password", None)
        if plain_password:
            user["password_hash"] = hash_password(str(plain_password))
            user["updated_at"] = int(time.time())
            changed = True

        if not user["username"] or not user["phone"] or not user.get("password_hash"):
            raise RuntimeError("用户文件格式错误，每个用户都需要 username、phone、password_hash 或 password")

    if changed:
        write_user_store(raw)
    return raw


def write_user_store(store: dict[str, Any]) -> None:
    path = users_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)
    path.chmod(0o600)


def create_default_user_store(path: Path) -> None:
    password = secrets.token_urlsafe(12)
    default_phone = normalize_phone(settings.default_admin_phone) or "13800000000"
    store = {
        "users": [
            {
                "username": "admin",
                "phone": default_phone,
                "password_hash": hash_password(password),
                "active": True,
                "created_at": int(time.time()),
            }
        ]
    }
    write_user_store(store)
    password_file = path.parent / "admin-password.txt"
    password_file.write_text(password + "\n", encoding="utf-8")
    password_file.chmod(0o600)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${b64encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations))
        return hmac.compare_digest(b64encode(digest), expected)
    except Exception:
        return False


def create_session_token(phone: str) -> str:
    payload = {
        "phone": normalize_phone(phone),
        "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
    }
    payload_text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    payload_part = b64encode(payload_text.encode("utf-8"))
    signature = sign(payload_part.encode("ascii"))
    return f"{payload_part}.{signature}"


def decode_session_token(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    payload_part, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(sign(payload_part.encode("ascii")), signature):
        return None
    try:
        payload = json.loads(b64decode(payload_part).decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def create_job_access_token(phone: str, job_id: str) -> str:
    payload = {
        "kind": "job-access",
        "phone": normalize_phone(phone),
        "job_id": str(job_id),
        "exp": int(time.time()) + JOB_ACCESS_MAX_AGE_SECONDS,
    }
    payload_text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    payload_part = b64encode(payload_text.encode("utf-8"))
    signature = sign(payload_part.encode("ascii"))
    return f"{payload_part}.{signature}"


def verify_job_access_token(token: str | None, job_id: str) -> str | None:
    payload = decode_signed_payload(token)
    if not payload:
        return None
    if payload.get("kind") != "job-access" or str(payload.get("job_id", "")) != str(job_id):
        return None
    phone = normalize_phone(str(payload.get("phone", "")))
    if not phone:
        return None
    for user in load_user_store()["users"]:
        if normalize_phone(user.get("phone", "")) == phone and user.get("active", True):
            return phone
    return None


def decode_signed_payload(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    payload_part, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(sign(payload_part.encode("ascii")), signature):
        return None
    try:
        payload = json.loads(b64decode(payload_part).decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def sign(value: bytes) -> str:
    return b64encode(hmac.new(get_auth_secret(), value, hashlib.sha256).digest())


def get_auth_secret() -> bytes:
    path = settings.data_dir / "auth_secret.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip().encode("utf-8")


def public_user(user: dict[str, Any]) -> dict[str, str]:
    return {
        "username": str(user["username"]),
        "phone": str(user["phone"]),
    }


def normalize_phone(phone: str) -> str:
    return "".join(character for character in phone.strip() if character.isdigit())


def users_file() -> Path:
    return settings.data_dir / "users.json"


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def main(argv: list[str]) -> int:
    if len(argv) == 5 and argv[1] == "add-user":
        user = create_or_update_user(argv[2], argv[3], argv[4])
        print(f"saved user: {user['username']} {user['phone']}")
        return 0
    if len(argv) == 2 and argv[1] == "list-users":
        for user in load_user_store()["users"]:
            active = "active" if user.get("active", True) else "disabled"
            print(f"{user['username']}\t{user['phone']}\t{active}")
        return 0
    print("usage:")
    print("  python -m app.auth add-user <username> <phone> <password>")
    print("  python -m app.auth list-users")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
