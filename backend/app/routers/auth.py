"""User bootstrap and cookie-session authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.services import auth_service
from app.services.auth_service import require_admin

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=10, max_length=128)


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(
        auth_service.SESSION_COOKIE, token, httponly=True, samesite="strict",
        secure=False, max_age=auth_service.SESSION_TTL_SECONDS, path="/",
    )


@router.get("/status")
async def status(request: Request):
    user = await auth_service.user_from_request(request, required=False)
    return {
        "initialized": await auth_service.has_users(),
        "authenticated": bool(user),
        "user": user,
    }


@router.post("/bootstrap")
async def bootstrap(credentials: Credentials, response: Response):
    try:
        user, token = await auth_service.bootstrap(credentials.username, credentials.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _set_session(response, token)
    return {"user": user}


@router.post("/login")
async def login(credentials: Credentials, response: Response):
    result = await auth_service.login(credentials.username, credentials.password)
    if not result:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user, token = result
    _set_session(response, token)
    return {"user": user}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    await auth_service.logout(request.cookies.get(auth_service.SESSION_COOKIE))
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")


class UserCreate(Credentials):
    role: str = Field("user", pattern="^(admin|user)$")


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class MemberUpsert(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    role: str = Field(..., pattern="^(owner|editor|viewer)$")


@router.post("/users", status_code=201)
async def create_user(payload: UserCreate, _admin=Depends(require_admin)):
    try:
        return await auth_service.create_user(payload.username, payload.password, payload.role)
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="用户名已存在") from exc
        raise


@router.get("/projects")
async def projects(request: Request):
    user = await auth_service.user_from_request(request)
    return await auth_service.list_projects(user)


@router.post("/projects", status_code=201)
async def create_project(payload: ProjectCreate, request: Request):
    user = await auth_service.user_from_request(request)
    return await auth_service.create_project(user, payload.name)


@router.put("/projects/{project_id}/members")
async def set_member(project_id: str, payload: MemberUpsert, request: Request):
    user = await auth_service.user_from_request(request)
    try:
        await auth_service.set_project_member(user, project_id, payload.username, payload.role)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"message": "项目成员权限已更新"}
