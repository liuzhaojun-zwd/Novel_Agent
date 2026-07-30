"""Password hashing, opaque sessions, and project role authorization."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request

from app.database import get_db

SESSION_COOKIE = "novel_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
_PBKDF2_ITERATIONS = 600_000


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations),
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public_user(row) -> dict:
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


async def has_users() -> bool:
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM users LIMIT 1")
        return await cursor.fetchone() is not None
async def _create_session(db, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(seconds=SESSION_TTL_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")
    await db.execute(
        "INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (_token_hash(token), user_id, expires),
    )
    return token


async def bootstrap(username: str, password: str) -> tuple[dict, str]:
    """Create the first administrator and claim all legacy unowned jobs."""
    username = username.strip().lower()
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM users LIMIT 1")
        if await cursor.fetchone():
            raise RuntimeError("系统已初始化，请直接登录")
        user_id = secrets.token_hex(8)
        project_id = secrets.token_hex(8)
        await db.execute(
            "INSERT INTO users (id, username, password_hash, role) VALUES (?, ?, ?, 'admin')",
            (user_id, username, _hash_password(password)),
        )
        await db.execute(
            "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)",
            (project_id, user_id, f"{username} 的项目"),
        )
        await db.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (?, ?, 'owner')",
            (project_id, user_id),
        )
        await db.execute("UPDATE jobs SET project_id = ? WHERE project_id IS NULL", (project_id,))
        token = await _create_session(db, user_id)
    return {"id": user_id, "username": username, "role": "admin"}, token


async def login(username: str, password: str) -> Optional[tuple[dict, str]]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ? AND status = 'active'",
            (username.strip().lower(),),
        )
        row = await cursor.fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return None
        token = await _create_session(db, row["id"])
        return _public_user(row), token


async def logout(token: str | None) -> None:
    if not token:
        return
    async with get_db() as db:
        await db.execute("DELETE FROM user_sessions WHERE token_hash = ?", (_token_hash(token),))
async def user_from_request(request: Request, required: bool = True) -> Optional[dict]:
    token = request.cookies.get(SESSION_COOKIE)
    row = None
    if token:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT u.id, u.username, u.role FROM user_sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > datetime('now')
                     AND u.status = 'active'""",
                (_token_hash(token),),
            )
            row = await cursor.fetchone()
    if not row:
        if required:
            raise HTTPException(status_code=401, detail="请先登录")
        return None
    user = _public_user(row)
    request.state.current_user = user
    return user


async def authorize_request(request: Request) -> dict:
    """Authenticate and enforce project membership for every /api/jobs/{id} route."""
    user = await user_from_request(request)
    job_id = request.path_params.get("job_id")
    if not job_id:
        return user
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT pm.role FROM jobs j
               JOIN project_members pm ON pm.project_id = j.project_id
               WHERE j.id = ? AND pm.user_id = ?""",
            (job_id, user["id"]),
        )
        membership = await cursor.fetchone()
    if not membership and user["role"] != "admin":
        raise HTTPException(status_code=404, detail="任务不存在")
    role = "owner" if user["role"] == "admin" else membership["role"]
    if request.method == "DELETE" and role != "owner":
        raise HTTPException(status_code=403, detail="仅项目所有者可删除任务")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and role not in {"owner", "editor"}:
        raise HTTPException(status_code=403, detail="当前项目角色没有写权限")
    request.state.project_role = role
    return user


async def require_admin(request: Request) -> dict:
    user = await user_from_request(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def default_project_id(user_id: str) -> str:
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT p.id FROM projects p JOIN project_members pm ON pm.project_id = p.id
               WHERE pm.user_id = ? ORDER BY CASE pm.role WHEN 'owner' THEN 0 ELSE 1 END, p.created_at LIMIT 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
    if not row:
        raise RuntimeError("用户尚未加入任何项目")
    return row["id"]


async def create_user(username: str, password: str, role: str = "user") -> dict:
    user_id = secrets.token_hex(8)
    normalized = username.strip().lower()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?)",
            (user_id, normalized, _hash_password(password), role),
        )
    return {"id": user_id, "username": normalized, "role": role}


async def create_project(owner: dict, name: str) -> dict:
    project_id = secrets.token_hex(8)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO projects (id, owner_user_id, name) VALUES (?, ?, ?)",
            (project_id, owner["id"], name.strip()),
        )
        await db.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (?, ?, 'owner')",
            (project_id, owner["id"]),
        )
    return {"id": project_id, "name": name.strip(), "role": "owner"}


async def list_projects(user: dict) -> list[dict]:
    async with get_db() as db:
        if user["role"] == "admin":
            cursor = await db.execute(
                """SELECT p.id, p.name, COALESCE(pm.role, 'owner') role FROM projects p
                   LEFT JOIN project_members pm ON pm.project_id = p.id AND pm.user_id = ?
                   ORDER BY p.created_at""",
                (user["id"],),
            )
        else:
            cursor = await db.execute(
                """SELECT p.id, p.name, pm.role FROM projects p
                   JOIN project_members pm ON pm.project_id = p.id
                   WHERE pm.user_id = ? ORDER BY p.created_at""",
                (user["id"],),
            )
        return [dict(row) for row in await cursor.fetchall()]


async def set_project_member(actor: dict, project_id: str, username: str, role: str) -> None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, actor["id"]),
        )
        membership = await cursor.fetchone()
        if actor["role"] != "admin" and (not membership or membership["role"] != "owner"):
            raise PermissionError("仅项目所有者可管理成员")
        cursor = await db.execute("SELECT id FROM users WHERE username = ?", (username.strip().lower(),))
        target = await cursor.fetchone()
        if not target:
            raise LookupError("用户不存在")
        await db.execute(
            """INSERT INTO project_members (project_id, user_id, role) VALUES (?, ?, ?)
               ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role""",
            (project_id, target["id"], role),
        )
