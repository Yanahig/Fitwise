"""客户：只保留 MVP 真正需要的两个动作 —— 建客户、按名字找客户。

客户的完整档案（联系人、统计、时间线）属于 P1：界面上没有入口，数据也没人维护，
所以随客户档案页一起下线；新建分析时只要能建出客户、能按名字查重就够了。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..domain import PENDING_CUSTOMER_NAME, is_pending_name
from ..models import Customer, User
from ..serializers import customer_out
from ..services.activity import log_activity

router = APIRouter(prefix="/api/customers", tags=["customers"])


class CustomerRequest(BaseModel):
    name: str
    industry: str = ""
    scale: str = ""
    region: str = ""
    tier: str = "B"
    owner_name: str = ""
    source: str = ""
    health: str = "normal"
    notes: str = ""


@router.get("")
def list_customers(
    q: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    """按名字/行业找客户：新建项目时要先知道客户 id（演示脚本也用它做查重）。"""
    query = select(Customer).order_by(Customer.updated_at.desc()).limit(limit)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Customer.name.like(like), Customer.industry.like(like)))
    return [customer_out(item) for item in db.execute(query).scalars().all()]


@router.post("", status_code=201)
def create_customer(
    payload: CustomerRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # 留空 = 等 AI 从材料里识别：这种"占位客户"允许多个，不做重名拦截
    if not is_pending_name(payload.name):
        duplicate = (
            db.execute(select(Customer).where(Customer.name == payload.name)).scalar_one_or_none()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail=f"客户「{payload.name}」已存在，直接用它建项目即可")
    else:
        payload.name = PENDING_CUSTOMER_NAME
    customer = Customer(**payload.model_dump())
    db.add(customer)
    db.flush()
    log_activity(db, actor=user.name, type="customer_created", summary=f"创建客户：{customer.name}", customer_id=customer.id)
    db.commit()
    return customer_out(customer)


class CustomerPatch(BaseModel):
    name: str | None = None
    industry: str | None = None
    notes: str | None = None


@router.patch("/{customer_id}")
def update_customer(
    customer_id: int,
    payload: CustomerPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """改客户名：AI 从材料里识别出真名后回填，人也可以手动改。"""
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    changes = payload.model_dump(exclude_none=True)
    name = str(changes.get("name") or "").strip()
    if name and not is_pending_name(name):
        duplicate = (
            db.execute(select(Customer).where(Customer.name == name, Customer.id != customer_id))
            .scalar_one_or_none()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail=f"客户「{name}」已存在")
        changes["name"] = name
    elif "name" in changes:
        changes.pop("name")
    for key, value in changes.items():
        setattr(customer, key, value)
    log_activity(
        db,
        actor=user.name,
        type="customer_updated",
        summary=f"更新客户名称：{customer.name}",
        customer_id=customer.id,
    )
    db.commit()
    return customer_out(customer)
