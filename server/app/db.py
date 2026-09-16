from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.resolved_database_url,
    connect_args={"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)

if settings.resolved_database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _record):  # pragma: no cover - 驱动回调
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册到 metadata

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """轻量迁移：给已存在的库补新列、清掉已下线功能留下的旧表，避免演示库需要重建。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    columns = {item["name"] for item in inspector.get_columns("projects")} if "projects" in tables else set()

    def missing(table: str, column: str) -> bool:
        return table in tables and column not in {item["name"] for item in inspector.get_columns(table)}

    with engine.begin() as connection:
        if missing("projects", "highlights"):
            connection.execute(text("ALTER TABLE projects ADD COLUMN highlights JSON"))
        if missing("materials", "summary"):
            connection.execute(text("ALTER TABLE materials ADD COLUMN summary TEXT DEFAULT ''"))
        # 判断的取证轨迹与自检裁决（docs/agent-core-design.md）
        if missing("match_results", "trace"):
            connection.execute(text("ALTER TABLE match_results ADD COLUMN trace JSON"))
        if missing("match_results", "self_check"):
            connection.execute(text("ALTER TABLE match_results ADD COLUMN self_check JSON"))
        if missing("requirements", "edited"):
            connection.execute(text("ALTER TABLE requirements ADD COLUMN edited BOOLEAN DEFAULT 0"))
        # 已下线功能的旧表：行动项（"下一步"只在售前建议页以三组清单呈现）、
        # 对客承诺登记、客户联系人（决策链 AI 既不读也不写）—— 连同数据一起清掉
        for table in ("action_items", "commitments", "contacts"):
            if table in tables:
                connection.execute(text(f"DROP TABLE {table}"))
        # 项目上这几列（金额 / 预计签约 / 竞争对手 / 赢单率）界面上已经没有了，也不该由 AI 生成
        for column in ("amount", "expected_close", "competitors", "win_probability"):
            if column in columns:
                connection.execute(text(f"ALTER TABLE projects DROP COLUMN {column}"))
