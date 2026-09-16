from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import agent, analysis, auth, customers, dashboard, knowledge, materials, projects
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


@app.get("/api/health-check")
def health_check() -> dict:
    return {"status": "ok", "parser": settings.textin_enabled, "llm": settings.llm_enabled}
