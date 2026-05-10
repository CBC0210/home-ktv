#!/bin/bash
# GPU Setup Check & Auto-Install (M0-T5)
# 檢查 NVIDIA driver / CUDA / cuDNN 是否安裝，沒有則安裝。
# 詳見 CLAUDE.md §3.3 與 SETUP.md。

set -euo pipefail

LOG_FILE="${HOME}/home-ktv/data/logs/gpu-setup.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== GPU Setup Check Starting ==="

# 1. nvidia-smi 是否存在
if command -v nvidia-smi &> /dev/null; then
    log "✅ nvidia-smi found"
    nvidia-smi | tee -a "$LOG_FILE"
else
    log "⚠️  nvidia-smi not found, attempting to install NVIDIA driver..."
    sudo apt update
    sudo apt install -y nvidia-driver-535
    log "🔄 NVIDIA driver installed. PLEASE REBOOT THE SERVER and re-run this script."
    exit 2
fi

# 2. CUDA Toolkit
if command -v nvcc &> /dev/null; then
    log "✅ CUDA Toolkit found: $(nvcc --version | grep release)"
else
    log "⚠️  CUDA Toolkit not found, installing..."
    sudo apt install -y nvidia-cuda-toolkit
    log "✅ CUDA Toolkit installed"
fi

# 3. Python + PyTorch CUDA 偵測
if command -v python3 &> /dev/null; then
    PYTORCH_CHECK=$(python3 -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)" 2>&1 || echo "FAILED")
    log "PyTorch CUDA check: $PYTORCH_CHECK"
fi

# 4. 列出 GPU
log "GPU Inventory:"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv | tee -a "$LOG_FILE"

log "=== GPU Setup Check Complete ==="
exit 0
