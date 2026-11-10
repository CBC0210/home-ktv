"""組態設定。從 .env 讀取所有環境變數。"""
import importlib.metadata
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _nvidia_lib_paths() -> list:
    """Locate the pip-installed nvidia/*/lib dirs on THIS machine.

    The nvidia-cudnn / cusparselt / nccl wheels install shared libraries into
    site-packages/nvidia/<pkg>/lib, which is not on the default loader path.
    Derived from the actual installed package location instead of a hardcoded
    path so any user / venv / Python version works.
    """
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        roots = list(spec.submodule_search_locations or []) if spec else []
    except Exception:
        roots = []
    paths = []
    for root in roots:
        for sub in ("cudnn", "cusparselt", "nccl"):
            p = Path(root) / sub / "lib"
            if p.is_dir():
                paths.append(str(p))
    return paths


def _configure_cuda_env() -> None:
    """Ensure CUDA shared libraries are found for Demucs / WhisperX.

    Prepends the nvidia wheel lib dirs to LD_LIBRARY_PATH so any subsequent
    import of torch / demucs works without requiring env vars.
    """
    paths = _nvidia_lib_paths()
    if paths:
        extra = ":".join(paths)
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = f"{extra}:{existing}" if existing else extra
    # Reduce VRAM fragmentation on small (4 GB) cards.
    # expandable_segments: lets the allocator grow/shrink blocks instead of
    #   keeping fixed-size pools → less stranded memory between Demucs and WhisperX.
    # garbage_collection_threshold:0.8 → CUDA GC kicks in at 80% pool usage,
    #   reclaiming freed-but-cached blocks before OOM is triggered.
    if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = (
            "expandable_segments:True,garbage_collection_threshold:0.8"
        )


_configure_cuda_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Unknown .env entries must never crash startup — deployers keep
        # legacy/extra vars around, and that's fine.
        extra="ignore",
    )

    admin_password: str = "admin"          # CHANGE in .env — gates /admin
    admin_cookie_secret: str = "change-me-32chars-minimum!!"
    public_base_url: str = ""              # optional; QR uses page origin
    local_port: int = 8000
    data_dir: Path = Path("./data")        # repo-local by default (LAN/dev)
    # Auth cookie. Bearer (localStorage) is the primary mechanism; the
    # cookie is secondary. Keep secure=False so it also works on a plain
    # HTTP LAN; set true only when always served over HTTPS.
    cookie_secure: bool = False
    # Cloudflare Tunnel is OPTIONAL — only needed for public/off-LAN access.
    cf_tunnel_name: str = ""
    cf_tunnel_uuid: str = ""
    cf_domain: str = ""
    cf_subdomain: str = ""
    enable_gpu: bool = True
    enable_word_alignment: bool = True
    whisperx_model: str = "small"
    demucs_model: str = "htdemucs"
    song_total_timeout_sec: int = 900
    pipeline_max_retries: int = 3
    pipeline_heartbeat_sec: int = 30
    prefetch_count: int = 2
    # Optional Netscape-format cookies file for yt-dlp (age-restricted /
    # members-only videos). Empty = no cookies.
    youtube_cookies_path: str = ""
    # Password for the auto-seeded default 'home' room on FIRST run (empty =
    # room without password — fine on a private LAN).
    default_room_password: str = ""
    # YouTube search result filter — drop non-song videos. A track is
    # normally 1–10 min; longer = compilation / live / concert / talk,
    # shorter = clip. Direct-pasted links bypass this.
    search_min_duration_sec: int = 60
    search_max_duration_sec: int = 600
    log_level: str = "INFO"
    dev_mode: bool = False
    # MiniMax LLM (Anthropic-compatible endpoint) — used to clean messy
    # YouTube titles into accurate {title, artist} for lyric search.
    minimax_api_key: str = ""
    minimax_model: str = "MiniMax-M2.5"
    minimax_base_url: str = "https://api.minimax.io/anthropic/v1/messages"

    @property
    def version(self) -> str:
        try:
            return importlib.metadata.version("ktv-pipeline")
        except importlib.metadata.PackageNotFoundError:
            return "0.0.0"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ktv.db"

    @property
    def log_dir(self) -> Path:
        """Always inside DATA_DIR so a fresh clone never writes outside it."""
        return self.data_dir / "logs"


settings = Settings()
