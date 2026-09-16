from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(value: str) -> str:
    """把相对路径解析到 server/ 目录下，保证从任何工作目录启动都一致。"""
    if value.startswith("sqlite:///"):
        raw = value.replace("sqlite:///", "", 1)
        path = Path(raw)
        if not path.is_absolute():
            path = (SERVER_DIR / raw.lstrip("./")).resolve()
        return f"sqlite:///{path.as_posix()}"
    path = Path(value)
    if not path.is_absolute():
        path = (SERVER_DIR / value.lstrip("./")).resolve()
    return str(path)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=SERVER_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 文档解析：TextIn xParse
    textin_app_id: str = ""
    textin_secret_code: str = ""
    textin_base_url: str = "https://api.textin.com"
    textin_async_page_threshold: int = 30

    # 大模型：DeepSeek（OpenAI 兼容协议）
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-flash"
    llm_timeout_seconds: int = 180

    # 服务与存储
    database_url: str = "sqlite:///./data/fitwise.db"
    storage_dir: str = "./data/uploads"
    # 前端构建产物目录。留空 = 仓库根目录下的 dist；目录存在时由后端同源托管（单端口部署）
    frontend_dir: str = ""
    jwt_secret: str = "fitwise-dev-secret-change-me"
    access_token_expire_minutes: int = 720
    cors_origins: str = "http://127.0.0.1:5183,http://localhost:5183"

    @property
    def resolved_database_url(self) -> str:
        url = _resolve_path(self.database_url)
        if url.startswith("sqlite:///"):
            Path(url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
        return url

    @property
    def resolved_storage_dir(self) -> Path:
        path = Path(_resolve_path(self.storage_dir))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def resolved_frontend_dir(self) -> Path:
        """前端构建产物目录；默认仓库根下的 dist，可用 FRONTEND_DIR 覆盖。"""
        raw = self.frontend_dir.strip() or "dist"
        path = Path(raw)
        if not path.is_absolute():
            path = (SERVER_DIR.parent / raw.lstrip("./")).resolve()
        return path

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def textin_enabled(self) -> bool:
        return bool(self.textin_app_id and self.textin_secret_code)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
