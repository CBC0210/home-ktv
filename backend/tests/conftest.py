"""conftest.py — test environment setup."""
import os

# Ensure CUDA libraries are on the path before any module that imports torch runs.
# This mirrors what config.py does, but needs to happen at pytest collection time
# before the torch import in test_demucs.py is resolved.
base = "/home/cbc/.local/lib/python3.12/site-packages"
extra = ":".join([
    f"{base}/nvidia/cudnn/lib",
    f"{base}/nvidia/cusparselt/lib",
    f"{base}/nvidia/nccl/lib",
])
existing = os.environ.get("LD_LIBRARY_PATH", "")
os.environ["LD_LIBRARY_PATH"] = f"{extra}:{existing}" if existing else extra