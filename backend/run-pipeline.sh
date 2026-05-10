#!/bin/bash
export LD_LIBRARY_PATH="/home/cbc/.local/lib/python3.12/site-packages/nvidia/cudnn/lib:/home/cbc/.local/lib/python3.12/site-packages/nvidia/cusparselt/lib:/home/cbc/.local/lib/python3.12/site-packages/nvidia/nccl/lib:$LD_LIBRARY_PATH"
cd /home/cbc/home-ktv/backend
uv run --no-env-file python -m ktv_pipeline.pipeline_orchestrator "$@"