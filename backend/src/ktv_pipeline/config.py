"""組態設定。從 .env 讀取所有環境變數。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    admin_password: str = "BCktv210"
    admin_cookie_secret: str = "change-me-32chars-minimum!!"
    public_base_url: str = "https://ktv.bc-verse.com"
    local_port: int = 8000
    data_dir: Path = Path("/data/ktv")
    cf_tunnel_uuid: str = ""
    cf_domain: str = "bc-verse.com"
    cf_subdomain: str = "ktv"
    enable_gpu: bool = True
    whisperx_model: str = "small"
    demucs_model: str = "htdemucs_ft"
    song_total_timeout_sec: int = 900
    prefetch_count: int = 2
    log_level: str = "INFO"
    log_dir: Path = Path("/data/ktv/logs")
    dev_mode: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ktv.db"


settings = Settings()
