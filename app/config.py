from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Gigapixel Heritage Viewer"
    api_prefix: str = "/api"
    data_root: Path = PROJECT_ROOT / "data"
    database_path: Path = PROJECT_ROOT / "data" / "gigapixel.db"
    allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    max_upload_files: int = 1000
    max_source_pixels: int = 10_000_000_000
    tile_size: int = 256
    tile_overlap: int = 1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"


settings = Settings()
settings.data_root.mkdir(parents=True, exist_ok=True)
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
