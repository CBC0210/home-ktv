"""組態設定。從 .env 讀取所有環境變數。"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _configure_cuda_env() -> None:
    """Ensure CUDA shared libraries are found for Demucs / WhisperX.

    nvidia-cublas-13, nvidia-cudnn-9, nvidia-cusparse-13 and nvidia-nccl
    packages install into a site-packages directory that is not on the
    default library search path.  We prepend the paths here so that any
    subsequent import of torch / demucs works without requiring env vars.
    """
    base = "/home/cbc/.local/lib/python3.12/site-packages"
    extra = ":".join([
        f"{base}/nvidia/cudnn/lib",
        f"{base}/nvidia/cusparselt/lib",
        f"{base}/nvidia/nccl/lib",
    ])
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = f"{extra}:{existing}" if existing else extra
    # Avoid CUDA OOM fragmentation on small GPUs (GTX 1650 4GB)
    if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"


_configure_cuda_env()


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
    cf_tunnel_name: str = "ktv"
    cf_tunnel_uuid: str = ""
    cf_domain: str = "bc-verse.com"
    cf_subdomain: str = "ktv"
    enable_gpu: bool = True
    whisperx_model: str = "small"
    demucs_model: str = "htdemucs"
    song_total_timeout_sec: int = 900
    prefetch_count: int = 2
    log_level: str = "INFO"
    log_dir: Path = Path("/data/ktv/logs")
    dev_mode: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ktv.db"


settings = Settings()
