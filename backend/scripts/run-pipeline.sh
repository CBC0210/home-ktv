#!/bin/bash
# Pipeline runner — sets up GPU library paths before invoking Python

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")/backend"

NCCL="/home/cbc/.local/lib/python3.12/site-packages/nvidia/nccl/lib"
CUDNN="/home/cbc/.local/lib/python3.12/site-packages/nvidia/cudnn/lib"
CUSPARSE="/home/cbc/.local/lib/python3.12/site-packages/nvidia/cusparselt/lib"
CUDA_LIB="/home/cbc/.cache/uv/archive-v0/e7XekT251rIJuwgA/torch/lib"

export LD_LIBRARY_PATH="${NCCL}:${CUDNN}:${CUSPARSE}:${CUDA_LIB}:$LD_LIBRARY_PATH"

cd "$BACKEND_DIR"
exec uv run python -m ktv_pipeline.pipeline_orchestrator "$@"
