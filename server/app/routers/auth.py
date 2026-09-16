from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_roles
from ..models import User
from ..security import create_access_token, hash_password, verify_password
from ..serializers import user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateUserRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str = "presales"


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码不正确")
    return {"token": create_access_token(user.id, user.email, user.role), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return user_out(user)


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[dict]:
    return [user_out(item) for item in db.execute(select(User).order_by(User.id)).scalars()]


@router.post("/users", status_code=201)
def create_user(
    payload: CreateUserRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    exists = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="该邮箱已存在")
    user = User(
        email=payload.email,
        name=payload.name,
        role=payload.role,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    return user_out(user)
