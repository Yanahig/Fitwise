from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import (
    agent,
    analysis,
    auth,
    customers,
    dashboard,
    events,
    knowledge,
    materials,
    projects,
    traces,
)
from .seed import seed_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_all()
    yield


app = FastAPI(
    title="Fitwise API",
    description="AI 售前决策助手：客户档案 × 项目全流程 × 证据化能力匹配",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store(request, call_next):
    """业务数据不做浏览器缓存，避免界面读到过期结论。"""
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(projects.router)
app.include_router(materials.router)
app.include_router(agent.router)
app.include_router(analysis.router)
app.include_router(dashboard.router)
app.include_router(knowledge.router)
app.include_router(traces.router)
app.include_router(events.router)


@app.get("/api/health-check")
def health_check() -> dict:
    return {"status": "ok", "parser": settings.textin_enabled, "llm": settings.llm_enabled}


# 前端构建产物存在时由后端同源托管：单端口部署（前端与 API 同一个源）就不用配 CORS，
# 也不会出现 https 页面调 http 接口被浏览器拦掉的情况。
# 必须在所有 API 路由之后挂载，否则 "/" 会把 /api/*、/docs 一起吃掉。
frontend_dir = settings.resolved_frontend_dir
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    logging.getLogger(__name__).info("已同源托管前端：%s", frontend_dir)
